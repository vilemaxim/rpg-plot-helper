"""Grants: a Plot Master letting one Mod Writer or Mod Runner read one
document in full, GM Notes included, until revoked (see **Grant** in
GLOSSARY.md, ADR-0010). Through `grants.py` and the pages a holder reads,
with plotcanon's sample World.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them."""

from django.db import IntegrityError, ProgrammingError, transaction
from django.utils import timezone

from accounts.models import User
from canon import grants
from canon.models import Assignment, Document, Grant
from canon.test_assignments import VIGIL as VIGIL_MOD
from canon.test_exporting import unzipped
from canon.test_reading import (FERRYMAN, FERRYMAN_SECRET, TIDEMOTHER, VIGIL_SECRET,
                                ReadingTest)
from organizations import tenancy
from organizations.models import Membership, World
from organizations.tests import sign_in

TIDEMOTHER_SECRET = "Status is unknown on purpose."


class GrantTest(ReadingTest):
    def grant(self, slug, email, assignment=None):
        """Mira grants this document to this person. Returns the Grant."""
        with self.in_world():
            return grants.grant(World.objects.get(), Document.objects.get(slug=slug),
                                self.user_id(email), by=User.objects.get(email="mira@example.com"),
                                assignment=assignment)


    def revoke_grant(self, slug, grant_id):
        """Mira revokes a Grant of this document. Returns it."""
        with self.in_world():
            return grants.revoke(World.objects.get(), Document.objects.get(slug=slug), grant_id,
                                 by=User.objects.get(email="mira@example.com"))

    def rhea_user(self):
        return User.objects.get(email="rhea@example.com")

    def assignment_of(self, mod, email):
        with self.in_world():
            return Assignment.objects.get(mod__slug=mod, runner__email=email)


class Reading(GrantTest):
    def test_a_mod_writer_reads_a_gm_only_npc_in_full_once_granted_it(self):
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.sam).status_code, 404)

        self.grant(TIDEMOTHER, "sam@example.com")

        page = self.page("npcs", TIDEMOTHER, by=self.sam)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, TIDEMOTHER_SECRET)
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)

    def test_a_mod_runner_reads_a_granted_mod_in_full(self):
        self.grant(VIGIL_MOD, "rhea@example.com")

        page = self.rhea.get(self.mod_page(VIGIL_MOD))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, VIGIL_SECRET)

    def test_not_once_revoked(self):
        granted = self.grant(TIDEMOTHER, "sam@example.com")

        revoked = self.revoke_grant(TIDEMOTHER, granted.pk)

        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.sam).status_code, 404)

    def test_a_public_document_granted_is_read_with_its_gm_notes(self):
        self.assertNotContains(self.page("npcs", FERRYMAN), FERRYMAN_SECRET)

        self.grant(FERRYMAN, "sam@example.com")

        self.assertContains(self.page("npcs", FERRYMAN), FERRYMAN_SECRET)


class ForAnAssignment(GrantTest):
    def test_lasts_while_the_assignment_is_live(self):
        self.assign(VIGIL_MOD, "rhea@example.com")
        self.grant(TIDEMOTHER, "rhea@example.com",
                   assignment=self.assignment_of(VIGIL_MOD, "rhea@example.com"))

        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.rhea), TIDEMOTHER_SECRET)

    def test_ends_when_the_assignment_is_revoked(self):
        self.assign(VIGIL_MOD, "rhea@example.com")
        assignment = self.assignment_of(VIGIL_MOD, "rhea@example.com")
        self.grant(TIDEMOTHER, "rhea@example.com", assignment=assignment)

        self.revoke(VIGIL_MOD, assignment.pk)

        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)

    def test_ends_with_the_event_the_assignment_was_for(self):
        self.assign(VIGIL_MOD, "rhea@example.com", event="e03-storm-moon")
        self.grant(TIDEMOTHER, "rhea@example.com",
                   assignment=self.assignment_of(VIGIL_MOD, "rhea@example.com"))

        self.set_dates("e03-storm-moon", real_date="2020-01-01")

        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)
        with self.in_world():
            self.assertEqual(grants.live_for(World.objects.get(), self.rhea_user()), [])

    def test_a_standing_grant_of_the_same_document_outlasts_it(self):
        self.assign(VIGIL_MOD, "rhea@example.com")
        assignment = self.assignment_of(VIGIL_MOD, "rhea@example.com")
        self.grant(TIDEMOTHER, "rhea@example.com", assignment=assignment)
        self.grant(TIDEMOTHER, "rhea@example.com")

        self.revoke(VIGIL_MOD, assignment.pk)

        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.rhea), TIDEMOTHER_SECRET)

    def test_a_revoked_grant_for_it_ends_before_it_does(self):
        self.assign(VIGIL_MOD, "rhea@example.com")
        granted = self.grant(TIDEMOTHER, "rhea@example.com",
                             assignment=self.assignment_of(VIGIL_MOD, "rhea@example.com"))

        self.revoke_grant(TIDEMOTHER, granted.pk)

        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.rhea).status_code, 404)


