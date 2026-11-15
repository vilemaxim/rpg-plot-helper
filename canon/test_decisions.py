"""Approving and rejecting Canon Changes, through web requests, with plotcanon's
sample World and script."""

import re

import plotcanon

from canon.models import CanonChange, Document
from canon.test_reports import LEDGER_2, STAIR, VIGIL, ReportTest
from organizations.tests import sign_in


class DecisionTest(ReportTest):
    def change(self, entity, report, kind=None):
        with self.in_world():
            changes = CanonChange.objects.filter(entity=entity, report__slug=report)
            if kind:
                changes = changes.filter(kind=kind)
            return changes.get()

    def rule(self, change, decision, by=None, back=None):
        address = f"{self.first_world}changes/{change.pk}/{decision}/"
        return (by or self.mira).post(address, {"next": back or self.pending}, follow=True)

    def npc(self, slug, by=None):
        return (by or self.mira).get(f"{self.first_world}npcs/{slug}/")

    def status_shown(self, slug):
        page = self.npc(slug).content.decode()
        return page.split('<span class="state">', 1)[1].split("<", 1)[0]


class Approving(DecisionTest):
    def setUp(self):
        super().setUp()
        self.submit(LEDGER_2)
        self.pell = self.change("clerk-pell", "aa-the-tax-collectors-ledger-2")

    def test_approving_a_status_change_updates_the_entitys_current_state(self):
        self.assertEqual(self.status_shown("clerk-pell"), "Missing")

        self.rule(self.pell, "approve")

        self.assertEqual(self.status_shown("clerk-pell"), "Alive")
        stored = self.stored("clerk-pell")
        self.assertEqual(stored.fields["status"], "alive")
        self.assertEqual(stored.fields["as_of"], "e03-storm-moon")

    def test_the_entitys_file_changes_in_those_two_values_only(self):
        before = self.stored("clerk-pell").text

        self.rule(self.pell, "approve")

        self.assertEqual(self.stored("clerk-pell").text,
                         before.replace("status: missing", "status: alive")
                         .replace("as_of: e01-low-tide", "as_of: e03-storm-moon"))

    def test_the_reports_file_records_the_decision(self):
        self.rule(self.pell, "approve")

        report = self.stored("aa-the-tax-collectors-ledger-2")
        decisions = [c["decision"] for c in report.fields["canon_changes"]]
        self.assertEqual(decisions, ["approved", "proposed"])
        self.assertEqual(report.text.count("decision: approved"), 1)

    def test_an_approved_change_is_no_longer_waiting(self):
        self.rule(self.pell, "approve")

        page = self.mira.get(self.pending)
        self.assertContains(page, "1 Canon Change waiting")

    def test_the_entitys_page_shows_its_history_and_the_report_each_came_from(self):
        self.rule(self.pell, "approve")

        page = self.npc("clerk-pell").content.decode()
        history = page.split("<h2>History</h2>", 1)[1]

        self.assertIn("Found alive, hiding in the boat shed at the light.", history)
        self.assertIn(f'href="{self.first_world}reports/aa-the-tax-collectors-ledger-2/"', history)
        self.assertIn("Gone from his counting room with the ledger.", history)
        self.assertIn(f'href="{self.first_world}reports/aa-the-tax-collectors-ledger/"', history)
        self.assertLess(history.index("Gone from his counting room"),
                        history.index("Found alive"))

    def test_the_change_records_who_decided_and_when(self):
        self.rule(self.pell, "approve")

        with self.in_world():
            change = CanonChange.objects.get(pk=self.pell.pk)
        self.assertEqual(change.decision, "approved")
        self.assertEqual(change.decided_by.email, "mira@example.com")
        self.assertIsNotNone(change.decided_at)

    def test_approving_a_change_that_names_no_field_changes_no_file(self):
        dunmore = self.change("harrow-dunmore", "aa-the-tax-collectors-ledger-2")
        before = self.stored("harrow-dunmore").text

        self.rule(dunmore, "approve")

        self.assertEqual(self.stored("harrow-dunmore").text, before)
        self.assertIn("Admitted he hid the clerk",
                      self.npc("harrow-dunmore").content.decode().split("<h2>History</h2>", 1)[1])

    def test_a_change_is_decided_once(self):
        self.rule(self.pell, "approve")

        response = self.rule(self.pell, "reject")

        self.assertContains(response, "already been approved")
        self.assertEqual(self.status_shown("clerk-pell"), "Alive")

    def test_the_world_stays_one_plotcanon_accepts(self):
        self.rule(self.pell, "approve")
        self.rule(self.change("harrow-dunmore", "aa-the-tax-collectors-ledger-2"), "reject")

        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        self.assertEqual(plotcanon.load_world(files).text(), "")


