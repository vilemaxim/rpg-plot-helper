"""Whether a World is reviewed after each Event (#61): the Organization's
setting, each World's override, and who may change them, through web
requests. Reconciliation's setting works the same way, and is tested in
`test_reconciling_on_submission`."""

import re

from organizations.test_people import ORGANIZATION, PeopleTest

ORGANIZATION_SETTING = f"{ORGANIZATION}world-review/"
LABEL = "Run a World review after each Event"
ON = "This World is reviewed after each Event."
OFF = "This World is not reviewed after each Event."
FOLLOWS = "This World follows the Organization's setting."
OVERRIDDEN = "An Organization Admin has set this for this World."


class WorldReviewSettingTest(PeopleTest):
    def setUp(self):
        super().setUp()
        self.setting = f"{self.first_world}world-review/setting/"

    def set_organization(self, on, by=None):
        return (by or self.mira).post(ORGANIZATION_SETTING, {"on": "on"} if on else {},
                                      follow=True)

    def set_world(self, choice, by=None):
        return (by or self.mira).post(self.setting, {"choice": choice}, follow=True)

    def organization_shows_on(self):
        """Whether the World review checkbox on the Organization page is
        ticked."""
        page = self.mira.get(ORGANIZATION).content.decode()
        form = page[page.index(f'action="{ORGANIZATION_SETTING}"'):]
        form = form[:form.index("</form>")]
        return bool(re.search(r'<input[^>]*name="on"[^>]*\bchecked\b', form))


class TheOrganizationsSetting(WorldReviewSettingTest):
    def test_it_is_off_by_default(self):
        self.assertContains(self.mira.get(ORGANIZATION), LABEL)
        self.assertFalse(self.organization_shows_on())
        self.assertContains(self.mira.get(self.setting), OFF)

    def test_an_organization_admin_turns_it_on_and_off(self):
        response = self.set_organization(True)

        self.assertEqual(response.redirect_chain[-1][0], ORGANIZATION)
        self.assertTrue(self.organization_shows_on())
        self.assertContains(self.mira.get(self.setting), ON)

        self.set_organization(False)

        self.assertFalse(self.organization_shows_on())
        self.assertContains(self.mira.get(self.setting), OFF)

    def test_it_is_apart_from_reconciliation(self):
        self.set_organization(True)

        self.assertContains(self.mira.get(f"{self.first_world}reconciliation/"),
                            "Drafts in this World are not reconciled")

    def test_someone_who_is_not_an_organization_admin_cannot(self):
        pat = self.join("pat@example.com")
        self.give("pat@example.com", "plot-master")

        self.assertEqual(self.set_organization(True, by=pat).status_code, 404)
        self.assertFalse(self.organization_shows_on())


class AWorldsOverride(WorldReviewSettingTest):
    def test_a_world_follows_the_organization_until_told_otherwise(self):
        page = self.mira.get(self.setting)

        self.assertContains(page, FOLLOWS)
        self.assertContains(page, OFF)

    def test_on_for_a_world_wins_over_the_organization_being_off(self):
        page = self.set_world("on")

        self.assertContains(page, ON)
        self.assertContains(page, OVERRIDDEN)

    def test_off_for_a_world_wins_over_the_organization_being_on(self):
        self.set_organization(True)

        page = self.set_world("off")

        self.assertContains(page, OFF)

    def test_following_again_takes_the_organizations_setting(self):
        self.set_organization(True)
        self.set_world("off")

        page = self.set_world("follow")

        self.assertContains(page, FOLLOWS)
        self.assertContains(page, ON)

    def test_a_plot_master_sees_it_but_cannot_change_it(self):
        pat = self.join("pat@example.com")
        self.give("pat@example.com", "plot-master")

        page = pat.get(self.setting)

        self.assertContains(page, OFF)
        self.assertContains(page, "Only an Organization Admin can change it.")
        self.assertEqual(self.set_world("on", by=pat).status_code, 404)

    def test_a_mod_writer_cannot_even_see_it(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

        self.assertEqual(sam.get(self.setting).status_code, 404)
