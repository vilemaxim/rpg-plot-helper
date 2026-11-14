"""Worlds, invitations, roles and switching Organization, through web requests."""

import re

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from accounts.models import User
from organizations import tenancy
from organizations.models import Invitation, Membership, World, WorldRole
from organizations.tests import sign_in, world_address

ORGANIZATION = "/organization/"
NOT_A_WORLD = "00000000-0000-4000-8000-000000000000"


def world_id(address):
    return re.fullmatch(r"/worlds/([0-9a-f-]{36})/", address).group(1)


@override_settings(OPEN_SIGN_UP=True)
class PeopleTest(TestCase):
    """Mira signed up and is Organization Admin of her own Organization."""

    def setUp(self):
        self.mira = sign_in("mira@example.com")
        self.first_world = world_address(self.mira)

    def invite(self, email, by=None):
        return (by or self.mira).post(f"{ORGANIZATION}invitations/", {"email": email},
                                      follow=True)

    def join(self, email):
        """Invite this address and sign in as it. Returns their browser."""
        self.invite(email)
        return sign_in(email)

    def user_id(self, email):
        return User.objects.get(email=email).pk

    def give(self, email, role, world=None, by=None):
        address = f"{world or self.first_world}roles/"
        return (by or self.mira).post(address, {"user": self.user_id(email), "role": role},
                                      follow=True)

    def take(self, email, role, world=None, by=None):
        address = f"{world or self.first_world}roles/remove/"
        return (by or self.mira).post(address, {"user": self.user_id(email), "role": role},
                                      follow=True)

    def make_world(self, name, by=None):
        response = (by or self.mira).post(f"{ORGANIZATION}worlds/", {"name": name})
        return response["Location"] if response.status_code == 302 else response


class MoreWorlds(PeopleTest):
    def test_an_organization_admin_creates_a_second_world(self):
        address = self.make_world("The Shattered Coast")

        self.assertRegex(address, r"^/worlds/[0-9a-f-]{36}/$")
        self.assertNotEqual(address, self.first_world)
        self.assertContains(self.mira.get(address), "The Shattered Coast")

    def test_with_two_worlds_the_home_page_lists_them(self):
        self.make_world("The Shattered Coast")

        response = self.mira.get("/")

        self.assertContains(response, "My first World")
        self.assertContains(response, "The Shattered Coast")

    def test_a_world_needs_a_name(self):
        response = self.make_world("   ")

        self.assertContains(response, "This field is required")
        self.assertNotContains(self.mira.get(ORGANIZATION), "<li>   </li>")

    def test_the_organization_page_lists_its_worlds_and_people(self):
        response = self.mira.get(ORGANIZATION)

        self.assertContains(response, "My first World")
        self.assertContains(response, "mira@example.com")


