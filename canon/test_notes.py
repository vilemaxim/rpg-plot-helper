"""A Plot Master's note on why a Canon Change was rejected or approved, through
web requests, with plotcanon's sample World and script."""

import plotcanon

from canon.models import CanonChange, Document
from canon.test_decisions import DecisionTest
from canon.test_exporting import unzipped
from canon.test_reports import STAIR, VIGIL
from canon.tests import upload

STAIR_ID = "aa-blood-on-the-salt-stair"
WHY = "Harrow is needed alive for the Second Lantern; the fall was survivable."


class NoteTest(DecisionTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.death = self.change("harrow-dunmore", STAIR_ID)

    def rule_with_note(self, change, decision, note, by=None, back=None):
        address = f"{self.first_world}changes/{change.pk}/{decision}/"
        return (by or self.mira).post(address, {"next": back or self.pending, "note": note},
                                      follow=True)

    def reloaded(self, change):
        with self.in_world():
            return CanonChange.objects.get(pk=change.pk)

    def stored_change(self, report, position=0):
        return self.stored(report).fields["canon_changes"][position]

    def assert_valid(self):
        """plotcanon accepts the World."""
        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        self.assertEqual(plotcanon.load_world(files).errors, ())


class ANoteOnARejection(NoteTest):
    def test_is_kept_with_the_change_and_in_the_reports_file(self):
        self.rule_with_note(self.death, "reject", WHY)

        self.assertEqual(self.reloaded(self.death).decision, "rejected")
        self.assertEqual(self.reloaded(self.death).note, WHY)
        stored = self.stored_change(STAIR_ID)
        self.assertEqual((stored["decision"], stored["note"]), ("rejected", WHY))
        self.assert_valid()


class ANoteOnAnApproval(NoteTest):
    def test_is_kept_with_the_change_and_in_the_reports_file(self):
        self.rule_with_note(self.death, "approve", "The fall was always going to kill him.")

        self.assertEqual(self.reloaded(self.death).decision, "approved")
        stored = self.stored_change(STAIR_ID)
        self.assertEqual((stored["decision"], stored["note"]),
                         ("approved", "The fall was always going to kill him."))
        self.assertEqual(self.status_shown("harrow-dunmore"), "Dead")
        self.assert_valid()

    def test_no_note_writes_none_into_the_file(self):
        self.rule_with_note(self.death, "approve", "   ")

        self.assertEqual(self.reloaded(self.death).note, "")
        self.assertNotIn("note", self.stored_change(STAIR_ID))


class WhereANoteIsWritten(NoteTest):
    def test_beside_the_buttons_on_the_review_screen_and_the_reports_page(self):
        for page in (self.pending, self.report_page):
            response = self.mira.get(page)
            self.assertContains(response, 'name="note"')

    @property
    def report_page(self):
        return f"{self.first_world}reports/{STAIR_ID}/"


class WhereANoteIsShown(NoteTest):
    def test_on_the_reports_page_beside_the_decision(self):
        self.rule_with_note(self.death, "reject", WHY)

        page = self.mira.get(f"{self.first_world}reports/{STAIR_ID}/").content.decode()
        row = page.split("Went over the edge", 1)[0].rsplit("<tr>", 1)[1]
        self.assertIn("Rejected by mira@example.com", row)
        self.assertIn(WHY, row)

    def test_in_the_review_screens_recently_decided_list(self):
        self.submit(VIGIL)  # Keeps Harrow on the review screen.
        self.rule_with_note(self.death, "reject", WHY)

        page = self.mira.get(self.pending).content.decode()
        recent = page.split("<h3>Recently decided</h3>", 1)[1].split("</ul>", 1)[0]
        self.assertIn("Went over the edge", recent)
        self.assertIn(WHY, recent)

    def test_on_the_entitys_page_under_its_rejected_changes(self):
        self.rule_with_note(self.death, "reject", WHY)

        page = self.npc("harrow-dunmore").content.decode()
        rejected = page.split("<h2>Rejected changes</h2>", 1)[1].split("</ul>", 1)[0]
        self.assertIn("Went over the edge", rejected)
        self.assertIn(WHY, rejected)
        self.assertIn(f'href="{self.first_world}reports/{STAIR_ID}/"', rejected)

    def test_an_approvals_note_in_the_entitys_history(self):
        self.rule_with_note(self.death, "approve", "The fall was always going to kill him.")

        history = self.npc("harrow-dunmore").content.decode().split("<h2>History</h2>", 1)[1]
        self.assertIn("The fall was always going to kill him.", history)
        self.assertNotIn("<h2>Rejected changes</h2>", self.npc("harrow-dunmore").content.decode())


class ANoteIsPlainText(NoteTest):
    TYPED = '<script>alert("x")</script> **not bold** <b>nor this</b>'
    SHOWN = ("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; **not bold** "
             "&lt;b&gt;nor this&lt;/b&gt;")

    def assert_shown_as_typed(self, page):
        response = self.mira.get(page)
        self.assertNotContains(response, "<script>alert")
        self.assertNotContains(response, "<b>nor this</b>")
        self.assertContains(response, self.SHOWN)

    def test_markup_in_it_is_shown_as_typed(self):
        self.submit(VIGIL)  # Keeps Harrow on the review screen.
        self.rule_with_note(self.death, "reject", self.TYPED)

        self.assert_shown_as_typed(f"{self.first_world}reports/{STAIR_ID}/")
        self.assert_shown_as_typed(self.pending)
        self.assert_shown_as_typed(f"{self.first_world}npcs/harrow-dunmore/")
        self.assertEqual(self.stored_change(STAIR_ID)["note"], self.TYPED)
        self.assert_valid()

    def test_one_with_quotes_and_two_lines_is_kept_whole_in_the_file(self):
        typed = 'First: "no".\nSecond line, with a # and a: colon'
        self.rule_with_note(self.death, "reject", typed)

        self.assertEqual(self.stored_change(STAIR_ID)["note"], typed)
        self.assert_valid()


class OnlyAPlotMaster(NoteTest):
    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-runner")

    def test_can_add_a_note(self):
        for decision in ("approve", "reject"):
            response = self.rule_with_note(self.death, decision, "Mine now.", by=self.sam)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.reloaded(self.death).note, "")
        self.assertNotIn("note", self.stored_change(STAIR_ID))

    def test_others_are_not_offered_the_box(self):
        self.assertNotContains(self.sam.get(self.pending), 'name="note"')
        self.assertNotContains(self.sam.get(f"{self.first_world}reports/{STAIR_ID}/"),
                               'name="note"')

    def test_others_can_read_it(self):
        self.rule_with_note(self.death, "reject", WHY)

        self.assertContains(self.sam.get(f"{self.first_world}reports/{STAIR_ID}/"), WHY)
        self.assertContains(self.sam.get(f"{self.first_world}npcs/harrow-dunmore/"), WHY)


