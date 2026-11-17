"""What a draft Mod refers to that its Mod Writer may not read in full, as
its page tells the plot team, who can grant it from there (ADR-0010).
Through web requests, with plotcanon's sample World.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them."""

from canon.test_approving import DAUGHTER
from canon.test_granting import SALT_TAX, GrantingTest
from canon.test_mod_submissions import a_mod
from canon.test_reading import FERRYMAN, FERRYMAN_SECRET, SISTER_ANE, TIDEMOTHER
from canon.test_resolving import WARRANT
from organizations.models import Membership

LANTERN = "the-lamplighters-debt"  # the draft Sam submits
HARROW = "harrow-dunmore"          # a GM-only NPC the warrant Mod features


def a_draft(npcs):
    """A draft Mod's file featuring these NPCs, and nothing else."""
    return a_mod(**{
        "npcs: [mirelle-vale, tobren-vale, ysolde-marr]": f"npcs: [{', '.join(npcs)}]",
        "  plots: [feud-of-vale-and-marr]\n": "",
        "requires:\n  - {entity: ysolde-marr, field: status, equals: alive}\n"
        "  - {entity: tobren-vale, field: status, equals: alive}\n": "requires: []\n"})


class DraftTest(GrantingTest):
    def submit_draft(self, *npcs, body_adds=""):
        text = a_draft(npcs).replace("## Premise\n\n", f"## Premise\n\n{body_adds}\n\n", 1)
        response = self.sam.post(f"{self.first_world}submit-mod/", {"text": text}, follow=True)
        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(LANTERN))

    def notice(self, mod=LANTERN, by=None):
        """The notice on a draft's page of what its Mod Writer has not been
        granted, or None."""
        return self.section((by or self.mira).get(self.mod_page(mod)), "not-granted")

    def grant_from_notice(self, slug, by=None):
        """Press the notice's Grant button by this document."""
        item = [li for li in self.notice().split("<li>")[1:] if f"/{slug}/" in li][0]
        action = item.split('<form method="post" action="', 1)[1].split('"', 1)[0]
        fields = dict(
            (field.split('name="', 1)[1].split('"', 1)[0],
             field.split('value="', 1)[1].split('"', 1)[0])
            for field in item.split("<input")[1:] if 'name="csrfmiddlewaretoken"' not in field)
        return (by or self.mira).post(action, fields, follow=True)


