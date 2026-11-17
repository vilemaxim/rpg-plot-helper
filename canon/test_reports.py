"""Submitting an After-Action Report, through web requests, with the scripted
reports that ship with plotcanon's sample World."""

import io

import plotcanon
from django.test import override_settings

from accounts.models import User
from canon.models import CanonChange, Document
from canon.tests import CanonTest
from organizations import tenancy
from organizations.models import Membership, Role
from organizations.tests import sign_in

SCRIPT = {s.path.rsplit("/", 1)[-1].removesuffix(".md"): s for s in plotcanon.sample_script()}
LEDGER_2 = SCRIPT["aa-the-tax-collectors-ledger-2"]      # interrupts the-tax-collectors-ledger
STAIR = SCRIPT["aa-blood-on-the-salt-stair"]            # finishes blood-on-the-salt-stair
VIGIL = SCRIPT["aa-storm-moon-vigil"]                   # interrupts storm-moon-vigil
VIGIL_2 = SCRIPT["aa-storm-moon-vigil-2"]               # finishes storm-moon-vigil
KEEPER = SCRIPT["aa-what-the-keeper-saw"]               # finishes what-the-keeper-saw

MOD_OF = {"aa-the-tax-collectors-ledger-2": "the-tax-collectors-ledger",
          "aa-blood-on-the-salt-stair": "blood-on-the-salt-stair",
          "aa-storm-moon-vigil": "storm-moon-vigil",
          "aa-storm-moon-vigil-2": "storm-moon-vigil",
          "aa-what-the-keeper-saw": "what-the-keeper-saw"}


class ReportTest(CanonTest):
    """Mira is Plot Master of a World holding the sample World."""

    def setUp(self):
        super().setUp()
        self.import_sample()
        self.pending = f"{self.first_world}changes/"

    def mod_page(self, mod):
        return f"{self.first_world}mods/{mod}/"

    def report_form(self, mod):
        return f"{self.first_world}mods/{mod}/report/"

    def submit(self, scripted, by=None, mod=None, text=None):
        name = scripted.path.rsplit("/", 1)[-1].removesuffix(".md")
        return (by or self.mira).post(self.report_form(mod or MOD_OF[name]),
                                      {"text": scripted.text if text is None else text},
                                      follow=True)

    def in_world(self):
        """Run database queries as Mira in her Organization."""
        user = User.objects.get(email="mira@example.com")
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get().organization_id
        return tenancy.acting_as(user=user, organization=organization)

    def stored(self, slug):
        with self.in_world():
            return Document.objects.get(slug=slug)

    def state_shown(self, mod):
        page = self.mira.get(self.mod_page(mod)).content.decode()
        return page.split('<span class="state">', 1)[1].split("<", 1)[0]


