"""How strictly a World asks for Dry Run structure in its Mods, through web
requests, with plotcanon's sample World. None of the sample World's Mods has
the structure, so none can be checked under `required`."""

import re

import plotcanon
from django.core.exceptions import ValidationError

from accounts.models import User
from canon.test_approving import DAUGHTER
from canon.test_exporting import unzipped
from canon.test_mod_submissions import NEW, SubmissionTest, a_mod
from canon.test_reports import ReportTest
from canon.tests import CanonTest
from organizations import tenancy
from organizations.models import Membership, World

SETTING = "dry-run-structure/"


def settings_file(structure):
    return plotcanon.WorldSettings(dry_run_structure=structure).text()


class DryRunStructureTest(ReportTest):
    def setting_page(self, world=None):
        return f"{world or self.first_world}{SETTING}"

    def choose(self, structure, world=None, by=None):
        return (by or self.mira).post(self.setting_page(world), {"structure": structure},
                                      follow=True)

    def chosen(self, world=None):
        """The setting the page shows as chosen."""
        page = self.mira.get(self.setting_page(world)).content.decode()
        return re.findall(r'<input[^>]*value="([a-z]+)"[^>]*\bchecked\b', page)


class ChangingTheWorldsSetting(DryRunStructureTest):
    def test_the_world_page_offers_a_plot_master_the_setting(self):
        self.assertContains(self.mira.get(self.first_world), self.setting_page())
        page = self.mira.get(self.setting_page())

        self.assertEqual(page.status_code, 200)
        for value in ("off", "encouraged", "required"):
            self.assertContains(page, f'value="{value}"')

    def test_an_imported_world_has_the_setting_in_its_files(self):
        self.assertEqual(self.chosen(), ["encouraged"])

    def test_a_plot_master_changes_it_and_the_export_carries_it(self):
        response = self.choose("off")

        self.assertEqual(response.redirect_chain[-1][0], self.first_world)
        self.assertEqual(self.chosen(), ["off"])
        files = unzipped(self.mira.get(f"{self.first_world}export/download/").content)
        self.assertEqual(files["my-first-world/world.yml"], settings_file("off"))

    def test_an_unknown_setting_is_refused(self):
        response = self.choose("sometimes")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertEqual(self.chosen(), ["encouraged"])

    def test_requiring_it_is_refused_while_the_worlds_mods_have_no_structure(self):
        response = self.choose("required")

        self.assertContains(response, "Nothing was changed")
        self.assertContains(response, "Dry Run: the body has no Dry Run structure")
        self.assertContains(response, "<pre>")
        self.assertEqual(self.chosen(), ["encouraged"])
        self.assertEqual(self.stored_files()["world.yml"], settings_file("encouraged"))

    def test_a_world_with_no_mods_can_require_it(self):
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)

        self.choose("required", world=second)

        self.assertEqual(self.chosen(world=second), ["required"])
        self.assertEqual(self.stored_files(world=second)["world.yml"], settings_file("required"))


class WhoMayChangeTheWorldsSetting(DryRunStructureTest):
    def test_a_mod_writer_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

        self.assertNotContains(sam.get(self.first_world), self.setting_page())
        self.assertEqual(sam.get(self.setting_page()).status_code, 404)
        self.assertEqual(self.choose("off", by=sam).status_code, 404)
        self.assertEqual(self.chosen(), ["encouraged"])

    def test_an_organization_admin_who_is_not_its_plot_master_can(self):
        second = self.make_world("Second World")

        self.assertEqual(self.mira.get(self.setting_page(second)).status_code, 200)


class TheOrganizationsDefault(DryRunStructureTest):
    ORGANIZATION_SETTING = "/organization/dry-run-structure/"

    def default_shown(self):
        page = self.mira.get("/organization/").content.decode()
        return re.findall(r'<input[^>]*value="([a-z]+)"[^>]*\bchecked\b', page)

    def new_world(self):
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)
        return second

    def test_it_starts_at_encouraged_and_new_worlds_are_given_it(self):
        self.assertEqual(self.default_shown(), ["encouraged"])

        second = self.new_world()

        self.assertEqual(self.stored_files(world=second),
                         {"world.yml": settings_file("encouraged")})

    def test_an_organization_admin_changes_it_for_worlds_created_after(self):
        response = self.mira.post(self.ORGANIZATION_SETTING, {"structure": "off"}, follow=True)

        self.assertEqual(response.redirect_chain[-1][0], "/organization/")
        self.assertEqual(self.default_shown(), ["off"])
        self.assertEqual(self.chosen(self.new_world()), ["off"])
        self.assertEqual(self.chosen(), ["encouraged"])

    def test_a_world_given_it_is_not_counted_as_having_canon(self):
        self.mira.post(self.ORGANIZATION_SETTING, {"structure": "required"})
        second = self.new_world()

        self.assertContains(self.mira.get(second), f"{second}import/")

    def miras_organization(self):
        """Mira's Organization, and a block to act in it as her."""
        user = User.objects.get(email="mira@example.com")
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get().organization
        return organization, tenancy.acting_as(user=user, organization=organization)

    def test_a_world_created_by_any_path_is_given_it(self):
        self.mira.post(self.ORGANIZATION_SETTING, {"structure": "off"})
        organization, acting = self.miras_organization()

        with acting:
            world = World.objects.create(organization=organization, name="Third World")

        self.assertEqual(world.settings_file, settings_file("off"))

    def test_a_setting_plotcanon_does_not_have_cannot_be_stored(self):
        organization, acting = self.miras_organization()
        organization.dry_run_structure = "sometimes"

        with self.assertRaises(ValidationError), acting:
            organization.save()

    def test_a_world_imported_without_a_settings_file_is_encouraged(self):
        self.mira.post(self.ORGANIZATION_SETTING, {"structure": "off"})
        second = self.new_world()
        files = {path: text for path, text in plotcanon.sample_world().items()
                 if path != "world.yml"}

        self.import_files(files, world=second)

        self.assertEqual(self.chosen(second), ["encouraged"])
        self.assertNotIn("world.yml", self.stored_files(world=second))

    def test_an_unknown_setting_is_refused(self):
        response = self.mira.post(self.ORGANIZATION_SETTING, {"structure": "sometimes"})

        self.assertContains(response, "Select a valid choice")
        self.assertEqual(self.default_shown(), ["encouraged"])

    def test_someone_who_is_not_an_organization_admin_cannot(self):
        sam = self.join("sam@example.com")

        self.assertEqual(sam.post(self.ORGANIZATION_SETTING, {"structure": "off"}).status_code,
                         404)
        self.assertEqual(self.default_shown(), ["encouraged"])


