"""An Organization Admin removing members, withdrawing invitations and
choosing who else is an Organization Admin, through web requests."""

import re
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import override_settings

from accounts.models import User
from organizations import tenancy
from organizations.models import Membership
from organizations.test_people import ORGANIZATION, PeopleTest
from organizations.tests import sign_in, world_address

INVITATIONS = "/invitations/"


class MembersTest(PeopleTest):
    """Sam belongs to Mira's Organization with a role in her first World."""

    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

    def button(self, email, action, by=None):
        """The address of a button shown beside this email address on the
        Organization page, or None if there is none."""
        page = (by or self.mira).get(ORGANIZATION).content.decode()
        for item in re.findall(r"<li[^>]*>(.*?)</li>", page, re.S):
            if email in item:
                found = re.search(rf'action="([^"]*/{action}/)"', item)
                if found:
                    return found.group(1)
        return None

    def press(self, email, action, by=None):
        address = self.button(email, action, by)
        assert address, f"no {action} button for {email}"
        return (by or self.mira).post(address, follow=True)


class RemovingAMember(MembersTest):
    def test_a_removed_member_can_open_none_of_its_worlds(self):
        self.press("sam@example.com", "remove")

        self.assertEqual(self.sam.get(self.first_world).status_code, 404)
        self.assertNotContains(self.mira.get(ORGANIZATION), "sam@example.com")

    def test_their_roles_go_and_they_can_be_invited_again(self):
        self.press("sam@example.com", "remove")

        self.assertNotContains(self.mira.get(f"{self.first_world}people/"), "sam@example.com")
        self.invite("sam@example.com")
        self.decide(self.sam, "accept")
        self.assertContains(self.mira.get(ORGANIZATION), "sam@example.com")
        # Back in, but with none of the roles they had before.
        self.assertEqual(self.sam.get(self.first_world).status_code, 404)

    def test_their_account_and_other_organizations_are_untouched(self):
        pat = sign_in("pat@example.com")
        own_world = pat.get("/", follow=True).redirect_chain[-1][0]
        self.invite("pat@example.com")
        self.decide(pat, "accept")

        self.press("pat@example.com", "remove")

        self.assertEqual(pat.get(own_world).status_code, 200)
        self.assertRedirects(pat.get("/"), own_world)


class RemovedFromTheirOnlyOrganization(MembersTest):
    """Sam joined by invitation, so Mira's is his only Organization. Removed
    from it, he belongs nowhere; signing in again gives him what sign-up would
    give anyone in that position (ADR-0005)."""

    def test_with_sign_up_open_the_next_sign_in_gives_them_one_of_their_own(self):
        self.press("sam@example.com", "remove")

        sam = sign_in("sam@example.com")

        own_world = world_address(sam)
        self.assertNotEqual(own_world, self.first_world)
        page = sam.get(own_world)
        self.assertContains(page, "My first World")
        self.assertEqual(sam.get(ORGANIZATION).status_code, 200)
        with tenancy.acting_as(user=self.user_id("sam@example.com")):
            [membership] = Membership.objects.filter(user__email="sam@example.com")
            self.assertTrue(membership.is_admin)
            self.assertEqual(membership.organization.name, "My Organization")

    def test_with_sign_up_closed_the_next_sign_in_needs_an_invitation(self):
        self.press("sam@example.com", "remove")

        with override_settings(OPEN_SIGN_UP=False):
            sam = sign_in("sam@example.com")
            response = sam.get("/")

        self.assertContains(response, "You need an invitation")
        with tenancy.acting_as(user=self.user_id("sam@example.com")):
            self.assertFalse(Membership.objects.filter(user__email="sam@example.com").exists())

    def test_with_an_invitation_waiting_they_answer_it_first(self):
        self.press("sam@example.com", "remove")
        self.invite("sam@example.com")

        sam = sign_in("sam@example.com")

        self.assertRedirects(sam.get("/"), INVITATIONS)
        with tenancy.acting_as(user=self.user_id("sam@example.com")):
            self.assertFalse(Membership.objects.filter(user__email="sam@example.com").exists())


