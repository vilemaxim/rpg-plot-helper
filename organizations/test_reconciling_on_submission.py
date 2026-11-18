"""Whether a World's drafts are reconciled when they are submitted: the
Organization's setting, each World's override, and who may change them,
through web requests."""

import re

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from accounts.models import User
from organizations import tenancy
from organizations.models import Membership, ReconcilingOverride, World
from organizations.reconciling import reconciles_on_submission
from organizations.test_people import ORGANIZATION, PeopleTest, world_id
from organizations.tests import sign_in

ORGANIZATION_SETTING = f"{ORGANIZATION}reconciliation/"
LABEL = "Reconcile each draft when it&#x27;s submitted"


@override_settings(OPEN_SIGN_UP=True)
class ReconcilingTest(PeopleTest):
    def reconciles(self, world=None):
        """What the automatic run will be told for this World."""
        user = User.objects.get(email="mira@example.com")
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get(user=user).organization_id
        with tenancy.acting_as(user=user, organization=organization):
            return reconciles_on_submission(
                World.objects.get(pk=world_id(world or self.first_world)))

    def set_organization(self, on, by=None):
        return (by or self.mira).post(ORGANIZATION_SETTING, {"on": "on"} if on else {},
                                      follow=True)

    def organization_shows_on(self):
        page = self.mira.get(ORGANIZATION).content.decode()
        return bool(re.search(r'<input[^>]*name="on"[^>]*\bchecked\b', page))


class TheOrganizationsSetting(ReconcilingTest):
    def test_it_is_off_by_default(self):
        self.assertContains(self.mira.get(ORGANIZATION), LABEL)
        self.assertFalse(self.organization_shows_on())
        self.assertFalse(self.reconciles())

    def test_an_organization_admin_turns_it_on_and_off(self):
        response = self.set_organization(True)

        self.assertEqual(response.redirect_chain[-1][0], ORGANIZATION)
        self.assertTrue(self.organization_shows_on())
        self.assertTrue(self.reconciles())

        self.set_organization(False)

        self.assertFalse(self.organization_shows_on())
        self.assertFalse(self.reconciles())

    def test_someone_who_is_not_an_organization_admin_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "plot-master")

        self.assertEqual(self.set_organization(True, by=sam).status_code, 404)
        self.assertFalse(self.reconciles())


ON = "Drafts in this World are reconciled when they're submitted."
OFF = "Drafts in this World are not reconciled when they're submitted."
FOLLOWS = "This World follows the Organization's setting."
OVERRIDDEN = "An Organization Admin has set this for this World."


class OverrideTest(ReconcilingTest):
    def page(self, world=None):
        return f"{world or self.first_world}reconciliation/"

    def set_world(self, choice, world=None, by=None):
        return (by or self.mira).post(self.page(world), {"choice": choice}, follow=True)

    def chosen(self, world=None):
        page = self.mira.get(self.page(world)).content.decode()
        return re.findall(r'<input[^>]*value="([a-z]+)"[^>]*\bchecked\b', page)


class AWorldsOverride(OverrideTest):
    def test_a_world_follows_the_organization_until_told_otherwise(self):
        self.assertContains(self.mira.get(self.first_world), self.page())
        page = self.mira.get(self.page())

        self.assertContains(page, OFF)
        self.assertContains(page, FOLLOWS)
        self.assertEqual(self.chosen(), ["follow"])

        self.set_organization(True)

        self.assertContains(self.mira.get(self.page()), ON)
        self.assertTrue(self.reconciles())

    def test_on_for_a_world_wins_over_the_organization_being_off(self):
        response = self.set_world("on")

        self.assertEqual(response.redirect_chain[-1][0], self.page())
        self.assertContains(response, ON)
        self.assertContains(response, OVERRIDDEN)
        self.assertEqual(self.chosen(), ["on"])
        self.assertTrue(self.reconciles())

    def test_off_for_a_world_wins_over_the_organization_being_on(self):
        self.set_organization(True)

        self.set_world("off")

        self.assertContains(self.mira.get(self.page()), OFF)
        self.assertFalse(self.reconciles())

    def test_following_again_takes_the_organizations_setting(self):
        self.set_world("on")

        self.set_world("follow")

        self.assertEqual(self.chosen(), ["follow"])
        self.assertFalse(self.reconciles())

    def test_it_is_set_for_one_world_only(self):
        second = self.make_world("Second World")

        self.set_world("on", world=second)

        self.assertTrue(self.reconciles(second))
        self.assertFalse(self.reconciles())

    def test_an_unknown_choice_is_refused(self):
        response = self.set_world("sometimes")

        self.assertContains(response, "Select a valid choice")
        self.assertEqual(self.chosen(), ["follow"])


class WhoSeesAndChangesAWorldsOverride(OverrideTest):
    def test_a_plot_master_sees_the_setting_but_cannot_change_it(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "plot-master")
        self.set_world("on")

        self.assertContains(sam.get(self.first_world), self.page())
        page = sam.get(self.page())
        self.assertContains(page, ON)
        self.assertContains(page, OVERRIDDEN)
        self.assertNotContains(page, 'name="choice"')

        self.assertEqual(self.set_world("off", by=sam).status_code, 404)
        self.assertTrue(self.reconciles())

    def test_a_mod_writer_does_not_see_it(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

        self.assertNotContains(sam.get(self.first_world), self.page())
        self.assertEqual(sam.get(self.page()).status_code, 404)
        self.assertEqual(self.set_world("on", by=sam).status_code, 404)
        self.assertFalse(self.reconciles())

    def test_an_organization_admin_who_holds_no_role_in_the_world_can_change_it(self):
        second = self.make_world("Second World")

        self.set_world("on", world=second)

        self.assertTrue(self.reconciles(second))


@override_settings(OPEN_SIGN_UP=True)
class OverridesInTheDatabase(TestCase):
    """Row-level security on a World's override, with no help from the app."""

    def setUp(self):
        self.miras_org, self.miras_world = self.signed_up("mira@example.com")
        self.sams_org, _ = self.signed_up("sam@example.com")

    def signed_up(self, email):
        sign_in(email)
        with tenancy.acting_as(user=User.objects.get(email=email)):
            organization = Membership.objects.get().organization_id
        with tenancy.acting_as(organization=organization):
            return organization, World.objects.get().pk

    def test_another_organization_sees_none_of_them(self):
        with tenancy.acting_as(organization=self.miras_org):
            ReconcilingOverride.objects.create(organization_id=self.miras_org,
                                               world_id=self.miras_world, reconciles=True)

        with tenancy.acting_as(organization=self.sams_org):
            self.assertEqual(ReconcilingOverride.objects.count(), 0)
        with tenancy.acting_as():
            self.assertEqual(ReconcilingOverride.objects.count(), 0)

    def test_one_cannot_point_at_another_organizations_world(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with tenancy.acting_as(organization=self.sams_org):
                ReconcilingOverride.objects.create(organization_id=self.sams_org,
                                                   world_id=self.miras_world, reconciles=True)
