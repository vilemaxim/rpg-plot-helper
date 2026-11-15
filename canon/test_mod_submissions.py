"""A Mod Writer submitting a Mod, or a revision of a draft, through web
requests, with plotcanon's sample World and script."""

import io

import plotcanon

from canon.models import Document, Flag
from canon.test_approving import DAUGHTER, ApprovingTest
from canon.test_resolving import WARRANT
from organizations.tests import sign_in

NEW = "the-lamplighters-debt"
SUBMIT = "submit-mod/"


def a_mod(slug=NEW, title="The Lamplighter's Debt", **replacing):
    """A new Mod's file, made from the sample World's draft."""
    text = plotcanon.sample_world()[f"inbox/{DAUGHTER}.md"]
    text = text.replace(f"id: {DAUGHTER}", f"id: {slug}") \
        .replace("title: \"The Guildmaster's Daughter\"", f'title: "{title}"') \
        .replace('aliases: ["The Guildmaster\'s Daughter", "the daughter mod"]',
                 f'aliases: ["{title}"]')
    for old, new in replacing.items():
        text = text.replace(old, new)
    return text


class SubmissionTest(ApprovingTest):
    """Sam is a Mod Writer in Mira's World, and Rhea only runs Mods there."""

    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        self.rhea = self.join("rhea@example.com")
        self.give("rhea@example.com", "mod-runner")
        self.form = f"{self.first_world}{SUBMIT}"

    def submit_mod(self, text, by=None):
        return (by or self.sam).post(self.form, {"text": text}, follow=True)

    def revise(self, mod, text, by=None):
        return (by or self.sam).post(f"{self.mod_page(mod)}revise/", {"text": text},
                                     follow=True)

    def exists(self, slug):
        with self.in_world():
            return Document.objects.filter(slug=slug).exists()


class SubmittingAMod(SubmissionTest):
    def test_the_world_page_offers_a_mod_writer_the_form(self):
        self.assertContains(self.sam.get(self.first_world), self.form)
        page = self.sam.get(self.form)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "<textarea")
        self.assertContains(page, 'type="file"')

    def test_a_valid_mod_is_saved_as_a_draft_in_the_inbox(self):
        response = self.submit_mod(a_mod())

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertEqual(self.state_shown(NEW), "Draft")
        stored = self.stored(NEW)
        self.assertEqual(stored.path, f"inbox/{NEW}.md")
        self.assertEqual(stored.text, a_mod())
        self.assertEqual(stored.submitted_by.email, "sam@example.com")
        self.assertIsNotNone(stored.submitted_at)
        self.assertContains(response, "Submitted by sam@example.com on")

    def test_a_mod_can_be_uploaded_as_a_file(self):
        upload = io.BytesIO(a_mod().encode())
        upload.name = f"{NEW}.md"

        self.sam.post(self.form, {"file": upload}, follow=True)

        self.assertEqual(self.stored(NEW).text, a_mod())

    def test_a_plot_master_can_submit_one_too(self):
        self.submit_mod(a_mod(), by=self.mira)

        self.assertEqual(self.stored(NEW).submitted_by.email, "mira@example.com")

    def test_a_mod_that_claims_to_be_approved_is_taken_in_as_a_draft(self):
        claims = a_mod(**{"state: draft": "state: approved", "canon: proposed": "canon: approved"})

        self.submit_mod(claims)

        stored = self.stored(NEW)
        self.assertEqual(stored.text, a_mod())
        self.assertEqual(stored.fields["state"], "draft")

    def test_a_mod_may_name_things_the_world_does_not_have_yet(self):
        self.submit_mod(a_mod(**{"ysolde-marr]": "ysolde-marr, the-drowned-uncle]"}))

        self.assertEqual(self.stored(NEW).fields["features"]["npcs"][-1], "the-drowned-uncle")

    def test_submitting_a_mod_raises_no_flags(self):
        with self.in_world():
            before = Flag.objects.count()

        self.submit_mod(a_mod())

        with self.in_world():
            self.assertEqual(Flag.objects.count(), before)

    def test_what_is_stored_is_still_a_world_plotcanon_accepts(self):
        self.submit_mod(a_mod())

        with self.in_world():
            files = dict(Document.objects.values_list("path", "text"))
        self.assertTrue(plotcanon.load_world(files).ok)

    def test_it_can_then_be_approved(self):
        self.submit_mod(a_mod())

        self.approve(NEW, campaign="lanternlight")

        self.assertEqual(self.state_shown(NEW), "Approved")