class WithdrawingAnInvitation(MembersTest):
    def setUp(self):
        super().setUp()
        self.invite("lee@example.com")

    @override_settings(OPEN_SIGN_UP=False)
    def test_signing_in_with_a_withdrawn_address_does_not_offer_it_or_join(self):
        self.press("lee@example.com", "withdraw")

        self.assertNotContains(self.mira.get(ORGANIZATION), "lee@example.com")
        lee = sign_in("lee@example.com")
        response = lee.get("/", follow=True)
        self.assertNotContains(response, "invited you to join")
        self.assertContains(response, "You need an invitation")
        self.assertEqual(lee.get(INVITATIONS).status_code, 200)
        self.assertNotContains(lee.get(INVITATIONS), "My Organization")

    def test_a_withdrawn_address_can_be_invited_again(self):
        self.press("lee@example.com", "withdraw")

        self.invite("lee@example.com")

        self.assertContains(sign_in("lee@example.com").get("/", follow=True),
                            "invited you to join")


class ChoosingOrganizationAdmins(MembersTest):
    def test_a_member_made_organization_admin_can_open_the_organization_page(self):
        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 404)

        self.press("sam@example.com", "make-admin")

        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 200)
        self.assertContains(self.mira.get(ORGANIZATION), "sam@example.com — Organization Admin")

    def test_an_organization_admin_stops_another_being_one(self):
        self.press("sam@example.com", "make-admin")

        self.press("sam@example.com", "stop-admin")

        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 404)
        self.assertNotContains(self.mira.get(ORGANIZATION),
                               "sam@example.com — Organization Admin")

    def test_a_new_organization_admin_can_demote_the_one_who_made_them(self):
        self.press("sam@example.com", "make-admin")

        self.press("mira@example.com", "stop-admin", by=self.sam)

        self.assertEqual(self.mira.get(ORGANIZATION).status_code, 404)
        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 200)


class TheLastOrganizationAdmin(MembersTest):
    """Mira is the only Organization Admin."""

    def assert_still_the_admin(self):
        self.assertContains(self.mira.get(ORGANIZATION), "mira@example.com — Organization Admin")

    def test_cannot_be_demoted_and_is_told_why(self):
        response = self.press("mira@example.com", "stop-admin")

        self.assertContains(response, "the only Organization Admin")
        self.assert_still_the_admin()

    def test_cannot_be_removed_and_is_told_why(self):
        response = self.press("mira@example.com", "remove")

        self.assertContains(response, "the only Organization Admin")
        self.assert_still_the_admin()
        self.assertEqual(self.mira.get(self.first_world).status_code, 200)

    def test_with_a_second_one_either_can_step_down_or_be_removed(self):
        self.press("sam@example.com", "make-admin")

        response = self.press("mira@example.com", "stop-admin")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mira.get(ORGANIZATION).status_code, 404)
        response = self.press("sam@example.com", "remove", by=self.sam)
        self.assertContains(response, "the only Organization Admin")
        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 200)

    def test_an_organization_admin_can_remove_themselves_while_another_remains(self):
        self.press("sam@example.com", "make-admin")

        response = self.press("mira@example.com", "remove")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mira.get(self.first_world).status_code, 404)
        self.assertNotContains(self.sam.get(ORGANIZATION), "mira@example.com")


class OnlyAnOrganizationAdmin(MembersTest):
    """Sam is a member but not an Organization Admin. Eve is Organization
    Admin of another Organization altogether. Pat is a second member, and
    lee@example.com is invited."""

    def setUp(self):
        super().setUp()
        self.pat = self.join("pat@example.com")
        self.invite("lee@example.com")
        self.eve = sign_in("eve@example.com")
        self.addresses = [
            self.button("pat@example.com", "remove"),
            self.button("pat@example.com", "make-admin"),
            self.button("mira@example.com", "stop-admin"),
            self.button("mira@example.com", "remove"),
            self.button("lee@example.com", "withdraw"),
        ]

    def test_can_do_none_of_it(self):
        for browser in (self.sam, self.eve):
            for address in self.addresses:
                self.assertEqual(browser.post(address).status_code, 404, address)

        page = self.mira.get(ORGANIZATION)
        self.assertContains(page, "pat@example.com")
        self.assertNotContains(page, "pat@example.com — Organization Admin")
        self.assertContains(page, "mira@example.com — Organization Admin")
        self.assertContains(page, "lee@example.com")
        self.assertEqual(self.pat.get(ORGANIZATION).status_code, 404)

    def test_the_actions_cannot_be_reached_with_a_link(self):
        for address in self.addresses:
            self.assertEqual(self.mira.get(address).status_code, 405, address)



