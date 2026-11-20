"""Reconciliation (#63): a Plot Master reconciles a draft Mod and reads the
report. Through web requests, with a fake provider in place of the real one:
the tests never call an LLM."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest import mock

import plotcanon
from django.db import IntegrityError, ProgrammingError, transaction
from django.test import override_settings

from accounts.models import User
from canon.models import Document
from canon.test_approving import DAUGHTER
from canon.test_mod_submissions import NEW, SubmissionTest, a_mod
from canon.test_resolving import WARRANT
from interviews import config, reconciling
from interviews.models import Reconciliation, TokenUsage
from interviews.providers import ProviderError, Usage
from interviews.providers.base import BUSY
from interviews.test_interviews import FakeProvider
from organizations import tenancy
from organizations.models import Membership, World
from organizations.tests import sign_in

RECONCILING = config.ReconciliationSettings(provider="anthropic", model="fake-model")

REPORT = """\
Verdict: conflicts, do not approve yet

## Conflicts

- `harrow-dunmore`: the Mod has him meet the PCs at the docks.
  Source: canon/npcs/harrow-dunmore.md
  Options: move the meeting, or write him in as a ghost.

## Warnings

None.

## Missing links

- `the-tidemother`: "the old woman of the tide" in the second scene is her.

## Slug mapping

None.

## New entities

None.

## Player agency

None.

## Other drafts

None.

## Proposed changes

None.
"""


class ReconciliationTest(SubmissionTest):
    """Mira is Organization Admin and Plot Master; Sam writes Mods. The
    sample World's one draft is the Guildmaster's Daughter."""

    @contextmanager
    def reconciling(self, fake):
        """Reconciliation is on, with `fake` as its LLM."""
        with mock.patch.object(config, "reconciliation_llm",
                               lambda loaded=None: config.Llm(RECONCILING, fake)):
            yield fake

    @contextmanager
    def not_reconciling(self):
        with mock.patch.object(config, "reconciliation_llm", lambda loaded=None: None):
            yield

    def reconcile(self, mod, by=None):
        return (by or self.mira).post(f"{self.mod_page(mod)}reconcile/", follow=True)

    def kept(self, mod):
        """The Mod's Reconciliations, latest first."""
        with self.in_world():
            return list(Reconciliation.objects.filter(mod__slug=mod))

    def report_page(self, mod, kept):
        return f"{self.mod_page(mod)}reconciliations/{kept.pk}/"


class TheReconcileButton(ReconciliationTest):
    def test_with_no_config_entry_there_is_none(self):
        with self.not_reconciling():
            page = self.mira.get(self.mod_page(DAUGHTER))

        self.assertNotContains(page, f"{self.mod_page(DAUGHTER)}reconcile/")

    def test_a_plot_master_is_offered_it_on_a_draft(self):
        with self.reconciling(FakeProvider()):
            page = self.mira.get(self.mod_page(DAUGHTER))

        self.assertContains(page, f'action="{self.mod_page(DAUGHTER)}reconcile/"')

    def test_a_mod_writer_is_not_even_on_their_own_draft(self):
        self.submit_mod(a_mod())
        with self.reconciling(FakeProvider()):
            page = self.sam.get(self.mod_page(NEW))

        self.assertNotContains(page, f"{self.mod_page(NEW)}reconcile/")


