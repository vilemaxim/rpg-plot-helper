"""What each person may read in a World, by role (ADR-0010). Through web
requests, with plotcanon's sample World, in which every Mod and Plot is
GM-only, and some NPCs, Locations and Factions are public or player-known.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them."""

import html

from accounts.models import User
from canon import access
from canon.models import CanonChange, Document
from canon.test_assignments import AssignmentTest
from canon.test_mod_submissions import a_mod
from canon.test_reports import LEDGER_2, STAIR
from canon.test_runner_links import LinkTest
from organizations.models import Membership, World

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
        self.assertIn("locations/the-sunken-chapel/", page)

    def test_a_link_in_a_body_to_a_document_they_may_not_read_reads_another_document(self):
        with self.in_world():
            ferryman = Document.objects.get(slug=FERRYMAN)
            ferryman.body = ferryman.body.replace(
                "Wants out of a debt.",
                "Owes [[the-tidemother]], as canon/npcs/the-tidemother.md says.")
            ferryman.save(update_fields=["body"])

        page = self.page("npcs", FERRYMAN).content.decode()

        self.assertNotIn(TIDEMOTHER, page)
        self.assertIn(f"Owes [[{HIDDEN}]], as {HIDDEN} says.", page)
        self.assertIn(TIDEMOTHER, self.page("npcs", FERRYMAN, by=self.mira).content.decode())

    def test_a_change_to_a_readable_document_names_no_other_in_its_history(self):
        self.submit(LEDGER_2)
        with self.in_world():
            change = CanonChange.objects.filter(entity="harrow-dunmore").first()
            change.entity, change.summary = FERRYMAN, "Rowed Harrow Dunmore out at night."
            change.decision, change.note = "approved", "As Harrow Dunmore paid him to."
            change.save(update_fields=["entity", "summary", "decision", "note"])

        page = self.page("npcs", FERRYMAN, by=self.mira).content.decode()
        self.assertIn("Rowed Harrow Dunmore out at night.", page)
        page = self.page("npcs", FERRYMAN).content.decode()
        self.assertIn(f"Rowed {HIDDEN} out at night.", page)
        self.assertIn(f"As {HIDDEN} paid him to.", page)
        self.assertNotIn("Harrow", page)
        self.assertNotIn(f"reports/aa-{LEDGER}-2/", page)

    def test_a_document_as_read_cannot_be_saved(self):
        with self.in_world():
            sam = User.objects.get(email="sam@example.com")
            world = World.objects.get()
            ferryman = access.readable_documents(world, sam).get(slug=FERRYMAN)
            as_read = access.as_read(ferryman)

            self.assertNotIn(FERRYMAN_SECRET, as_read.text)
            with self.assertRaises(access.ReadOnly):
                as_read.save()
            with self.assertRaises(access.ReadOnly):
                as_read.delete()
        self.assertIn(FERRYMAN_SECRET, self.stored(FERRYMAN).text)

    def test_a_finding_left_out_says_only_the_plot_team_may_read_it(self):
        with self.in_world():
            sam = User.objects.get(email="sam@example.com")
            shown = access.readable_findings(
                World.objects.get(), sam,
                f"ERROR  canon/npcs/{TIDEMOTHER}.md: something is wrong")

        self.assertEqual(shown, "There are more errors, about documents only the plot team "
                                "may read. Ask a Plot Master to look at it.")


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


VIGIL_SECRET = "Whatever happens to the crypt sets up the Lanternlight bell mod."


class AModRunner(ReadingTest):
    def mod_pages(self, mod, by):
        """The status of a Mod's page, its Dry Run and its Twine download."""
        base = self.mod_page(mod)
        return [by.get(f"{base}{page}").status_code for page in ("", "dry-run/", "twee/")]

    def test_reads_a_mod_in_full_while_assigned_to_it(self):
        self.assertEqual(self.mod_pages(VIGIL_MOD, self.rhea), [404, 404, 404])

        self.assign(VIGIL_MOD, "rhea@example.com")

        self.assertEqual(self.mod_pages(VIGIL_MOD, self.rhea), [200, 200, 200])
        self.assertContains(self.rhea.get(self.mod_page(VIGIL_MOD)), VIGIL_SECRET)
        self.assertIn(VIGIL_SECRET,
                      self.rhea.get(f"{self.mod_page(VIGIL_MOD)}twee/").content.decode())
        self.assertEqual(self.mod_pages(VIGIL_MOD, self.tom), [404, 404, 404])

    def test_not_once_the_assignment_is_revoked(self):
        self.assign(VIGIL_MOD, "rhea@example.com")
        self.revoke(VIGIL_MOD, self.assignment_ids(VIGIL_MOD)[0])

        self.assertEqual(self.mod_pages(VIGIL_MOD, self.rhea), [404, 404, 404])

    def test_not_once_the_event_it_was_for_has_ended(self):
        self.assign(VIGIL_MOD, "rhea@example.com", event="e03-storm-moon")
        self.assertEqual(self.mod_pages(VIGIL_MOD, self.rhea), [200, 200, 200])

        self.set_dates("e03-storm-moon", real_date="2020-01-01")

        self.assertEqual(self.mod_pages(VIGIL_MOD, self.rhea), [404, 404, 404])

    def test_reads_a_public_mod_without_its_gm_notes_once_it_ended(self):
        self.assign(VIGIL_MOD, "rhea@example.com", event="e03-storm-moon")
        with self.in_world():
            mod =Document.objects.get(slug=VIGIL_MOD)
            mod.fields["visibility"] = "public"
            mod.save(update_fields=["fields"])
        self.set_dates("e03-storm-moon", real_date="2020-01-01")

        self.assertEqual(self.mod_pages(VIGIL_MOD, self.rhea), [200, 200, 200])
        self.assertNotContains(self.rhea.get(self.mod_page(VIGIL_MOD)), VIGIL_SECRET)
        self.assertNotIn(VIGIL_SECRET,
                         self.rhea.get(f"{self.mod_page(VIGIL_MOD)}twee/").content.decode())


