"""Approving or rejecting several Canon Changes in one step, through web
requests, with plotcanon's sample World and script."""

from canon.models import CanonChange
from canon.test_decisions import DecisionTest, report_text
from canon.test_reports import LEDGER_2, STAIR, VIGIL


class DecidingManyTest(DecisionTest):
    def changes_of(self, report):
        with self.in_world():
            return list(CanonChange.objects.filter(report__slug=report).order_by("position"))

    def decisions_of(self, report):
        return [c.decision for c in self.changes_of(report)]

    def rule_many(self, changes, decision, by=None, back=None, note=None):
        data = {"change": [c.pk for c in changes], "decision": decision,
                "next": back or self.pending}
        if note is not None:
            data["note"] = note
        return (by or self.mira).post(f"{self.first_world}changes/decide/", data, follow=True)


class ApprovingSeveral(DecidingManyTest):
    def setUp(self):
        super().setUp()
        self.submit(LEDGER_2)
        self.ledger = self.changes_of("aa-the-tax-collectors-ledger-2")

    def test_several_selected_changes_are_approved_in_one_step(self):
        response = self.rule_many(self.ledger, "approve")

        self.assertEqual(self.decisions_of("aa-the-tax-collectors-ledger-2"),
                         ["approved", "approved"])
        self.assertEqual(self.status_shown("clerk-pell"), "Alive")
        self.assertContains(response, "Approved 2 Canon Changes")
        self.assertContains(response, "No Canon Changes are waiting")

    def test_several_selected_changes_are_rejected_in_one_step(self):
        before = self.stored("clerk-pell").text

        response = self.rule_many(self.ledger, "reject")

        self.assertEqual(self.decisions_of("aa-the-tax-collectors-ledger-2"),
                         ["rejected", "rejected"])
        self.assertEqual(self.stored("clerk-pell").text, before)
        self.assertContains(response, "Rejected 2 Canon Changes")

    def test_one_note_is_given_to_each_change_decided(self):
        why = "Pell never left the city; both stories are wrong."

        self.rule_many(self.ledger, "reject", note=f"  {why} ")

        self.assertEqual([c.note for c in self.changes_of("aa-the-tax-collectors-ledger-2")],
                         [why, why])
        stored = self.stored("aa-the-tax-collectors-ledger-2").fields["canon_changes"]
        self.assertEqual([(c["decision"], c["note"]) for c in stored],
                         [("rejected", why), ("rejected", why)])

    def test_without_a_note_none_is_written(self):
        self.rule_many(self.ledger, "approve", note="")

        self.assertEqual([c.note for c in self.changes_of("aa-the-tax-collectors-ledger-2")],
                         ["", ""])
        stored = self.stored("aa-the-tax-collectors-ledger-2").fields["canon_changes"]
        self.assertFalse(any("note" in c for c in stored))

    def test_a_long_note_is_refused_and_nothing_is_decided(self):
        response = self.rule_many(self.ledger, "approve", note="Too long. " * 60)

        self.assertContains(response, "500 characters")
        self.assertEqual(self.decisions_of("aa-the-tax-collectors-ledger-2"),
                         ["proposed", "proposed"])

    def test_the_selection_form_offers_a_note_box(self):
        page = self.mira.get(self.pending).content.decode()
        form = page.split('id="decide-selected"', 1)[1].split("</form>", 1)[0]
        self.assertIn('name="note"', form)


