"""Reconciliation on submission (#65): with the setting on for a World, a
draft is reconciled when it is submitted and when a revision is, inside the
request that submits it. A run that is refused or fails never stops the
submission, and the draft's page tells the plot team it is not reconciled.
Through web requests, with fake providers: the tests never call an LLM."""

import html
import re
from contextlib import contextmanager
from unittest import mock

from canon.test_mod_submissions import NEW, a_mod
from interviews import config, test_reconciliation
from interviews.providers import ProviderError, Usage
from interviews.providers.base import BUSY
from interviews.test_interviews import QUESTION, SETTINGS, FakeProvider, fenced, hidden
from interviews.test_reconciliation import REPORT, ReconciliationTest
from organizations.test_people import ORGANIZATION

NOT_RECONCILED = "This revision of the draft has not been reconciled."


class OnSubmissionTest(ReconciliationTest):
    def setting(self, on):
        self.mira.post(f"{ORGANIZATION}reconciliation/", {"on": "on"} if on else {})

    @contextmanager
    def interviewing(self, fake):
        """Interviews are on, with `fake` as their LLM."""
        with mock.patch.object(config, "llm_for",
                               lambda kind, loaded=None: config.Llm(SETTINGS, fake)):
            yield fake

    def revised(self):
        return a_mod().replace("The Lamplighter's Debt", "The Lamplighter's Second Debt")