class ReconcilingADraft(ReconciliationTest):
    def test_a_plot_master_reconciles_it_and_reads_the_reports_sections(self):
        with self.reconciling(FakeProvider(REPORT)) as fake:
            page = self.reconcile(DAUGHTER)

        self.assertEqual(len(fake.asked), 1)
        self.assertEqual(page.redirect_chain[-1][0], self.mod_page(DAUGHTER))
        self.assertContains(page, "Verdict: conflicts, do not approve yet")
        for heading in plotcanon.RECONCILIATION_SECTIONS:
            self.assertContains(page, f"<h3>{heading}</h3>")
        self.assertContains(page, "<code>harrow-dunmore</code>: the Mod has him meet")
        self.assertContains(page, "by mira@example.com")
        self.assertContains(page, "fake-model")

    def test_the_llm_is_given_plotcanons_instructions_for_the_draft_the_world_and_the_rest(self):
        self.submit_mod(a_mod())
        draft = self.stored(DAUGHTER)
        files = self.stored_files()
        findings = [f for f in plotcanon.load_world(files).findings if f.path == draft.path]
        with self.reconciling(FakeProvider(REPORT)) as fake:
            self.reconcile(DAUGHTER)

        system, messages = fake.asked[0]
        self.assertEqual(system, plotcanon.reconciliation_instructions(
            "web", draft=draft.text, world=files, other_drafts=[self.stored(NEW).text],
            findings=findings))
        self.assertEqual([m.role for m in messages], ["user"])

    def test_the_world_it_reads_is_the_plot_teams_whoever_runs_it(self):
        # Mira's World as she reads it is everything; so is what a run on
        # submission is given, with nobody asking.
        draft = self.stored(DAUGHTER)
        with self.reconciling(FakeProvider(REPORT)) as fake, self.in_world():
            reconciling.reconcile(draft, by=None)

        self.assertIn(self.stored_files()["canon/npcs/harrow-dunmore.md"].split("## GM Notes")[1]
                      .strip().splitlines()[0], fake.asked[0][0])

    def test_a_mod_writer_cannot_reconcile_or_read_a_report(self):
        self.submit_mod(a_mod())
        with self.reconciling(FakeProvider(REPORT)) as fake:
            refused = self.sam.post(f"{self.mod_page(NEW)}reconcile/")
            self.reconcile(NEW)
        kept = self.kept(NEW)[0]

        self.assertEqual(refused.status_code, 404)
        self.assertEqual(len(fake.asked), 1)
        self.assertEqual(self.sam.get(self.report_page(NEW, kept)).status_code, 404)
        self.assertNotContains(self.sam.get(self.mod_page(NEW)), "harrow-dunmore</code>")
        self.assertEqual(self.mira.get(self.report_page(NEW, kept)).status_code, 200)

    def test_a_plot_master_who_is_not_an_admin_may(self):
        pat = self.join("pat@example.com")
        self.give("pat@example.com", "plot-master")
        with self.reconciling(FakeProvider(REPORT)):
            page = self.reconcile(DAUGHTER, by=pat)

        self.assertContains(page, "by pat@example.com")

    def test_with_no_config_entry_nothing_runs(self):
        with self.not_reconciling():
            page = self.reconcile(DAUGHTER)

        self.assertContains(page, "not set up")
        self.assertEqual(self.kept(DAUGHTER), [])

    def test_a_mod_that_is_not_a_draft_is_not_reconciled(self):
        with self.reconciling(FakeProvider(REPORT)) as fake:
            page = self.reconcile(WARRANT)

        self.assertContains(page, "is not a draft")
        self.assertEqual(fake.asked, [])

    def test_a_provider_failure_keeps_nothing_and_says_so(self):
        with self.reconciling(FakeProvider(ProviderError(BUSY))):
            page = self.reconcile(DAUGHTER)

        self.assertContains(page, "busy")
        self.assertEqual(self.kept(DAUGHTER), [])

    def test_approving_is_unaffected_by_a_report_of_conflicts(self):
        with self.reconciling(FakeProvider(REPORT)):
            self.reconcile(DAUGHTER)
            self.approve(DAUGHTER, campaign="lanternlight")

        self.assertEqual(self.stored(DAUGHTER).fields["state"], "approved")


class History(ReconciliationTest):
    def test_earlier_reports_stay_listed_after_a_revision(self):
        self.submit_mod(a_mod())
        with self.reconciling(FakeProvider(REPORT, REPORT.replace("docks", "quay"))):
            self.reconcile(NEW)
            self.revise(NEW, a_mod(title="The Lamplighter's Second Debt"))
            page = self.reconcile(NEW)
        first, = self.kept(NEW)[1:]

        self.assertContains(page, "meet the PCs at the quay")
        self.assertContains(page, "Earlier Reconciliations")
        self.assertContains(page, f'href="{self.report_page(NEW, first)}"')
        earlier = self.mira.get(self.report_page(NEW, first))
        self.assertContains(earlier, "meet the PCs at the docks")
        self.assertContains(earlier, "an earlier revision")


class RunningOnSubmission(ReconciliationTest):
    """The run another part of the app calls, as on submission (#65)."""

    def test_it_keeps_the_other_drafts_the_report_names(self):
        self.submit_mod(a_mod())
        names_new = REPORT.replace(
            "## Other drafts\n\nNone.",
            f"## Other drafts\n\n- `{NEW}`, `tobren-vale`: both end the feud.")
        with self.reconciling(FakeProvider(names_new)), self.in_world():
            kept = reconciling.reconcile(Document.objects.get(slug=DAUGHTER), by=None)

        self.assertTrue(kept.on_submission)
        self.assertIsNone(kept.ran_by)
        self.assertEqual(kept.other_drafts, [NEW])
        self.assertEqual(kept.verdict, "conflicts, do not approve yet")
        self.assertIn("on submission", self.mira.get(self.mod_page(DAUGHTER)).content.decode())


