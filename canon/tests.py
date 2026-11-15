"""Importing a World from a zip of its files, and browsing what was imported.
Tested through web requests, with the sample World that ships in plotcanon."""

import io
import re
import zipfile

import plotcanon
from django.test import TestCase, override_settings

from accounts.models import User
from canon.models import Document
from canon.storing import files_of
from organizations import tenancy
from organizations.models import Membership, World
from organizations.test_people import ORGANIZATION, PeopleTest, world_id
from organizations.tests import sign_in

NOT_A_WORLD = "/worlds/00000000-0000-4000-8000-000000000000/"


def zipped(files, inside=""):
    """A zip of `{path: text}`, as bytes. `inside` puts everything in a folder,
    the way zipping a folder from a file manager does."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in files.items():
            archive.writestr(f"{inside}{path}", text)
    return buffer.getvalue()


def upload(content, name="world.zip"):
    file = io.BytesIO(content)
    file.name = name
    return file


class CanonTest(PeopleTest):
    """Mira is Organization Admin and Plot Master of her first World."""

    def setUp(self):
        super().setUp()
        self.import_page = f"{self.first_world}import/"

    def import_files(self, files, by=None, world=None, **zip_options):
        address = f"{world or self.first_world}import/"
        return (by or self.mira).post(address, {"archive": upload(zipped(files, **zip_options))},
                                      follow=True)

    def import_sample(self, **options):
        return self.import_files(plotcanon.sample_world(), **options)

    def stored_files(self, world=None):
        """Every file of one of Mira's Worlds as stored, as `{path: text}`.
        `world` is its address, and her first World if not given."""
        user = User.objects.get(email="mira@example.com")
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get().organization_id
        with tenancy.acting_as(user=user, organization=organization):
            return files_of(World.objects.get(pk=world_id(world or self.first_world)))

    def documents(self):
        user = User.objects.get(email="mira@example.com")
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get().organization_id
        with tenancy.acting_as(user=user, organization=organization):
            return list(Document.objects.order_by("path"))


class Importing(CanonTest):
    def test_the_sample_world_is_imported_into_the_chosen_world(self):
        response = self.import_sample()

        self.assertEqual(response.redirect_chain[-1][0], self.first_world)
        self.assertContains(response, "Imported 48 documents")
        self.assertEqual(len(self.documents()), 48)

    def test_the_world_page_then_shows_what_it_holds(self):
        response = self.import_sample()

        for kind, count in (("NPCs", 12), ("Mods", 11), ("Plots", 3), ("Factions", 3),
                            ("Locations", 4), ("PCs", 5), ("Campaigns", 2), ("Events", 4)):
            with self.subTest(kind):
                self.assertRegex(response.content.decode(),
                                 rf'href="{self.first_world}[a-z-]+/">{kind}</a>\s*<span[^>]*>{count}<')

    def test_a_zip_made_by_zipping_the_folder_works_too(self):
        response = self.import_sample(inside="brackwater/")

        self.assertContains(response, "Imported 48 documents")

    def test_a_world_whose_files_all_sit_in_one_of_its_own_folders_is_not_mistaken_for_wrapped(self):
        """A zip with only `canon/...` in it shares one top folder, but that
        folder is part of the World, not a wrapper round it."""
        files = {path: text for path, text in plotcanon.sample_world().items()
                 if path.startswith("canon/campaigns/")}

        response = self.import_files(files)

        self.assertContains(response, "Imported 2 documents")

    def test_the_world_page_stops_offering_import_once_there_is_canon(self):
        self.assertContains(self.mira.get(self.first_world), self.import_page)

        self.import_sample()

        self.assertNotContains(self.mira.get(self.first_world), self.import_page)

    def test_files_that_are_not_part_of_the_world_are_ignored(self):
        files = plotcanon.sample_world()
        files["README.md"] = "# Notes to self\n"
        files["lore/the-old-kingdom.md"] = "Long ago.\n"
        files["canon/npcs/portrait.png"] = "not really a picture"

        response = self.import_files(files)

        self.assertContains(response, "Imported 48 documents")

    def test_each_file_is_kept_exactly_as_it_was_uploaded(self):
        files = plotcanon.sample_world()
        self.import_files(files)

        self.assertIn("world.yml", files)
        self.assertEqual(self.stored_files(), files)

    def test_the_settings_file_is_kept_from_a_zip_made_by_zipping_the_folder(self):
        self.import_sample(inside="brackwater/")

        self.assertEqual(self.stored_files()["world.yml"], plotcanon.sample_world()["world.yml"])

    def test_a_settings_file_anywhere_but_the_worlds_root_is_ignored(self):
        files = plotcanon.sample_world()
        files["canon/world.yml"] = "not: settings\n"

        self.import_files(files)

        self.assertNotIn("canon/world.yml", self.stored_files())

    def test_nothing_is_written_to_the_apps_disk(self):
        from django.conf import settings

        self.assertEqual(settings.FILE_UPLOAD_HANDLERS,
                         ["django.core.files.uploadhandler.MemoryFileUploadHandler"])

    def test_the_import_page_explains_what_to_upload(self):
        response = self.mira.get(self.import_page)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="file"')
        self.assertContains(response, ".zip")


class RejectedImports(CanonTest):
    def assert_nothing_imported(self):
        self.assertEqual(self.documents(), [])

    def test_an_invalid_world_is_rejected_with_its_errors_and_nothing_is_imported(self):
        files = plotcanon.sample_world()
        mod = "mods/tideward/storm-moon-vigil.md"
        files[mod] = files[mod].replace("npcs: [sister-ane,", "npcs: [nobody-at-all, sister-ane,")
        report = "after-actions/e01-low-tide/aa-a-light-gone-dark.md"
        files[report] = files[report].replace("mod_runner: mira\n", "")

        response = self.import_files(files)

        self.assertContains(response, "Nothing was imported")
        self.assertContains(response, "ERROR  mods/tideward/storm-moon-vigil.md: `features.npcs: "
                                      "nobody-at-all` does not resolve to any document")
        self.assertContains(response, "missing required field `mod_runner`")
        self.assert_nothing_imported()

    def test_a_file_that_is_not_a_zip_is_rejected(self):
        response = self.mira.post(self.import_page, {"archive": upload(b"just some text")},
                                  follow=True)

        self.assertContains(response, "That file is not a zip")
        self.assert_nothing_imported()

    def test_a_zip_with_no_world_in_it_is_rejected(self):
        response = self.import_files({"README.md": "# Nothing here\n"})

        self.assertContains(response, "no World files in that zip")
        self.assert_nothing_imported()

    def test_choosing_no_file_is_rejected(self):
        response = self.mira.post(self.import_page, {}, follow=True)

        self.assertContains(response, "This field is required")

    def test_a_file_that_is_not_text_is_named(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for path, text in plotcanon.sample_world().items():
                archive.writestr(path, text)
            archive.writestr("canon/npcs/broken.md", b"\xff\xfe\x00")

        response = self.mira.post(self.import_page, {"archive": upload(buffer.getvalue())},
                                  follow=True)

        self.assertContains(response, "canon/npcs/broken.md is not UTF-8 text")
        self.assert_nothing_imported()

    def test_a_file_with_a_character_the_database_cannot_hold_is_named(self):
        files = plotcanon.sample_world()
        files["canon/npcs/cutter-jass.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "A harbour pilot", "A harbour\x00 pilot")

        response = self.import_files(files)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "canon/npcs/cutter-jass.md")
        self.assertContains(response, "Nothing was imported")
        self.assert_nothing_imported()

    @override_settings(IMPORT_MAX_FILE_BYTES=600)
    def test_a_single_file_that_is_too_large_is_named(self):
        response = self.import_sample()

        self.assertContains(response, "is larger than")
        self.assertContains(response, ".md")
        self.assert_nothing_imported()

    def test_a_damaged_zip_is_rejected_not_crashed_on(self):
        content = bytearray(zipped(plotcanon.sample_world()))
        middle = len(content) // 3
        content[middle:middle + 400] = b"\x00" * 400

        response = self.mira.post(self.import_page, {"archive": upload(bytes(content))},
                                  follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was imported")
        self.assert_nothing_imported()

    def test_a_file_built_to_exhaust_memory_is_refused(self):
        """YAML lets one value stand for another. Nested a few times, a few
        hundred bytes unpack into millions of values."""
        files = plotcanon.sample_world()
        bomb = "a: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
            f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, "
            f"*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}]\n"
            for i in range(8))
        files["canon/npcs/cutter-jass.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "type: npc\n", "type: npc\n" + bomb)

        response = self.import_files(files)

        self.assertContains(response, "ERROR  canon/npcs/cutter-jass.md: uses a YAML alias")
        self.assertContains(response, "Nothing was imported")
        self.assert_nothing_imported()

    def test_an_id_too_long_to_store_is_named(self):
        files = plotcanon.sample_world()
        long_id = "a" * 250
        files[f"canon/npcs/{long_id}.md"] = files.pop("canon/npcs/cutter-jass.md").replace(
            "id: cutter-jass", f"id: {long_id}")
        mod = "mods/lanternlight/the-ferrymans-price.md"
        files[mod] = files[mod].replace("cutter-jass", long_id)
        report = "after-actions/e02-first-lantern/aa-the-ferrymans-price.md"
        files[report] = files[report].replace("cutter-jass", long_id)

        response = self.import_files(files)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is longer than")
        self.assert_nothing_imported()

    def test_values_the_database_cannot_hold_as_they_are_do_not_stop_an_import(self):
        files = plotcanon.sample_world()
        files["canon/npcs/cutter-jass.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "type: npc\n", "type: npc\nweight: .nan\nreach: .inf\nseen: 2026-05-02\n"
                            "blob: !!binary aGVsbG8=\nkeys: !!set {a, b}\n")

        response = self.import_files(files)

        self.assertContains(response, "Imported 48 documents")
        self.assertEqual(self.mira.get(f"{self.first_world}npcs/cutter-jass/").status_code, 200)

    @override_settings(IMPORT_MAX_FILES=10)
    def test_a_zip_with_too_many_files_is_rejected(self):
        response = self.import_sample()

        self.assertContains(response, "more than 10 files")
        self.assert_nothing_imported()

    @override_settings(IMPORT_MAX_UNPACKED_BYTES=5000)
    def test_a_zip_that_unpacks_too_large_is_rejected(self):
        response = self.import_sample()

        self.assertContains(response, "too large once unpacked")
        self.assert_nothing_imported()

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=2000)
    def test_an_upload_that_is_too_large_is_rejected(self):
        response = self.import_sample()

        self.assertContains(response, "too large")
        self.assert_nothing_imported()

    def test_a_world_that_already_has_canon_cannot_be_imported_into(self):
        self.import_sample()

        page = self.mira.get(self.import_page)
        again = self.import_sample()

        self.assertContains(page, "already has Canon")
        self.assertNotContains(page, 'type="file"')
        self.assertContains(again, "already has Canon")
        self.assertEqual(len(self.documents()), 48)


class WhoMayImport(CanonTest):
    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        self.eve = sign_in("eve@example.com")

    def test_someone_who_is_not_a_plot_master_of_the_world_cannot(self):
        for browser in (self.sam, self.eve):
            self.assertEqual(browser.get(self.import_page).status_code, 404)
            self.assertEqual(self.import_sample(by=browser).status_code, 404)

        self.assertEqual(self.documents(), [])

    def test_the_world_page_offers_import_to_a_plot_master_only(self):
        self.assertContains(self.mira.get(self.first_world), self.import_page)
        self.assertNotContains(self.sam.get(self.first_world), self.import_page)

    def test_an_organization_admin_who_is_not_its_plot_master_cannot(self):
        second = self.make_world("Second World")

        self.assertEqual(self.mira.get(f"{second}import/").status_code, 404)

    def test_a_signed_out_person_is_sent_to_sign_in(self):
        response = self.client.get(self.import_page)

        self.assertRedirects(response, f"/sign-in/?next={self.import_page}")


class Browsing(CanonTest):
    KINDS = ("campaigns", "events", "mods", "plots", "npcs", "factions", "locations", "pcs",
             "reports")

    def setUp(self):
        super().setUp()
        self.import_sample()

    def page(self, path, by=None):
        return (by or self.mira).get(f"{self.first_world}{path}")

    def test_each_kind_has_a_list_page(self):
        expected = {"campaigns": "Tideward", "events": "Storm Moon", "mods": "Storm Moon Vigil",
                    "plots": "The Drowned Bell", "npcs": "Ysolde Marr",
                    "factions": "The Salt Guild", "locations": "The Salt Stair",
                    "pcs": "Wren Halloway", "reports": "The Low Tide Market at Low Tide"}
        for kind in self.KINDS:
            with self.subTest(kind):
                response = self.page(f"{kind}/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected[kind])

    def test_every_document_has_a_detail_page_reached_from_its_list(self):
        for kind in self.KINDS:
            listing = self.page(f"{kind}/").content.decode()
            links = re.findall(rf'href="({self.first_world}{kind}/[a-z0-9-]+/)"', listing)
            self.assertTrue(links, kind)
            for link in links:
                with self.subTest(link):
                    self.assertEqual(self.mira.get(link).status_code, 200)

    def test_all_forty_eight_documents_are_reachable(self):
        found = set()
        for kind in self.KINDS:
            listing = self.page(f"{kind}/").content.decode()
            found |= set(re.findall(rf'href="({self.first_world}{kind}/[a-z0-9-]+/)"', listing))

        self.assertEqual(len(found), 48)

    def test_a_mods_page_shows_its_state_its_events_and_its_features_as_links(self):
        response = self.page("mods/the-tax-collectors-ledger/")

        self.assertContains(response, "The Tax Collector&#x27;s Ledger")
        self.assertContains(response, "In progress")
        for link, text in (("events/e01-low-tide/", "Low Tide"),
                           ("events/e03-storm-moon/", "Storm Moon"),
                           ("campaigns/tideward/", "Tideward"),
                           ("npcs/clerk-pell/", "Clerk Pell"),
                           ("npcs/harrow-dunmore/", "Harrow Dunmore"),
                           ("factions/salt-guild/", "The Salt Guild"),
                           ("plots/the-salt-tax-revolt/", "The Salt Tax Revolt")):
            with self.subTest(link):
                self.assertContains(response, f'<a href="{self.first_world}{link}">{text}</a>',
                                    html=True)
                self.assertEqual(self.page(link).status_code, 200)

    def test_a_mods_page_shows_what_it_says(self):
        response = self.page("mods/storm-moon-vigil/")

        self.assertContains(response, "<h2>Premise</h2>", html=True)
        self.assertContains(response, "The order keeps its vigil on the reef.")
        self.assertContains(response, "Approved")

    def test_a_mods_page_lists_the_reports_filed_on_it(self):
        response = self.page("mods/the-tax-collectors-ledger/")

        self.assertContains(response, f'href="{self.first_world}reports/aa-the-tax-collectors-ledger/"')

    def test_a_plots_page_shows_its_state_and_its_mods(self):
        response = self.page("plots/the-drowned-bell/")

        page = response.content.decode()
        self.assertContains(response, "The Drowned Bell")
        self.assertContains(response, '<span class="state">Open</span>', html=True)
        listed = re.findall(r'mods/([a-z-]+)/">[^<]+</a>\s*<span class="state">([\w ]+)</span>', page)
        self.assertEqual(listed, [("a-light-gone-dark", "Finished"),
                                  ("storm-moon-vigil", "Approved"),
                                  ("what-the-keeper-saw", "Approved"),
                                  ("the-bell-beneath", "Approved")])

    def test_a_campaigns_page_lists_its_events_and_its_mods(self):
        response = self.page("campaigns/lanternlight/")

        for link in ("events/e02-first-lantern/", "events/e04-second-lantern/",
                     "mods/the-ferrymans-price/", "mods/what-the-keeper-saw/",
                     "mods/a-warrant-for-dunmore/", "mods/the-bell-beneath/"):
            with self.subTest(link):
                self.assertContains(response, f'href="{self.first_world}{link}"')
        self.assertNotContains(response, "mods/storm-moon-vigil/")

    def test_an_events_page_lists_the_mods_run_at_it_and_their_reports(self):
        response = self.page("events/e01-low-tide/")

        for link in ("mods/the-low-tide-market/", "mods/a-light-gone-dark/",
                     "mods/the-tax-collectors-ledger/", "reports/aa-the-low-tide-market/",
                     "campaigns/tideward/"):
            with self.subTest(link):
                self.assertContains(response, f'href="{self.first_world}{link}"')

    def test_an_npcs_page_links_the_reports_that_changed_them(self):
        """The trail: why Clerk Pell is missing, and who reported it."""
        response = self.page("npcs/clerk-pell/")

        self.assertContains(response, '<span class="state">Missing</span>', html=True)
        self.assertContains(response, f'href="{self.first_world}reports/aa-the-tax-collectors-ledger/"')

    def test_a_pcs_page_links_the_reports_they_took_part_in(self):
        response = self.page("pcs/pc-ilse-marrow/")

        for report in ("aa-the-low-tide-market", "aa-a-light-gone-dark"):
            self.assertContains(response, f'href="{self.first_world}reports/{report}/"')

    def test_a_state_is_shown_once(self):
        page = self.page("mods/storm-moon-vigil/").content.decode()

        self.assertEqual(page.count('class="state">Approved<'), 1)
        self.assertNotIn("<dt>State</dt>", page)
        self.assertIn("<dt>In Canon</dt>", page)

    def test_an_npcs_page_shows_their_state_and_where_they_are_featured(self):
        response = self.page("npcs/harrow-dunmore/")

        self.assertContains(response, "Harrow Dunmore")
        self.assertContains(response, "Alive")
        self.assertContains(response, "e01-low-tide")
        for mod in ("the-tax-collectors-ledger", "blood-on-the-salt-stair", "a-warrant-for-dunmore"):
            self.assertContains(response, f'href="{self.first_world}mods/{mod}/"')

    def test_a_reports_page_shows_its_canon_changes(self):
        response = self.page("reports/aa-the-tax-collectors-ledger/")

        self.assertContains(response, "Clerk Pell")
        self.assertContains(response, "missing")
        self.assertContains(response, "Approved")
        self.assertContains(response, "Gone from his counting room with the ledger.")

    def test_the_mods_list_shows_each_state(self):
        response = self.page("mods/")

        for state in ("Draft", "Approved", "In progress", "Finished", "Shelved"):
            self.assertContains(response, state)

    def test_a_kind_or_a_document_that_does_not_exist_is_not_found(self):
        self.assertEqual(self.page("dragons/").status_code, 404)
        self.assertEqual(self.page("npcs/nobody-at-all/").status_code, 404)
        self.assertEqual(self.page("npcs/storm-moon-vigil/").status_code, 404)

    def test_anyone_with_a_role_in_the_world_can_browse(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-runner")

        self.assertEqual(self.page("npcs/", by=sam).status_code, 200)
        self.assertEqual(self.page("mods/storm-moon-vigil/", by=sam).status_code, 200)

    def test_someone_with_no_role_in_the_world_cannot(self):
        sam = self.join("sam@example.com")
        eve = sign_in("eve@example.com")

        for browser in (sam, eve):
            self.assertEqual(self.page("npcs/", by=browser).status_code, 404)
            self.assertEqual(self.page("npcs/ysolde-marr/", by=browser).status_code, 404)

    def test_another_world_in_the_same_organization_holds_none_of_it(self):
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)

        self.assertEqual(self.mira.get(f"{second}npcs/ysolde-marr/").status_code, 404)
        self.assertNotContains(self.mira.get(f"{second}npcs/"), "Ysolde Marr")


class WhatAPageShows(CanonTest):
    def test_markup_in_a_file_is_shown_safely(self):
        files = plotcanon.sample_world()
        npc = "canon/npcs/cutter-jass.md"
        files[npc] = files[npc].replace(
            "A harbour pilot who knows every channel through the reef.",
            'A harbour pilot. <script>alert("x")</script> <img src=x onerror="alert(1)"> '
            '[a link](javascript:alert(2)) and **bold**.')
        self.import_files(files)

        page = self.mira.get(f"{self.first_world}npcs/cutter-jass/").content.decode()

        self.assertNotIn("<script>alert", page)
        self.assertNotIn("onerror", page)
        self.assertNotIn("javascript:", page)
        self.assertIn("<strong>bold</strong>", page)

    def test_a_picture_from_another_site_is_not_loaded(self):
        """Loading one would tell that site who is reading the page."""
        files = plotcanon.sample_world()
        files["canon/npcs/cutter-jass.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "A harbour pilot who", "![map](https://elsewhere.example/track.png) A harbour pilot who")
        self.import_files(files)

        page = self.mira.get(f"{self.first_world}npcs/cutter-jass/").content.decode()

        self.assertNotIn("<img", page)

    def test_a_persons_handle_is_not_mistaken_for_a_link(self):
        """`mod_writer: mira` names a person, even when a document has the id `mira`."""
        files = plotcanon.sample_world()
        files["canon/npcs/mira.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "id: cutter-jass", "id: mira").replace('["Cutter Jass", "Jass"]', '["Mira the Witch"]')
        mod = "mods/lanternlight/the-ferrymans-price.md"
        files[mod] = files[mod].replace("npcs: [the-ferryman, cutter-jass]",
                                        "npcs: [the-ferryman, cutter-jass, mira]")
        self.import_files(files)

        page = self.mira.get(f"{self.first_world}mods/the-low-tide-market/").content.decode()

        self.assertNotIn("Mira the Witch", page)
        self.assertIn("mira", page)

    def test_a_document_whose_id_is_a_persons_handle_is_not_said_to_be_named_by_their_mods(self):
        """An NPC `mira` is not featured in every Mod whose writer is `mira`."""
        files = plotcanon.sample_world()
        files["canon/npcs/mira.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "id: cutter-jass", "id: mira").replace('["Cutter Jass", "Jass"]', '["Mira the Witch"]')
        self.import_files(files)

        page = self.mira.get(f"{self.first_world}npcs/mira/").content.decode()

        self.assertNotIn(f'href="{self.first_world}mods/the-low-tide-market/"', page)
        self.assertNotIn(f'href="{self.first_world}reports/aa-the-low-tide-market/"', page)

    def test_a_field_the_file_format_does_not_call_a_reference_is_not_a_link(self):
        files = plotcanon.sample_world()
        mod = "mods/tideward/the-low-tide-market.md"
        files[mod] = files[mod].replace("slot: 1\n", "slot: 1\nrival_mod: clerk-pell\n")
        self.import_files(files)

        page = self.mira.get(f"{self.first_world}mods/the-low-tide-market/").content.decode()
        npc = self.mira.get(f"{self.first_world}npcs/clerk-pell/").content.decode()

        self.assertRegex(page, r"<dt>Rival mod</dt>\s*<dd>clerk-pell</dd>")
        self.assertNotIn(f'href="{self.first_world}mods/the-low-tide-market/"', npc)

    def test_an_odd_but_accepted_document_still_has_a_page(self):
        files = plotcanon.sample_world()
        files["canon/npcs/cutter-jass.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "type: npc\n", "type: npc\nmods: [[a]]\nentities: 5\nweight: {a: [b]}\n")
        self.import_files(files)

        self.assertEqual(self.mira.get(f"{self.first_world}npcs/cutter-jass/").status_code, 200)

    def test_a_world_the_validator_cannot_cope_with_is_refused_not_crashed_on(self):
        files = plotcanon.sample_world()
        files["canon/npcs/cutter-jass.md"] = files["canon/npcs/cutter-jass.md"].replace(
            "type: npc\n", "type: npc\ncanon_changes: [1, {entity: [x]}]\n")

        response = self.import_files(files)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was imported")
        self.assertEqual(self.documents(), [])

    def test_one_document_is_counted_as_one(self):
        files = {path: text for path, text in plotcanon.sample_world().items()
                 if path == "canon/campaigns/tideward.md"}

        self.assertContains(self.import_files(files), "Imported 1 document.")

    def test_a_name_with_markup_in_it_is_shown_as_typed(self):
        files = plotcanon.sample_world()
        npc = "canon/npcs/cutter-jass.md"
        files[npc] = files[npc].replace('aliases: ["Cutter Jass", "Jass"]',
                                        'aliases: ["<b>Cutter</b> Jass", "Jass"]')
        self.import_files(files)

        page = self.mira.get(f"{self.first_world}npcs/").content.decode()

        self.assertIn("&lt;b&gt;Cutter&lt;/b&gt; Jass", page)


class TheDatabaseOnItsOwn(CanonTest):
    def test_with_no_organization_set_a_query_for_documents_returns_no_rows(self):
        self.import_sample()

        with tenancy.acting_as():
            self.assertEqual(Document.objects.count(), 0)

    def test_another_organization_sees_none_of_them(self):
        self.import_sample()
        sign_in("eve@example.com")
        eve = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=eve):
            organization = Membership.objects.get().organization_id

        with tenancy.acting_as(user=eve, organization=organization):
            self.assertEqual(Document.objects.count(), 0)