HOOKED = {"- She asks a player to carry the message.":
          "- She asks a player to carry the message → [[The message]]"}
# Structure throughout: the Hook leads to the first scene, each scene to the
# next, and the last to an outcome.
STRUCTURED = {
    **HOOKED,
    "**If players do nothing:** it is not delivered.":
        "**If players do nothing:** it is not delivered → [[The answer]]",
    "**If players do nothing:** the captain tells her the truth.":
        "**If players do nothing:** the captain tells her the truth → [[The truth is told]]",
    "The feud ends, deepens, or goes on unspoken.": "### The truth is told\n\nThe feud ends.",
}
GAP = "Dry Run: scene `The answer` has no exits"
UNSTRUCTURED = "Dry Run: the body has no Dry Run structure"


class DryRunChecks(SubmissionTest):
    """Submitting, revising and approving a Mod are checked against the
    World's setting. The sample World encourages the structure."""

    def required_world(self):
        """A second World that requires the structure, holding only the
        sample World's Campaigns, in which Sam writes Mods."""
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)
        self.give("sam@example.com", "mod-writer", world=second)
        files = {path: text for path, text in plotcanon.sample_world().items()
                 if path.startswith("canon/campaigns/")}
        files["world.yml"] = settings_file("required")
        self.import_files(files, world=second)
        return second

    def test_under_encouraged_a_mod_with_gaps_is_saved_and_its_warnings_shown(self):
        response = self.submit_mod(a_mod(**HOOKED))

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertContains(response, GAP)
        self.assertContains(response, "<pre")

    def test_under_encouraged_a_mod_with_no_structure_is_left_alone(self):
        response = self.submit_mod(a_mod())

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertNotContains(response, "Dry Run:")

    def test_a_revision_shows_its_warnings_too(self):
        self.submit_mod(a_mod())

        response = self.revise(NEW, a_mod(**HOOKED))

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertContains(response, GAP)

    def test_approving_shows_the_warnings_that_remain(self):
        self.revise(DAUGHTER, a_mod(slug=DAUGHTER, **HOOKED), by=self.mira)

        response = self.approve(DAUGHTER, campaign="tideward")

        self.assertEqual(self.state_shown(DAUGHTER), "Approved")
        self.assertContains(response, GAP)

    def test_under_off_none_are_shown(self):
        self.choose("off")

        response = self.submit_mod(a_mod(**HOOKED))

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertNotContains(response, "Dry Run:")

    def test_under_required_a_mod_with_no_structure_is_refused(self):
        second = self.required_world()

        response = self.sam.post(f"{second}submit-mod/", {"text": a_mod()}, follow=True)

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, UNSTRUCTURED)

    def test_under_required_a_mod_with_gaps_is_refused(self):
        second = self.required_world()

        response = self.sam.post(f"{second}submit-mod/", {"text": a_mod(**HOOKED)}, follow=True)

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, GAP)

    def test_under_required_a_mod_with_structure_throughout_is_saved(self):
        second = self.required_world()

        response = self.sam.post(f"{second}submit-mod/", {"text": a_mod(**STRUCTURED)},
                                 follow=True)

        self.assertEqual(response.redirect_chain[-1][0], f"{second}mods/{NEW}/")
        self.assertNotContains(response, "Dry Run:")

    choose = DryRunStructureTest.choose
    setting_page = DryRunStructureTest.setting_page


class AFirstWorld(CanonTest):
    def test_is_given_the_organizations_default_and_still_has_no_canon(self):
        self.assertEqual(self.stored_files(), {"world.yml": settings_file("encouraged")})
        self.assertContains(self.mira.get(self.first_world), self.import_page)
