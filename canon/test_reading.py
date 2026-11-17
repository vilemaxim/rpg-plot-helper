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
    def link_handle(self, handle, email):
        """Make this person the Mod Writer of every Mod with this handle."""
        self.mira.post(f"{self.first_world}mod-writers/",
                       {"handle": handle, "user": self.user_id(email)})

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

    def test_mentions_of_documents_they_may_not_read_read_another_document(self):
        page = self.page("npcs", SISTER_ANE).content.decode()

        self.assertIn(HIDDEN, page)
        self.assertNotIn(DROWNED_BELL, page)
        self.assertNotIn("The Drowned Bell", page)
        self.assertIn(f"locations/the-sunken-chapel/", page)


VIGIL_MOD = "storm-moon-vigil"
WARRANT = "a-warrant-for-dunmore"            # approved, by `sam`
WARRANT_SECRET = "Pointless if the smuggler is already dead or gone when it runs."
FERRY = "the-ferrymans-price"                # finished, by `sam`, reported on
DAUGHTER = "the-guildmasters-daughter"       # a draft, by `kay`
DAUGHTER_SECRET = "Still a draft. Needs both the captain and the guildmaster alive."
MARKET = "the-low-tide-market"               # finished, by `mira`, reported on
LEDGER = "the-tax-collectors-ledger"         # in progress, by `dev`, reported on


class AModWritersOwnMods(ReadingTest):
    def setUp(self):
        super().setUp()
        self.link_handle("sam", "sam@example.com")
        self.link_handle("kay", "sam@example.com")

    def test_are_read_in_full_draft_or_approved(self):
        for mod, secret in ((DAUGHTER, DAUGHTER_SECRET), (WARRANT, WARRANT_SECRET)):
            page = self.page("mods", mod)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "GM Notes")
            self.assertContains(page, secret)
        self.assertIn(f"mods/{WARRANT}/", self.listed("mods"))
        self.assertNotIn(f"mods/{MARKET}/", self.listed("mods"))

    def test_the_reports_on_them_are_readable_and_no_one_elses(self):
        self.assertEqual(self.page("reports", f"aa-{FERRY}").status_code, 200)
        self.assertEqual(self.page("reports", f"aa-{MARKET}").status_code, 404)
        reports = self.listed("reports")
        self.assertIn(f"reports/aa-{FERRY}/", reports)
        self.assertNotIn(f"reports/aa-{MARKET}/", reports)

    def test_their_features_they_may_not_read_read_another_document(self):
        page = self.page("mods", WARRANT).content.decode()

        self.assertIn(HIDDEN, page)
        self.assertNotIn("npcs/harrow-dunmore/", page)
        self.assertNotIn("Harrow Dunmore", page.split('<div class="body">')[0])
        self.assertIn("factions/harbour-wardens/", page)

    def test_once_no_longer_theirs_they_are_not_read(self):
        self.link_handle("sam", "mira@example.com")

        self.assertEqual(self.page("mods", WARRANT).status_code, 404)


class AReadableReport(ReadingTest):
    def setUp(self):
        super().setUp()
        self.link_handle("dev", "sam@example.com")

    def test_leaves_out_canon_changes_about_documents_they_may_not_read(self):
        page = self.page("reports", f"aa-{LEDGER}")

        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "npcs/clerk-pell/")
        self.assertNotContains(page, "Clerk Pell")
        self.assertContains(page, "There are more Canon Changes in it, about documents only "
                                  "the plot team may read.")

    def test_the_plot_team_sees_every_change_and_no_such_line(self):
        page = self.page("reports", f"aa-{LEDGER}", by=self.mira)

        self.assertContains(page, "npcs/clerk-pell/")
        self.assertNotContains(page, "There are more Canon Changes")
