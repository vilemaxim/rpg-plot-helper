"""Suggestions when making an Assignment: a Plot Master assigning a Mod Runner
to a Mod is shown the Mod's Features, unticked, and the ticked ones become
Grants that belong to that Assignment and end when it does (#57, ADR-0010).
Through web requests, with plotcanon's sample World.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them. Storm Moon Vigil features the GM-only
NPC the Tidemother and the GM-only Plot the Drowned Bell, among others."""

from canon.models import Document, Grant
from canon.test_assignments import STORM_MOON, VIGIL
from canon.test_grants import TIDEMOTHER_SECRET, GrantTest
from canon.test_reading import DROWNED_BELL, TIDEMOTHER

# Every id under Storm Moon Vigil's `features`, in the order its file lists them.
VIGIL_FEATURES = ["sister-ane", "brother-castan", TIDEMOTHER, "drowned-chapel",
                  "the-sunken-chapel", DROWNED_BELL]


class FeatureTest(GrantTest):
    def assign_with(self, mod, email, features, event="", by=None):
        """Assign this person to a Mod with these Features ticked."""
        return (by or self.mira).post(f"{self.mod_page(mod)}assignments/",
                                      {"user": self.user_id(email), "event": event,
                                       "feature": features},
                                      follow=True)

    def assign_form(self, mod=VIGIL):
        return self.section(self.mira.get(self.mod_page(mod)), "assignments")

    def stored_grants(self):
        with self.in_world():
            return list(Grant.objects.order_by("document__slug")
                        .values_list("document__slug", "person__email", "assignment_id"))


class TheAssignForm(FeatureTest):
    def test_offers_every_feature_of_the_mod_unticked(self):
        form = self.assign_form()

        for slug in VIGIL_FEATURES:
            self.assertIn(f'name="feature" value="{slug}"', form)
        self.assertNotIn("checked", form)

    def test_leaves_out_an_id_that_names_no_document(self):
        with self.in_world():
            mod = Document.objects.get(slug=VIGIL)
            mod.fields["features"]["npcs"].append("nobody-at-all")
            mod.save(update_fields=["fields"])

        form = self.assign_form()

        self.assertIn(f'value="{TIDEMOTHER}"', form)
        self.assertNotIn("nobody-at-all", form)

    def test_a_mod_with_no_features_offers_none(self):
        with self.in_world():
            mod = Document.objects.get(slug=VIGIL)
            del mod.fields["features"]
            mod.save(update_fields=["fields"])

        self.assertNotIn('name="feature"', self.assign_form())


class TickingFeatures(FeatureTest):
    def test_the_mod_runner_reads_the_ticked_ones_in_full(self):
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)

        response = self.assign_with(VIGIL, "rhea@example.com", [TIDEMOTHER])

        self.assertContains(response, "rhea@example.com is assigned to Storm Moon Vigil")
        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.rhea), TIDEMOTHER_SECRET)
        self.assertEqual(self.page("plots", DROWNED_BELL, by=self.rhea).status_code, 404)

    def test_the_grants_belong_to_the_assignment(self):
        self.assign_with(VIGIL, "rhea@example.com", [TIDEMOTHER, DROWNED_BELL])

        assignment = self.assignment_of(VIGIL, "rhea@example.com")
        self.assertEqual(self.stored_grants(),
                         [(DROWNED_BELL, "rhea@example.com", assignment.pk),
                          (TIDEMOTHER, "rhea@example.com", assignment.pk)])

    def test_nothing_is_granted_unless_ticked(self):
        self.assign_with(VIGIL, "rhea@example.com", [])

        self.assertEqual(len(self.assignment_ids(VIGIL)), 1)
        self.assertEqual(self.stored_grants(), [])

    def test_the_grants_end_when_the_assignment_is_revoked(self):
        self.assign_with(VIGIL, "rhea@example.com", [TIDEMOTHER])

        self.revoke(VIGIL, self.assignment_of(VIGIL, "rhea@example.com").pk)

        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)

    def test_the_grants_end_with_the_event_the_assignment_was_for(self):
        self.assign_with(VIGIL, "rhea@example.com", [TIDEMOTHER], event=STORM_MOON)
        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.rhea), TIDEMOTHER_SECRET)

        self.set_dates(STORM_MOON, real_date="2020-01-01")

        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)


class Refused(FeatureTest):
    def test_a_document_that_is_not_a_feature_of_the_mod(self):
        response = self.assign_with(VIGIL, "rhea@example.com", [TIDEMOTHER, "clerk-pell"])

        self.assertContains(response, "Storm Moon Vigil has no Feature")
        self.assertEqual(self.assignment_ids(VIGIL), [])
        self.assertEqual(self.stored_grants(), [])

    def test_an_assignment_refused_grants_nothing(self):
        response = self.assign_with(VIGIL, "sam@example.com", [TIDEMOTHER])

        self.assertContains(response, "cannot be assigned to run a Mod here")
        self.assertEqual(self.stored_grants(), [])

    def test_nothing_is_granted_to_a_mod_runner_on_the_plot_team(self):
        self.give("mira@example.com", "mod-runner")

        response = self.assign_with(VIGIL, "mira@example.com", [TIDEMOTHER])

        self.assertContains(response, "mira@example.com is assigned to Storm Moon Vigil.")
        self.assertEqual(self.stored_grants(), [])
