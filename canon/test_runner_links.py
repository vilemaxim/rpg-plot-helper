"""Private links that let a Mod Runner read one Mod, take it offline and file
a report on it, with no account. Through web requests, with plotcanon's
sample World and script."""

import re

from django.test import override_settings

from canon.models import CanonChange, Document, ModLink
from canon.test_reports import LEDGER_2, VIGIL, VIGIL_2
from canon.test_resolving import WARRANT, ResolvingTest
from organizations import tenancy

VIGIL_MOD = "storm-moon-vigil"


class LinkTest(ResolvingTest):
    """The stair report has been filed, so the warrant Mod has open Flags."""

    def links_page(self, mod):
        return f"{self.mod_page(mod)}links/"

    def create_link(self, mod, label="Rhea, Saturday night", by=None):
        """Create a link and return its address, as shown once to the Plot
        Master."""
        response = (by or self.mira).post(self.links_page(mod), {"label": label}, follow=True)
        found = re.search(r"http://testserver(/run/[\w-]+/)", response.content.decode())
        return found.group(1) if found else response

    def file(self, link, scripted, text=None):
        return self.client.post(f"{link}report/",
                                {"text": scripted.text if text is None else text},
                                follow=True)

    def turn_off(self, mod, link_row, by=None):
        return (by or self.mira).post(f"{self.links_page(mod)}{link_row.pk}/off/", follow=True)

    def link_rows(self):
        with self.in_world():
            return list(ModLink.objects.all())


class CreatingALink(LinkTest):
    def test_a_plot_master_creates_one_and_is_shown_it_once(self):
        link = self.create_link(VIGIL_MOD)

        secret = link.removeprefix("/run/").removesuffix("/")
        self.assertGreaterEqual(len(secret), 40)
        page = self.mira.get(self.mod_page(VIGIL_MOD))
        self.assertContains(page, "Rhea, Saturday night")
        self.assertNotContains(page, secret)

    def test_the_secret_is_kept_only_as_a_hash(self):
        link = self.create_link(VIGIL_MOD)
        secret = link.removeprefix("/run/").removesuffix("/")

        [row] = self.link_rows()
        self.assertNotIn(secret, str(vars(row)))
        with self.in_world():
            self.assertFalse(any(secret in text for text in
                                 Document.objects.values_list("text", flat=True)))

    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-runner")

        self.assertNotContains(sam.get(self.mod_page(VIGIL_MOD)), self.links_page(VIGIL_MOD))
        self.assertEqual(sam.post(self.links_page(VIGIL_MOD), {"label": "x"}).status_code, 404)
        self.assertEqual(self.link_rows(), [])

    def test_a_mod_that_cannot_be_run_gets_no_link(self):
        response = self.create_link("blood-on-the-salt-stair")    # finished

        self.assertContains(response, "cannot be run")
        self.assertEqual(self.link_rows(), [])


class UsingALink(LinkTest):
    def setUp(self):
        super().setUp()
        self.link = self.create_link(VIGIL_MOD)

    def test_anyone_with_it_reads_the_mod_without_signing_in(self):
        page = self.client.get(self.link)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "<h1>Storm Moon Vigil</h1>")
        body = self.stored(VIGIL_MOD).body.strip().splitlines()[0].lstrip("# ")
        self.assertContains(page, body)

    def test_it_opens_nothing_else_in_the_world(self):
        page = self.client.get(self.link)

        self.assertNotContains(page, self.first_world)
        self.assertRedirects(self.client.get(self.first_world),
                             f"/sign-in/?next={self.first_world}")

    def test_the_mod_downloads_as_its_file(self):
        response = self.client.get(f"{self.link}file/")

        self.assertEqual(response.content.decode(), self.stored(VIGIL_MOD).text)
        self.assertIn(f'filename="{VIGIL_MOD}.md"', response["Content-Disposition"])

    def test_a_report_filed_through_it_is_saved_and_says_so(self):
        response = self.file(self.link, VIGIL)

        self.assertContains(response, "Report filed")
        with self.in_world():
            report = Document.objects.select_related("filed_through") \
                .get(slug="aa-storm-moon-vigil")
            self.assertIsNone(report.submitted_by_id)
            self.assertEqual(report.filed_through.label, "Rhea, Saturday night")
            self.assertTrue(CanonChange.objects.filter(report=report,
                                                       decision="proposed").exists())
        page = self.mira.get(f"{self.first_world}reports/aa-storm-moon-vigil/")
        self.assertContains(page, "private link for Rhea, Saturday night")

    def test_an_invalid_report_saves_nothing_and_shows_its_errors(self):
        response = self.file(self.link, VIGIL, text=VIGIL.text.replace("finished: false", "finished: maybe"))

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "finished: maybe")
        with self.in_world():
            self.assertFalse(Document.objects.filter(slug="aa-storm-moon-vigil").exists())

    def test_a_report_on_another_mod_is_refused(self):
        response = self.file(self.link, LEDGER_2)

        self.assertContains(response, "Nothing was saved.")
        with self.in_world():
            self.assertFalse(Document.objects.filter(slug="aa-the-tax-collectors-ledger-2")
                             .exists())

    def test_once_its_mod_is_finished_it_opens_nothing(self):
        self.file(self.link, VIGIL)
        self.file(self.link, VIGIL_2)

        self.assertEqual(self.client.get(self.link).status_code, 404)
        self.assertEqual(self.client.get(f"{self.link}file/").status_code, 404)


