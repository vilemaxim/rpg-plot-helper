"""Plot Masters granting and revoking documents from their pages, and who sees
Grants (see **Grant** in GLOSSARY.md, ADR-0010). Through web requests, with
plotcanon's sample World.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them."""

from accounts.models import User
from canon import grants
from canon.models import Assignment, Document, Grant
from canon.test_assignments import VIGIL
from canon.test_grants import TIDEMOTHER_SECRET
from canon.test_reading import DROWNED_BELL, FERRYMAN, TIDEMOTHER, ReadingTest
from organizations.models import Membership, World
from organizations.tests import sign_in


class GrantingTest(ReadingTest):
    def doc_page(self, kind, slug):
        return f"{self.first_world}{kind}/{slug}/"

    def grant(self, kind, slug, email, by=None):
        return (by or self.mira).post(f"{self.doc_page(kind, slug)}grants/",
                                      {"user": self.user_id(email)}, follow=True)

    def revoke_grant(self, kind, slug, grant_id, by=None):
        return (by or self.mira).post(f"{self.doc_page(kind, slug)}grants/{grant_id}/revoke/",
                                      follow=True)

    def grant_ids(self, slug):
        with self.in_world():
            return list(Grant.objects.filter(document__slug=slug).values_list("pk", flat=True))

    def live_grants_shown(self, kind, slug, by=None):
        """The live Grants a document's page lists, as text."""
        page = (by or self.mira).get(self.doc_page(kind, slug)).content.decode()
        start = '<ul class="live-grants">'
        return page.split(start, 1)[1].split("</ul>", 1)[0] if start in page else ""


class Granting(GrantingTest):
    def test_a_plot_master_grants_a_gm_only_npc_to_a_mod_writer_from_its_page(self):
        response = self.grant("npcs", TIDEMOTHER, "sam@example.com")

        self.assertEqual(response.redirect_chain[-1][0], self.doc_page("npcs", TIDEMOTHER))
        self.assertContains(response, "sam@example.com is granted The Tidemother.")
        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.sam), TIDEMOTHER_SECRET)
        self.assertIn("sam@example.com", self.live_grants_shown("npcs", TIDEMOTHER))

    def test_a_plot_master_revokes_it_from_the_documents_page(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        [grant_id] = self.grant_ids(TIDEMOTHER)

        response = self.revoke_grant("npcs", TIDEMOTHER, grant_id)

        self.assertEqual(response.redirect_chain[-1][0], self.doc_page("npcs", TIDEMOTHER))
        self.assertContains(response, "Grant of The Tidemother is revoked.")
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.sam).status_code, 404)
        self.assertNotIn("sam@example.com", self.live_grants_shown("npcs", TIDEMOTHER))

    def test_the_page_offers_a_plot_master_only_those_who_may_be_granted_it(self):
        self.join("nora@example.com")

        form = self.section(self.mira.get(self.doc_page("npcs", TIDEMOTHER)), "grants")

        for someone in ("sam@example.com", "rhea@example.com", "tom@example.com"):
            self.assertIn(f'<option value="{self.user_id(someone)}">{someone}</option>', form)
        self.assertNotIn("mira@example.com", form)
        self.assertNotIn("nora@example.com", form)

    def test_any_kind_of_document_can_be_granted(self):
        self.grant("plots", DROWNED_BELL, "rhea@example.com")

        self.assertEqual(self.page("plots", DROWNED_BELL, by=self.rhea).status_code, 200)
        self.assertIn("rhea@example.com, granted by mira@example.com",
                      self.live_grants_shown("plots", DROWNED_BELL))

    def test_a_refusal_is_said_on_the_page(self):
        response = self.grant("npcs", TIDEMOTHER, "mira@example.com")

        self.assertContains(response, "That person cannot be granted a document here")
        self.assertEqual(self.live_grants_shown("npcs", TIDEMOTHER), "")

    def test_a_grant_for_an_assignment_says_it_ends_with_it(self):
        self.assign(VIGIL, "rhea@example.com")
        with self.in_world():
            assignment = Assignment.objects.get()
            grants.grant(World.objects.get(), Document.objects.get(slug=TIDEMOTHER),
                         self.user_id("rhea@example.com"),
                         by=User.objects.get(email="mira@example.com"), assignment=assignment)

        self.assertIn("ending with their Assignment to Storm Moon Vigil",
                      self.live_grants_shown("npcs", TIDEMOTHER))