class InAnExportedWorld(NoteTest):
    def test_the_note_is_in_the_reports_file_and_the_world_still_validates(self):
        self.rule_with_note(self.death, "reject", WHY)

        files = unzipped(self.mira.get(f"{self.first_world}export/download/").content)

        world = {path.split("/", 1)[1]: text for path, text in files.items()}
        self.assertTrue(plotcanon.load_world(world).ok)
        report = next(text for path, text in world.items() if path.endswith(f"/{STAIR_ID}.md"))
        self.assertIn(WHY, report)

    def test_importing_it_keeps_the_note_with_the_change(self):
        self.rule_with_note(self.death, "reject", WHY)
        content = self.mira.get(f"{self.first_world}export/download/").content
        second = self.make_world("Second World")
        self.give("mira@example.com", "plot-master", world=second)

        self.mira.post(f"{second}import/", {"archive": upload(content)}, follow=True)

        with self.in_world():
            imported = CanonChange.objects.exclude(pk=self.death.pk).get(
                report__slug=STAIR_ID, entity="harrow-dunmore")
        self.assertEqual((imported.decision, imported.note), ("rejected", WHY))


class UndoingADecisionWithANote(NoteTest):
    def test_takes_the_note_off_the_change_and_out_of_the_file(self):
        self.rule_with_note(self.death, "reject", WHY)

        self.rule(self.death, "undo")

        self.assertEqual(self.reloaded(self.death).note, "")
        self.assertEqual(self.stored_change(STAIR_ID)["decision"], "proposed")
        self.assertNotIn("note", self.stored_change(STAIR_ID))
        self.assert_valid()

    def test_keeps_it_on_record_beside_the_decision_undone(self):
        self.rule_with_note(self.death, "reject", WHY)

        self.rule(self.death, "undo")

        page = self.mira.get(f"{self.first_world}reports/{STAIR_ID}/").content.decode()
        earlier = page.split("Earlier rejected", 1)[1].split("</small>", 1)[0]
        self.assertIn(WHY, earlier)

    def test_a_new_decision_takes_a_new_note(self):
        self.rule_with_note(self.death, "reject", WHY)
        self.rule(self.death, "undo")

        self.rule_with_note(self.death, "approve", "On reflection, he fell.")

        self.assertEqual(self.stored_change(STAIR_ID)["note"], "On reflection, he fell.")
        self.assert_valid()


class ALongNote(NoteTest):
    def test_is_refused_and_nothing_is_decided(self):
        response = self.rule_with_note(self.death, "reject", "Too long. " * 60)

        self.assertContains(response, "500 characters")
        self.assertEqual(self.reloaded(self.death).decision, "proposed")
