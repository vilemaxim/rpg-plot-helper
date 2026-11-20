"""Plot Masters assigning Mod Runners to Mods, for one Event or until revoked.
Through web requests, with plotcanon's sample World, two of whose Events are
moved far into the future so that they have not ended yet:

- Storm Moon (`e03-storm-moon`), a weekend, 19 to 21 June 2999;
- Second Lantern (`e04-second-lantern`), one night, 11 July 2999.

Low Tide (`e01-low-tide`) ended in April 2026."""

import datetime

import plotcanon
from django.db import IntegrityError, ProgrammingError, transaction
from django.utils import timezone

from accounts.models import User
from canon import assignments
from canon.models import Assignment, Document
from canon.test_exporting import unzipped
from canon.test_reports import ReportTest
from organizations import tenancy
from organizations.models import Membership, World
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

    def set_dates(self, slug, **dates):
        """Give an Event these dates in place of the ones it has, as time
        passing or a file with fewer dates would. None leaves one out."""
        with self.in_world():
            event = Document.objects.get(slug=slug)
            for field in ("real_date", "real_date_end"):
                event.fields.pop(field, None)
            event.fields.update({k: v for k, v in dates.items() if v is not None})
            event.save(update_fields=["fields"])

    def stored_assignment(self, pk):
        with self.in_world():
            return Assignment.objects.get(pk=pk)

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

    def test_an_event_with_only_its_last_day_is_offered(self):
        self.set_dates(STORM_MOON, real_date_end="2999-06-21")

        form = self.section(self.mira.get(self.mod_page(VIGIL)), "assignments")

        self.assertIn(f'<option value="{STORM_MOON}" selected>', form)
        self.assertIn(f'<option value="{SECOND_LANTERN}"', form)

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

    def test_an_event_with_no_date(self):
        self.set_dates(SECOND_LANTERN)

        response = self.assign(VIGIL, "rhea@example.com", event=SECOND_LANTERN)

        self.assertContains(response, "Second Lantern has no date")
        self.assertNotIn("rhea@example.com", self.live_shown(VIGIL))
        self.assertNotIn(f'<option value="{SECOND_LANTERN}"',
                         self.section(self.mira.get(self.mod_page(VIGIL)), "assignments"))

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