class Invitations(PeopleTest):
    def test_the_invited_address_is_emailed_a_link_to_sign_in(self):
        response = self.invite("sam@example.com")

        self.assertContains(response, "sam@example.com")
        message = mail.outbox[-1]
        self.assertEqual(message.to, ["sam@example.com"])
        self.assertIn("mira@example.com", message.body)
        self.assertIn("My Organization", message.body)
        self.assertIn("http://testserver/sign-in/?email=sam%40example.com", message.body)

    def test_the_link_opens_sign_in_with_the_address_filled_in(self):
        self.invite("sam@example.com")

        response = self.client.get("/sign-in/?email=sam%40example.com")

        self.assertContains(response, 'value="sam@example.com"')

    def test_until_they_sign_in_the_invitation_is_shown_as_waiting(self):
        self.invite("sam@example.com")

        response = self.mira.get(ORGANIZATION)

        self.assertContains(response, "Invited, not yet joined")
        self.assertContains(response, "sam@example.com")

    def test_signing_in_with_that_address_joins_the_organization(self):
        self.join("sam@example.com")

        response = self.mira.get(ORGANIZATION)

        self.assertNotContains(response, "Invited, not yet joined")
        self.assertContains(response, "sam@example.com")

    def test_someone_already_signed_in_joins_by_following_the_link(self):
        sam = sign_in("sam@example.com")
        self.invite("sam@example.com")

        response = sam.get("/sign-in/?email=sam%40example.com", follow=True)

        self.assertContains(response, "you do not have a role in any World")
        self.assertNotContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")

    def test_someone_signed_in_with_another_address_is_told_which_one_was_invited(self):
        eve = sign_in("eve@example.com")
        self.invite("sam@example.com")

        response = eve.get("/sign-in/?email=sam%40example.com")

        self.assertContains(response, "You are signed in as")
        self.assertContains(response, "eve@example.com")
        self.assertContains(response, "sam@example.com")
        self.assertContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")

    def test_the_new_member_is_not_an_organization_admin_and_has_no_world_yet(self):
        sam = self.join("sam@example.com")

        self.assertContains(sam.get("/"), "you do not have a role in any World")
        self.assertEqual(sam.get(ORGANIZATION).status_code, 404)
        self.assertEqual(sam.get(self.first_world).status_code, 404)

    def test_an_invited_person_does_not_also_get_an_organization_of_their_own(self):
        self.join("sam@example.com")

        sam = User.objects.get(email="sam@example.com")
        with tenancy.acting_as(user=sam):
            self.assertEqual(Membership.objects.count(), 1)

    def test_the_address_is_matched_whatever_its_capitalisation(self):
        self.invite(" Sam@Example.COM ")

        sam = sign_in("sam@example.com")

        self.assertContains(sam.get("/"), "you do not have a role in any World")

    def test_inviting_the_same_address_twice_sends_again_without_a_second_invitation(self):
        self.invite("sam@example.com")
        self.invite("sam@example.com")

        self.assertEqual([m.to for m in mail.outbox[-2:]],
                         [["sam@example.com"], ["sam@example.com"]])
        self.assertEqual(self.mira.get(ORGANIZATION).content.decode().count("sam@example.com"), 1)

    def test_inviting_someone_who_already_belongs_is_refused(self):
        self.join("sam@example.com")
        before = len(mail.outbox)

        response = self.invite("sam@example.com")

        self.assertContains(response, "already belongs to this Organization")
        self.assertEqual(len(mail.outbox), before)

    def test_an_address_too_long_to_be_real_is_refused(self):
        response = self.invite("a" * 300 + "@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at most 254 characters")

    def test_something_that_is_not_an_email_is_refused(self):
        before = len(mail.outbox)

        response = self.invite("sam at example")

        self.assertContains(response, "Enter a valid email address")
        self.assertEqual(len(mail.outbox), before)

    @override_settings(OPEN_SIGN_UP=False)
    def test_an_invitation_is_how_people_join_when_sign_up_is_closed(self):
        sam = self.join("sam@example.com")

        self.assertNotContains(sam.get("/"), "You need an invitation")
        self.assertContains(sam.get("/"), "you do not have a role in any World")