class WhatARefusedReportShows(LinkTest):
    def setUp(self):
        super().setUp()
        self.link = self.create_link(VIGIL_MOD)

    def test_no_other_documents_path_is_shown(self):
        named = VIGIL.text.replace("id: aa-storm-moon-vigil", "id: harrow-dunmore")

        response = self.file(self.link, VIGIL, text=named)

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "another document")
        self.assertNotContains(response, "canon/npcs/")

    def test_the_link_is_shown_once_and_kept_in_no_cookie(self):
        secret = self.create_link(VIGIL_MOD).removeprefix("/run/").removesuffix("/")

        self.assertNotIn(secret, str(self.mira.cookies))
        self.assertNotIn(secret, str(dict(self.mira.session)))


@override_settings(MOD_LINK_REPORTS_ALLOWED=2)
class ReportsThroughOneLink(LinkTest):
    def test_are_limited_whether_or_not_they_are_saved(self):
        link = self.create_link(VIGIL_MOD)
        self.file(link, VIGIL, text="nonsense")
        self.file(link, VIGIL, text="nonsense")

        response = self.client.post(f"{link}report/", {"text": VIGIL.text})

        self.assertEqual(response.status_code, 429)
        with self.in_world():
            self.assertFalse(Document.objects.filter(slug="aa-storm-moon-vigil").exists())
        self.assertEqual(self.client.get(link).status_code, 200)


class FlagsOnALinkedMod(LinkTest):
    def test_its_open_flags_are_shown_as_a_warning(self):
        link = self.create_link(WARRANT)

        page = self.client.get(link)

        self.assertContains(page, 'class="warning"')
        self.assertContains(page, "2 Flags")


class TurningALinkOff(LinkTest):
    def setUp(self):
        super().setUp()
        self.link = self.create_link(VIGIL_MOD)
        [self.row] = self.link_rows()

    def test_a_turned_off_link_opens_nothing(self):
        self.turn_off(VIGIL_MOD, self.row)

        self.assertEqual(self.client.get(self.link).status_code, 404)
        self.assertEqual(self.file(self.link, VIGIL).status_code, 404)
        self.assertContains(self.mira.get(self.mod_page(VIGIL_MOD)), "Turned off")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-runner")

        self.assertEqual(self.turn_off(VIGIL_MOD, self.row, by=sam).status_code, 404)
        self.assertEqual(self.client.get(self.link).status_code, 200)


@override_settings(MOD_LINK_FAILURES_ALLOWED=3)
class GuessingLinks(LinkTest):
    def test_a_made_up_link_opens_nothing(self):
        self.assertEqual(self.client.get("/run/not-a-real-link-at-all/").status_code, 404)

    def test_repeated_failures_are_refused_for_a_while(self):
        link = self.create_link(VIGIL_MOD)
        for attempt in range(3):
            self.client.get(f"/run/guess-{attempt}/")

        self.assertEqual(self.client.get("/run/guess-again/").status_code, 429)
        self.assertEqual(self.client.get(link).status_code, 429)

    def test_reloading_a_link_that_has_stopped_working_is_not_a_guess(self):
        link = self.create_link(VIGIL_MOD)
        [row] = self.link_rows()
        self.turn_off(VIGIL_MOD, row)
        for attempt in range(5):
            self.assertEqual(self.client.get(link).status_code, 404)

        other = self.create_link(WARRANT)
        self.assertEqual(self.client.get(other).status_code, 200)

    def test_another_address_is_not_held_up(self):
        for attempt in range(3):
            self.client.get(f"/run/guess-{attempt}/")

        link = self.create_link(VIGIL_MOD)
        self.assertEqual(self.client.get(link, REMOTE_ADDR="10.0.0.9").status_code, 200)


class TheDatabaseOnItsOwn(LinkTest):
    def test_with_nothing_set_no_link_can_be_seen(self):
        self.create_link(VIGIL_MOD)

        with tenancy.acting_as():
            self.assertEqual(ModLink.objects.count(), 0)

    def test_presenting_a_secret_shows_that_link_alone(self):
        link = self.create_link(VIGIL_MOD)
        self.create_link(WARRANT)
        secret = link.removeprefix("/run/").removesuffix("/")

        with tenancy.acting_as():
            tenancy.present_link(ModLink.hash_of(secret))
            self.assertEqual([row.label for row in ModLink.objects.all()],
                             ["Rhea, Saturday night"])
            self.assertEqual(Document.objects.count(), 0)