class MovesAndAffiliations(DecisionTest):
    def test_a_location_change_and_an_affiliation_change(self):
        text = LEDGER_2.text.replace("canon_changes:\n", """canon_changes:
  - entity: clerk-pell
    kind: location
    decision: proposed
    from: null
    to: saint-oreths-light
    summary: "Hidden at the light."
  - entity: clerk-pell
    kind: affiliation
    decision: proposed
    from: salt-guild
    to: harbour-wardens
    summary: "Went over to the Wardens with the ledger."
""", 1)
        self.submit(LEDGER_2, text=text)

        self.rule(self.change("clerk-pell", "aa-the-tax-collectors-ledger-2", "location"),
                    "approve")
        self.rule(self.change("clerk-pell", "aa-the-tax-collectors-ledger-2", "affiliation"),
                    "approve")

        stored = self.stored("clerk-pell")
        self.assertEqual(stored.fields["location"], "saint-oreths-light")
        self.assertEqual(stored.fields["factions"], ["harbour-wardens"])
        self.assertEqual(stored.fields["as_of"], "e03-storm-moon")
        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        self.assertEqual(plotcanon.load_world(files).errors, ())


def report_text(report_id, mod, event, changes):
    """A report of our own on a sample Mod, with the given Canon Changes."""
    listed = "".join(
        f"  - entity: {entity}\n    kind: {kind}\n    decision: proposed\n"
        + (f"    from: {before}\n    to: {after}\n" if kind in ("status", "location",
                                                                  "affiliation") else "")
        + f"    summary: \"{summary}\"\n"
        for entity, kind, before, after, summary in changes)
    return (f"---\nid: {report_id}\ntype: after-action\nmod: {mod}\nevent: {event}\n"
            f"ran: true\nfinished: false\nmod_runner: dev\npcs: [pc-wren-halloway]\n"
            f"canon_changes:\n{listed}---\n\n## What Happened\n\n## Divergences From The Mod\n\n"
            f"## Loose Ends\n")


class TheChainOfChanges(DecisionTest):
    """Approved changes to one field follow on from each other, in the order
    of the Events they happened at, however they are approved."""

    def file(self, report_id, event, changes):
        """File a report on the ledger, which runs at Low Tide and Storm Moon,
        or on the warrant, which runs at Second Lantern."""
        mod = "the-tax-collectors-ledger" if event != "e04-second-lantern" else "a-warrant-for-dunmore"
        response = self.submit(LEDGER_2, mod=mod, text=report_text(report_id, mod, event, changes))
        self.assertNotContains(response, "Nothing was saved")

    def assert_world_agrees(self):
        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        report = plotcanon.load_world(files)
        self.assertEqual(report.errors, ())
        self.assertEqual([w for w in report.warnings if "not applied" in w.message
                          or "advance `as_of`" in w.message], [])

    def test_a_change_that_does_not_follow_the_one_before_it_is_refused(self):
        """Pell went missing at Low Tide (already approved). Approve his death at
        Second Lantern, then try a Storm Moon change that says he was dead before."""
        self.file("aa-warrant-pell", "e04-second-lantern",
                  [("clerk-pell", "status", "missing", "dead", "Found dead.")])
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "status", "dead", "missing", "Rose and walked off.")])
        self.rule(self.change("clerk-pell", "aa-warrant-pell"), "approve")

        response = self.rule(self.change("clerk-pell", "aa-ledger-pell"), "approve")

        self.assertContains(response, "contradicts")
        self.assertEqual(self.change("clerk-pell", "aa-ledger-pell").decision, "proposed")
        self.assert_world_agrees()

    def test_an_earlier_change_that_fits_between_is_approved(self):
        self.file("aa-warrant-pell", "e04-second-lantern",
                  [("clerk-pell", "status", "alive", "dead", "Found dead.")])
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "status", "missing", "alive", "Found alive.")])
        self.rule(self.change("clerk-pell", "aa-warrant-pell"), "reject")
        self.rule(self.change("clerk-pell", "aa-ledger-pell"), "approve")

        self.assertEqual(self.status_shown("clerk-pell"), "Alive")
        self.assert_world_agrees()

    def test_two_changes_to_one_field_in_one_report(self):
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "status", "missing", "alive", "Found alive."),
                   ("clerk-pell", "status", "alive", "dead", "Then killed.")])
        first, second = (self.change_at("aa-ledger-pell", 0), self.change_at("aa-ledger-pell", 1))

        self.rule(first, "approve")
        self.rule(second, "approve")

        self.assertEqual(self.change_at("aa-ledger-pell", 1).decision, "approved")
        self.assertEqual(self.status_shown("clerk-pell"), "Dead")
        self.assert_world_agrees()

    def test_a_later_faction_change_already_approved(self):
        self.file("aa-warrant-pell", "e04-second-lantern",
                  [("clerk-pell", "affiliation", "salt-guild", "harbour-wardens", "Joined the Wardens.")])
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "affiliation", "harbour-wardens", "drowned-chapel", "Took orders.")])
        self.rule(self.change("clerk-pell", "aa-warrant-pell"), "approve")

        response = self.rule(self.change("clerk-pell", "aa-ledger-pell"), "approve")

        self.assertContains(response, "in the order they happened")
        self.assert_world_agrees()

    def test_factions_written_as_a_list_down_the_page(self):
        with self.in_world():
            pell = Document.objects.get(slug="clerk-pell")
            pell.text = pell.text.replace("factions: [salt-guild]", "factions:\n  - salt-guild")
            pell.save(update_fields=["text"])
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "affiliation", "salt-guild", "harbour-wardens", "Joined the Wardens.")])

        response = self.rule(self.change("clerk-pell", "aa-ledger-pell"), "approve")

        self.assertNotContains(response, "could not")
        self.assertEqual(self.stored("clerk-pell").fields["factions"], ["harbour-wardens"])
        self.assert_world_agrees()

    def change_at(self, report, position):
        with self.in_world():
            return CanonChange.objects.get(report__slug=report, position=position)