class ThePendingPage(ReadingTest):
    def setUp(self):
        super().setUp()
        self.submit(LEDGER_2)
        with self.in_world():
            self.change_id = CanonChange.objects.filter(decision="proposed").first().pk

    def test_and_deciding_are_not_found_outside_the_plot_team(self):
        for someone in (self.sam, self.rhea):
            self.assertEqual(someone.get(self.pending).status_code, 404)
            self.assertEqual(someone.post(f"{self.pending}{self.change_id}/approve/")
                             .status_code, 404)
            self.assertEqual(someone.post(f"{self.pending}decide/",
                                          {"decision": "approve", "change": self.change_id})
                             .status_code, 404)
            self.assertNotContains(someone.get(self.first_world), self.pending)
        self.assertEqual(self.mira.get(self.pending).status_code, 200)

    def test_a_document_page_shows_no_one_else_the_changes_waiting_for_it(self):
        self.submit(STAIR)

        self.assertContains(self.page("locations", "the-salt-stair", by=self.mira),
                            "Waiting to be decided")
        self.assertNotContains(self.page("locations", "the-salt-stair"),
                               "Waiting to be decided")


class ThePlotTeam(ReadingTest):
    def setUp(self):
        super().setUp()
        self.ada = self.join("ada@example.com")
        with self.in_world():
            Membership.objects.filter(user__email="ada@example.com").update(is_admin=True)

    def test_plot_masters_and_organization_admins_read_everything_in_full(self):
        for someone in (self.mira, self.ada):
            self.assertContains(self.page("npcs", TIDEMOTHER, by=someone), "GM Notes")
            self.assertContains(self.page("npcs", FERRYMAN, by=someone), FERRYMAN_SECRET)
            self.assertContains(self.page("mods", VIGIL_MOD, by=someone), VIGIL_SECRET)
            self.assertIn(f"npcs/{TIDEMOTHER}/", self.listed("npcs", by=someone))
            self.assertEqual(someone.get(self.pending).status_code, 200)


class APrivateLink(LinkTest):
    """The stair report has been filed, so the warrant Mod has open Flags on
    Harrow Dunmore, a GM-only NPC."""

    def test_shows_its_own_mod_in_full_and_names_nothing_else(self):
        link = self.create_link(WARRANT)

        page = self.client.get(link)
        file = self.client.get(f"{link}file/").content.decode()

        self.assertContains(page, WARRANT_SECRET)
        self.assertIn(WARRANT_SECRET, file)
        flags = page.content.decode().split('<div class="warning">', 1)[1].split("</div>")[0]
        self.assertIn("2 Flags", flags)
        self.assertIn(HIDDEN, flags)
        self.assertNotIn("Harrow", flags)
        self.assertNotIn("harrow-dunmore", page.content.decode())
        self.assertEqual(self.client.get(f"{link}npcs/harrow-dunmore/").status_code, 404)

    def test_names_no_other_document_in_its_body_or_dry_run(self):
        with self.in_world():
            for slug in (WARRANT, BELL):
                mod = Document.objects.get(slug=slug)
                mod.body = mod.body.replace("## Premise\n\n", f"## Premise\n\n{LINKS_TIDEMOTHER}\n\n", 1)
                mod.save(update_fields=["body"])

        for page in (self.client.get(self.create_link(WARRANT)),
                     self.client.get(f"{self.create_link(BELL)}dry-run/")):
            self.assertContains(page, LINKS_HIDDEN)
            self.assertNotContains(page, TIDEMOTHER)


BELL = "the-bell-beneath"
LINKS_TIDEMOTHER = f"Ask [[{TIDEMOTHER}]], or read canon/npcs/{TIDEMOTHER}.md."
LINKS_HIDDEN = f"Ask [[{HIDDEN}]], or read {HIDDEN}."


class ADryRunInTheWorld(ReadingTest):
    def test_names_no_document_its_reader_may_not_read(self):
        with self.in_world():
            mod = Document.objects.get(slug=BELL)
            mod.body = mod.body.replace("## Premise\n\n", f"## Premise\n\n{LINKS_TIDEMOTHER}\n\n", 1)
            mod.save(update_fields=["body"])
        self.assign(BELL, "rhea@example.com")

        page = self.rhea.get(f"{self.mod_page(BELL)}dry-run/")

        self.assertContains(page, LINKS_HIDDEN)
        self.assertNotContains(page, TIDEMOTHER)
        self.assertContains(self.mira.get(f"{self.mod_page(BELL)}dry-run/"), LINKS_TIDEMOTHER)


class CheckErrorsOnThePastePath(ReadingTest):
    def test_name_documents_they_may_not_read_as_another_document(self):
        names_gm_only = a_mod(**{"npcs: [mirelle-vale, tobren-vale, ysolde-marr]":
                                 f"npcs: [mirelle-vale, tobren-vale, ysolde-marr, {WARRANT}]"})

        page = self.sam.post(f"{self.first_world}submit-mod/", {"text": names_gm_only},
                             follow=True).content.decode()
        shown = page.replace(html.escape(names_gm_only), "")

        self.assertIn("points at a `mod`", html.unescape(shown))
        self.assertIn(HIDDEN, shown)
        self.assertNotIn(WARRANT, shown)