class WithTheSettingOn(OnSubmissionTest):
    def setUp(self):
        super().setUp()
        self.setting(True)

    def test_submitting_a_mod_reconciles_it(self):
        with self.reconciling(FakeProvider(REPORT)) as fake:
            submitted = self.submit_mod(a_mod())

        self.assertEqual(submitted.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertEqual(len(fake.asked), 1)
        [kept] = self.kept(NEW)
        self.assertTrue(kept.on_submission)
        self.assertIsNone(kept.ran_by)
        self.assertEqual(kept.draft, self.stored(NEW).text)
        page = self.mira.get(self.mod_page(NEW))
        self.assertContains(page, "Verdict: conflicts, do not approve yet")
        self.assertContains(page, "on submission")
        self.assertNotContains(page, NOT_RECONCILED)

    def test_revising_it_reconciles_the_revision_and_keeps_the_first(self):
        with self.reconciling(FakeProvider(REPORT, REPORT)) as fake:
            self.submit_mod(a_mod())
            self.revise(NEW, self.revised())

        self.assertEqual(len(fake.asked), 2)
        latest, first = self.kept(NEW)
        self.assertEqual(latest.draft, self.revised())
        self.assertEqual(first.draft, a_mod())
        self.assertTrue(latest.on_submission)

    def test_the_mod_writer_who_submits_it_is_not_shown_the_report(self):
        with self.reconciling(FakeProvider(REPORT)):
            submitted = self.submit_mod(a_mod())

        self.assertNotContains(submitted, "Verdict: conflicts")
        self.assertNotContains(submitted, "Reconcil")

    def test_a_mod_written_in_an_interview_is_reconciled_when_submitted(self):
        interview = f"{self.first_world}interview/"
        with self.reconciling(FakeProvider(REPORT)) as reconciler, \
                self.interviewing(FakeProvider(fenced(a_mod()))):
            page = self.sam.post(interview, {"said": "Hello", "transcript": ""})
            page = b"".join(page.streaming_content).decode()
            file = re.search(r'<textarea name="text"[^>]*>\n?(.*?)</textarea>', page, re.S)
            self.sam.post(f"{interview}submit/",
                          {"text": html.unescape(file.group(1)),
                           "transcript": hidden(page, "transcript")})

        self.assertEqual(len(reconciler.asked), 1)
        self.assertEqual(len(self.kept(NEW)), 1)

    def test_a_revision_written_in_an_interview_is_reconciled_when_submitted(self):
        with self.reconciling(FakeProvider(REPORT, REPORT)) as reconciler:
            self.submit_mod(a_mod())
            revise = f"{self.mod_page(NEW)}interview/"
            with self.interviewing(FakeProvider(QUESTION)):
                page = self.sam.post(revise, {"transcript": ""})
                page = b"".join(page.streaming_content).decode()
                self.sam.post(f"{revise}submit/",
                              {"text": self.revised(),
                               "transcript": hidden(page, "transcript")})

        self.assertEqual(len(reconciler.asked), 2)
        self.assertEqual(self.kept(NEW)[0].draft, self.revised())


class WithTheSettingOff(OnSubmissionTest):
    def test_neither_submitting_nor_revising_reconciles(self):
        with self.reconciling(FakeProvider()) as fake:
            self.submit_mod(a_mod())
            self.revise(NEW, self.revised())

        self.assertEqual(fake.asked, [])
        self.assertEqual(self.kept(NEW), [])
        with self.reconciling(FakeProvider()):
            page = self.mira.get(self.mod_page(NEW))
        self.assertNotContains(page, NOT_RECONCILED)


class WhenItCannotRun(OnSubmissionTest):
    """A refused or failed run leaves the draft saved, and its page says so."""

    # Borrowed through its module, so that its tests are not run here too.
    capped_at = test_reconciliation.Spending.capped_at

    def setUp(self):
        super().setUp()
        self.setting(True)

    def test_at_the_token_cap_the_draft_is_saved_and_says_it_was_not_reconciled(self):
        with self.capped_at(0), self.reconciling(FakeProvider(REPORT)) as fake:
            submitted = self.submit_mod(a_mod())
            page = self.mira.get(self.mod_page(NEW))

        self.assertEqual(submitted.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertTrue(self.exists(NEW))
        self.assertEqual(fake.asked, [])
        self.assertEqual(self.kept(NEW), [])
        self.assertContains(page, NOT_RECONCILED)
        self.assertContains(page, "used this month&#x27;s tokens")

    def test_with_no_config_entry_the_draft_is_saved_and_says_so(self):
        with self.not_reconciling():
            self.submit_mod(a_mod())
            page = self.mira.get(self.mod_page(NEW))

        self.assertTrue(self.exists(NEW))
        self.assertContains(page, NOT_RECONCILED)
        self.assertContains(page, "Reconciliation is not set up on this site.")

    def test_a_provider_failure_saves_the_draft_and_it_says_it_was_not_reconciled(self):
        with self.reconciling(FakeProvider(ProviderError(BUSY, usage=Usage(30, 0)))):
            submitted = self.submit_mod(a_mod())
            page = self.mira.get(self.mod_page(NEW))

        self.assertEqual(submitted.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertTrue(self.exists(NEW))
        self.assertContains(page, NOT_RECONCILED)
        # And the Plot Master may reconcile it with the button.
        self.assertContains(page, f'action="{self.mod_page(NEW)}reconcile/"')

    def test_a_fault_in_the_run_itself_still_saves_the_draft(self):
        with self.reconciling(FakeProvider(REPORT)), \
                mock.patch("plotcanon.read_reconciliation", side_effect=ValueError("broken")), \
                self.assertLogs("canon.intake", "ERROR"):
            submitted = self.submit_mod(a_mod())

        self.assertEqual(submitted.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertTrue(self.exists(NEW))
        self.assertEqual(self.kept(NEW), [])

    def test_a_revision_that_is_not_reconciled_says_so_beside_the_earlier_report(self):
        with self.reconciling(FakeProvider(REPORT, ProviderError(BUSY))):
            self.submit_mod(a_mod())
            self.revise(NEW, self.revised())
            page = self.mira.get(self.mod_page(NEW))

        self.assertEqual(self.stored(NEW).text, self.revised())
        self.assertEqual(len(self.kept(NEW)), 1)
        self.assertContains(page, NOT_RECONCILED)

    def test_a_mod_writer_is_not_told(self):
        with self.not_reconciling():
            self.submit_mod(a_mod())
            page = self.sam.get(self.mod_page(NEW))

        self.assertNotContains(page, NOT_RECONCILED)