class WhileTheyMayHoldOne(GrantTest):
    """Sam holds only the Mod Writer role, the World has no role that is not
    the plot team's or a Mod's, so losing it leaves him none."""

    def live_for_sam(self):
        with self.in_world():
            return [grant.document.slug for grant in grants.live_for(
                World.objects.get(), User.objects.get(email="sam@example.com"))]

    def holders_of(self, slug):
        with self.in_world():
            return [grant.person.email for grant in
                    grants.live_on(Document.objects.get(slug=slug))]

    def test_not_once_they_no_longer_write_or_run_mods_here(self):
        self.grant(TIDEMOTHER, "sam@example.com")

        self.take("sam@example.com", "mod-writer")

        self.assertEqual(self.live_for_sam(), [])
        self.assertEqual(self.holders_of(TIDEMOTHER), [])
        self.assertEqual(self.page("npcs", TIDEMOTHER, by=self.sam).status_code, 404)

    def test_live_again_once_given_the_role_back(self):
        self.grant(TIDEMOTHER, "sam@example.com")
        self.take("sam@example.com", "mod-writer")

        self.give("sam@example.com", "mod-writer")

        self.assertEqual(self.live_for_sam(), [TIDEMOTHER])
        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.sam), TIDEMOTHER_SECRET)

    def test_not_once_they_join_the_plot_team(self):
        self.grant(TIDEMOTHER, "sam@example.com")

        self.give("sam@example.com", "plot-master")

        self.assertEqual(self.live_for_sam(), [])
        self.assertEqual(self.holders_of(TIDEMOTHER), [])
        self.assertContains(self.page("npcs", TIDEMOTHER, by=self.sam), TIDEMOTHER_SECRET)


class Refused(GrantTest):
    def assertRefused(self, slug, email_or_id, assignment=None):
        with self.in_world():
            before = Grant.objects.count()
        user_id = self.user_id(email_or_id) if "@" in str(email_or_id) else email_or_id
        with self.in_world(), self.assertRaises(grants.GrantRefused):
            grants.grant(World.objects.get(), Document.objects.get(slug=slug), user_id,
                         by=User.objects.get(email="mira@example.com"), assignment=assignment)
        with self.in_world():
            self.assertEqual(Grant.objects.count(), before)

    def test_to_a_plot_master(self):
        self.join("pia@example.com")
        self.give("pia@example.com", "plot-master")
        self.give("pia@example.com", "mod-writer")

        self.assertRefused(TIDEMOTHER, "pia@example.com")

    def test_to_an_organization_admin(self):
        self.assertRefused(TIDEMOTHER, "mira@example.com")
        with self.in_world():
            Membership.objects.filter(user__email="sam@example.com").update(is_admin=True)

        self.assertRefused(TIDEMOTHER, "sam@example.com")

    def test_to_someone_with_no_role_in_the_world(self):
        self.join("nora@example.com")

        self.assertRefused(TIDEMOTHER, "nora@example.com")

    def test_to_someone_who_does_not_belong_to_the_organization(self):
        sign_in("eve@example.com")

        self.assertRefused(TIDEMOTHER, "eve@example.com")
        self.assertRefused(TIDEMOTHER, "not a person")

    def test_twice(self):
        self.grant(TIDEMOTHER, "sam@example.com")

        self.assertRefused(TIDEMOTHER, "sam@example.com")

    def test_for_someone_elses_assignment(self):
        self.assign(VIGIL_MOD, "rhea@example.com")

        self.assertRefused(TIDEMOTHER, "tom@example.com",
                           assignment=self.assignment_of(VIGIL_MOD, "rhea@example.com"))

    def test_for_an_assignment_no_longer_live(self):
        self.assign(VIGIL_MOD, "rhea@example.com")
        assignment = self.assignment_of(VIGIL_MOD, "rhea@example.com")
        self.revoke(VIGIL_MOD, assignment.pk)

        self.assertRefused(TIDEMOTHER, "rhea@example.com", assignment=assignment)

    def test_revoking_one_already_revoked(self):
        granted = self.grant(TIDEMOTHER, "sam@example.com")
        self.revoke_grant(TIDEMOTHER, granted.pk)

        with self.assertRaises(grants.GrantRefused):
            self.revoke_grant(TIDEMOTHER, granted.pk)

    def test_revoking_one_of_another_document(self):
        granted = self.grant(TIDEMOTHER, "sam@example.com")

        with self.assertRaises(grants.GrantRefused):
            self.revoke_grant(FERRYMAN, granted.pk)
        self.assertContains(self.page("npcs", TIDEMOTHER), TIDEMOTHER_SECRET)


