"""Renaming an Organization and a World, through web requests."""

from django.core import mail

from organizations.test_people import ORGANIZATION, PeopleTest
from organizations.tests import sign_in


class RenamingTest(PeopleTest):
    """Mira is Organization Admin and Plot Master of her first World. Sam is a
    member with a role that is not Plot Master. Eve is in another Organization."""

    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        self.eve = sign_in("eve@example.com")
        self.rename_page = f"{self.first_world}rename/"

    def rename_organization(self, name, by=None):
        return (by or self.mira).post(f"{ORGANIZATION}name/", {"name": name}, follow=True)

    def rename_world(self, name, by=None, world=None):
        address = f"{world or self.first_world}rename/"
        return (by or self.mira).post(address, {"name": name}, follow=True)


class RenamingAnOrganization(RenamingTest):
    def test_an_organization_admin_changes_the_name(self):
        self.rename_organization("Greymoor Plot Team")

        response = self.mira.get(self.first_world)

        self.assertContains(response, "Greymoor Plot Team")
        self.assertNotContains(response, "My Organization")

    def test_everyone_in_the_organization_sees_the_new_name(self):
        self.rename_organization("Greymoor Plot Team")

        self.assertContains(self.sam.get(self.first_world), "Greymoor Plot Team")

    def test_the_world_page_links_to_it_for_an_organization_admin_only(self):
        link = f'href="{ORGANIZATION}#name"'

        self.assertContains(self.mira.get(self.first_world), link)
        self.assertNotContains(self.sam.get(self.first_world), link)

    def test_the_organization_page_offers_the_current_name_to_edit(self):
        self.rename_organization("Greymoor Plot Team")

        self.assertContains(self.mira.get(ORGANIZATION), 'value="Greymoor Plot Team"')

    def test_a_blank_name_is_refused(self):
        response = self.rename_organization("   ")

        self.assertContains(response, "This field is required")
        self.assertContains(self.mira.get(self.first_world), "My Organization")

    def test_a_name_with_nothing_visible_in_it_is_refused(self):
        for invisible in ("\u200b", "\ufeff\u200b", "\u200b \u2060"):
            with self.subTest(repr(invisible)):
                response = self.rename_organization(invisible)

                self.assertContains(response, "Enter a name people can see")
        self.assertContains(self.mira.get(self.first_world), "My Organization")

    def test_characters_that_reverse_or_control_text_are_refused(self):
        for sneaky in ("Team\u202egnp.exe", "Team\x01", "Te\x7fam"):
            with self.subTest(repr(sneaky)):
                response = self.rename_organization(sneaky)

                self.assertContains(response, "cannot be used in a name")

    def test_line_breaks_and_runs_of_spaces_become_single_spaces(self):
        self.rename_organization("  Greymoor\r\nPlot \t  Team ")

        self.assertContains(self.mira.get(ORGANIZATION), 'value="Greymoor Plot Team"')

    def test_invitations_still_send_after_a_rename_with_a_line_break(self):
        self.rename_organization("Greymoor\nBcc: victim@example.com")

        response = self.invite("friend@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ["friend@example.com"])
        self.assertEqual(mail.outbox[-1].subject,
                         "You are invited to Greymoor Bcc: victim@example.com on RPG Plot Helper")

    def test_a_name_in_another_script_is_accepted(self):
        for name in ("グレイムーア", "مجموعة الحبكة", "Ærø og Søn 🎲"):
            with self.subTest(name):
                self.rename_organization(name)

                self.assertContains(self.mira.get(ORGANIZATION), name)

    def test_a_name_is_shown_as_typed_not_run_as_markup(self):
        self.rename_organization('<script>alert("x")</script>')

        response = self.mira.get(self.first_world)

        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;script&gt;")

    def test_someone_who_is_not_an_organization_admin_cannot(self):
        response = self.rename_organization("Sam's Now", by=self.sam)

        self.assertEqual(response.status_code, 404)
        self.assertContains(self.mira.get(self.first_world), "My Organization")

    def test_a_person_in_another_organization_changes_only_their_own(self):
        self.rename_organization("Eve's Team", by=self.eve)

        self.assertContains(self.mira.get(self.first_world), "My Organization")
        self.assertContains(self.eve.get("/", follow=True), "Eve&#x27;s Team")

    def test_it_cannot_be_done_with_a_link(self):
        self.assertEqual(self.mira.get(f"{ORGANIZATION}name/").status_code, 405)
        self.assertEqual(self.sam.get(f"{ORGANIZATION}name/").status_code, 404)

    def test_the_new_name_tells_two_organizations_apart_when_switching(self):
        sign_in("pat@example.com")
        self.rename_organization("Greymoor Plot Team")
        pat = self.join("pat@example.com")

        response = pat.get("/")

        self.assertContains(response, "Greymoor Plot Team")
        self.assertContains(response, "My Organization")


class RenamingAWorld(RenamingTest):
    def test_a_plot_master_changes_the_name(self):
        self.rename_world("The Shattered Coast")

        response = self.mira.get(self.first_world)

        self.assertContains(response, "The Shattered Coast")
        self.assertNotContains(response, "My first World")

    def test_the_worlds_address_does_not_change(self):
        response = self.rename_world("The Shattered Coast")

        self.assertEqual(response.redirect_chain[-1][0], self.first_world)
        self.assertEqual(self.mira.get(self.first_world).status_code, 200)

    def test_the_rename_page_offers_the_current_name_to_edit(self):
        response = self.mira.get(self.rename_page)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="My first World"')

    def test_the_world_page_links_to_it_for_a_plot_master_only(self):
        self.assertContains(self.mira.get(self.first_world), self.rename_page)
        self.assertNotContains(self.sam.get(self.first_world), self.rename_page)

    def test_a_blank_name_is_refused(self):
        response = self.rename_world("")

        self.assertContains(response, "This field is required")
        self.assertContains(self.mira.get(self.first_world), "My first World")

    def test_sending_no_name_at_all_is_refused_with_a_message(self):
        response = self.mira.post(self.rename_page, {})

        self.assertContains(response, "This field is required")

    def test_a_name_with_nothing_visible_in_it_is_refused(self):
        response = self.rename_world("\u200b")

        self.assertContains(response, "Enter a name people can see")

    def test_a_new_world_cannot_be_given_an_invisible_name_either(self):
        response = self.make_world("\u200b")

        self.assertContains(response, "Enter a name people can see")

    def test_someone_with_another_role_in_the_world_cannot(self):
        self.assertEqual(self.sam.get(self.rename_page).status_code, 404)

        response = self.rename_world("Sam's World", by=self.sam)

        self.assertEqual(response.status_code, 404)
        self.assertContains(self.mira.get(self.first_world), "My first World")

    def test_a_plot_master_who_is_not_an_organization_admin_can(self):
        self.give("sam@example.com", "plot-master")

        self.rename_world("Sam's World", by=self.sam)

        self.assertContains(self.mira.get(self.first_world), "Sam&#x27;s World")

    def test_an_organization_admin_who_is_not_its_plot_master_can(self):
        second = self.make_world("Second World")

        self.rename_world("Renamed", world=second)

        self.assertContains(self.mira.get(second), "Renamed")

    def test_a_person_in_another_organization_gets_not_found(self):
        self.assertEqual(self.eve.get(self.rename_page).status_code, 404)

        response = self.rename_world("Eve's World", by=self.eve)

        self.assertEqual(response.status_code, 404)
        self.assertContains(self.mira.get(self.first_world), "My first World")

    def test_a_signed_out_person_is_sent_to_sign_in(self):
        response = self.client.get(self.rename_page)

        self.assertRedirects(response, f"/sign-in/?next={self.rename_page}")