class Spending(ReconciliationTest):
    @contextmanager
    def capped_at(self, tokens):
        loaded = config.Config(limits=config.Limits(tokens_per_organization_per_month=tokens))
        with mock.patch.object(config, "current", lambda: loaded), \
                mock.patch("interviews.spending._now", return_value=datetime(2026, 11, 3, 9,
                                                                             tzinfo=UTC)):
            yield

    def used(self):
        with self.in_world():
            return TokenUsage.objects.values_list("tokens", flat=True).first() or 0

    def test_a_runs_tokens_count_toward_the_cap(self):
        with self.capped_at(1000), self.reconciling(FakeProvider(REPORT)):
            self.reconcile(DAUGHTER)

        self.assertEqual(self.used(), 120)

    def test_at_the_cap_it_does_not_run_and_the_page_says_why(self):
        with self.capped_at(120), self.reconciling(FakeProvider(REPORT, REPORT)) as fake:
            self.reconcile(DAUGHTER)
            page = self.reconcile(DAUGHTER)

        self.assertEqual(len(fake.asked), 1)
        self.assertEqual(len(self.kept(DAUGHTER)), 1)
        self.assertContains(page, "was not reconciled")
        self.assertContains(page, "used this month&#x27;s tokens")
        self.assertContains(page, "1 December")

    def test_a_failed_runs_tokens_count_all_the_same(self):
        with self.capped_at(1000), self.reconciling(
                FakeProvider(ProviderError(BUSY, usage=Usage(30, 0)))):
            self.reconcile(DAUGHTER)

        self.assertEqual(self.used(), 30)


@override_settings(OPEN_SIGN_UP=True)
class KeptApart(ReconciliationTest):
    """Row-level security keeps each Organization's Reconciliations apart."""

    def setUp(self):
        super().setUp()
        with self.reconciling(FakeProvider(REPORT)):
            self.reconcile(DAUGHTER)
        sign_in("olga@example.com")
        olga = User.objects.get(email="olga@example.com")
        with tenancy.acting_as(user=olga):
            self.olgas = Membership.objects.get().organization_id

    def test_another_organization_sees_none(self):
        with tenancy.acting_as(organization=self.olgas):
            self.assertEqual(Reconciliation.objects.count(), 0)
        with tenancy.acting_as():
            self.assertEqual(Reconciliation.objects.count(), 0)
        self.assertEqual(len(self.kept(DAUGHTER)), 1)

    def test_one_cannot_be_written_into_another_organization(self):
        kept = self.kept(DAUGHTER)[0]
        with self.assertRaises(ProgrammingError), transaction.atomic():
            with tenancy.acting_as(organization=self.olgas):
                Reconciliation.objects.create(
                    organization_id=kept.organization_id, world_id=kept.world_id,
                    mod_id=kept.mod_id, draft="", model="m", text="")

    def test_one_cannot_point_at_another_organizations_mod(self):
        kept = self.kept(DAUGHTER)[0]
        with tenancy.acting_as(organization=self.olgas):
            world = World.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with tenancy.acting_as(organization=self.olgas):
                Reconciliation.objects.create(
                    organization_id=self.olgas, world=world, mod_id=kept.mod_id,
                    draft="", model="m", text="")


class ALaterDraftMayConflict(ReconciliationTest):
    """A report naming another draft puts a note on that draft's page (#66)."""

    def setUp(self):
        super().setUp()
        self.submit_mod(a_mod())
        names_new = REPORT.replace(
            "## Other drafts\n\nNone.",
            f"## Other drafts\n\n- `{NEW}`: both end the feud.")
        with self.reconciling(FakeProvider(names_new)):
            self.reconcile(DAUGHTER)
        self.naming, = self.kept(DAUGHTER)

    def test_the_named_drafts_page_tells_the_plot_team_with_a_link_to_the_report(self):
        page = self.mira.get(self.mod_page(NEW))

        self.assertContains(page, "A later draft may conflict with this one")
        self.assertContains(page, f'href="{self.report_page(DAUGHTER, self.naming)}"')

    def test_a_mod_writer_never_sees_it(self):
        page = self.sam.get(self.mod_page(NEW))

        self.assertNotContains(page, "may conflict with this one")
        self.assertNotContains(page, self.report_page(DAUGHTER, self.naming))

    def test_the_draft_the_report_is_on_has_no_such_note(self):
        page = self.mira.get(self.mod_page(DAUGHTER))

        self.assertNotContains(page, "A later draft may conflict with this one")

    def test_it_goes_once_the_naming_drafts_latest_report_no_longer_names_it(self):
        with self.reconciling(FakeProvider(REPORT)):
            self.reconcile(DAUGHTER)

        self.assertNotContains(self.mira.get(self.mod_page(NEW)), "may conflict with this one")

    def test_it_goes_once_the_naming_draft_is_approved(self):
        self.approve(DAUGHTER, campaign="lanternlight")

        self.assertNotContains(self.mira.get(self.mod_page(NEW)), "may conflict with this one")

    def test_an_approved_mod_has_no_such_note(self):
        self.approve(NEW, campaign="lanternlight")

        self.assertNotContains(self.mira.get(self.mod_page(NEW)), "may conflict with this one")
