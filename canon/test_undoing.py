"""Undoing a decision on a Canon Change, through web requests, with plotcanon's
sample World and script."""

import plotcanon

from canon.models import CanonChange, Document, Flag
from canon.test_decisions import DecisionTest
from canon.test_interludes import QUIET, RECORD, InterludeTest
from canon.test_reports import LEDGER_2
from canon.test_resolving import WARRANT, ResolvingTest
from organizations.models import Membership

LEDGER_2_ID = "aa-the-tax-collectors-ledger-2"


class UndoTest(DecisionTest):
    def setUp(self):
        super().setUp()
        self.submit(LEDGER_2)
        self.pell = self.change("clerk-pell", LEDGER_2_ID)

    def undo(self, change, by=None):
        return self.rule(change, "undo", by=by)

    def assert_valid(self):
        """plotcanon accepts the World, with no warnings at all."""
        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        self.assertEqual(plotcanon.load_world(files).text(), "")

    def reloaded(self, change):
        with self.in_world():
            return CanonChange.objects.get(pk=change.pk)


class UndoingAnApproval(UndoTest):
    def test_the_change_is_proposed_again_in_its_row_and_the_reports_file(self):
        self.rule(self.pell, "approve")

        self.undo(self.pell)

        change = self.reloaded(self.pell)
        self.assertEqual(change.decision, "proposed")
        self.assertIsNone(change.decided_by)
        decisions = [c["decision"] for c in self.stored(LEDGER_2_ID).fields["canon_changes"]]
        self.assertEqual(decisions, ["proposed", "proposed"])

    def test_the_entity_goes_back_to_what_the_remaining_approved_changes_say(self):
        before = self.stored("clerk-pell").text
        self.rule(self.pell, "approve")

        self.undo(self.pell)

        # The earlier report's approved change left him missing as of e01.
        self.assertEqual(self.stored("clerk-pell").text, before)
        self.assertEqual(self.status_shown("clerk-pell"), "Missing")
        self.assert_valid()

    def test_an_approval_a_later_one_follows_on_from_waits_for_that_one(self):
        self.rule(self.pell, "approve")
        earlier = self.change("clerk-pell", "aa-the-tax-collectors-ledger")
        before = self.stored("clerk-pell").text

        response = self.undo(earlier)

        self.assertContains(response, "Undo that one first")
        self.assertContains(response, "Found alive, hiding in the boat shed")
        self.assertEqual(self.reloaded(earlier).decision, "approved")
        self.assertEqual(self.stored("clerk-pell").text, before)

        self.undo(self.pell)
        self.undo(earlier)

        self.assertEqual(self.reloaded(earlier).decision, "proposed")
        self.assert_valid()


class UndoingARejection(UndoTest, ResolvingTest):
    def setUp(self):
        super().setUp()
        self.death = self.change("harrow-dunmore", "aa-blood-on-the-salt-stair")

    def test_the_change_is_proposed_again_and_canon_is_as_it_was(self):
        before = self.stored("harrow-dunmore").text
        self.rule(self.death, "reject")

        self.undo(self.death)

        self.assertEqual(self.reloaded(self.death).decision, "proposed")
        self.assertIn("decision: proposed", self.stored("aa-blood-on-the-salt-stair").text)
        self.assertEqual(self.stored("harrow-dunmore").text, before)
        self.assertContains(self.mira.get(self.pending), "Went over the edge at the third landing")
        self.assert_valid()

    def test_the_flags_rejecting_it_cleared_come_back(self):
        flag = next(f for f in self.flags_on(WARRANT) if f.change_id == self.death.pk)
        self.rule(self.death, "reject")

        self.undo(self.death)

        self.assertIn(flag.pk, [f.pk for f in self.flags_on(WARRANT)])
        self.assertTrue(self.warns(WARRANT))

    def test_a_flag_dismissed_before_stays_dismissed(self):
        flag = next(f for f in self.flags_on(WARRANT) if f.change_id == self.death.pk)
        self.dismiss(flag)
        self.rule(self.death, "reject")

        self.undo(self.death)

        with self.in_world():
            self.assertEqual(Flag.objects.get(pk=flag.pk).resolution, "dismissed")