class Submitting(ReportTest):
    def test_a_mod_that_can_be_run_offers_the_form(self):
        self.assertContains(self.mira.get(self.mod_page("storm-moon-vigil")),
                            self.report_form("storm-moon-vigil"))
        form = self.mira.get(self.report_form("storm-moon-vigil"))
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, "<textarea")
        self.assertContains(form, 'type="file"')

    def test_a_valid_report_is_saved_and_shown(self):
        response = self.submit(LEDGER_2)

        self.assertEqual(response.redirect_chain[-1][0],
                         f"{self.first_world}reports/aa-the-tax-collectors-ledger-2/")
        self.assertContains(response, "The Tax Collector&#x27;s Ledger at Storm Moon")
        self.assertEqual(self.stored("aa-the-tax-collectors-ledger-2").text, LEDGER_2.text)

    def test_its_proposed_canon_changes_are_listed_as_pending(self):
        self.submit(LEDGER_2)

        response = self.mira.get(self.pending)

        self.assertContains(response, "mira@example.com")

        self.assertContains(response, "Clerk Pell")
        self.assertContains(response, "Found alive, hiding in the boat shed at the light.")
        self.assertContains(response, "Harrow Dunmore")
        self.assertContains(response, "Admitted he hid the clerk and has read the ledger.")
        self.assertContains(response, f"{self.first_world}reports/aa-the-tax-collectors-ledger-2/")
        self.assertContains(response, "2 Canon Changes waiting")

    def test_before_any_report_nothing_is_pending(self):
        """The reports that came in with the import were already decided."""
        response = self.mira.get(self.pending)

        self.assertContains(response, "No Canon Changes are waiting")

    def test_the_world_page_says_how_many_are_waiting(self):
        self.assertNotContains(self.mira.get(self.first_world), self.pending)

        self.submit(LEDGER_2)

        page = self.mira.get(self.first_world)
        self.assertContains(page, self.pending)
        self.assertContains(page, "2 Canon Changes waiting")

    def test_the_report_records_its_mod_event_mod_runner_and_pcs(self):
        page = self.submit(LEDGER_2)

        for link in ("mods/the-tax-collectors-ledger/", "events/e03-storm-moon/",
                     "pcs/pc-wren-halloway/", "pcs/pc-dask-orrin/"):
            with self.subTest(link):
                self.assertContains(page, f'href="{self.first_world}{link}"')
        self.assertContains(page, "<dt>Mod Runner</dt>")
        self.assertContains(page, "dev")

    def test_the_report_shows_who_submitted_it(self):
        page = self.submit(LEDGER_2)

        self.assertContains(page, "Submitted by mira@example.com")

    def test_each_change_on_the_report_shows_as_proposed(self):
        page = self.submit(LEDGER_2).content.decode()

        self.assertEqual(page.count("<td>Proposed</td>"), 2)

    def test_a_report_can_be_uploaded_as_a_file_instead(self):
        upload = io.BytesIO(LEDGER_2.text.encode())
        upload.name = "report.md"

        response = self.mira.post(self.report_form("the-tax-collectors-ledger"),
                                  {"file": upload}, follow=True)

        self.assertContains(response, "The Tax Collector&#x27;s Ledger at Storm Moon")

    def test_the_mods_page_lists_the_new_report(self):
        self.submit(LEDGER_2)

        page = self.mira.get(self.mod_page("the-tax-collectors-ledger"))

        self.assertContains(page, f"{self.first_world}reports/aa-the-tax-collectors-ledger-2/")
        self.assertContains(page, f"{self.first_world}reports/aa-the-tax-collectors-ledger/")


