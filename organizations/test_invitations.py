"""Deciding on an invitation, and leaving an Organization, through web requests."""

import re

from django.test import override_settings

from accounts.models import User
from organizations import tenancy
from organizations.models import Invitation, Membership, Organization
from organizations.test_people import ORGANIZATION, PeopleTest
from organizations.tests import sign_in

INVITATIONS = "/invitations/"
LEAVE = "/organization/leave/"


class BeingInvited(PeopleTest):
    """Mira, Organization Admin of her own Organization, has invited Sam."""

    def setUp(self):
        super().setUp()
        self.mira.post(f"{ORGANIZATION}name/", {"name": "Greymoor Plot Team"})
        self.invite("sam@example.com")

    def memberships(self, email):
        user = User.objects.get(email=email)
        with tenancy.acting_as(user=user):
            return Membership.objects.count()

    def test_signing_in_shows_the_invitation_and_does_not_join(self):
        sam = sign_in("sam@example.com")

        response = sam.get("/", follow=True)

        self.assertEqual(response.redirect_chain[-1][0], INVITATIONS)
        self.assertContains(response, "Greymoor Plot Team")
        self.assertContains(response, "mira@example.com")
        self.assertContains(response, "invited you to join")
        self.assertEqual(self.memberships("sam@example.com"), 0)
        self.assertContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")

    def test_accepting_makes_them_a_member_and_lands_them_there(self):
        sam = sign_in("sam@example.com")

        response = self.decide(sam, "accept")

        self.assertContains(response, "Greymoor Plot Team")
        self.assertContains(response, "you do not have a role in any World")
        self.assertEqual(self.memberships("sam@example.com"), 1)
        self.assertNotContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")

    def test_declining_does_not_join_and_the_invitation_stops_waiting(self):
        sam = sign_in("sam@example.com")

        self.decide(sam, "decline")

        self.assertNotContains(sam.get(INVITATIONS), "Greymoor Plot Team")
        self.assertNotContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")
        self.assertEqual(sam.get(self.first_world).status_code, 404)

    def test_the_organization_admin_sees_that_it_was_declined(self):
        self.decide(sign_in("sam@example.com"), "decline")

        response = self.mira.get(ORGANIZATION)

        self.assertContains(response, "Declined")
        self.assertContains(response, "sam@example.com")

    @override_settings(OPEN_SIGN_UP=False)
    def test_a_declined_address_can_be_invited_again(self):
        sam = sign_in("sam@example.com")
        self.decide(sam, "decline")

        self.invite("sam@example.com")

        self.assertContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")
        self.assertContains(sam.get("/", follow=True), "invited you to join")
        self.decide(sam, "accept")
        self.assertEqual(self.memberships("sam@example.com"), 1)

    @override_settings(OPEN_SIGN_UP=True)
    def test_with_sign_up_open_someone_who_declines_gets_an_organization_of_their_own(self):
        sam = sign_in("sam@example.com")

        response = self.decide(sam, "decline")

        self.assertContains(response, "My Organization")
        self.assertContains(response, "Organization Admin")

    @override_settings(OPEN_SIGN_UP=True)
    def test_they_do_not_get_one_of_their_own_while_still_deciding(self):
        sign_in("sam@example.com")

        self.assertEqual(self.memberships("sam@example.com"), 0)

    @override_settings(OPEN_SIGN_UP=False)
    def test_with_sign_up_closed_someone_who_declines_needs_an_invitation(self):
        sam = sign_in("sam@example.com")

        response = self.decide(sam, "decline")

        self.assertContains(response, "You need an invitation")

    def test_someone_who_already_has_an_organization_stays_in_it_until_they_decide(self):
        self.invite("pat@example.com")
        pat = sign_in("pat@example.com")
        self.decide(pat, "decline")
        own = pat.get("/", follow=True)
        self.assertContains(own, "My Organization")

        self.invite("pat@example.com")

        self.assertContains(pat.get("/", follow=True), "invited you to join")
        self.assertEqual(self.memberships("pat@example.com"), 1)

    def test_every_page_tells_them_an_invitation_is_waiting(self):
        pat = sign_in("pat@example.com")
        world = pat.get("/", follow=True).redirect_chain[-1][0]
        self.invite("pat@example.com")

        response = pat.get(world)

        self.assertContains(response, f'href="{INVITATIONS}"')
        self.assertNotContains(self.mira.get(self.first_world), f'href="{INVITATIONS}"')

    def test_someone_with_worlds_of_their_own_can_decide_later(self):
        pat = sign_in("pat@example.com")
        world = pat.get("/", follow=True).redirect_chain[-1][0]
        self.invite("pat@example.com")

        self.assertContains(pat.get("/", follow=True), 'href="/?later"')

        self.assertRedirects(pat.get("/?later"), world)
        self.assertContains(pat.get(INVITATIONS), "invited you to join")

    def test_an_invitation_cannot_be_decided_with_a_link(self):
        sam = sign_in("sam@example.com")
        with tenancy.acting_as(user=User.objects.get(email="sam@example.com")):
            invitation = Invitation.objects.get().pk

        for choice in ("accept", "decline"):
            self.assertEqual(sam.get(f"{INVITATIONS}{invitation}/{choice}/").status_code, 405)
        self.assertEqual(self.memberships("sam@example.com"), 0)