class InTheOrderTheyHappened(DecidingManyTest):
    def file(self, report_id, event, changes):
        mod = ("the-tax-collectors-ledger" if event != "e04-second-lantern"
               else "a-warrant-for-dunmore")
        response = self.submit(LEDGER_2, mod=mod,
                               text=report_text(report_id, mod, event, changes))
        self.assertNotContains(response, "Nothing was saved")

    def test_a_chain_of_changes_to_one_field_is_approved_together(self):
        """Changes to factions must be decided in the order they happened. The
        later one is filed first, and both are approved in one step."""
        self.file("aa-warrant-pell", "e04-second-lantern",
                  [("clerk-pell", "affiliation", "harbour-wardens", "drowned-chapel",
                    "Took orders.")])
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "affiliation", "salt-guild", "harbour-wardens",
                    "Joined the Wardens.")])

        response = self.rule_many(self.changes_of("aa-warrant-pell")
                                  + self.changes_of("aa-ledger-pell"), "approve")

        self.assertContains(response, "Approved 2 Canon Changes")
        self.assertEqual(self.stored("clerk-pell").fields["factions"], ["drowned-chapel"])
        self.assertEqual(self.stored("clerk-pell").fields["as_of"], "e04-second-lantern")

    def test_a_chain_within_one_report_in_its_place_in_the_report(self):
        """Selected last change first; each is decided in its place."""
        self.file("aa-ledger-pell", "e03-storm-moon",
                  [("clerk-pell", "status", "missing", "alive", "Found alive."),
                   ("clerk-pell", "status", "alive", "dead", "Then killed.")])

        response = self.rule_many(list(reversed(self.changes_of("aa-ledger-pell"))), "approve")

        self.assertContains(response, "Approved 2 Canon Changes")
        self.assertEqual(self.decisions_of("aa-ledger-pell"), ["approved", "approved"])
        self.assertEqual(self.status_shown("clerk-pell"), "Dead")


class AllOrNothing(DecidingManyTest):
    def setUp(self):
        super().setUp()
        self.submit(LEDGER_2)
        self.submit(STAIR)
        self.submit(VIGIL)
        self.ledger = self.changes_of("aa-the-tax-collectors-ledger-2")
        self.death = self.change("harrow-dunmore", "aa-blood-on-the-salt-stair")
        self.departure = self.change("harrow-dunmore", "aa-storm-moon-vigil")

    def test_the_two_contradicting_reports_cannot_both_be_approved_in_one_step(self):
        before = self.stored("harrow-dunmore").text

        response = self.rule_many([self.death, self.departure], "approve")

        self.assertEqual(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair").decision,
                         "proposed")
        self.assertEqual(self.change("harrow-dunmore", "aa-storm-moon-vigil").decision,
                         "proposed")
        self.assertEqual(self.stored("harrow-dunmore").text, before)
        self.assertContains(response, "Nothing was decided")
        self.assertContains(response, "contradicts")

    def test_one_refused_change_means_none_is_decided(self):
        response = self.rule_many(self.ledger + [self.death, self.departure], "approve")

        self.assertEqual(self.decisions_of("aa-the-tax-collectors-ledger-2"),
                         ["proposed", "proposed"])
        self.assertEqual(self.status_shown("clerk-pell"), "Missing")
        self.assertEqual(self.status_shown("harrow-dunmore"), "Alive")
        self.assertContains(response, "8 Canon Changes waiting")

    def test_the_page_says_which_change_and_why(self):
        """The Stair is at Storm Moon before the Vigil, so the Vigil's change
        is the one turned down."""
        response = self.rule_many(self.ledger + [self.death, self.departure], "approve")

        message = response.content.decode().split("Nothing was decided", 1)[1].split("<", 1)[0]
        self.assertIn("Seen rowing out past the light", message)
        self.assertIn("contradicts", message)

    def test_the_others_are_left_selected_and_the_refused_one_is_not(self):
        response = self.rule_many(self.ledger + [self.death, self.departure], "approve")

        page = response.content.decode()
        for change in self.ledger + [self.death]:
            self.assertRegex(page, rf'value="{change.pk}"[^>]*checked')
        self.assertNotRegex(page, rf'value="{self.departure.pk}"[^>]*checked')
        self.assertRegex(page, rf'value="{self.departure.pk}"[^>]*> Select</label> '
                               rf'<strong class="conflict">Could not be decided')
        self.assertEqual(page.count("Could not be decided"), 1)

    def test_untick_the_refused_one_and_try_again(self):
        self.rule_many(self.ledger + [self.death, self.departure], "approve")

        response = self.rule_many(self.ledger + [self.death], "approve")

        self.assertContains(response, "Approved 3 Canon Changes")
        self.assertEqual(self.status_shown("harrow-dunmore"), "Dead")

    def test_a_change_already_decided_is_refused_and_nothing_is_decided(self):
        self.rule(self.death, "reject")

        response = self.rule_many(self.ledger + [self.death], "approve")

        self.assertContains(response, "already been rejected")
        self.assertEqual(self.decisions_of("aa-the-tax-collectors-ledger-2"),
                         ["proposed", "proposed"])

    def test_nothing_selected(self):
        response = self.rule_many([], "approve")

        self.assertContains(response, "Select the Canon Changes to decide")


