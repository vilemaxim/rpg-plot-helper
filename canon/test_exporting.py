"""Exporting a World as a zip of its files, through web requests, with
plotcanon's sample World and script."""

import contextlib
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import plotcanon
from plotcanon.cli import main as plotcanon_command

from canon.models import Document
from canon.test_decisions import DecisionTest
from canon.test_reports import LEDGER_2
from canon.tests import upload
from organizations.tests import sign_in


def unzipped(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()
                if not name.endswith("/")}


class ExportTest(DecisionTest):
    """Mira's World holds the sample World, with a report filed since and one
    of its changes approved, so the stored files are not the ones imported."""

    def setUp(self):
        super().setUp()
        self.submit(LEDGER_2)
        self.rule(self.change("clerk-pell", "aa-the-tax-collectors-ledger-2"), "approve")
        self.export_page = f"{self.first_world}export/"
        self.download = f"{self.export_page}download/"


class Exporting(ExportTest):
    def test_the_world_page_offers_a_plot_master_the_export(self):
        self.assertContains(self.mira.get(self.first_world), self.export_page)
        page = self.mira.get(self.export_page)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.download)

    def test_the_page_says_what_is_not_in_the_files(self):
        page = self.mira.get(self.export_page)

        self.assertContains(page, "not in the files")
        self.assertContains(page, "Flags")

    def test_the_zip_holds_each_file_as_stored_in_one_folder(self):
        response = self.mira.get(self.download)

        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn('filename="my-first-world.zip"', response["Content-Disposition"])
        files = unzipped(response.content)
        self.assertEqual({path.split("/", 1)[0] for path in files}, {"my-first-world"})
        self.assertEqual({path.split("/", 1)[1]: text for path, text in files.items()},
                         self.stored_files())

    def test_it_includes_what_has_happened_since_the_import(self):
        files = unzipped(self.mira.get(self.download).content)

        self.assertIn("my-first-world/after-actions/e03-storm-moon/"
                      "aa-the-tax-collectors-ledger-2.md", files)
        self.assertIn("status: alive", files["my-first-world/canon/npcs/clerk-pell.md"])

    def test_it_includes_the_worlds_settings_file(self):
        files = unzipped(self.mira.get(self.download).content)

        self.assertEqual(files["my-first-world/world.yml"],
                         plotcanon.sample_world()["world.yml"])

    def test_plotcanon_finds_no_errors_in_it(self):
        files = unzipped(self.mira.get(self.download).content)

        report = plotcanon.load_world({path.split("/", 1)[1]: text
                                       for path, text in files.items()})
        self.assertTrue(report.ok, report.text)

    def test_unpacked_it_passes_the_check_a_larp_llm_repo_runs(self):
        # larp-llm's scripts/validate.py is `plotcanon validate --root <repo>`.
        content = self.mira.get(self.download).content
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                archive.extractall(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = plotcanon_command(
                    ["validate", "--root", str(Path(directory) / "my-first-world")])

        self.assertEqual(status, 0, output.getvalue())
        self.assertIn("0 errors", output.getvalue())

    def test_importing_it_into_an_empty_world_gives_the_same_documents(self):
        content = self.mira.get(self.download).content
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)

        self.mira.post(f"{second}import/", {"archive": upload(content)}, follow=True)

        self.assertEqual(self.stored_files(world=second), self.stored_files())

    def test_nothing_is_written_to_the_apps_disk(self):
        with mock.patch("builtins.open", side_effect=AssertionError("opened a file")), \
                mock.patch("tempfile.NamedTemporaryFile",
                           side_effect=AssertionError("made a file")):
            response = self.mira.get(self.download)

        self.assertEqual(response.status_code, 200)


class AWorldPlotcanonRefuses(ExportTest):
    def test_is_reported_as_a_fault_and_not_handed_over(self):
        with self.in_world():
            Document.objects.filter(slug="clerk-pell").update(text="not a file at all")

        with self.assertLogs("canon.exporting", level="ERROR"):
            response = self.mira.get(self.download)

        self.assertEqual(response.status_code, 500)
        self.assertNotEqual(response.get("Content-Type"), "application/zip")
        self.assertContains(response, "could not be exported", status_code=500)


class AWorldWithAPathOutsideIt(ExportTest):
    def test_is_reported_as_a_fault_and_not_handed_over(self):
        with self.in_world():
            Document.objects.filter(slug="clerk-pell").update(path="../../clerk-pell.md")

        with self.assertLogs("canon.exporting", level="ERROR"):
            response = self.mira.get(self.download)

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "could not be exported", status_code=500)


class FolderNames(ExportTest):
    def test_a_name_in_another_alphabet_is_kept(self):
        self.mira.post(f"{self.first_world}rename/", {"name": "Ærø Saga"})

        response = self.mira.get(self.download)

        self.assertIn("filename*=utf-8''%C3%A6r%C3%B8-saga.zip", response["Content-Disposition"])

    def test_the_download_is_not_kept_by_caches(self):
        self.assertIn("no-cache", self.mira.get(self.download)["Cache-Control"])


class WhoMayExport(ExportTest):
    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

        self.assertNotContains(sam.get(self.first_world), self.export_page)
        self.assertEqual(sam.get(self.export_page).status_code, 404)
        self.assertEqual(sam.get(self.download).status_code, 404)

    def test_an_organization_admin_who_is_not_its_plot_master_can(self):
        second = self.make_world("Second World")

        self.assertRedirects(self.mira.get(f"{second}export/download/"), f"{second}export/")

    def test_someone_from_another_organization_cannot(self):
        self.assertEqual(sign_in("eve@example.com").get(self.download).status_code, 404)

    def test_a_world_with_nothing_in_it_has_nothing_to_export(self):
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)

        self.assertNotContains(self.mira.get(second), f"{second}export/")
        self.assertContains(self.mira.get(f"{second}export/"), "nothing to export")
        self.assertRedirects(self.mira.get(f"{second}export/download/"), f"{second}export/")