class SeveralInvitations(PeopleTest):
    """Sam has been invited by Mira's Organization and by Eve's."""

    def setUp(self):
        super().setUp()
        self.mira.post(f"{ORGANIZATION}name/", {"name": "Greymoor Plot Team"})
        self.eve = sign_in("eve@example.com")
        self.eve.post(f"{ORGANIZATION}name/", {"name": "Tidewater"})
        self.invite("sam@example.com")
        self.invite("sam@example.com", by=self.eve)
        self.sam = sign_in("sam@example.com")

    def test_each_is_shown_and_decided_separately(self):
        page = self.sam.get(INVITATIONS)
        self.assertContains(page, "Greymoor Plot Team")
        self.assertContains(page, "Tidewater")

        self.decide(self.sam, "decline", "Greymoor Plot Team")

        page = self.sam.get(INVITATIONS)
        self.assertNotContains(page, "Greymoor Plot Team")
        self.assertContains(page, "Tidewater")

        response = self.decide(self.sam, "accept", "Tidewater")

        self.assertContains(response, "Tidewater")
        self.assertNotContains(self.eve.get(ORGANIZATION), "Invited, not yet joined")
        self.assertContains(self.mira.get(ORGANIZATION), "Declined")

    def test_accepting_one_leaves_the_other_waiting(self):
        self.decide(self.sam, "accept", "Tidewater")

        self.assertContains(self.sam.get("/", follow=True), "Greymoor Plot Team")
        self.assertContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")


