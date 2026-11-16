"""Plot Masters assigning Mod Runners to Mods, for one Event or until revoked.
Through web requests, with plotcanon's sample World, two of whose Events are
moved far into the future so that they have not ended yet:

- Storm Moon (`e03-storm-moon`), a weekend, 19 to 21 June 2999;
- Second Lantern (`e04-second-lantern`), one night, 11 July 2999.

Low Tide (`e01-low-tide`) ended in April 2026."""

import plotcanon

from canon.models import Assignment
from canon.test_reports import ReportTest
from organizations.tests import sign_in

VIGIL = "storm-moon-vigil"            # approved
LEDGER = "the-tax-collectors-ledger"  # in progress
FERRY = "the-ferrymans-price"         # finished
DAUGHTER = "the-guildmasters-daughter"  # a draft
STORM_MOON = "e03-storm-moon"
SECOND_LANTERN = "e04-second-lantern"
LOW_TIDE = "e01-low-tide"


def a_world_with_events_to_come():
    files = plotcanon.sample_world()
    files["canon/events/e03-storm-moon.md"] = files["canon/events/e03-storm-moon.md"] \
        .replace("real_date: 2026-06-19", "real_date: 2999-06-19") \
        .replace("real_date_end: 2026-06-21", "real_date_end: 2999-06-21")
    files["canon/events/e04-second-lantern.md"] = files["canon/events/e04-second-lantern.md"] \
        .replace("real_date: 2026-07-11", "real_date: 2999-07-11")
    return files


class AssignmentTest(ReportTest):
    """Mira is Plot Master. Rhea and Tom run Mods, and Sam only writes them."""

    def setUp(self):
        super().setUp()
        self.rhea = self.join("rhea@example.com")
        self.give("rhea@example.com", "mod-runner")
        self.tom = self.join("tom@example.com")
        self.give("tom@example.com", "mod-runner")
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")

    def import_sample(self, **options):
        return self.import_files(a_world_with_events_to_come(), **options)

    def assign(self, mod, email, event="", by=None):
        return (by or self.mira).post(f"{self.mod_page(mod)}assignments/",
                                      {"user": self.user_id(email), "event": event},
                                      follow=True)

    def revoke(self, mod, assignment_id, by=None):
        return (by or self.mira).post(
            f"{self.mod_page(mod)}assignments/{assignment_id}/revoke/", follow=True)

    def assignment_ids(self, mod):
        with self.in_world():
            return list(Assignment.objects.filter(mod__slug=mod).values_list("pk", flat=True))

    def section(self, page, name):
        """The text of one `<section class="name">` of a page, or None."""
        page = page.content.decode()
        start = f'<section class="{name}">'
        if start not in page:
            return None
        return page.split(start, 1)[1].split("</section>", 1)[0]

    def live_shown(self, mod, by=None):
        """The live Assignments a Mod's page lists, as text."""
        page = (by or self.mira).get(self.mod_page(mod)).content.decode()
        start = '<ul class="live-assignments">'
        return page.split(start, 1)[1].split("</ul>", 1)[0] if start in page else ""