class Rejected(ReportTest):
    def assert_nothing_saved(self):
        with self.in_world():
            self.assertEqual(Document.objects.count(), 48)
            self.assertEqual(CanonChange.objects.filter(decision="proposed").count(), 0)

    def test_an_invalid_file_saves_nothing_and_shows_the_errors_as_copyable_text(self):
        broken = LEDGER_2.text.replace("mod_runner: dev\n", "").replace("pc-dask-orrin", "pc-nobody")

        response = self.submit(LEDGER_2, text=broken)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was saved")
        page = response.content.decode()
        errors = page.split("<pre>", 1)[1].split("</pre>", 1)[0]
        self.assertIn("missing required field `mod_runner`", errors)
        self.assertIn("`pcs: pc-nobody` does not resolve to any document", errors)
        self.assert_nothing_saved()

    def test_what_was_pasted_is_kept_so_it_can_be_corrected(self):
        broken = LEDGER_2.text.replace("mod_runner: dev\n", "")

        response = self.submit(LEDGER_2, text=broken)

        self.assertContains(response, "Scene 2 and the start of scene 3.")

    def test_something_that_is_not_a_report_at_all(self):
        response = self.submit(LEDGER_2, text="Here is what happened on Saturday night.")

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, "no YAML frontmatter block")
        self.assert_nothing_saved()

    def test_a_file_that_is_some_other_kind_of_document(self):
        npc = plotcanon.sample_world()["canon/npcs/cutter-jass.md"]

        response = self.submit(LEDGER_2, text=npc)

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, "is not an After-Action Report")
        self.assert_nothing_saved()

    def test_a_report_for_a_different_mod_than_the_one_chosen(self):
        response = self.submit(STAIR, mod="storm-moon-vigil")

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, "blood-on-the-salt-stair")
        self.assert_nothing_saved()

    def test_the_same_report_twice(self):
        self.submit(LEDGER_2)

        response = self.submit(LEDGER_2)

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, "`aa-the-tax-collectors-ledger-2` has already been filed")
        with self.in_world():
            self.assertEqual(Document.objects.count(), 49)

    def test_neither_pasted_nor_uploaded(self):
        response = self.mira.post(self.report_form("storm-moon-vigil"), {"text": "  "}, follow=True)

        self.assertContains(response, "Paste the report or choose its file")
        self.assert_nothing_saved()

    def test_both_pasted_and_uploaded(self):
        upload = io.BytesIO(VIGIL.text.encode())
        upload.name = "report.md"

        response = self.mira.post(self.report_form("storm-moon-vigil"),
                                  {"text": VIGIL.text, "file": upload}, follow=True)

        self.assertContains(response, "not both")
        self.assert_nothing_saved()

    def test_an_uploaded_file_that_is_not_text(self):
        upload = io.BytesIO(b"\xff\xfe\x00 not text")
        upload.name = "report.md"

        response = self.mira.post(self.report_form("storm-moon-vigil"), {"file": upload},
                                  follow=True)

        self.assertContains(response, "is not UTF-8 text")
        self.assert_nothing_saved()

    @override_settings(IMPORT_MAX_FILE_BYTES=500)
    def test_a_report_far_too_large(self):
        response = self.submit(VIGIL)

        self.assertContains(response, "too large")
        self.assert_nothing_saved()

    def test_a_report_with_a_character_the_database_cannot_hold(self):
        response = self.submit(VIGIL, text=VIGIL.text.replace("The brother", "The\x00 brother"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Null characters are not allowed")
        self.assert_nothing_saved()

    def test_an_uploaded_report_with_such_a_character(self):
        upload = io.BytesIO(VIGIL.text.replace("The brother", "The\x00 brother").encode())
        upload.name = "report.md"

        response = self.mira.post(self.report_form("storm-moon-vigil"), {"file": upload},
                                  follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was saved")
        self.assert_nothing_saved()

    def test_a_report_given_the_id_of_some_other_document(self):
        clash = VIGIL.text.replace("id: aa-storm-moon-vigil", "id: harrow-dunmore")

        response = self.submit(VIGIL, text=clash)

        self.assertContains(response, "Nothing was saved")
        self.assertContains(response, "duplicate id `harrow-dunmore`")
        self.assert_nothing_saved()


class ReadingTheReport(ReportTest):
    """A report is read as YAML reads it, however it is laid out."""

    def assert_filed(self, text, slug="aa-storm-moon-vigil"):
        response = self.submit(VIGIL, text=text)
        self.assertNotContains(response, "Nothing was saved")
        self.assertEqual(response.redirect_chain[-1][0], f"{self.first_world}reports/{slug}/")

    def test_a_report_cannot_decide_its_own_canon_changes(self):
        for decision in ("approved", "rejected"):
            with self.subTest(decision):
                text = VIGIL.text.replace("decision: proposed", f"decision: {decision}")

                response = self.submit(VIGIL, text=text)

                self.assertContains(response, "Nothing was saved")
                self.assertContains(response, "only a Plot Master")
                with self.in_world():
                    self.assertFalse(Document.objects.filter(slug="aa-storm-moon-vigil").exists())

    def test_an_uploaded_report_with_windows_line_endings(self):
        upload = io.BytesIO(VIGIL.text.replace("\n", "\r\n").encode())
        upload.name = "report.md"

        response = self.mira.post(self.report_form("storm-moon-vigil"), {"file": upload},
                                  follow=True)

        self.assertContains(response, "Storm Moon Vigil at Storm Moon")

    def test_comments_after_the_values_that_say_where_it_belongs(self):
        self.assert_filed(VIGIL.text
                          .replace("id: aa-storm-moon-vigil\n", "id: aa-storm-moon-vigil  # mine\n")
                          .replace("event: e03-storm-moon\n", "event: e03-storm-moon # Sat\n")
                          .replace("type: after-action\n", "type: after-action # yes\n"))

    def test_a_report_an_llm_wrapped_in_a_code_fence(self):
        """Each fence on a report of its own, since a report is filed once."""
        for scripted, fence in ((LEDGER_2, "```markdown"), (STAIR, "```md"), (VIGIL, "```"),
                                (KEEPER, "~~~")):
            with self.subTest(fence):
                closing = fence[:3]
                name = scripted.path.rsplit("/", 1)[-1].removesuffix(".md")
                response = self.submit(
                    scripted, text=f"Here is your report:\n\n{fence}\n{scripted.text}{closing}\n")
                self.assertNotContains(response, "Nothing was saved")
                self.assertEqual(response.redirect_chain[-1][0],
                                 f"{self.first_world}reports/{name}/")

    def test_quoted_values_and_a_value_on_the_next_line(self):
        self.assert_filed(VIGIL.text
                          .replace("id: aa-storm-moon-vigil\n", "id:\n  aa-storm-moon-vigil\n")
                          .replace("event: e03-storm-moon\n", "event: 'e03-storm-moon'\n"))


class ChangingTheModsFile(ReportTest):
    """Only the Mod's state changes, however its file is laid out."""

    MOD = "storm-moon-vigil"

    def lay_out(self, change):
        with self.in_world():
            mod = Document.objects.get(slug=self.MOD)
            mod.text = change(mod.text)
            report = plotcanon.load_world({**{d.path: d.text for d in Document.objects.all()},
                                           mod.path: mod.text})
            self.assertEqual(report.errors, (), "the laid-out Mod must still be valid")
            mod.save(update_fields=["text"])
        return mod.text

    def assert_only_the_state_moved(self, before):
        response = self.submit(VIGIL)
        self.assertNotContains(response, "Nothing was saved")
        self.assertEqual(self.state_shown(self.MOD), "In progress")
        return self.stored(self.MOD).text

    def test_a_line_inside_a_quoted_title_that_looks_like_the_state(self):
        before = self.lay_out(lambda t: t.replace(
            'title: "Storm Moon Vigil"', 'title: "Storm Moon\nstate: approved\n  Vigil"'))

        after = self.assert_only_the_state_moved(before)

        self.assertIn('title: "Storm Moon\nstate: approved\n  Vigil"', after)

    def test_a_state_with_a_comment_after_it(self):
        before = self.lay_out(lambda t: t.replace("state: approved\n",
                                                  "state: approved  # ready\n"))

        after = self.assert_only_the_state_moved(before)

        self.assertEqual(after, before.replace("state: approved  # ready",
                                               "state: in-progress  # ready"))

    def test_a_state_in_quotes(self):
        before = self.lay_out(lambda t: t.replace("state: approved\n", "state: 'approved'\n"))

        after = self.assert_only_the_state_moved(before)

        self.assertEqual(after, before.replace("state: 'approved'", "state: in-progress"))

    def test_a_state_on_the_line_after_its_name(self):
        before = self.lay_out(lambda t: t.replace("state: approved\n", "state:\n  approved\n"))

        after = self.assert_only_the_state_moved(before)

        self.assertEqual(after, before.replace("state:\n  approved", "state:\n  in-progress"))

    def test_windows_line_endings_are_all_kept(self):
        before = self.lay_out(lambda t: t.replace("\n", "\r\n"))

        after = self.assert_only_the_state_moved(before)

        self.assertEqual(after.count("\r\n"), before.count("\r\n"))
        self.assertEqual(after, before.replace("state: approved", "state: in-progress"))


class TheModsState(ReportTest):
    def test_an_approved_mod_becomes_in_progress_when_a_report_says_there_is_more(self):
        self.assertEqual(self.state_shown("storm-moon-vigil"), "Approved")

        self.submit(VIGIL)

        self.assertEqual(self.state_shown("storm-moon-vigil"), "In progress")

    def test_a_mod_becomes_finished_when_the_report_says_it_finished(self):
        self.submit(STAIR)

        self.assertEqual(self.state_shown("blood-on-the-salt-stair"), "Finished")

    def test_a_report_that_says_the_mod_was_not_played_leaves_it_as_it_was(self):
        text = VIGIL.text.replace("ran: true", "ran: false")

        response = self.submit(VIGIL, text=text)

        self.assertNotContains(response, "Nothing was saved")
        self.assertEqual(self.state_shown("storm-moon-vigil"), "Approved")

    def test_a_mod_already_in_progress_stays_so_after_another_interruption(self):
        self.submit(LEDGER_2)

        self.assertEqual(self.state_shown("the-tax-collectors-ledger"), "In progress")

    def test_a_second_report_can_be_filed_for_the_same_mod_and_can_finish_it(self):
        self.submit(VIGIL)

        response = self.submit(VIGIL_2)

        self.assertContains(response, "Storm Moon Vigil at Storm Moon")
        self.assertEqual(self.state_shown("storm-moon-vigil"), "Finished")
        page = self.mira.get(self.mod_page("storm-moon-vigil"))
        self.assertContains(page, "reports/aa-storm-moon-vigil/")
        self.assertContains(page, "reports/aa-storm-moon-vigil-2/")

    def test_the_mods_stored_file_says_the_same_as_its_page(self):
        self.submit(STAIR)

        text = self.stored("blood-on-the-salt-stair").text

        self.assertIn("\nstate: finished\n", text)
        self.assertNotIn("state: approved", text)
        self.assertEqual(self.stored("blood-on-the-salt-stair").fields["state"], "finished")

    def test_nothing_else_in_the_mods_file_changes(self):
        before = self.stored("blood-on-the-salt-stair").text

        self.submit(STAIR)

        after = self.stored("blood-on-the-salt-stair").text
        self.assertEqual(after, before.replace("state: approved", "state: finished"))

    def test_a_finished_mod_takes_no_more_reports(self):
        self.submit(STAIR)

        self.assertNotContains(self.mira.get(self.mod_page("blood-on-the-salt-stair")),
                               self.report_form("blood-on-the-salt-stair"))
        form = self.mira.get(self.report_form("blood-on-the-salt-stair"))
        self.assertContains(form, "is finished")
        self.assertNotContains(form, "<textarea")

    def test_a_draft_or_shelved_mod_cannot_be_reported_on(self):
        for mod in ("the-guildmasters-daughter", "the-wardens-ball"):
            with self.subTest(mod):
                self.assertNotContains(self.mira.get(self.mod_page(mod)), self.report_form(mod))
                form = self.mira.get(self.report_form(mod))
                self.assertNotContains(form, "<textarea")
                response = self.mira.post(self.report_form(mod), {"text": VIGIL.text}, follow=True)
                self.assertNotContains(response, "Storm Moon Vigil at Storm Moon")

    def test_after_the_whole_script_the_world_is_still_one_plotcanon_accepts(self):
        """What is stored can always be exported as a valid World."""
        for scripted in plotcanon.sample_script():
            response = self.submit(scripted)
            self.assertNotContains(response, "Nothing was saved")

        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        report = plotcanon.load_world(files)

        self.assertEqual(report.text(), "")
        self.assertEqual(len(files), 53)


class PendingChangesDoNotAlterCanon(ReportTest):
    def test_an_npc_a_report_says_died_is_still_alive_until_someone_decides(self):
        before = self.stored("harrow-dunmore").text

        self.submit(STAIR)

        page = self.mira.get(f"{self.first_world}npcs/harrow-dunmore/")
        self.assertContains(page, '<span class="state">Alive</span>', html=True)
        self.assertEqual(self.stored("harrow-dunmore").text, before)
        self.assertEqual(self.stored("harrow-dunmore").fields["status"], "alive")

    def test_the_npcs_page_links_the_report_that_proposes_the_change(self):
        self.submit(STAIR)

        page = self.mira.get(f"{self.first_world}npcs/harrow-dunmore/")

        self.assertContains(page, f"{self.first_world}reports/aa-blood-on-the-salt-stair/")

    def test_two_reports_that_contradict_each_other_are_both_pending(self):
        self.submit(STAIR)
        self.submit(VIGIL)

        page = self.mira.get(self.pending).content.decode()

        self.assertIn("Went over the edge at the third landing", page)
        self.assertIn("Seen rowing out past the light", page)

    def test_only_what_is_still_proposed_is_pending(self):
        with self.in_world():
            decided = CanonChange.objects.exclude(decision="proposed").count()
            self.assertEqual(CanonChange.objects.filter(decision="proposed").count(), 0)

        self.submit(STAIR)

        with self.in_world():
            self.assertEqual(CanonChange.objects.exclude(decision="proposed").count(), decided)
            self.assertEqual(CanonChange.objects.filter(decision="proposed").count(), 3)
        self.assertGreater(decided, 0, "the imported reports' changes are on record too")


class WhoMaySubmit(ReportTest):
    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.eve = sign_in("eve@example.com")

    def test_anyone_with_a_role_in_the_world_can(self):
        # Each may read the Mod: a Plot Master reads everything, the Mod
        # Writer writes it, and the Mod Runner is assigned to it (ADR-0010).
        reports = dict(zip(Role, (VIGIL, STAIR, KEEPER), strict=True))
        for role, scripted in reports.items():
            with self.subTest(role=role):
                email = f"{role}@example.com"
                browser = self.join(email)
                self.give(email, role)
                if role == Role.MOD_WRITER:
                    self.mira.post(f"{self.first_world}mod-writers/",
                                   {"handle": "dev", "user": User.objects.get(email=email).pk})
                if role == Role.MOD_RUNNER:
                    self.mira.post(f"{self.mod_page('what-the-keeper-saw')}assignments/",
                                   {"user": User.objects.get(email=email).pk, "event": ""})

                response = self.submit(scripted, by=browser)

                self.assertContains(response, f"Submitted by {email}")
                self.assertEqual(browser.get(self.pending).status_code,
                                 200 if role == Role.PLOT_MASTER else 404)

    def test_someone_with_no_role_in_the_world_cannot(self):
        for browser in (self.sam, self.eve):
            self.assertEqual(browser.get(self.report_form("storm-moon-vigil")).status_code, 404)
            self.assertEqual(self.submit(VIGIL, by=browser).status_code, 404)
            self.assertEqual(browser.get(self.pending).status_code, 404)
        self.assertEqual(self.state_shown("storm-moon-vigil"), "Approved")

    def test_a_signed_out_person_is_sent_to_sign_in(self):
        form = self.report_form("storm-moon-vigil")

        self.assertRedirects(self.client.get(form), f"/sign-in/?next={form}")

    def test_a_mod_that_does_not_exist_is_not_found(self):
        self.assertEqual(self.mira.get(self.report_form("no-such-mod")).status_code, 404)
        self.assertEqual(self.mira.get(self.report_form("harrow-dunmore")).status_code, 404)


class TheDatabaseOnItsOwn(ReportTest):
    def test_with_no_organization_set_a_query_for_canon_changes_returns_no_rows(self):
        self.submit(STAIR)

        with tenancy.acting_as():
            self.assertEqual(CanonChange.objects.count(), 0)

    def test_another_organization_sees_none_of_them(self):
        self.submit(STAIR)
        sign_in("eve@example.com")
        eve = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=eve):
            organization = Membership.objects.get().organization_id

        with tenancy.acting_as(user=eve, organization=organization):
            self.assertEqual(CanonChange.objects.count(), 0)


class AnotherEventTest(ReportTest):
    """Reports on a Mod at an Event it does not list."""

    MOD = "storm-moon-vigil"            # lists e03-storm-moon, in Tideward

    def at(self, event, text=None):
        return (text or VIGIL.text).replace("event: e03-storm-moon\n", f"event: {event}\n")


class AtAnEventTheModDoesNotList(AnotherEventTest):
    """A Mod can be interrupted and go on at another Event. Filing a report at
    an Event of the Mod's Campaign that it does not list yet adds that Event."""

    def test_the_report_is_saved_and_the_mod_then_lists_that_event(self):
        response = self.submit(VIGIL, text=self.at("e01-low-tide"))

        self.assertNotContains(response, "Nothing was saved")
        self.assertEqual(response.redirect_chain[-1][0],
                         f"{self.first_world}reports/aa-storm-moon-vigil/")
        self.assertEqual(self.stored(self.MOD).fields["events"],
                         ["e03-storm-moon", "e01-low-tide"])
        self.assertContains(self.mira.get(self.mod_page(self.MOD)),
                            f'href="{self.first_world}events/e01-low-tide/"')

    def test_nothing_else_in_the_mods_file_changes(self):
        before = self.stored(self.MOD).text

        self.submit(VIGIL, text=self.at("e01-low-tide"))

        self.assertEqual(self.stored(self.MOD).text,
                         before.replace("events: [e03-storm-moon]\n",
                                        "events: [e03-storm-moon, e01-low-tide]\n")
                               .replace("state: approved", "state: in-progress"))

    def test_the_mods_state_follows_the_report(self):
        self.submit(VIGIL, text=self.at("e01-low-tide"))

        self.assertEqual(self.state_shown(self.MOD), "In progress")

    def test_a_report_that_says_the_mod_was_not_played_still_adds_the_event(self):
        before = self.stored(self.MOD).text

        response = self.submit(VIGIL, text=self.at("e01-low-tide").replace("ran: true",
                                                                            "ran: false"))

        self.assertNotContains(response, "Nothing was saved")
        self.assertEqual(self.state_shown(self.MOD), "Approved")
        self.assertEqual(self.stored(self.MOD).text,
                         before.replace("[e03-storm-moon]", "[e03-storm-moon, e01-low-tide]"))

    def test_a_report_at_an_event_the_mod_already_lists_leaves_its_events_alone(self):
        before = self.stored(self.MOD).text

        self.submit(VIGIL)

        self.assertEqual(self.stored(self.MOD).text,
                         before.replace("state: approved", "state: in-progress"))

    def test_what_is_stored_is_still_a_world_plotcanon_accepts(self):
        self.submit(VIGIL, text=self.at("e01-low-tide"))

        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        self.assertIn("after-actions/e01-low-tide/aa-storm-moon-vigil.md", files)
        self.assertEqual(plotcanon.load_world(files).text(), "")


class RefusedAtAnEventTheModCannotRunAt(AnotherEventTest):
    def assert_refused_saying(self, event, *words):
        before = self.stored(self.MOD).text

        response = self.submit(VIGIL, text=self.at(event))

        self.assertContains(response, "Nothing was saved")
        for said in words:
            self.assertContains(response, said)
        self.assertEqual(self.stored(self.MOD).text, before)
        self.assertEqual(self.state_shown(self.MOD), "Approved")
        with self.in_world():
            self.assertFalse(Document.objects.filter(slug="aa-storm-moon-vigil").exists())
            self.assertEqual(CanonChange.objects.filter(decision="proposed").count(), 0)

    def test_an_event_in_another_campaign(self):
        self.assert_refused_saying("e04-second-lantern", "e04-second-lantern",
                                   "Second Lantern", "tideward", "the report&#x27;s `event`")

    def test_an_event_that_does_not_exist(self):
        self.assert_refused_saying("e09-nowhere", "There is no Event `e09-nowhere`",
                                   "the report&#x27;s `event`")

    def test_the_name_of_some_other_kind_of_document(self):
        self.assert_refused_saying("tideward", "There is no Event `tideward`")


class AddingTheEventToTheModsFile(AnotherEventTest):
    """Only the Mod's `events` and state change, however its file is laid out."""

    lay_out = ChangingTheModsFile.lay_out

    def file_at_low_tide(self, events=("e03-storm-moon", "e01-low-tide")):
        """The Mod's file once a report at Low Tide is filed, with its state
        put back, so that what is left to compare is its events."""
        response = self.submit(VIGIL, text=self.at("e01-low-tide"))
        self.assertNotContains(response, "Nothing was saved")
        self.assertEqual(self.stored(self.MOD).fields["events"], list(events))
        return self.stored(self.MOD).text.replace("state: in-progress", "state: approved")

    def test_a_list_down_the_page(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n",
                                                  "events:\n  - e03-storm-moon\n"))

        self.assertEqual(self.file_at_low_tide(),
                         before.replace("  - e03-storm-moon\n",
                                        "  - e03-storm-moon\n  - e01-low-tide\n"))

    def test_a_list_down_the_page_not_indented(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n",
                                                  "events:\n- e03-storm-moon\n"))

        self.assertEqual(self.file_at_low_tide(),
                         before.replace("- e03-storm-moon\n",
                                        "- e03-storm-moon\n- e01-low-tide\n"))

    def test_a_list_down_the_page_with_comments(self):
        before = self.lay_out(lambda t: t.replace(
            "events: [e03-storm-moon]\n",
            "events:  # where it runs\n    - e03-storm-moon  # the first night\n"
            "    # more to come\n"))

        self.assertEqual(self.file_at_low_tide(),
                         before.replace("    - e03-storm-moon  # the first night\n",
                                        "    - e03-storm-moon  # the first night\n"
                                        "    - e01-low-tide\n"))

    def test_a_list_on_one_line_with_a_comment_and_spacing(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n",
                                                  "events: [ e03-storm-moon ]  # so far\n"))

        self.assertEqual(self.file_at_low_tide(),
                         before.replace("[ e03-storm-moon ]",
                                        "[ e03-storm-moon, e01-low-tide ]"))

    def test_quoted_items(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n",
                                                  "events: ['e03-storm-moon']\n"))

        self.assertEqual(self.file_at_low_tide(),
                         before.replace("['e03-storm-moon']",
                                        "['e03-storm-moon', e01-low-tide]"))

    def test_an_empty_list(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n",
                                                  "events: []\n"))

        self.assertEqual(self.file_at_low_tide(events=["e01-low-tide"]),
                         before.replace("events: []", "events: [e01-low-tide]"))

    def test_no_events_at_all(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n", ""))

        self.assertEqual(self.file_at_low_tide(events=["e01-low-tide"]), before.replace("supersedes: []\n",
                                              "supersedes: []\nevents: [e01-low-tide]\n"))

    def test_windows_line_endings_down_the_page(self):
        before = self.lay_out(lambda t: t.replace("events: [e03-storm-moon]\n",
                                                  "events:\n  - e03-storm-moon\n")
                                         .replace("\n", "\r\n"))

        after = self.file_at_low_tide()

        self.assertNotIn("\n", after.replace("\r\n", ""))
        self.assertEqual(after, before.replace("  - e03-storm-moon\r\n",
                                               "  - e03-storm-moon\r\n  - e01-low-tide\r\n"))

    def test_windows_line_endings_on_one_line(self):
        before = self.lay_out(lambda t: t.replace("\n", "\r\n"))

        self.assertEqual(self.file_at_low_tide(),
                         before.replace("[e03-storm-moon]", "[e03-storm-moon, e01-low-tide]"))
