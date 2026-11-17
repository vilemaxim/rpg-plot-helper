"""What each person may read in a World, by role (ADR-0010). Through web
requests, with plotcanon's sample World, in which every Mod and Plot is
GM-only, and some NPCs, Locations and Factions are public or player-known.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them."""

from canon.test_assignments import AssignmentTest

SISTER_ANE = "sister-ane"              # player-known, in the GM-only drowned bell Plot
SISTER_ANE_SECRET = "She knows what the tidemother is."
FERRYMAN = "the-ferryman"              # public
FERRYMAN_SECRET = "A good NPC to bring back."
TIDEMOTHER = "the-tidemother"          # GM-only
DROWNED_BELL = "the-drowned-bell"      # a GM-only Plot
HIDDEN = "another document"


class ReadingTest(AssignmentTest):
    def page(self, kind, slug, by=None):
        return (by or self.sam).get(f"{self.first_world}{kind}/{slug}/")

    def listed(self, kind, by=None):
        return (by or self.sam).get(f"{self.first_world}{kind}/").content.decode()


class AModWriterWithNoModsOfTheirOwn(ReadingTest):
    def test_lists_only_public_and_player_known_documents(self):
        npcs = self.listed("npcs")

        self.assertIn(f"npcs/{SISTER_ANE}/", npcs)
        self.assertIn(f"npcs/{FERRYMAN}/", npcs)
        self.assertNotIn(f"npcs/{TIDEMOTHER}/", npcs)
        self.assertNotIn("mods/", self.listed("mods"))
        self.assertNotIn("plots/", self.listed("plots"))

    def test_a_gm_only_documents_page_is_not_found(self):
        self.assertEqual(self.page("npcs", TIDEMOTHER).status_code, 404)
        self.assertEqual(self.page("plots", DROWNED_BELL).status_code, 404)
        self.assertEqual(self.page("mods", VIGIL_MOD).status_code, 404)

    def test_a_readable_documents_page_shows_no_gm_notes(self):
        page = self.page("npcs", FERRYMAN)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Rows the harbour mouth")
        self.assertNotContains(page, FERRYMAN_SECRET)
        self.assertNotContains(page, "GM Notes")


VIGIL_MOD = "storm-moon-vigil"