class WhoMayGrant(GrantingTest):
    def test_anyone_else_in_the_world_is_forbidden(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        [grant_id] = self.grant_ids(TIDEMOTHER)

        for someone in (self.rhea, self.sam):
            self.assertEqual(self.grant("npcs", TIDEMOTHER, "tom@example.com",
                                        by=someone).status_code, 403)
            self.assertEqual(self.revoke_grant("npcs", TIDEMOTHER, grant_id,
                                               by=someone).status_code, 403)
        live = self.live_grants_shown("npcs", TIDEMOTHER)
        self.assertIn("sam@example.com", live)
        self.assertNotIn("tom@example.com", live)

    def test_an_admin_who_is_not_a_plot_master_sees_them_and_cannot_grant(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        with self.in_world():
            Membership.objects.filter(user__email="mira@example.com").update(is_admin=True)
        self.take("mira@example.com", "plot-master")
        admin = self.mira

        self.assertIn("sam@example.com", self.live_grants_shown("npcs", TIDEMOTHER, by=admin))
        self.assertNotIn("grants/", self.section(admin.get(self.doc_page("npcs", TIDEMOTHER)),
                                                 "grants"))
        self.assertEqual(self.grant("npcs", TIDEMOTHER, "tom@example.com", by=admin)
                         .status_code, 403)

    def test_someone_outside_the_world_is_told_there_is_no_such_page(self):
        eve = sign_in("eve@example.com")

        self.assertEqual(self.grant("npcs", TIDEMOTHER, "sam@example.com", by=eve)
                         .status_code, 404)

    def test_a_document_that_does_not_exist_is_not_found(self):
        self.assertEqual(self.grant("npcs", "nobody-at-all", "sam@example.com").status_code, 404)
        self.assertEqual(self.grant("npcs", DROWNED_BELL, "sam@example.com").status_code, 404)
        self.assertEqual(self.grant("nothing", TIDEMOTHER, "sam@example.com").status_code, 404)

    def test_it_cannot_be_done_with_a_link(self):
        self.assertEqual(self.mira.get(f"{self.doc_page('npcs', TIDEMOTHER)}grants/")
                         .status_code, 405)


class WhoSeesThem(GrantingTest):
    def test_nobody_but_the_plot_team_sees_a_documents_grants(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        self.grant("npcs", FERRYMAN, "rhea@example.com")

        for someone in (self.sam, self.rhea, self.tom):
            for slug in (TIDEMOTHER, FERRYMAN):
                page = self.page("npcs", slug, by=someone)
                if page.status_code == 200:
                    self.assertIsNone(self.section(page, "grants"))
                    self.assertNotIn("Grant", page.content.decode())


class TheirOwnList(GrantingTest):
    def world_page(self, by):
        return by.get(self.first_world)

    def test_a_holder_sees_their_live_grants_on_the_worlds_page(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        self.grant("plots", DROWNED_BELL, "sam@example.com")
        self.grant("npcs", FERRYMAN, "rhea@example.com")

        mine = self.section(self.world_page(self.sam), "my-grants")

        self.assertIn(f'href="{self.doc_page("npcs", TIDEMOTHER)}"', mine)
        self.assertIn("The Tidemother", mine)
        self.assertIn(f'href="{self.doc_page("plots", DROWNED_BELL)}"', mine)
        self.assertNotIn(FERRYMAN, mine)

    def test_not_once_revoked(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")
        [grant_id] = self.grant_ids(TIDEMOTHER)
        self.revoke_grant("npcs", TIDEMOTHER, grant_id)

        self.assertIsNone(self.section(self.world_page(self.sam), "my-grants"))

    def test_nobody_else_sees_them(self):
        self.grant("npcs", TIDEMOTHER, "sam@example.com")

        for someone in (self.rhea, self.mira):
            self.assertIsNone(self.section(self.world_page(someone), "my-grants"))


SALT_TAX = "the-salt-tax-revolt"        # a GM-only Plot
SALT_TAX_TIES = {                       # what lists it: NPCs and factions by `plots`,
    "npcs": ["clerk-pell", "harrow-dunmore", "oslo-reth", "tobren-vale", "ysolde-marr"],
    "factions": ["harbour-wardens", "salt-guild"],  # and Mods by `features.plots`
    "mods": ["a-warrant-for-dunmore", "blood-on-the-salt-stair", "the-low-tide-market",
             "the-tax-collectors-ledger"],
}
SALT_STAIR = "the-salt-stair"           # a Location whose `plots` list it too


class GrantingAPlot(GrantingTest):
    def ties_offered(self, response):
        """The documents a page offers to grant along with a Plot: slug to
        whether its box is ticked."""
        form = self.section(response, "ties") or ""
        offered = {}
        for box in form.split('<input type="checkbox"')[1:]:
            box = box.split(">", 1)[0]
            offered[box.split('value="', 1)[1].split('"', 1)[0]] = "checked" in box
        return offered

    def test_granting_a_plot_offers_its_npcs_factions_and_mods_unticked(self):
        response = self.grant("plots", SALT_TAX, "rhea@example.com")

        self.assertContains(response, "rhea@example.com is granted The Salt Tax Revolt.")
        offered = self.ties_offered(response)
        self.assertEqual(set(offered),
                         {slug for slugs in SALT_TAX_TIES.values() for slug in slugs})
        self.assertNotIn(True, offered.values())
        self.assertNotIn(SALT_STAIR, offered)

    def grant_ties(self, response, slugs, by=None):
        """Tick these on the page offering a Plot's ties, and send it."""
        return (by or self.mira).post(response.redirect_chain[-1][0], {"document": slugs},
                                      follow=True)

    def test_only_the_ticked_ones_are_granted_to_the_same_person(self):
        offer = self.grant("plots", SALT_TAX, "rhea@example.com")

        response = self.grant_ties(offer, ["clerk-pell", "a-warrant-for-dunmore"])

        self.assertEqual(response.redirect_chain[-1][0], self.doc_page("plots", SALT_TAX))
        self.assertContains(response, "rhea@example.com is granted Clerk Pell and "
                                      "A Warrant for Dunmore as well.")
        self.assertEqual(self.page("npcs", "clerk-pell", by=self.rhea).status_code, 200)
        self.assertEqual(self.page("mods", "a-warrant-for-dunmore", by=self.rhea).status_code,
                         200)
        for slug in ("harrow-dunmore", "oslo-reth"):
            self.assertEqual(self.page("npcs", slug, by=self.rhea).status_code, 404)
        self.assertEqual(self.page("mods", "the-low-tide-market", by=self.rhea).status_code, 404)
        self.assertEqual(self.page("npcs", "clerk-pell", by=self.sam).status_code, 404)
        self.assertIn("rhea@example.com", self.live_grants_shown("npcs", "clerk-pell"))

    def test_nothing_ticked_grants_nothing_more(self):
        offer = self.grant("plots", SALT_TAX, "rhea@example.com")

        response = self.grant_ties(offer, [])

        self.assertContains(response, "Nothing more was granted.")
        with self.in_world():
            self.assertEqual(Grant.objects.count(), 1)

    def test_something_not_tied_to_the_plot_is_refused_and_nothing_is_granted(self):
        offer = self.grant("plots", SALT_TAX, "rhea@example.com")

        response = self.grant_ties(offer, ["clerk-pell", SALT_STAIR])

        self.assertContains(response, "is not tied to The Salt Tax Revolt")
        self.assertEqual(self.page("npcs", "clerk-pell", by=self.rhea).status_code, 404)

    def test_not_once_the_plots_grant_is_revoked(self):
        offer = self.grant("plots", SALT_TAX, "rhea@example.com")
        [grant_id] = self.grant_ids(SALT_TAX)
        self.revoke_grant("plots", SALT_TAX, grant_id)

        response = self.grant_ties(offer, ["clerk-pell"])

        self.assertContains(response, "is no longer live, so nothing more was granted.")
        self.assertEqual(self.page("npcs", "clerk-pell", by=self.rhea).status_code, 404)

    def test_nothing_is_offered_once_the_plots_grant_is_revoked(self):
        offer = self.grant("plots", SALT_TAX, "rhea@example.com")
        [grant_id] = self.grant_ids(SALT_TAX)
        self.revoke_grant("plots", SALT_TAX, grant_id)

        response = self.mira.get(offer.redirect_chain[-1][0], follow=True)

        self.assertEqual(response.redirect_chain[-1][0], self.doc_page("plots", SALT_TAX))
        self.assertContains(response, "is no longer live, so nothing more was granted.")
        self.assertIsNone(self.section(response, "ties"))

    def test_what_they_already_hold_a_grant_of_is_not_offered(self):
        self.grant("npcs", "clerk-pell", "rhea@example.com")
        self.grant("npcs", "oslo-reth", "sam@example.com")

        offered = self.ties_offered(self.grant("plots", SALT_TAX, "rhea@example.com"))

        self.assertNotIn("clerk-pell", offered)
        self.assertIn("oslo-reth", offered)

    def test_granting_any_other_kind_offers_nothing_more(self):
        response = self.grant("npcs", "clerk-pell", "rhea@example.com")

        self.assertEqual(response.redirect_chain[-1][0], self.doc_page("npcs", "clerk-pell"))
        self.assertIsNone(self.section(response, "ties"))

    def test_only_a_plot_master_is_offered_them_or_may_grant_them(self):
        offer = self.grant("plots", SALT_TAX, "rhea@example.com")
        ties_page = offer.redirect_chain[-1][0]

        for someone in (self.rhea, self.sam):
            self.assertEqual(someone.get(ties_page).status_code, 403)
            self.assertEqual(self.grant_ties(offer, ["clerk-pell"], by=someone).status_code,
                             403)
        eve = sign_in("eve@example.com")
        self.assertEqual(eve.get(ties_page).status_code, 404)
        self.assertEqual(self.page("npcs", "clerk-pell", by=self.rhea).status_code, 404)

    def test_a_grant_of_another_document_has_no_such_page(self):
        self.grant("npcs", TIDEMOTHER, "rhea@example.com")
        [grant_id] = self.grant_ids(TIDEMOTHER)

        self.assertEqual(self.mira.get(f"{self.doc_page('plots', SALT_TAX)}grants/{grant_id}/"
                                       f"ties/").status_code, 404)
