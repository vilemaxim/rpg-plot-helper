"""Approving a draft Mod, so that it can be run, through web requests, with
plotcanon's sample World and script. The sample World holds one draft, the
Guildmaster's Daughter, which names no Campaign."""

import plotcanon

from canon.models import Document
from canon.test_resolving import WARRANT, ResolvingTest

DAUGHTER = "the-guildmasters-daughter"


def frontmatter_end(text):
    """Where a file's frontmatter ends: the start of its closing line."""
    return text.index("\n---", 3)


class ApprovingTest(ResolvingTest):
    """The stair report has been filed, so the warrant Mod and the daughter
    draft are each flagged."""

    def approve(self, mod, campaign=None, by=None):
        data = {} if campaign is None else {"campaign": campaign}
        return (by or self.mira).post(f"{self.mod_page(mod)}approve/", data, follow=True)


class Approving(ApprovingTest):
    def test_a_draft_offers_a_plot_master_the_approval_form(self):
        page = self.mira.get(self.mod_page(DAUGHTER))

        self.assertContains(page, f'action="{self.mod_page(DAUGHTER)}approve/"')
        self.assertContains(page, '<option value="lanternlight">')

    def test_an_approved_draft_can_be_reported_on(self):
        self.assertNotContains(self.mira.get(self.mod_page(DAUGHTER)), self.report_form(DAUGHTER))

        response = self.approve(DAUGHTER, campaign="lanternlight")

        self.assertContains(response, "approved")
        self.assertEqual(self.state_shown(DAUGHTER), "Approved")
        self.assertContains(self.mira.get(self.mod_page(DAUGHTER)), self.report_form(DAUGHTER))

    def test_its_file_moves_to_its_campaign_and_says_it_is_canon(self):
        before = self.stored(DAUGHTER).text

        self.approve(DAUGHTER, campaign="lanternlight")

        stored = self.stored(DAUGHTER)
        self.assertEqual(stored.path, f"mods/lanternlight/{DAUGHTER}.md")
        end = frontmatter_end(before)
        expected = (before[:end] + "\ncampaign: lanternlight" + before[end:]) \
            .replace("state: draft", "state: approved") \
            .replace("canon: proposed", "canon: approved")
        self.assertEqual(stored.text, expected)
        self.assertEqual(stored.fields["campaign"], "lanternlight")

    def test_what_is_stored_is_still_a_world_plotcanon_accepts(self):
        self.approve(DAUGHTER, campaign="lanternlight")

        with self.in_world():
            files = dict(Document.objects.values_list("path", "text"))
        checked = plotcanon.load_world(files)
        self.assertTrue(checked.ok, checked.text)
        self.assertEqual([str(w) for w in checked.warnings], [])

    def test_the_page_says_who_approved_it_and_when(self):
        self.approve(DAUGHTER, campaign="lanternlight")

        self.assertContains(self.mira.get(self.mod_page(DAUGHTER)),
                            "Approved by mira@example.com on")

    def test_its_open_flags_stay_open(self):
        self.assertTrue(self.flags_on(DAUGHTER))

        self.approve(DAUGHTER, campaign="lanternlight")

        self.assertTrue(self.flags_on(DAUGHTER))
        self.assertTrue(self.warns(DAUGHTER))


class ApprovingASentBackMod(ApprovingTest):
    def setUp(self):
        super().setUp()
        self.original = self.stored(WARRANT)
        self.send_back(WARRANT)

    def test_it_keeps_its_campaign_and_returns_to_its_place(self):
        self.approve(WARRANT)

        stored = self.stored(WARRANT)
        self.assertEqual(stored.path, self.original.path)
        self.assertEqual(stored.text, self.original.text)
        self.assertEqual(self.state_shown(WARRANT), "Approved")

    def test_its_page_says_it_has_been_approved_since(self):
        self.approve(WARRANT)

        page = self.mira.get(self.mod_page(WARRANT))
        self.assertContains(page, "Approved by mira@example.com on")
        self.assertNotContains(page, "Sent back to its Mod Writer</strong>")
        # The sending back stays on record with its reason.
        self.assertContains(page, "The smuggler is dead; rewrite around his partner.")

    def test_a_campaign_chosen_for_a_mod_that_names_one_is_not_written(self):
        self.approve(WARRANT, campaign="tideward")

        self.assertEqual(self.stored(WARRANT).text, self.original.text)


class RefusedApprovals(ApprovingTest):
    def assert_still_a_draft(self, mod, text):
        stored = self.stored(mod)
        self.assertEqual(stored.text, text)
        self.assertEqual(stored.fields["state"], "draft")
        self.assertTrue(stored.path.startswith("inbox/"))

    def test_a_draft_with_no_campaign_needs_one_chosen(self):
        before = self.stored(DAUGHTER).text

        response = self.approve(DAUGHTER)

        self.assertContains(response, "Choose the Campaign")
        self.assert_still_a_draft(DAUGHTER, before)

    def test_a_campaign_the_world_does_not_have_is_refused(self):
        before = self.stored(DAUGHTER).text

        response = self.approve(DAUGHTER, campaign="nowhere")

        self.assertContains(response, "Choose the Campaign")
        self.assert_still_a_draft(DAUGHTER, before)

    def test_a_mod_that_is_not_a_draft_is_not_approved_again(self):
        before = self.stored(WARRANT).text

        response = self.approve(WARRANT)

        self.assertContains(response, "is not a draft")
        self.assertEqual(self.stored(WARRANT).text, before)
        self.assertNotContains(self.mira.get(self.mod_page(WARRANT)),
                               f'action="{self.mod_page(WARRANT)}approve/"')

    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        before = self.stored(DAUGHTER).text

        self.assertNotContains(sam.get(self.mod_page(DAUGHTER)), "approve/")
        response = self.approve(DAUGHTER, campaign="lanternlight", by=sam)

        self.assertEqual(response.status_code, 404)
        self.assert_still_a_draft(DAUGHTER, before)

    def test_approving_only_answers_a_post(self):
        self.assertEqual(self.mira.get(f"{self.mod_page(DAUGHTER)}approve/").status_code, 405)


class ApprovingADraftPlotcanonRefuses(ApprovingTest):
    """A draft may name things the World does not have yet; Canon may not."""

    def setUp(self):
        super().setUp()
        files = plotcanon.sample_world()
        path = f"inbox/{DAUGHTER}.md"
        files[path] = files[path].replace("ysolde-marr]", "ysolde-marr, the-drowned-uncle]")
        self.second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=self.second)
        self.import_files(files, world=self.second)

    def test_the_errors_are_shown_and_nothing_is_saved(self):
        page = f"{self.second}mods/{DAUGHTER}/"

        response = self.mira.post(f"{page}approve/", {"campaign": "lanternlight"}, follow=True)

        findings = response.content.decode().split('<pre class="message', 1)[1]
        self.assertIn("the-drowned-uncle", findings.split("</pre>", 1)[0])
        detail = self.mira.get(page).content.decode()
        self.assertIn('<span class="state">Draft<', detail)