class Rejecting(DecisionTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.death = self.change("harrow-dunmore", "aa-blood-on-the-salt-stair")

    def test_a_rejected_change_leaves_canon_untouched(self):
        before = self.stored("harrow-dunmore").text

        self.rule(self.death, "reject")

        self.assertEqual(self.status_shown("harrow-dunmore"), "Alive")
        self.assertEqual(self.stored("harrow-dunmore").text, before)

    def test_it_is_kept_on_record_as_rejected(self):
        self.rule(self.death, "reject")

        report = self.mira.get(f"{self.first_world}reports/aa-blood-on-the-salt-stair/")
        self.assertContains(report, "<td>Rejected by mira@example.com</td>", html=True)
        self.assertEqual(self.stored("aa-blood-on-the-salt-stair").fields["canon_changes"][0]
                         ["decision"], "rejected")
        self.assertNotContains(self.mira.get(self.pending), "Went over the edge")

    def test_it_is_not_in_the_entitys_history(self):
        self.rule(self.death, "reject")

        history = (self.npc("harrow-dunmore").content.decode()
                   .split("<h2>History</h2>", 1)[-1].split("</ol>", 1)[0])
        self.assertNotIn("Went over the edge", history)


class TheReviewScreen(DecisionTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.submit(VIGIL)

    def group(self, entity):
        """The part of the review screen about one entity."""
        page = self.mira.get(self.pending).content.decode()
        groups = re.split(r'<section class="entity"', page)[1:]
        return next(g for g in groups if f"npcs/{entity}/" in g.split("</h2>", 1)[0])

    def test_changes_are_grouped_by_what_they_change(self):
        harrow = self.group("harrow-dunmore")

        self.assertIn("Went over the edge at the third landing", harrow)
        self.assertIn("Seen rowing out past the light", harrow)

    def test_the_two_contradicting_reports_appear_side_by_side(self):
        harrow = self.group("harrow-dunmore")

        self.assertIn("alive → dead", harrow)
        self.assertIn("alive → departed", harrow)
        self.assertIn("reports/aa-blood-on-the-salt-stair/", harrow)
        self.assertIn("reports/aa-storm-moon-vigil/", harrow)

    def test_changes_that_disagree_are_marked_before_anyone_tries_to_approve(self):
        harrow = self.group("harrow-dunmore")

        self.assertEqual(harrow.count('class="conflict"'), 2)
        self.assertIn("Disagrees with", harrow)

    def test_a_change_that_agrees_with_the_rest_is_not_marked(self):
        self.submit(LEDGER_2)

        self.assertNotIn('class="conflict"', self.group("clerk-pell"))

    def test_recently_rejected_changes_are_shown_alongside_too(self):
        self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "reject")

        harrow = self.group("harrow-dunmore")

        self.assertIn("Recently decided", harrow)
        self.assertIn("Rejected", harrow)
        self.assertIn("Seen rowing out past the light", harrow)

    def test_recent_approved_changes_are_shown_alongside(self):
        self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "approve")

        harrow = self.group("harrow-dunmore")

        self.assertIn("Recently decided", harrow)
        self.assertIn("Seen rowing out past the light", harrow)
        self.assertIn("Went over the edge at the third landing", harrow)

    def test_approving_one_side_of_a_contradiction_turns_the_other_down(self):
        self.rule(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair"), "approve")

        response = self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "approve")

        self.assertContains(response, "contradicts")
        self.assertContains(response, "Reject this change, or correct its report")
        self.assertNotContains(response, "reject that one")
        self.assertEqual(self.status_shown("harrow-dunmore"), "Dead")

    def test_whichever_side_is_approved_first(self):
        self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "approve")

        response = self.rule(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair"),
                               "approve")

        self.assertContains(response, "contradicts")
        self.assertEqual(self.status_shown("harrow-dunmore"), "Departed")

    def test_the_other_side_can_then_be_rejected(self):
        self.rule(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair"), "approve")

        self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "reject")

        self.assertEqual(self.change("harrow-dunmore", "aa-storm-moon-vigil").decision, "rejected")
        self.assertEqual(self.status_shown("harrow-dunmore"), "Dead")