class Assigning(AssignmentTest):
    def test_a_plot_master_assigns_a_mod_runner_until_revoked(self):
        response = self.assign(VIGIL, "rhea@example.com")

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(VIGIL))
        live = self.live_shown(VIGIL)
        self.assertIn("rhea@example.com", live)
        self.assertIn("until revoked", live)

    def test_for_an_event_still_to_come(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)

        live = self.live_shown(VIGIL)
        self.assertIn("rhea@example.com", live)
        self.assertIn("for Storm Moon", live)

    def test_one_event_is_the_default_and_only_events_to_come_are_offered(self):
        form = self.section(self.mira.get(self.mod_page(VIGIL)), "assignments")

        self.assertIn(f'<option value="{STORM_MOON}" selected>', form)
        self.assertIn(f'<option value="{SECOND_LANTERN}"', form)
        self.assertNotIn(f'<option value="{LOW_TIDE}"', form)
        self.assertIn('<option value="">Until revoked</option>', form)
        # Only people who run Mods are offered.
        self.assertIn(f'<option value="{self.user_id("rhea@example.com")}"', form)
        self.assertNotIn(f'<option value="{self.user_id("sam@example.com")}"', form)

    def test_a_mod_in_progress_can_be_assigned(self):
        self.assign(LEDGER, "rhea@example.com", event=SECOND_LANTERN)

        self.assertIn("rhea@example.com", self.live_shown(LEDGER))

    def test_several_mod_runners_at_one_event(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.assign(VIGIL, "tom@example.com", event=STORM_MOON)

        live = self.live_shown(VIGIL)
        self.assertIn("rhea@example.com", live)
        self.assertIn("tom@example.com", live)

    def test_one_mod_runner_at_two_events_and_standing(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.assign(VIGIL, "rhea@example.com", event=SECOND_LANTERN)
        self.assign(VIGIL, "rhea@example.com")

        live = self.live_shown(VIGIL)
        self.assertIn("for Storm Moon", live)
        self.assertIn("for Second Lantern", live)
        self.assertIn("until revoked", live)

    def test_it_says_who_assigned_it_and_when(self):
        self.assign(VIGIL, "rhea@example.com")

        self.assertIn("assigned by mira@example.com on", self.live_shown(VIGIL))


class RefusedAssignments(AssignmentTest):
    def test_someone_who_does_not_run_mods_in_the_world(self):
        response = self.assign(VIGIL, "sam@example.com")

        self.assertContains(response, "only someone with the Mod Runner role")
        self.assertNotIn("sam@example.com", self.live_shown(VIGIL))

    def test_someone_from_another_organization(self):
        sign_in("eve@example.com")

        response = self.assign(VIGIL, "eve@example.com")

        self.assertContains(response, "only someone with the Mod Runner role")
        self.assertNotIn("eve@example.com", self.live_shown(VIGIL))

    def test_a_draft(self):
        response = self.assign(DAUGHTER, "rhea@example.com")

        self.assertContains(response, "approved or in progress")
        self.assertNotIn("rhea@example.com", self.live_shown(DAUGHTER))
        self.assertIsNone(self.section(self.mira.get(self.mod_page(DAUGHTER)), "assignments"))

    def test_a_finished_mod(self):
        response = self.assign(FERRY, "rhea@example.com")

        self.assertContains(response, "approved or in progress")
        self.assertNotIn("rhea@example.com", self.live_shown(FERRY))

    def test_an_event_that_has_ended(self):
        response = self.assign(VIGIL, "rhea@example.com", event=LOW_TIDE)

        self.assertContains(response, "Low Tide has ended")
        self.assertNotIn("rhea@example.com", self.live_shown(VIGIL))

    def test_an_event_the_world_does_not_have(self):
        response = self.assign(VIGIL, "rhea@example.com", event="no-such-event")

        self.assertContains(response, "no such Event")
        self.assertNotIn("rhea@example.com", self.live_shown(VIGIL))

    def test_the_same_mod_runner_twice_for_one_event(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)

        response = self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)

        self.assertContains(response, "rhea@example.com is already assigned to Storm Moon Vigil "
                                      "for Storm Moon")
        self.assertEqual(self.live_shown(VIGIL).count("rhea@example.com"), 1)

    def test_the_same_mod_runner_standing_twice(self):
        self.assign(VIGIL, "rhea@example.com")

        response = self.assign(VIGIL, "rhea@example.com")

        self.assertContains(response, "already assigned to Storm Moon Vigil until revoked")
        self.assertEqual(self.live_shown(VIGIL).count("rhea@example.com"), 1)

    def test_assigned_again_once_revoked(self):
        self.assign(VIGIL, "rhea@example.com")
        self.revoke(VIGIL, self.assignment_ids(VIGIL)[0])

        self.assign(VIGIL, "rhea@example.com")

        self.assertIn("rhea@example.com", self.live_shown(VIGIL))


class WhoMayAssign(AssignmentTest):
    def test_anyone_else_in_the_world_is_forbidden(self):
        self.assign(VIGIL, "rhea@example.com")
        [assignment] = self.assignment_ids(VIGIL)

        for someone in (self.rhea, self.sam):
            self.assertEqual(self.assign(VIGIL, "tom@example.com", by=someone).status_code, 403)
            self.assertEqual(self.revoke(VIGIL, assignment, by=someone).status_code, 403)
        live = self.live_shown(VIGIL)
        self.assertIn("rhea@example.com", live)
        self.assertNotIn("tom@example.com", live)

    def test_they_are_not_offered_the_forms(self):
        self.assign(VIGIL, "rhea@example.com")

        page = self.rhea.get(self.mod_page(VIGIL)).content.decode()

        self.assertNotIn("assignments/", page)

    def test_someone_outside_the_world_is_told_there_is_no_such_page(self):
        eve = sign_in("eve@example.com")

        self.assertEqual(self.assign(VIGIL, "rhea@example.com", by=eve).status_code, 404)

    def test_it_cannot_be_done_with_a_link(self):
        self.assertEqual(self.mira.get(f"{self.mod_page(VIGIL)}assignments/").status_code, 405)