class UndoingAnApprovalThatKeptNothing(UndoTest):
    """An approval made before what it replaced was kept, or imported already
    approved, has nothing in `replaced`. Undoing one of a status change."""

    def forget_replaced(self, change):
        with self.in_world():
            CanonChange.objects.filter(pk=change.pk).update(replaced={})

    def test_as_of_goes_back_to_the_latest_remaining_approved_change(self):
        before = self.stored("clerk-pell").text
        self.rule(self.pell, "approve")
        self.forget_replaced(self.pell)

        self.undo(self.pell)

        # The earlier report's approved change left him missing as of e01.
        self.assertEqual(self.stored("clerk-pell").text, before)
        self.assertEqual(self.status_shown("clerk-pell"), "Missing")
        self.assert_valid()

    def test_with_no_approved_change_remaining_the_field_goes_back_and_as_of_stays(self):
        earlier = self.change("clerk-pell", "aa-the-tax-collectors-ledger")
        self.assertEqual(self.reloaded(earlier).replaced, {})    # imported approved
        as_of = self.stored("clerk-pell").fields["as_of"]

        self.undo(earlier)

        self.assertEqual(self.reloaded(earlier).decision, "proposed")
        pell = self.stored("clerk-pell").fields
        self.assertEqual(pell["status"], earlier.before)
        self.assertEqual(pell["as_of"], as_of)
        self.assert_valid()


class UndoingAMoveThatKeptNothing(InterludeTest):
    """A change of location, recorded during an Interlude, whose approval kept
    nothing in `replaced`."""

    def test_the_location_goes_back_and_as_of_stays_with_no_approved_change_left(self):
        self.add()
        before = self.stored("the-ferryman").fields
        self.record(entity="the-ferryman", kind="location", before="brackwater-harbour",
                    after="saint-oreths-light", summary="Rowed out to the light.")
        change = self.change("the-ferryman", RECORD)
        with self.in_world():
            CanonChange.objects.filter(pk=change.pk).update(replaced={})

        self.rule(change, "undo")

        after = self.stored("the-ferryman").fields
        self.assertEqual(after["location"], "brackwater-harbour")
        # Nothing says where "as of" stood before, so it stays where it is.
        self.assertEqual(after["as_of"], QUIET)
        self.assertNotEqual(before.get("as_of"), QUIET)
        self.assert_valid()


class TheUndoIsRecorded(UndoTest):
    def test_with_who_did_it_when_and_what_the_decision_had_been(self):
        self.rule(self.pell, "approve")
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "plot-master")

        self.undo(self.pell, by=sam)

        page = self.mira.get(f"{self.first_world}reports/{LEDGER_2_ID}/").content.decode()
        changes = page.split("<h2>Canon Changes</h2>", 1)[1].split("</table>", 1)[0]
        self.assertIn("Earlier approved by mira@example.com, undone by sam@example.com", changes)


class WhoMayUndo(UndoTest):
    def setUp(self):
        super().setUp()
        self.rule(self.pell, "approve")
        self.report_page = f"{self.first_world}reports/{LEDGER_2_ID}/"

    def test_a_plot_master_is_offered_it_on_the_reports_page(self):
        self.assertContains(self.mira.get(self.report_page),
                            f"changes/{self.pell.pk}/undo/")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        before = self.stored("clerk-pell").text
        # An Organization Admin reads the report, but is not a Plot Master.
        with self.in_world():
            Membership.objects.filter(user__email="sam@example.com").update(is_admin=True)

        self.assertNotContains(sam.get(self.report_page), "/undo/")
        self.assertEqual(self.undo(self.pell, by=sam).status_code, 404)

        self.assertEqual(self.reloaded(self.pell).decision, "approved")
        self.assertEqual(self.stored("clerk-pell").text, before)

    def test_a_change_still_proposed_has_nothing_to_undo(self):
        harrow = self.change("harrow-dunmore", LEDGER_2_ID)

        response = self.undo(harrow)

        self.assertContains(response, "nothing to undo")


class UndoingAChangeOfFactions(InterludeTest):
    """Recorded during an Interlude, which approves it at once."""

    def test_puts_back_the_faction_it_took_out_and_takes_out_the_one_it_put_in(self):
        self.add()
        before = self.stored("mirelle-vale").text
        self.record(entity="mirelle-vale", kind="affiliation", before="salt-guild",
                    after="harbour-wardens", summary="Went over to the Wardens.")
        self.assertEqual(self.stored("mirelle-vale").fields["factions"], ["harbour-wardens"])
        change = self.change("mirelle-vale", RECORD)

        self.rule(change, "undo")

        # No other approved change to her remains, so "as of" goes back to
        # what her file said before this one was approved.
        self.assertEqual(self.stored("mirelle-vale").text, before)
        self.assert_valid()

    def test_a_faction_already_held_is_kept(self):
        # She is in the Salt Guild already, so joining it changed nothing.
        self.add()
        before = self.stored("mirelle-vale").text
        self.record(entity="mirelle-vale", kind="affiliation", before="",
                    after="salt-guild", summary="Swore to the Guild again.")
        change = self.change("mirelle-vale", RECORD)

        self.rule(change, "undo")

        self.assertEqual(self.stored("mirelle-vale").text, before)
        self.assert_valid()
