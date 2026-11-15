"""Interludes: adding one to the World's order of Events, and recording the
Canon Changes made during it, with no Mod run. Through web requests, with
plotcanon's sample World, whose Events run e01 to e04."""

import plotcanon

from canon.models import CanonChange, Document, Flag
from canon.test_decisions import DecisionTest
from canon.test_resolving import WARRANT
from organizations.tests import sign_in

QUIET = "the-quiet-month"
RECORD = f"ic-{QUIET}"

PASTED = f"""---
id: {RECORD}
type: interlude-changes
event: {QUIET}
recorded_by: mira
canon_changes:
  - entity: harrow-dunmore
    kind: status
    from: alive
    to: dead
    decision: proposed
    summary: Died of the fever over the quiet month.
  - entity: harrow-dunmore
    kind: narrative
    decision: proposed
    summary: His ledger passed to the harbour office.
---

A hard month on the docks.
"""


class InterludeTest(DecisionTest):
    def setUp(self):
        super().setUp()
        self.events_page = f"{self.first_world}events/"
        self.add_page = f"{self.first_world}add-interlude/"

    def add(self, name="The Quiet Month", after="e03-storm-moon", campaign="lanternlight",
            by=None, **extra):
        data = {"name": name, "after": after, "campaign": campaign,
                "in_world": "the month after the storm", "real_date": "2026-04-01", **extra}
        return (by or self.mira).post(self.add_page, data, follow=True)

    def record_page(self, event=QUIET):
        return f"{self.first_world}events/{event}/record/"

    def record(self, by=None, **change):
        data = {"entity": "harrow-dunmore", "kind": "status", "before": "", "after": "dead",
                "summary": "Died of the fever over the quiet month.", **change}
        return (by or self.mira).post(self.record_page(), data, follow=True)

    def paste(self, text=PASTED, by=None):
        return (by or self.mira).post(self.record_page(), {"text": text}, follow=True)

    def ordinal(self, event):
        return self.stored(event).fields["ordinal"]

    def files(self):
        with self.in_world():
            return dict(Document.objects.values_list("path", "text"))

    def assert_valid(self):
        """plotcanon accepts the World, and no entity's file disagrees with its
        approved changes. A Mod may be warned about: a change can leave a Mod
        expecting what is no longer so, which is what its Flag is for."""
        report = plotcanon.load_world(self.files())
        self.assertTrue(report.ok, report.text())
        self.assertFalse([w for w in report.warnings
                          if "approved but not applied" in w.message
                          or "advance `as_of`" in w.message], report.text())


class AddingAnInterlude(InterludeTest):
    def test_the_events_page_offers_a_plot_master_the_form(self):
        self.assertContains(self.mira.get(self.events_page), self.add_page)
        page = self.mira.get(self.add_page)
        self.assertContains(page, '<option value="e03-storm-moon">')
        self.assertContains(page, '<option value="lanternlight">')

    def test_it_takes_the_place_after_the_chosen_event(self):
        before = self.stored("e04-second-lantern").text

        response = self.add()

        self.assertEqual(response.redirect_chain[-1][0], f"{self.events_page}{QUIET}/")
        event = self.stored(QUIET)
        self.assertEqual(event.path, f"canon/events/{QUIET}.md")
        self.assertEqual(event.fields["ordinal"], 4)
        self.assertEqual(event.fields["period_type"], "interlude")
        self.assertEqual(event.fields["campaign"], "lanternlight")
        self.assertEqual(event.name, "The Quiet Month")
        # Every later Event moves up one, and nothing else in its file changes.
        self.assertEqual(self.stored("e04-second-lantern").text,
                         before.replace("ordinal: 4", "ordinal: 5"))
        self.assertEqual(self.ordinal("e03-storm-moon"), 3)
        self.assert_valid()

    def test_after_the_last_event_nothing_moves(self):
        self.add(after="e04-second-lantern")

        self.assertEqual(self.ordinal(QUIET), 5)
        self.assertEqual(self.ordinal("e04-second-lantern"), 4)
        self.assert_valid()

    def test_a_name_already_used_as_an_id_gets_an_id_of_its_own(self):
        self.add()
        self.add(after="e04-second-lantern")

        self.assertEqual(self.ordinal(f"{QUIET}-2"), 6)
        self.assert_valid()

    def test_what_is_typed_cannot_break_the_file(self):
        self.add(name='The "Quiet": Month\n---', in_world="a: b\n- c")

        self.assert_valid()
        with self.in_world():
            event = Document.objects.get(kind="event", fields__period_type="interlude")
        self.assertEqual(event.fields["in_world"], "a: b - c")

    def test_a_campaign_or_event_the_world_does_not_have_is_refused(self):
        for bad in ({"campaign": "nowhere"}, {"after": "e99-nothing"}, {"name": "  "}):
            response = self.add(**bad)
            self.assertContains(response, "errorlist")

        with self.in_world():
            self.assertFalse(Document.objects.filter(fields__period_type="interlude").exists())

    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

        self.assertNotContains(sam.get(self.events_page), self.add_page)
        self.assertEqual(sam.get(self.add_page).status_code, 404)
        self.assertEqual(self.add(by=sam).status_code, 404)