class DecidingWhereTheReportIs(DecisionTest):
    def test_a_plot_master_can_decide_on_the_reports_page(self):
        response = self.submit(VIGIL)
        report_page = response.redirect_chain[-1][0]

        self.assertContains(response, "/approve/")
        change = self.change("harrow-dunmore", "aa-storm-moon-vigil")
        back = self.rule(change, "approve", back=report_page)

        self.assertEqual(back.redirect_chain[-1][0], report_page)
        self.assertContains(back, "<td>Approved by mira@example.com</td>", html=True)

    def test_filing_says_so(self):
        response = self.submit(VIGIL)

        self.assertContains(response, "Report filed")

    def test_the_report_page_says_who_decided_each_change(self):
        response = self.submit(VIGIL)
        report_page = response.redirect_chain[-1][0]

        back = self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "approve",
                         back=report_page)

        self.assertContains(back, "by mira@example.com")

    def test_the_entitys_history_says_who_approved(self):
        self.submit(VIGIL)

        self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "approve")

        self.assertContains(self.npc("harrow-dunmore"), "approved by mira@example.com")

    def test_a_return_address_on_another_site_is_ignored(self):
        self.submit(VIGIL)

        response = self.rule(self.change("harrow-dunmore", "aa-storm-moon-vigil"), "approve",
                               back="https://elsewhere.example/")

        self.assertEqual(response.redirect_chain[-1][0], self.pending)


class WhoMayDecide(DecisionTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.death = self.change("harrow-dunmore", "aa-blood-on-the-salt-stair")
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-runner")
        self.give("sam@example.com", "mod-writer")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        for decision in ("approve", "reject"):
            self.assertEqual(self.rule(self.death, decision, by=self.sam).status_code, 404)
        self.assertEqual(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair").decision,
                         "proposed")

    def test_they_are_not_offered_the_buttons(self):
        self.assertNotContains(self.sam.get(self.pending), "/approve/")
        self.assertNotContains(
            self.sam.get(f"{self.first_world}reports/aa-blood-on-the-salt-stair/"), "approve/")

    def test_an_organization_admin_who_is_not_its_plot_master_cannot(self):
        second = self.make_world("Second World")
        self.give("sam@example.com", "plot-master", world=second)

        self.assertEqual(self.rule(self.death, "approve", by=self.sam).status_code, 404)

    def test_a_plot_master_of_another_organization_cannot(self):
        eve = sign_in("eve@example.com")

        self.assertEqual(self.rule(self.death, "approve", by=eve).status_code, 404)

    def test_a_member_with_no_role_in_the_world_cannot(self):
        pat = self.join("pat@example.com")

        self.assertEqual(self.rule(self.death, "approve", by=pat).status_code, 404)

    def test_deciding_cannot_be_done_with_a_link(self):
        address = f"{self.first_world}changes/{self.death.pk}/approve/"

        self.assertEqual(self.mira.get(address).status_code, 405)
