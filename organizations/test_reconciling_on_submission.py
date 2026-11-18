"""Whether a World's drafts are reconciled when they are submitted: the
Organization's setting, each World's override, and who may change them,
through web requests."""

import re

from django.test import override_settings

from accounts.models import User
from organizations import tenancy
from organizations.models import Membership, World
from organizations.reconciling import reconciles_on_submission
from organizations.test_people import ORGANIZATION, PeopleTest, world_id

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