class Revoking(AssignmentTest):
    def test_a_plot_master_revokes_a_live_assignment(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.assign(VIGIL, "tom@example.com")
        rhea, tom = self.assignment_ids(VIGIL)

        self.revoke(VIGIL, rhea)

        live = self.live_shown(VIGIL)
        self.assertNotIn("rhea@example.com", live)
        self.assertIn("tom@example.com", live)

    def test_it_is_kept_with_who_assigned_and_revoked_it(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.revoke(VIGIL, self.assignment_ids(VIGIL)[0])

        past = self.section(self.mira.get(self.mod_page(VIGIL)), "past-assignments")

        self.assertIn("rhea@example.com, for Storm Moon; assigned by mira@example.com on", past)
        self.assertIn("revoked by mira@example.com on", past)

    def test_past_assignments_are_shown_to_plot_masters_alone(self):
        self.assign(VIGIL, "rhea@example.com")
        self.revoke(VIGIL, self.assignment_ids(VIGIL)[0])

        for someone in (self.rhea, self.sam):
            self.assertIsNone(self.section(someone.get(self.mod_page(VIGIL)),
                                           "past-assignments"))

    def test_one_already_revoked_is_not_revoked_again(self):
        self.assign(VIGIL, "rhea@example.com")
        [assignment] = self.assignment_ids(VIGIL)
        self.revoke(VIGIL, assignment)
        when = self.stored_assignment(assignment).revoked_at

        self.revoke(VIGIL, assignment)

        self.assertEqual(self.stored_assignment(assignment).revoked_at, when)

    def test_revoking_one_already_revoked_says_so(self):
        self.assign(VIGIL, "rhea@example.com")
        [assignment] = self.assignment_ids(VIGIL)
        self.revoke(VIGIL, assignment)

        self.assertContains(self.revoke(VIGIL, assignment), "already revoked")

    def test_revoking_one_whose_event_has_ended_says_so(self):
        self.assign(VIGIL, "rhea@example.com", event=SECOND_LANTERN)
        self.set_dates(SECOND_LANTERN, real_date="2026-07-11")

        response = self.revoke(VIGIL, self.assignment_ids(VIGIL)[0])

        self.assertContains(response, "Second Lantern has ended")
        self.assertIsNone(self.stored_assignment(self.assignment_ids(VIGIL)[0]).revoked_at)

    def test_one_on_another_mod_is_not_revoked_through_this_one(self):
        self.assign(LEDGER, "rhea@example.com")
        [assignment] = self.assignment_ids(LEDGER)

        self.revoke(VIGIL, assignment)

        self.assertIn("rhea@example.com", self.live_shown(LEDGER))


class WhenAnAssignmentIsLive(AssignmentTest):
    """`assignments.is_assigned`, which later work asks."""

    def is_assigned(self, email, mod=VIGIL, event=None, on=None):
        with self.in_world():
            return assignments.is_assigned(Document.objects.get(slug=mod),
                                           User.objects.get(email=email), event=event, on=on)

    def test_for_one_event_until_its_last_day_has_passed(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)

        self.assertTrue(self.is_assigned("rhea@example.com"))
        self.assertTrue(self.is_assigned("rhea@example.com", on=datetime.date(2999, 6, 21)))
        self.assertFalse(self.is_assigned("rhea@example.com", on=datetime.date(2999, 6, 22)))

    def test_a_one_day_event_ends_with_its_only_day(self):
        self.assign(VIGIL, "rhea@example.com", event=SECOND_LANTERN)

        self.assertTrue(self.is_assigned("rhea@example.com", on=datetime.date(2999, 7, 11)))
        self.assertFalse(self.is_assigned("rhea@example.com", on=datetime.date(2999, 7, 12)))

    def test_at_one_event(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)

        self.assertTrue(self.is_assigned("rhea@example.com", event=STORM_MOON))
        self.assertFalse(self.is_assigned("rhea@example.com", event=SECOND_LANTERN))

    def test_standing_until_revoked_whatever_the_event(self):
        self.assign(VIGIL, "rhea@example.com")

        self.assertTrue(self.is_assigned("rhea@example.com", event=SECOND_LANTERN,
                                         on=datetime.date(3000, 1, 1)))
        self.revoke(VIGIL, self.assignment_ids(VIGIL)[0])
        self.assertFalse(self.is_assigned("rhea@example.com"))

    def test_only_the_person_and_mod_assigned(self):
        self.assign(VIGIL, "rhea@example.com")

        self.assertFalse(self.is_assigned("tom@example.com"))
        self.assertFalse(self.is_assigned("rhea@example.com", mod=LEDGER))

    def test_one_whose_event_has_ended_is_past_on_the_mods_page(self):
        self.assign(VIGIL, "rhea@example.com", event=SECOND_LANTERN)
        self.set_dates(SECOND_LANTERN, real_date="2026-07-11")

        self.assertNotIn("rhea@example.com", self.live_shown(VIGIL))
        past = self.section(self.mira.get(self.mod_page(VIGIL)), "past-assignments")
        self.assertIn("rhea@example.com, for Second Lantern", past)
        self.assertIn("ended with the Event", past)

    def test_not_once_they_no_longer_run_mods_here(self):
        self.assign(VIGIL, "rhea@example.com")

        self.take("rhea@example.com", "mod-runner")

        self.assertFalse(self.is_assigned("rhea@example.com"))
        self.assertNotIn("rhea@example.com", self.live_shown(VIGIL))
        past = self.section(self.mira.get(self.mod_page(VIGIL)), "past-assignments")
        self.assertIn("no longer a Mod Runner here", past)


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


class WhoSeesThem(AssignmentTest):
    def test_every_world_role_sees_the_live_ones_on_the_mods_page(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.assign(VIGIL, "tom@example.com")

        for someone in (self.mira, self.rhea, self.tom):
            live = self.live_shown(VIGIL, by=someone)
            self.assertIn("rhea@example.com, for Storm Moon", live)
            self.assertIn("tom@example.com, until revoked", live)
        # Sam may not read the Mod at all (ADR-0010).
        self.assertEqual(self.sam.get(self.mod_page(VIGIL)).status_code, 404)

    def test_a_mod_runner_sees_their_own_live_assignments_on_the_world_page(self):
        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.assign(LEDGER, "rhea@example.com")
        self.assign(LEDGER, "tom@example.com", event=SECOND_LANTERN)
        self.assign(VIGIL, "rhea@example.com", event=SECOND_LANTERN)
        self.revoke(VIGIL, self.assignment_ids(VIGIL)[-1])

        mine = self.section(self.rhea.get(self.first_world), "my-assignments")

        self.assertIn(f"mods/{VIGIL}/", mine)
        self.assertIn("Storm Moon Vigil</a>, for Storm Moon", mine)
        self.assertIn("The Tax Collector&#x27;s Ledger</a>, until revoked", mine)
        self.assertNotIn("Second Lantern", mine)
        self.assertNotIn("tom@example.com", mine)

    def test_someone_with_none_live_sees_no_list(self):
        self.assign(VIGIL, "rhea@example.com")

        self.assertIsNone(self.section(self.tom.get(self.first_world), "my-assignments"))
        self.assertIsNone(self.section(self.mira.get(self.first_world), "my-assignments"))


class KeptOutOfTheFiles(AssignmentTest):
    def test_no_file_in_the_world_changes(self):
        before = self.stored_files()

        self.assign(VIGIL, "rhea@example.com", event=STORM_MOON)
        self.assign(VIGIL, "tom@example.com")
        self.revoke(VIGIL, self.assignment_ids(VIGIL)[0])

        self.assertEqual(self.stored_files(), before)

    def test_an_export_leaves_them_out(self):
        before = unzipped(self.mira.get(f"{self.first_world}export/download/").content)

        self.assign(VIGIL, "rhea@example.com")

        self.assertEqual(unzipped(self.mira.get(f"{self.first_world}export/download/").content),
                         before)
        self.assertContains(self.mira.get(f"{self.first_world}export/"),
                            "who is assigned to run each Mod")


class TheDatabaseOnItsOwn(AssignmentTest):
    """Eve has an Organization and World of her own."""

    def setUp(self):
        super().setUp()
        self.assign(VIGIL, "rhea@example.com")
        sign_in("eve@example.com")
        self.eve = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=self.eve):
            self.eves = Membership.objects.get().organization_id
        with tenancy.acting_as(user=self.eve, organization=self.eves):
            self.eves_world = World.objects.get()
        with self.in_world():
            self.miras = Membership.objects.filter(user__email="mira@example.com") \
                .get().organization_id
            self.vigil = Document.objects.get(slug=VIGIL)
            self.rhea_user = User.objects.get(email="rhea@example.com")

    def as_eve(self):
        return tenancy.acting_as(user=self.eve, organization=self.eves)

    def an_assignment(self, **fields):
        """Eve writes an Assignment to Mira's Mod, in her own World unless
        `fields` say otherwise."""
        return Assignment.objects.create(**{
            "organization_id": self.eves, "world_id": self.eves_world.pk,
            "mod_id": self.vigil.pk, "runner_id": self.eve.pk, "assigned_at": timezone.now(),
            **fields})

    def test_another_organization_sees_no_assignments(self):
        with self.as_eve():
            self.assertEqual(Assignment.objects.count(), 0)
        with tenancy.acting_as():
            self.assertEqual(Assignment.objects.count(), 0)
        with self.in_world():
            self.assertEqual(Assignment.objects.count(), 1)

    def test_another_organization_cannot_change_or_delete_one(self):
        with self.as_eve():
            changed = Assignment.objects.update(revoked_at=timezone.now())
            deleted, _ = Assignment.objects.all().delete()

        self.assertEqual((changed, deleted), (0, 0))
        with self.in_world():
            self.assertIsNone(Assignment.objects.get().revoked_at)

    def test_one_cannot_be_written_into_another_organization(self):
        with self.assertRaises(ProgrammingError), transaction.atomic():
            with self.as_eve():
                self.an_assignment(organization_id=self.miras, world_id=self.vigil.world_id,
                                   runner_id=self.rhea_user.pk)

    def test_one_cannot_point_at_another_organizations_world(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.as_eve():
                self.an_assignment(world_id=self.vigil.world_id)

    def test_one_cannot_point_at_another_organizations_mod(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.as_eve():
                self.an_assignment()

    def test_one_cannot_name_someone_outside_the_organization(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.in_world():
                Assignment.objects.create(
                    organization_id=self.miras, world_id=self.vigil.world_id, mod=self.vigil,
                    runner=self.eve, assigned_at=timezone.now())