class Roles(PeopleTest):
    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.second_world = self.make_world("The Shattered Coast")

    def test_an_organization_admin_gives_a_person_a_role_in_one_world(self):
        self.give("sam@example.com", "mod-writer")

        response = self.sam.get(self.first_world)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mod Writer")
        self.assertNotContains(response, "Organization Admin")

    def test_a_role_in_one_world_does_not_open_another_in_the_same_organization(self):
        self.give("sam@example.com", "mod-writer")

        self.assertEqual(self.sam.get(self.first_world).status_code, 200)
        self.assertEqual(self.sam.get(self.second_world).status_code, 404)

    def test_with_one_world_open_to_them_home_goes_straight_there(self):
        self.give("sam@example.com", "mod-writer")

        self.assertRedirects(self.sam.get("/"), self.first_world)

    def test_a_person_can_hold_several_roles_in_a_world(self):
        self.give("sam@example.com", "mod-writer")
        self.give("sam@example.com", "mod-runner")

        response = self.sam.get(self.first_world)

        self.assertContains(response, "Mod Writer")
        self.assertContains(response, "Mod Runner")

    def test_giving_the_same_role_twice_changes_nothing(self):
        self.give("sam@example.com", "mod-writer")

        response = self.give("sam@example.com", "mod-writer")

        self.assertEqual(response.status_code, 200)

    def test_an_organization_admin_removes_a_role(self):
        self.give("sam@example.com", "mod-writer")
        self.give("sam@example.com", "mod-runner")

        self.take("sam@example.com", "mod-writer")

        response = self.sam.get(self.first_world)
        self.assertNotContains(response, "Mod Writer")
        self.assertContains(response, "Mod Runner")

    def test_removing_their_last_role_closes_the_world_to_them(self):
        self.give("sam@example.com", "mod-writer")

        self.take("sam@example.com", "mod-writer")

        self.assertEqual(self.sam.get(self.first_world).status_code, 404)

    def test_the_people_page_shows_who_holds_what(self):
        self.give("sam@example.com", "mod-writer")

        response = self.mira.get(f"{self.first_world}people/")

        self.assertContains(response, "sam@example.com")
        self.assertContains(response, "Mod Writer")
        self.assertContains(response, "Plot Master")

    def test_a_role_that_does_not_exist_is_refused(self):
        response = self.give("sam@example.com", "dungeon-master")

        self.assertEqual(response.status_code, 400)

    def test_a_person_outside_the_organization_cannot_be_given_a_role(self):
        sign_in("stranger@example.com")

        response = self.give("stranger@example.com", "mod-writer")

        self.assertEqual(response.status_code, 400)


class OnlyAnOrganizationAdmin(PeopleTest):
    """Sam belongs to Mira's Organization and is a Plot Master, but not an
    Organization Admin. Eve belongs to another Organization altogether."""

    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "plot-master")
        self.eve = sign_in("eve@example.com")
        mail.outbox.clear()

    def assert_refused(self, response):
        self.assertEqual(response.status_code, 404)

    def test_cannot_open_the_organization_or_people_pages(self):
        for browser in (self.sam, self.eve):
            self.assert_refused(browser.get(f"{self.first_world}people/"))
        self.assert_refused(self.sam.get(ORGANIZATION))

    def test_cannot_invite_people(self):
        self.assert_refused(self.invite("friend@example.com", by=self.sam))

        self.assertEqual(mail.outbox, [])
        self.assertNotContains(self.mira.get(ORGANIZATION), "friend@example.com")

    def test_cannot_give_a_role(self):
        for browser in (self.sam, self.eve):
            self.assert_refused(self.give("sam@example.com", "mod-runner", by=browser))

        self.assertNotContains(self.sam.get(self.first_world), "Mod Runner")

    def test_cannot_remove_a_role(self):
        for browser in (self.sam, self.eve):
            self.assert_refused(self.take("sam@example.com", "plot-master", by=browser))

        self.assertContains(self.sam.get(self.first_world), "Plot Master")

    def test_cannot_create_a_world(self):
        self.assert_refused(self.make_world("Sam's Secret World", by=self.sam))

        self.assertNotContains(self.mira.get(ORGANIZATION), "Secret World")

    def test_an_admin_of_one_organization_cannot_touch_anothers_world(self):
        response = self.eve.post(f"{self.first_world}roles/",
                                 {"user": self.user_id("eve@example.com"), "role": "plot-master"})

        self.assert_refused(response)
        self.assertEqual(self.eve.get(self.first_world).status_code, 404)

    def test_the_actions_do_not_reveal_themselves_to_anyone_else(self):
        """A wrong kind of request gets "not found" too, not a hint that the
        address is real."""
        for address in (f"{ORGANIZATION}invitations/", f"{ORGANIZATION}worlds/",
                        f"{self.first_world}roles/", f"{self.first_world}roles/remove/"):
            self.assert_refused(self.sam.get(address))
        self.assert_refused(self.sam.post(ORGANIZATION))

    def test_the_actions_cannot_be_reached_with_a_link(self):
        for address in (f"{ORGANIZATION}invitations/", f"{ORGANIZATION}worlds/",
                        f"{self.first_world}roles/", f"{self.first_world}roles/remove/",
                        f"{ORGANIZATION}switch/"):
            self.assertEqual(self.mira.get(address).status_code, 405, address)