class KeptOutOfTheFiles(GrantTest):
    def test_no_file_in_the_world_changes(self):
        before = self.stored_files()

        granted = self.grant(TIDEMOTHER, "sam@example.com")
        self.grant(VIGIL_MOD, "rhea@example.com")
        self.revoke_grant(TIDEMOTHER, granted.pk)

        self.assertEqual(self.stored_files(), before)

    def test_an_export_leaves_them_out(self):
        before = unzipped(self.mira.get(f"{self.first_world}export/download/").content)

        self.grant(TIDEMOTHER, "sam@example.com")

        self.assertEqual(unzipped(self.mira.get(f"{self.first_world}export/download/").content),
                         before)
        self.assertContains(self.mira.get(f"{self.first_world}export/"),
                            "who has been granted which documents")


class TheDatabaseOnItsOwn(GrantTest):
    """Eve has an Organization and World of her own."""

    def setUp(self):
        super().setUp()
        self.grant(TIDEMOTHER, "sam@example.com")
        self.assign(VIGIL_MOD, "rhea@example.com")
        sign_in("eve@example.com")
        self.eve = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=self.eve):
            self.eves = Membership.objects.get().organization_id
        with tenancy.acting_as(user=self.eve, organization=self.eves):
            self.eves_world = World.objects.get()
        with self.in_world():
            self.miras = Membership.objects.filter(user__email="mira@example.com") \
                .get().organization_id
            self.tidemother = Document.objects.get(slug=TIDEMOTHER)
            self.sam_user = User.objects.get(email="sam@example.com")
            self.rheas = Assignment.objects.get()

    def as_eve(self):
        return tenancy.acting_as(user=self.eve, organization=self.eves)

    def a_grant(self, **fields):
        """Eve writes a Grant to herself in her own World, of Mira's
        document unless `fields` say otherwise."""
        return Grant.objects.create(**{
            "organization_id": self.eves, "world_id": self.eves_world.pk,
            "document_id": self.tidemother.pk, "person_id": self.eve.pk,
            "granted_at": timezone.now(), **fields})

    def test_another_organization_sees_no_grants(self):
        with self.as_eve():
            self.assertEqual(Grant.objects.count(), 0)
        with tenancy.acting_as():
            self.assertEqual(Grant.objects.count(), 0)
        with self.in_world():
            self.assertEqual(Grant.objects.count(), 1)

    def test_another_organization_cannot_change_or_delete_one(self):
        with self.as_eve():
            changed = Grant.objects.update(revoked_at=timezone.now())
            deleted, _ = Grant.objects.all().delete()

        self.assertEqual((changed, deleted), (0, 0))
        with self.in_world():
            self.assertIsNone(Grant.objects.get().revoked_at)

    def test_one_cannot_be_written_into_another_organization(self):
        with self.assertRaises(ProgrammingError), transaction.atomic():
            with self.as_eve():
                self.a_grant(organization_id=self.miras, world_id=self.tidemother.world_id,
                             person_id=self.sam_user.pk)

    def test_one_cannot_point_at_another_organizations_world(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.as_eve():
                self.a_grant(world_id=self.tidemother.world_id)

    def test_one_cannot_point_at_another_organizations_document(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.as_eve():
                self.a_grant()

    def test_one_cannot_point_at_another_organizations_assignment(self):
        with self.as_eve():
            eves_document = Document.objects.create(
                organization_id=self.eves, world=self.eves_world, kind="npc", slug="eves-npc",
                path="canon/npcs/eves-npc.md", name="Eve's NPC", text="", fields={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.as_eve():
                self.a_grant(document_id=eves_document.pk, assignment_id=self.rheas.pk)

    def test_one_cannot_name_someone_outside_the_organization(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with self.in_world():
                Grant.objects.create(
                    organization_id=self.miras, world_id=self.tidemother.world_id,
                    document=self.tidemother, person=self.eve, granted_at=timezone.now())
