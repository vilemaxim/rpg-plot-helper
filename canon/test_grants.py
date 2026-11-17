"""Grants: a Plot Master letting one Mod Writer or Mod Runner read one
document in full, GM Notes included, until revoked (see **Grant** in
GLOSSARY.md, ADR-0010). Through `grants.py` and the pages a holder reads,
with plotcanon's sample World.

Mira is the plot team (Plot Master and Organization Admin). Sam only writes
Mods, and Rhea and Tom only run them."""

from accounts.models import User
from canon import grants
from canon.models import Assignment, Document, Grant
from canon.test_assignments import VIGIL as VIGIL_MOD
from canon.test_reading import (FERRYMAN, FERRYMAN_SECRET, TIDEMOTHER, VIGIL_SECRET,
                                ReadingTest)
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