class OnTheReportsPage(DecidingManyTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.report_page = f"{self.first_world}reports/aa-blood-on-the-salt-stair/"

    def approve_all(self, report="aa-blood-on-the-salt-stair", by=None):
        return (by or self.mira).post(
            f"{self.first_world}changes/decide/",
            {"report": report, "decision": "approve", "next": self.report_page}, follow=True)

    def test_the_review_screen_and_the_report_offer_to_decide_a_selection(self):
        for page in (self.pending, self.report_page):
            response = self.mira.get(page)
            self.assertContains(response, "Approve selected")
            self.assertContains(response, "Reject selected")
            self.assertContains(response, 'type="checkbox" name="change"', count=3)
        self.assertNotContains(self.mira.get(self.pending), "Approve all")

    def test_a_report_offers_to_approve_all_its_waiting_changes(self):
        self.assertContains(self.mira.get(self.report_page), "Approve all")

    def test_approve_all_approves_every_waiting_change_of_the_report(self):
        response = self.approve_all()

        self.assertEqual(self.decisions_of("aa-blood-on-the-salt-stair"),
                         ["approved", "approved", "approved"])
        self.assertEqual(response.redirect_chain[-1][0], self.report_page)
        self.assertContains(response, "Approved 3 Canon Changes")
        self.assertEqual(self.status_shown("harrow-dunmore"), "Dead")

    def test_approve_all_leaves_out_changes_already_decided(self):
        self.rule(self.changes_of("aa-blood-on-the-salt-stair")[1], "reject")

        response = self.approve_all()

        self.assertContains(response, "Approved 2 Canon Changes")
        self.assertEqual(self.decisions_of("aa-blood-on-the-salt-stair")[1], "rejected")

    def test_with_every_change_decided_it_is_no_longer_offered(self):
        self.approve_all()

        page = self.mira.get(self.report_page)
        self.assertNotContains(page, "Approve all")
        self.assertNotContains(page, "Approve selected")

    def test_the_contradicting_report_cannot_then_be_approved_all_at_once(self):
        self.submit(VIGIL)
        self.approve_all()

        response = self.approve_all("aa-storm-moon-vigil")

        self.assertContains(response, "Nothing was decided")
        self.assertContains(response, "contradicts")
        self.assertEqual(set(self.decisions_of("aa-storm-moon-vigil")), {"proposed"})


class WhoMayDecideMany(DecidingManyTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.stair = self.changes_of("aa-blood-on-the-salt-stair")
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-runner")
        self.give("sam@example.com", "mod-writer")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        for decision in ("approve", "reject"):
            self.assertEqual(self.rule_many(self.stair, decision, by=self.sam).status_code, 404)
        response = self.sam.post(f"{self.first_world}changes/decide/",
                                 {"report": "aa-blood-on-the-salt-stair",
                                  "decision": "approve"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(set(self.decisions_of("aa-blood-on-the-salt-stair")), {"proposed"})

    def test_they_are_not_offered_the_checkboxes(self):
        for page in (self.pending, f"{self.first_world}reports/aa-blood-on-the-salt-stair/"):
            response = self.sam.get(page)
            self.assertNotContains(response, 'name="change"')
            self.assertNotContains(response, "Approve all")

    def test_changes_of_another_world_are_not_decided_from_this_one(self):
        other = self.make_world("Second World")

        self.give("mira@example.com", "plot-master", world=other)

        response = self.mira.post(f"{other}changes/decide/",
                                  {"change": [c.pk for c in self.stair], "decision": "approve",
                                   "next": f"{other}changes/"}, follow=True)

        self.assertContains(response, "There is no such Canon Change")
        self.assertEqual(set(self.decisions_of("aa-blood-on-the-salt-stair")), {"proposed"})

    def test_deciding_cannot_be_done_with_a_link(self):
        self.assertEqual(self.mira.get(f"{self.first_world}changes/decide/").status_code, 405)