class RecordingChanges(InterludeTest):
    def setUp(self):
        super().setUp()
        self.add()

    def test_an_interludes_page_offers_a_plot_master_the_form(self):
        page = self.mira.get(f"{self.events_page}{QUIET}/")

        self.assertContains(page, self.record_page())
        self.assertNotContains(self.mira.get(f"{self.events_page}e03-storm-moon/"),
                               "/record/")
        self.assertEqual(self.mira.get(self.record_page("e03-storm-moon")).status_code, 404)

    def test_a_change_entered_is_canon_at_once(self):
        response = self.record()

        self.assertContains(response, "Canon")
        harrow = self.stored("harrow-dunmore")
        self.assertEqual(harrow.fields["status"], "dead")
        self.assertEqual(harrow.fields["as_of"], QUIET)
        change = self.change("harrow-dunmore", RECORD)
        self.assertEqual(change.decision, "approved")
        self.assertEqual(change.before, "alive")
        self.assertEqual(change.decided_by.email, "mira@example.com")
        record = self.stored(RECORD)
        self.assertEqual(record.path, f"interludes/{QUIET}/{RECORD}.md")
        # Who recorded it is kept here, not in the file (ADR-0001).
        self.assertEqual(record.fields["recorded_by"], "plot-master")
        self.assertEqual(record.submitted_by.email, "mira@example.com")
        self.assertNotIn("mira", record.text)
        self.assert_valid()

    def test_it_appears_in_the_history_marked_as_from_the_interlude(self):
        self.record()

        page = self.npc("harrow-dunmore").content.decode()
        history = page.split("<h2>History</h2>", 1)[1]
        self.assertIn("Changes during The Quiet Month", history)

    def test_a_pasted_file_records_all_its_changes_approved(self):
        self.paste()

        with self.in_world():
            decisions = list(CanonChange.objects.filter(report__slug=RECORD)
                             .values_list("decision", flat=True))
        self.assertEqual(decisions, ["approved", "approved"])
        self.assertIn("decision: approved", self.stored(RECORD).text)
        self.assertEqual(self.stored("harrow-dunmore").fields["status"], "dead")
        self.assert_valid()

    def test_they_raise_flags_on_the_mods_they_affect(self):
        self.record()

        with self.in_world():
            flagged = set(Flag.objects.filter(change__report__slug=RECORD)
                          .values_list("mod__slug", flat=True))
        self.assertIn(WARRANT, flagged)

    def test_a_second_record_in_the_same_interlude_gets_its_own_id(self):
        self.record()
        self.record(kind="narrative", after="", summary="Buried at sea.")

        self.assertEqual(self.stored(f"{RECORD}-2").fields["canon_changes"][0]["summary"],
                         "Buried at sea.")
        self.assert_valid()

    def test_a_change_that_contradicts_canon_saves_nothing(self):
        before = self.files()

        response = self.record(before="missing")

        self.assertContains(response, "Nothing was saved.")
        self.assertEqual(self.files(), before)

    def test_an_invalid_file_saves_nothing_and_shows_its_errors(self):
        before = self.files()

        response = self.paste(PASTED.replace("to: dead", "to: sleeping"))

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "sleeping")
        self.assertEqual(self.files(), before)

    def test_a_file_with_a_rejected_change_is_refused(self):
        before = self.files()

        response = self.paste(PASTED.replace("decision: proposed", "decision: rejected", 1))

        self.assertContains(response, "says it was rejected")
        self.assertEqual(self.files(), before)

    def test_if_a_later_change_in_a_file_cannot_be_approved_nothing_is_saved(self):
        before = self.files()
        second = PASTED.replace(
            "  - entity: harrow-dunmore\n    kind: narrative\n    decision: proposed\n"
            "    summary: His ledger passed to the harbour office.\n",
            "  - entity: harrow-dunmore\n    kind: status\n    from: missing\n    to: alive\n"
            "    decision: proposed\n    summary: Seen again.\n")
        self.assertNotEqual(second, PASTED)

        response = self.paste(second)

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "Correct the change.")
        self.assertEqual(self.files(), before)

    def test_from_is_what_canon_says_at_the_interludes_place_in_the_order(self):
        # A later Interlude finds Harrow dead. At the earlier one he was still
        # alive, whatever his file says now.
        self.add(name="The Long Dark", after="e04-second-lantern")
        self.mira.post(self.record_page("the-long-dark"),
                       {"entity": "harrow-dunmore", "kind": "status", "before": "",
                        "after": "dead", "summary": "Died."})
        self.assertEqual(self.stored("harrow-dunmore").fields["status"], "dead")

        response = self.record(after="alive", summary="Still about the docks.")

        self.assertNotContains(response, "Nothing was saved.")
        self.assertEqual(self.change("harrow-dunmore", RECORD).before, "alive")
        self.assertEqual(self.stored("harrow-dunmore").fields["status"], "dead")
        self.assert_valid()

    def test_a_file_for_another_interlude_is_refused(self):
        before = self.files()

        response = self.paste(PASTED.replace(f"event: {QUIET}", "event: e03-storm-moon"))

        self.assertContains(response, "Nothing was saved.")
        self.assertEqual(self.files(), before)

    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        before = self.files()

        self.assertNotContains(sam.get(f"{self.events_page}{QUIET}/"), "/record/")
        self.assertEqual(self.record(by=sam).status_code, 404)
        self.assertEqual(self.record(by=sign_in("eve@example.com")).status_code, 404)
        self.assertEqual(self.files(), before)