class TwoOrganizations(PeopleTest):
    """Sam signed up on his own, so has his own Organization, and was then
    invited into Mira's."""

    def setUp(self):
        super().setUp()
        sign_in("sam@example.com")
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        user = User.objects.get(email="sam@example.com")
        with tenancy.acting_as(user=user):
            self.sams_own, self.miras = [str(m.organization_id) for m in
                                         Membership.objects.order_by("joined_at")]

    def switch(self, organization, browser=None):
        return (browser or self.sam).post(f"{ORGANIZATION}switch/",
                                          {"organization": organization}, follow=True)

    def test_a_person_in_two_organizations_is_offered_a_way_to_switch(self):
        response = self.sam.get("/", follow=True)

        self.assertContains(response, f"{ORGANIZATION}switch/")

    def test_a_person_in_one_organization_is_not(self):
        response = self.mira.get("/", follow=True)

        self.assertNotContains(response, f"{ORGANIZATION}switch/")

    def test_switching_changes_which_organization_they_work_in(self):
        in_own = self.switch(self.sams_own)
        self.assertContains(in_own, "Organization Admin")

        in_miras = self.switch(self.miras)

        self.assertNotContains(in_miras, "Organization Admin")
        self.assertContains(in_miras, "Mod Writer")

    def test_the_choice_is_remembered_between_pages(self):
        self.switch(self.miras)

        self.assertEqual(self.sam.get(self.first_world).status_code, 200)
        self.assertEqual(self.sam.get(ORGANIZATION).status_code, 404)

    def test_a_world_in_the_organization_not_chosen_is_not_found(self):
        self.switch(self.sams_own)

        self.assertEqual(self.sam.get(self.first_world).status_code, 404)

    def test_switching_to_an_organization_they_do_not_belong_to_does_nothing(self):
        self.switch(self.miras)
        eve = sign_in("eve@example.com")
        user = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=user):
            eves = str(Membership.objects.get().organization_id)

        self.switch(eves)

        self.assertEqual(self.sam.get(self.first_world).status_code, 200)
        self.assertEqual(eve.get(self.first_world).status_code, 404)

    def test_switching_to_something_that_is_not_an_organization_does_nothing(self):
        self.switch(self.miras)

        self.switch("not-an-id")

        self.assertEqual(self.sam.get(self.first_world).status_code, 200)


class TheDatabaseOnItsOwn(PeopleTest):
    def setUp(self):
        super().setUp()
        self.invite("sam@example.com")
        sign_in("eve@example.com")
        self.mira_user = User.objects.get(email="mira@example.com")
        self.eve_user = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=self.mira_user):
            self.miras = Membership.objects.get().organization_id
        with tenancy.acting_as(user=self.eve_user):
            self.eves = Membership.objects.get().organization_id

    def test_an_invitation_is_hidden_from_other_organizations(self):
        with tenancy.acting_as(user=self.eve_user, organization=self.eves):
            self.assertEqual(Invitation.objects.count(), 0)
        with tenancy.acting_as(user=self.mira_user, organization=self.miras):
            self.assertEqual(Invitation.objects.count(), 1)

    def test_the_invited_person_can_see_their_own_invitation_and_no_other(self):
        self.invite("eve@example.com")

        with tenancy.acting_as(user=self.eve_user):
            self.assertEqual([i.email for i in Invitation.objects.all()], ["eve@example.com"])

    def test_a_role_cannot_be_given_to_someone_outside_the_organization(self):
        with tenancy.acting_as(organization=self.miras):
            world = World.objects.get()

        with self.assertRaises(IntegrityError), transaction.atomic():
            with tenancy.acting_as(user=self.mira_user, organization=self.miras):
                WorldRole.objects.create(organization_id=self.miras, world=world,
                                         user=self.eve_user, role="mod-runner")