class RefusedSubmissions(SubmissionTest):
    def test_an_invalid_mod_saves_nothing_and_shows_its_errors_to_copy(self):
        broken = a_mod(**{"visibility: gm-only": "visibility: everyone"})

        response = self.submit_mod(broken)

        self.assertFalse(self.exists(NEW))
        self.assertContains(response, "Nothing was saved.")
        errors = response.content.decode().split("<pre>", 1)[1].split("</pre>", 1)[0]
        self.assertIn("visibility", errors)
        # What was pasted is given back to correct.
        pasted = response.content.decode().split("<textarea", 1)[1].split("</textarea>", 1)[0]
        self.assertIn("visibility: everyone", pasted)

    def test_a_file_that_is_not_a_mod_is_refused(self):
        npc = plotcanon.sample_world()["canon/npcs/ysolde-marr.md"]

        response = self.submit_mod(npc.replace("id: ysolde-marr", "id: someone-new"))

        self.assertContains(response, "It is not a Mod")
        self.assertFalse(self.exists("someone-new"))

    def test_an_id_the_world_already_uses_is_refused(self):
        response = self.submit_mod(a_mod(slug="harrow-dunmore"))

        self.assertContains(response, "already has")
        self.assertEqual(self.stored("harrow-dunmore").kind, "npc")

    def test_an_id_that_cannot_be_used_is_refused(self):
        response = self.submit_mod(a_mod(slug="The Lamplighter"))

        self.assertContains(response, "no id that can be used")
        with self.in_world():
            self.assertFalse(Document.objects.filter(path__startswith="inbox/the-lamp").exists())

    def test_the_id_of_a_draft_points_to_revising_it(self):
        before = self.stored(DAUGHTER).text

        response = self.submit_mod(a_mod(slug=DAUGHTER))

        self.assertContains(response, "revise it from its page")
        self.assertEqual(self.stored(DAUGHTER).text, before)

    def test_someone_who_only_runs_mods_cannot_submit_one(self):
        self.assertNotContains(self.rhea.get(self.first_world), self.form)
        self.assertEqual(self.rhea.get(self.form).status_code, 404)
        self.assertEqual(self.submit_mod(a_mod(), by=self.rhea).status_code, 404)
        self.assertFalse(self.exists(NEW))

    def test_someone_with_no_role_in_the_world_cannot(self):
        eve = sign_in("eve@example.com")

        self.assertEqual(self.submit_mod(a_mod(), by=eve).status_code, 404)
        self.assertFalse(self.exists(NEW))


    def test_a_world_with_no_canon_yet_takes_no_mods(self):
        # A Mod is checked against the World, and a World's Canon arrives by
        # importing it, which a World holding a draft could no longer do.
        empty = self.make_world("Empty World")
        self.give("mira@example.com", "plot-master", world=empty)

        self.assertNotContains(self.mira.get(empty), "submit-mod/")
        self.assertEqual(self.mira.get(f"{empty}{SUBMIT}").status_code, 404)


class RevisingADraft(SubmissionTest):
    def setUp(self):
        super().setUp()
        self.submit_mod(a_mod())

    def test_its_mod_writer_replaces_it_with_a_revised_file(self):
        revised = a_mod(title="The Lamplighter's Last Debt")

        response = self.revise(NEW, revised)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        stored = self.stored(NEW)
        self.assertEqual(stored.text, revised)
        self.assertEqual(stored.name, "The Lamplighter's Last Debt")
        self.assertEqual(stored.path, f"inbox/{NEW}.md")
        self.assertEqual(stored.submitted_by.email, "sam@example.com")

    def test_the_draft_offers_its_mod_writer_the_form(self):
        self.assertContains(self.sam.get(self.mod_page(NEW)), f"{self.mod_page(NEW)}revise/")
        self.assertEqual(self.sam.get(f"{self.mod_page(NEW)}revise/").status_code, 200)

    def test_a_revision_with_another_id_is_refused(self):
        response = self.revise(NEW, a_mod(slug="another-mod"))

        self.assertContains(response, "another-mod")
        self.assertEqual(self.stored(NEW).text, a_mod())
        self.assertFalse(self.exists("another-mod"))

    def test_an_invalid_revision_saves_nothing(self):
        response = self.revise(NEW, a_mod(**{"visibility: gm-only": "visibility: everyone"}))

        self.assertContains(response, "Nothing was saved.")
        self.assertEqual(self.stored(NEW).text, a_mod())

    def test_a_revision_claiming_approval_stays_a_draft(self):
        self.revise(NEW, a_mod(**{"state: draft": "state: approved"}))

        self.assertEqual(self.stored(NEW).fields["state"], "draft")

    def test_another_mod_writer_cannot_revise_it(self):
        kay = self.join("kay@example.com")
        self.give("kay@example.com", "mod-writer")

        self.assertNotContains(kay.get(self.mod_page(NEW)), "revise/")
        self.assertEqual(self.revise(NEW, a_mod(title="Mine Now"), by=kay).status_code, 404)
        self.assertEqual(self.stored(NEW).text, a_mod())

    def test_a_plot_master_can_revise_it(self):
        self.revise(NEW, a_mod(title="Tidied"), by=self.mira)

        self.assertEqual(self.stored(NEW).name, "Tidied")

    def test_a_mod_writer_cannot_revise_an_imported_draft(self):
        self.assertEqual(self.revise(DAUGHTER, a_mod(slug=DAUGHTER)).status_code, 404)


class RevisingASentBackMod(SubmissionTest):
    def setUp(self):
        super().setUp()
        self.original = self.stored(WARRANT).text
        self.send_back(WARRANT)
        self.draft = self.stored(WARRANT).text

    def test_the_revision_keeps_the_mods_history(self):
        revised = self.draft.replace("duration_est: 90", "duration_est: 120")

        self.revise(WARRANT, revised, by=self.mira)

        self.assertEqual(self.stored(WARRANT).text, revised)
        page = self.mira.get(self.mod_page(WARRANT))
        self.assertContains(page, "Sent back to its Mod Writer</strong>")
        self.assertContains(page, "The smuggler is dead; rewrite around his partner.")
        self.assertTrue(self.flags_on(WARRANT, open_only=False))

    def test_and_it_can_be_approved_again(self):
        self.revise(WARRANT, self.draft.replace("duration_est: 90", "duration_est: 120"),
                    by=self.mira)

        self.approve(WARRANT)

        self.assertEqual(self.stored(WARRANT).text,
                         self.original.replace("duration_est: 90", "duration_est: 120"))


class RevisingAModThatIsNotADraft(SubmissionTest):
    def test_it_is_refused(self):
        before = self.stored(WARRANT).text

        self.assertNotContains(self.mira.get(self.mod_page(WARRANT)), "revise/")
        response = self.revise(WARRANT, before.replace("duration_est: 90", "duration_est: 5"),
                               by=self.mira)

        self.assertContains(response, "only a draft")
        self.assertEqual(self.stored(WARRANT).text, before)
