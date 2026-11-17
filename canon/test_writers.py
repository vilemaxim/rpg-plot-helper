"""Who a Mod's Mod Writer is: the person who submitted it, the person a Plot
Master linked its file's handle to, or the person a Plot Master reassigned it
to. Through web requests, with plotcanon's sample World and script.

In the sample World, Sam's handle `sam` wrote the warrant Mod and the bell
Mod, and Kay's handle `kay` wrote the daughter draft."""

from django.core import mail

from accounts.models import User
from canon.models import Document, WriterHandle
from canon.test_approving import DAUGHTER
from canon.test_mod_submissions import NEW, SubmissionTest, a_mod
from canon.test_resolving import WARRANT
from organizations import tenancy
from organizations.models import Membership
from organizations.tests import sign_in

BELL = "the-bell-beneath"


class WriterTest(SubmissionTest):
    def setUp(self):
        super().setUp()
        self.writers_page = f"{self.first_world}mod-writers/"

    def link(self, handle, email, by=None):
        user = "" if email is None else self.user_id(email)
        return (by or self.mira).post(self.writers_page, {"handle": handle, "user": user},
                                      follow=True)

    def reassign(self, mod, email, by=None):
        return (by or self.mira).post(f"{self.mod_page(mod)}reassign/",
                                      {"user": self.user_id(email)}, follow=True)

    def writer_shown(self, mod):
        page = self.mira.get(self.mod_page(mod)).content.decode()
        if '<p class="writer">' not in page:
            return None
        return page.split('<p class="writer">', 1)[1].split("</p>", 1)[0]

    def files(self):
        with self.in_world():
            return dict(Document.objects.values_list("path", "text"))


class LinkingHandles(WriterTest):
    def test_a_plot_master_sees_each_handle_in_the_worlds_mods(self):
        page = self.mira.get(self.writers_page)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<td class="handle">sam</td>')
        self.assertContains(page, '<td class="handle">kay</td>')
        self.assertContains(self.mira.get(self.first_world), self.writers_page)

    def test_linking_a_handle_makes_its_person_the_writer_of_every_mod_with_it(self):
        self.assertNotIn("sam@example.com", self.writer_shown(WARRANT) or "")

        self.link("sam", "sam@example.com")

        self.assertIn("sam@example.com", self.writer_shown(WARRANT))
        self.assertIn("sam@example.com", self.writer_shown(BELL))
        self.assertNotIn("sam@example.com", self.writer_shown(DAUGHTER) or "")

    def test_a_link_can_be_changed_and_removed(self):
        kay = self.join("kay@example.com")
        self.give("kay@example.com", "mod-writer")
        self.link("kay", "sam@example.com")

        self.link("kay", "kay@example.com")
        self.assertIn("kay@example.com", self.writer_shown(DAUGHTER))

        self.link("kay", None)
        self.assertNotIn("kay@example.com", self.writer_shown(DAUGHTER) or "")
        self.assertEqual(kay.get(f"{self.mod_page(DAUGHTER)}revise/").status_code, 404)

    def test_the_linked_mod_writer_may_revise_a_draft_with_that_handle(self):
        self.assertEqual(self.sam.get(f"{self.mod_page(DAUGHTER)}revise/").status_code, 404)

        self.link("kay", "sam@example.com")

        self.assertEqual(self.sam.get(f"{self.mod_page(DAUGHTER)}revise/").status_code, 200)

    def test_only_someone_who_may_write_mods_in_the_world_can_be_linked(self):
        response = self.link("sam", "rhea@example.com")

        self.assertContains(response, "cannot be the Mod Writer")
        self.assertNotIn("rhea@example.com", self.writer_shown(WARRANT) or "")

    def test_a_handle_no_mod_uses_cannot_be_linked(self):
        response = self.link("nobody", "sam@example.com")

        self.assertContains(response, "No Mod")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        self.assertEqual(self.sam.get(self.writers_page).status_code, 404)
        self.assertEqual(self.link("sam", "sam@example.com", by=self.sam).status_code, 404)
        self.assertNotIn("sam@example.com", self.writer_shown(WARRANT) or "")

    def test_no_file_changes(self):
        before = self.files()

        self.link("sam", "sam@example.com")

        self.assertEqual(self.files(), before)


class SubmittedMods(WriterTest):
    def test_the_submitter_is_the_mod_writer(self):
        self.submit_mod(a_mod())

        self.assertIn("sam@example.com", self.writer_shown(NEW))

    def test_the_submitter_stays_its_writer_whatever_its_handle_is_linked_to(self):
        self.submit_mod(a_mod())      # its file says `mod_writer: kay`
        self.link("kay", "mira@example.com")

        self.assertIn("sam@example.com", self.writer_shown(NEW))