class SomeoneElsesInvitation(PeopleTest):
    def setUp(self):
        super().setUp()
        self.invite("sam@example.com")
        self.eve = sign_in("eve@example.com")
        with tenancy.acting_as(user=User.objects.get(email="mira@example.com")):
            organization = Membership.objects.get().organization_id
        with tenancy.acting_as(organization=organization):
            self.invitation = Invitation.objects.get().pk

    def test_it_is_not_shown_to_anyone_else(self):
        self.assertNotContains(self.eve.get(INVITATIONS), "invited you to join")

    def test_it_cannot_be_accepted_by_anyone_else(self):
        response = self.eve.post(f"{INVITATIONS}{self.invitation}/accept/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.eve.get(self.first_world).status_code, 404)
        self.assertContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")

    def test_it_cannot_be_declined_by_anyone_else(self):
        response = self.eve.post(f"{INVITATIONS}{self.invitation}/decline/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(self.mira.get(ORGANIZATION), "Invited, not yet joined")

    def test_one_already_decided_cannot_be_decided_again(self):
        sam = sign_in("sam@example.com")
        self.decide(sam, "decline")

        response = sam.post(f"{INVITATIONS}{self.invitation}/accept/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(sam.get(self.first_world).status_code, 404)

    def test_the_organizations_name_is_hidden_from_people_it_has_not_invited(self):
        with tenancy.acting_as(user=User.objects.get(email="eve@example.com")):
            names = [o.name for o in Organization.objects.all()]

        self.assertEqual(len(names), 1)


class Leaving(PeopleTest):
    """Sam belongs to Mira's Organization with a role in her first World."""

    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

    def leave(self, browser):
        """Open the confirmation page and press its button."""
        page = browser.get(LEAVE).content.decode()
        organization = re.search(r'name="organization" value="([0-9a-f-]{36})"', page)
        data = {"organization": organization.group(1)} if organization else {}
        return browser.post(LEAVE, data, follow=True)

    def test_a_member_is_asked_before_leaving(self):
        response = self.sam.get(LEAVE)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Organization")
        self.assertEqual(self.sam.get(self.first_world).status_code, 200)

    def test_a_member_leaves_and_can_no_longer_open_its_worlds(self):
        self.leave(self.sam)

        self.assertEqual(self.sam.get(self.first_world).status_code, 404)
        self.assertNotContains(self.mira.get(ORGANIZATION), "sam@example.com")

    def test_their_roles_go_with_them(self):
        self.leave(self.sam)

        self.assertNotContains(self.mira.get(f"{self.first_world}people/"), "sam@example.com")

    def test_someone_who_left_can_be_invited_back_and_starts_with_no_roles(self):
        self.leave(self.sam)

        self.invite("sam@example.com")
        self.decide(self.sam, "accept")

        self.assertEqual(self.sam.get(self.first_world).status_code, 404)
        self.assertContains(self.mira.get(ORGANIZATION), "sam@example.com")

    def test_the_last_organization_admin_cannot_leave_and_is_told_why(self):
        response = self.leave(self.mira)

        self.assertContains(response, "the only Organization Admin")
        self.assertEqual(self.mira.get(self.first_world).status_code, 200)
        self.assertEqual(self.mira.get(ORGANIZATION).status_code, 200)

    def test_leaving_one_organization_keeps_the_others(self):
        pat = sign_in("pat@example.com")
        own_world = pat.get("/", follow=True).redirect_chain[-1][0]
        self.invite("pat@example.com")
        self.decide(pat, "accept")

        self.leave(pat)

        self.assertEqual(pat.get(own_world).status_code, 200)
        self.assertRedirects(pat.get("/"), own_world)

    def test_every_member_is_offered_the_way_to_leave(self):
        self.assertContains(self.sam.get(self.first_world), f'href="{LEAVE}"')

    @override_settings(OPEN_SIGN_UP=False)
    def test_someone_in_no_organization_has_nothing_to_leave(self):
        self.leave(self.sam)

        self.assertEqual(self.sam.get(LEAVE).status_code, 404)
        self.assertEqual(self.sam.post(LEAVE, {}).status_code, 404)

    def test_with_sign_up_open_leaving_your_last_organization_gives_you_your_own(self):
        response = self.leave(self.sam)

        self.assertContains(response, "Organization Admin")
        self.assertEqual(self.sam.get(self.first_world).status_code, 404)

    @override_settings(OPEN_SIGN_UP=False)
    def test_with_sign_up_closed_it_leaves_you_needing_an_invitation(self):
        response = self.leave(self.sam)

        self.assertContains(response, "You need an invitation")

    def test_the_button_leaves_the_organization_it_named_and_no_other(self):
        """Someone who opens the page, switches Organization in another tab and
        then presses the button must not leave the one they switched to."""
        pat = sign_in("pat@example.com")
        own_world = pat.get("/", follow=True).redirect_chain[-1][0]
        self.invite("pat@example.com")
        self.decide(pat, "accept")
        page_for_miras = pat.get(LEAVE).content.decode()
        miras = re.search(r'name="organization" value="([0-9a-f-]{36})"', page_for_miras).group(1)
        self.give("pat@example.com", "mod-runner")
        with tenancy.acting_as(user=User.objects.get(email="pat@example.com")):
            own = next(str(m.organization_id) for m in Membership.objects.all()
                       if str(m.organization_id) != miras)
        pat.post(f"{ORGANIZATION}switch/", {"organization": own})

        response = pat.post(LEAVE, {"organization": miras})

        self.assertContains(response, "You switched Organization")
        self.assertEqual(pat.get(own_world).status_code, 200)
        pat.post(f"{ORGANIZATION}switch/", {"organization": miras})
        self.assertEqual(pat.get(self.first_world).status_code, 200)

    def test_leaving_needs_the_button_not_a_bare_request(self):
        response = self.sam.post(LEAVE, {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sam.get(self.first_world).status_code, 200)