class TheNotice(DraftTest):
    def test_a_draft_naming_a_gm_only_npc_its_mod_writer_cannot_read_shows_it(self):
        self.submit_draft(TIDEMOTHER)

        notice = self.notice()

        self.assertIn("sam@example.com refers to documents they haven't been granted:", notice)
        self.assertIn(f'href="{self.doc_page("npcs", TIDEMOTHER)}"', notice)
        self.assertIn("The Tidemother", notice)

    def test_granting_from_it_brings_the_plot_master_back_and_drops_it_from_the_list(self):
        self.submit_draft(TIDEMOTHER)

        response = self.grant_from_notice(TIDEMOTHER)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(LANTERN))
        self.assertContains(response, "sam@example.com is granted The Tidemother.")
        self.assertIsNone(self.notice())
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.sam).status_code, 200)

    def test_a_public_document_read_without_its_gm_notes_is_not_read_in_full(self):
        self.submit_draft(FERRYMAN)

        self.assertIn(f'href="{self.doc_page("npcs", FERRYMAN)}"', self.notice())
        self.grant_from_notice(FERRYMAN)
        self.assertIsNone(self.notice())
        self.assertContains(self.page("npcs", FERRYMAN, by=self.sam), FERRYMAN_SECRET)

    def test_only_what_is_not_read_in_full_is_listed(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        self.submit_draft(TIDEMOTHER, FERRYMAN)

        notice = self.notice()

        self.assertIn(f"/{FERRYMAN}/", notice)
        self.assertNotIn(f"/{TIDEMOTHER}/", notice)

    def test_what_its_body_links_by_id_or_path_counts_too(self):
        self.submit_draft(FERRYMAN, body_adds=f"Owes [[{TIDEMOTHER}]], as "
                                              f"canon/npcs/{SISTER_ANE}.md says.")

        notice = self.notice()

        self.assertIn(f"/{TIDEMOTHER}/", notice)
        self.assertIn(f"/{SISTER_ANE}/", notice)


class WhatItBlocks(DraftTest):
    def test_a_draft_with_the_notice_is_approved_as_before(self):
        self.submit_draft(TIDEMOTHER)
        page = self.mira.get(self.mod_page(LANTERN))
        self.assertIsNotNone(self.section(page, "not-granted"))
        self.assertContains(page, f'action="{self.mod_page(LANTERN)}approve/"')

        approved = self.mira.post(f"{self.mod_page(LANTERN)}approve/",
                                  {"campaign": "lanternlight"}, follow=True)

        self.assertContains(approved, "approved")
        self.assertIsNone(self.notice())

    def test_a_mod_sent_back_shows_it_as_a_draft_and_is_sent_back_as_before(self):
        self.link_handle("sam", "sam@example.com")
        self.assertIsNone(self.notice(WARRANT))

        sent_back = self.mira.post(f"{self.mod_page(WARRANT)}send-back/",
                                   {"reason": "Leave Dunmore out of it."}, follow=True)

        self.assertContains(sent_back, "is a draft again, back with its Mod Writer")
        notice = self.notice(WARRANT)
        self.assertIn(f"/{HARROW}/", notice)
        self.assertContains(self.page("mods", WARRANT), "Leave Dunmore out of it.")


class WhoSeesIt(DraftTest):
    def test_its_mod_writer_does_not_on_their_own_draft(self):
        self.submit_draft(TIDEMOTHER)

        self.assertIsNone(self.notice(by=self.sam))

    def test_nobody_but_the_plot_team_does(self):
        self.submit_draft(FERRYMAN)
        self.grant("mods", LANTERN, "rhea@example.com")

        self.assertEqual(self.page("mods", LANTERN, by=self.rhea).status_code, 200)
        self.assertIsNone(self.notice(by=self.rhea))

    def test_not_when_its_mod_writer_reads_everything_it_refers_to(self):
        self.submit_draft(TIDEMOTHER, FERRYMAN)
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        self.grant("npcs", FERRYMAN, "sam@example.com")

        self.assertIsNone(self.notice())

    def test_not_when_the_draft_has_no_linked_mod_writer(self):
        # The sample draft names its writer by a handle nobody is linked to.
        self.assertIsNone(self.section(self.mira.get(self.mod_page(DAUGHTER)), "not-granted"))

    def test_not_when_its_mod_writer_may_no_longer_be_granted_anything(self):
        self.submit_draft(TIDEMOTHER)
        self.take("sam@example.com", "mod-writer")

        self.assertIsNone(self.notice())

    def test_an_admin_who_is_not_a_plot_master_sees_it_and_grants_from_it(self):
        self.submit_draft(TIDEMOTHER)
        with self.in_world():
            Membership.objects.filter(user__email="mira@example.com").update(is_admin=True)
        self.take("mira@example.com", "plot-master")

        self.assertIn(f"/{TIDEMOTHER}/", self.notice())
        response = self.grant_from_notice(TIDEMOTHER)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(LANTERN))
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.sam).status_code, 200)


class GrantingAPlotFromIt(DraftTest):
    def test_brings_the_plot_master_back_to_the_draft_not_to_what_is_tied_to_the_plot(self):
        self.submit_draft(FERRYMAN, body_adds=f"Turns on [[{SALT_TAX}]].")

        response = self.grant_from_notice(SALT_TAX)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(LANTERN))
        self.assertContains(response, "sam@example.com is granted The Salt Tax Revolt.")
        self.assertNotIn(f"/{SALT_TAX}/", self.notice())