class Reassigning(WriterTest):
    def setUp(self):
        super().setUp()
        self.kay = self.join("kay@example.com")
        self.give("kay@example.com", "mod-writer")
        self.submit_mod(a_mod())

    def test_the_new_mod_writer_may_revise_it_and_the_old_one_may_not(self):
        self.reassign(NEW, "kay@example.com")

        self.assertIn("kay@example.com", self.writer_shown(NEW))
        self.revise(NEW, a_mod(title="Kay's Version"), by=self.kay)
        self.assertEqual(self.stored(NEW).name, "Kay's Version")
        self.assertEqual(self.revise(NEW, a_mod(), by=self.sam).status_code, 404)
        self.assertEqual(self.sam.get(self.mod_page(NEW)).status_code, 404)

    def test_an_imported_draft_can_be_given_a_mod_writer(self):
        self.reassign(DAUGHTER, "sam@example.com")

        self.assertEqual(self.sam.get(f"{self.mod_page(DAUGHTER)}revise/").status_code, 200)

    def test_it_says_who_reassigned_it_and_when(self):
        self.reassign(NEW, "kay@example.com")

        self.assertContains(self.mira.get(self.mod_page(NEW)),
                            "reassigned by mira@example.com on")

    def test_the_draft_offers_a_plot_master_the_form(self):
        page = self.mira.get(self.mod_page(NEW))

        self.assertContains(page, f'action="{self.mod_page(NEW)}reassign/"')
        self.assertContains(page, f'<option value="{self.user_id("kay@example.com")}"')
        # Someone who only runs Mods is not offered.
        self.assertNotContains(page, f'<option value="{self.user_id("rhea@example.com")}"')

    def test_no_file_changes(self):
        before = self.files()

        self.reassign(NEW, "kay@example.com")

        self.assertEqual(self.files(), before)

    def test_only_to_someone_who_may_write_mods_in_the_world(self):
        response = self.reassign(NEW, "rhea@example.com")

        self.assertContains(response, "cannot be the Mod Writer")
        self.assertIn("sam@example.com", self.writer_shown(NEW))

    def test_only_a_draft(self):
        response = self.reassign(WARRANT, "kay@example.com")

        self.assertContains(response, "Only a draft")
        self.assertNotContains(self.mira.get(self.mod_page(WARRANT)), "reassign/")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        self.assertNotContains(self.sam.get(self.mod_page(NEW)), "reassign/")
        self.assertEqual(self.reassign(NEW, "kay@example.com", by=self.sam).status_code, 404)
        self.assertIn("sam@example.com", self.writer_shown(NEW))


class SendingBack(WriterTest):
    REASON = "The smuggler is dead; rewrite around his partner."

    def setUp(self):
        super().setUp()
        mail.outbox = []      # the invitations sent as people joined

    def send_back_and_mail(self, mod):
        with self.captureOnCommitCallbacks(execute=True):
            self.send_back(mod, reason=self.REASON)

    def test_its_mod_writer_is_emailed_the_reason_and_a_link(self):
        self.link("sam", "sam@example.com")

        self.send_back_and_mail(WARRANT)

        [sent] = mail.outbox
        self.assertEqual(sent.to, ["sam@example.com"])
        self.assertIn("A Warrant for Dunmore", sent.subject)
        self.assertIn(self.REASON, sent.body)
        self.assertIn("mira@example.com", sent.body)
        self.assertIn(f"http://testserver{self.mod_page(WARRANT)}", sent.body)

    def test_a_mod_with_no_mod_writer_known_emails_nobody(self):
        response = self.send_back(WARRANT, reason=self.REASON)

        self.assertEqual(mail.outbox, [])
        self.assertContains(response, "No Mod Writer")

    def test_a_mod_writer_sees_their_mods_sent_back_on_the_world_page(self):
        self.link("sam", "sam@example.com")
        self.send_back_and_mail(WARRANT)

        page = self.sam.get(self.first_world).content.decode()

        mine = page.split('<section class="my-drafts">', 1)[1].split("</section>", 1)[0]
        self.assertIn(f"mods/{WARRANT}/", mine)
        self.assertIn("sent back", mine)

    def test_a_mod_sent_back_with_no_flags_is_still_marked(self):
        self.link("sam", "sam@example.com")
        for flag in self.flags_on(WARRANT):
            self.dismiss(flag)

        self.send_back_and_mail(WARRANT)

        page = self.sam.get(self.first_world).content.decode()
        mine = page.split('<section class="my-drafts">', 1)[1].split("</section>", 1)[0]
        self.assertIn("sent back", mine)
        self.assertContains(self.mira.get(self.mod_page(WARRANT)),
                            "Sent back to its Mod Writer</strong> by mira@example.com")
        self.assertEqual(len(mail.outbox), 1)

    def test_a_draft_reassigned_since_is_not_marked_as_sent_back_to_its_new_writer(self):
        self.link("sam", "sam@example.com")
        self.send_back_and_mail(WARRANT)
        kay = self.join("kay@example.com")
        self.give("kay@example.com", "mod-writer")

        self.reassign(WARRANT, "kay@example.com")

        mine = kay.get(self.first_world).content.decode() \
            .split('<section class="my-drafts">', 1)[1].split("</section>", 1)[0]
        self.assertIn(f"mods/{WARRANT}/", mine)
        self.assertNotIn("sent back", mine)

    def test_a_mod_writer_who_has_lost_the_role_is_not_emailed(self):
        self.link("sam", "sam@example.com")
        self.take("sam@example.com", "mod-writer")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.send_back(WARRANT, reason=self.REASON)

        self.assertEqual(mail.outbox, [])
        self.assertContains(response, "no longer writes Mods here")

    def test_nobody_else_sees_them_as_theirs(self):
        self.link("sam", "sam@example.com")
        self.send_back_and_mail(WARRANT)

        self.assertNotContains(self.rhea.get(self.first_world), 'class="my-drafts"')


class TheDatabaseOnItsOwn(WriterTest):
    def test_another_organization_sees_no_handle_links(self):
        self.link("sam", "sam@example.com")
        sign_in("eve@example.com")
        eve = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=eve):
            organization = Membership.objects.get().organization_id

        with tenancy.acting_as(user=eve, organization=organization):
            self.assertEqual(WriterHandle.objects.count(), 0)
        with self.in_world():
            self.assertEqual(WriterHandle.objects.count(), 1)
