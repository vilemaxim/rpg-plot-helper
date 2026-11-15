"""How strictly a World asks for Dry Run structure in its Mods, through web
requests, with plotcanon's sample World. None of the sample World's Mods has
the structure, so none can be checked under `required`."""

import re

import plotcanon

from canon.test_exporting import unzipped
from canon.test_reports import ReportTest

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

    def test_an_organization_admin_who_is_not_its_plot_master_cannot(self):
        second = self.make_world("Second World")

        self.assertEqual(self.mira.get(self.setting_page(second)).status_code, 404)