class OnTheServer(MembersTest):
    """Mira's Organization, Greymoor Plot Team, has somehow been left with no
    Organization Admin, and sign-up is closed, so nobody can get in to fix it.
    Pat belongs to it and also runs an Organization of his own, Pat's Table."""

    def setUp(self):
        super().setUp()
        self.mira.post(f"{ORGANIZATION}name/", {"name": "Greymoor Plot Team"})
        self.pat = sign_in("pat@example.com")
        self.pat.post(f"{ORGANIZATION}name/", {"name": "Pat's Table"})
        self.invite("pat@example.com")
        self.decide(self.pat, "accept")
        mira = User.objects.get(email="mira@example.com")
        self.greymoor = self.organizations_of(mira)["Greymoor Plot Team"]
        with tenancy.acting_as(user=mira, organization=self.greymoor):
            Membership.objects.filter(organization=self.greymoor).update(is_admin=False)
        sign_up_closed = override_settings(OPEN_SIGN_UP=False)
        sign_up_closed.enable()
        self.addCleanup(sign_up_closed.disable)

    def organizations_of(self, user):
        with tenancy.acting_as(user=user):
            return {m.organization.name: m.organization_id
                    for m in Membership.objects.filter(user=user).select_related("organization")}

    def run_command(self, *args):
        out = StringIO()
        call_command("make_organization_admin", *args, stdout=out)
        return out.getvalue()

    def test_names_a_member_organization_admin(self):
        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 404)

        output = self.run_command("sam@example.com")

        self.assertIn("sam@example.com is now Organization Admin of Greymoor Plot Team", output)
        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 200)
        self.assertEqual(self.mira.get(ORGANIZATION).status_code, 404)

    def test_the_address_is_matched_whatever_its_capitalisation(self):
        self.run_command("Sam@Example.com")

        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 200)

    def test_someone_in_several_organizations_must_say_which(self):
        with self.assertRaisesMessage(CommandError, "Greymoor Plot Team"):
            self.run_command("pat@example.com")

        self.assertEqual(self.pat.get(ORGANIZATION).status_code, 404)

    def test_an_organization_is_named_by_its_name(self):
        self.run_command("pat@example.com", "--organization", "Greymoor Plot Team")

        self.assertEqual(self.pat.get(ORGANIZATION).status_code, 200)
        self.assertContains(self.pat.get(ORGANIZATION), "Greymoor Plot Team")

    def test_an_organization_they_do_not_belong_to_is_refused_by_name(self):
        with self.assertRaisesMessage(CommandError, "Pat's Table"):
            self.run_command("sam@example.com", "--organization", "Pat's Table")

    def test_an_organization_named_by_its_id_can_take_someone_new(self):
        eve = sign_in("eve@example.com")
        self.assertContains(eve.get("/"), "You need an invitation")

        output = self.run_command("eve@example.com", "--organization", str(self.greymoor))

        self.assertIn("Greymoor Plot Team", output)
        self.assertContains(eve.get(ORGANIZATION), "Greymoor Plot Team")

    def test_an_id_that_is_no_organization_is_refused(self):
        with self.assertRaisesMessage(CommandError, "No Organization"):
            self.run_command("sam@example.com", "--organization",
                             "00000000-0000-4000-8000-000000000000")

    def test_someone_with_no_account_is_refused(self):
        with self.assertRaisesMessage(CommandError, "nobody@example.com"):
            self.run_command("nobody@example.com")
