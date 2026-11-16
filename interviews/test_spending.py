"""Spend limits on Interviews (ADR-0008): turns per person per day and tokens
per Organization per month, set in `interviews.toml`. Through web requests,
with a fake provider; the tests never call an LLM."""

from contextlib import contextmanager
from datetime import UTC, date, datetime
from unittest import mock

from django.db import ProgrammingError, transaction
from django.test import TransactionTestCase, override_settings

from accounts.models import User
from interviews import config, spending
from interviews.models import TokenUsage
from interviews.providers import ProviderError, Usage
from canon.test_mod_submissions import NEW, a_mod
from interviews.test_interviews import (BROKEN, QUESTION, FakeProvider, InterviewTest, fenced,
                                        hidden)
from organizations import tenancy
from organizations.models import Membership, World
from organizations.tests import sign_in


def at(*when):
    return datetime(*when, tzinfo=UTC)


@override_settings(OPEN_SIGN_UP=True)
class SpendingTest(InterviewTest):
    @contextmanager
    def limited(self, **limits):
        loaded = config.Config(limits=config.Limits(**limits))
        with mock.patch.object(config, "current", lambda: loaded):
            yield

    @contextmanager
    def on(self, *when):
        """Days and months, as the limits see them, are those of `when`.
        Sign-in sessions keep real time."""
        with mock.patch("interviews.spending._now", return_value=at(*when)):
            yield

    def another_organization(self):
        sign_in("olga@example.com")
        olga = User.objects.get(email="olga@example.com")
        with tenancy.acting_as(user=olga):
            return Membership.objects.get().organization_id

    def organization(self):
        with self.in_world():
            return World.objects.first().organization_id

    def refused_turn(self, said, page, by=None):
        """Send an answer that is expected to be refused, not streamed."""
        response = (by or self.sam).post(self.interview, {
            "said": said, "transcript": hidden(page, "transcript") if page else ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.streaming)
        return response


class TurnsPerPersonPerDay(SpendingTest):
    def test_a_third_turn_the_same_day_is_refused_and_the_next_day_works(self):
        with self.limited(turns_per_person_per_day=2), \
                self.provider(FakeProvider(QUESTION, QUESTION, QUESTION)) as fake:
            with self.on(2026, 11, 16, 9):
                first = self.say("Hello")
                second = self.say("A debt", first)
            with self.on(2026, 11, 16, 23, 59):
                refused = self.refused_turn("A lamplighter", second)
            self.assertEqual(len(fake.asked), 2)
            with self.on(2026, 11, 17, 0, 1):
                self.say("A lamplighter", second)

        self.assertEqual(len(fake.asked), 3)
        self.assertContains(refused, "2 turns")
        self.assertContains(refused, "midnight UTC")
        self.assertContains(refused, f'href="{self.form}"')
        self.assertEqual(hidden(refused.content.decode(), "transcript"),
                         hidden(second, "transcript"))
        self.assertContains(refused, ">A lamplighter</textarea>")

    def test_each_person_has_their_own_turns(self):
        with self.limited(turns_per_person_per_day=1), \
                self.provider(FakeProvider(QUESTION, QUESTION)) as fake, \
                self.on(2026, 11, 16, 9):
            self.say("Hello")
            self.say("Hello", by=self.mira)

        self.assertEqual(len(fake.asked), 2)

    def test_with_no_limit_turns_are_not_refused(self):
        with self.limited(), self.provider(FakeProvider(*[QUESTION] * 3)) as fake:
            page = self.say("Hello")
            page = self.say("More", page)
            self.say("More", page)

        self.assertEqual(len(fake.asked), 3)


class TokensPerOrganizationPerMonth(SpendingTest):
    """Each fake turn uses 120 tokens."""

    def test_the_turn_that_crosses_the_cap_completes_and_the_next_is_refused(self):
        with self.limited(tokens_per_organization_per_month=200), \
                self.provider(FakeProvider(QUESTION, QUESTION, QUESTION)) as fake:
            with self.on(2026, 11, 3, 9):
                first = self.say("Hello")
                second = self.say("A debt", first)
            self.assertIn(QUESTION, second.rsplit("A debt", 1)[1])
            with self.on(2026, 11, 30, 23, 59):
                refused = self.refused_turn("A lamplighter", second)
            self.assertEqual(len(fake.asked), 2)
            with self.on(2026, 12, 1, 0, 1):
                self.say("A lamplighter", second)

        self.assertEqual(len(fake.asked), 3)
        self.assertContains(refused, "tokens")
        self.assertContains(refused, "1 December (UTC)")
        self.assertContains(refused, f'href="{self.form}"')
        self.assertEqual(hidden(refused.content.decode(), "transcript"),
                         hidden(second, "transcript"))

    def test_it_is_shared_by_everyone_in_the_organization(self):
        with self.limited(tokens_per_organization_per_month=100), \
                self.provider(FakeProvider(QUESTION)), self.on(2026, 11, 3, 9):
            self.say("Hello")
            self.refused_turn("Hello", None, by=self.mira)

    def test_another_organizations_tokens_do_not_count(self):
        with self.limited(tokens_per_organization_per_month=100), \
                self.provider(FakeProvider(QUESTION)) as fake, self.on(2026, 11, 3, 9):
            spending.record(self.another_organization(), Usage(500, 500))
            self.say("Hello")

        self.assertEqual(len(fake.asked), 1)


class FixAttempts(SpendingTest):
    """A fix attempt is an LLM call the Interview makes without the person,
    and reports its tokens through `spending.record` (#45)."""

    def test_they_count_toward_the_organizations_tokens(self):
        with self.limited(tokens_per_organization_per_month=1000), \
                self.provider(FakeProvider(QUESTION)) as fake, self.on(2026, 11, 3, 9):
            spending.record(self.organization(), Usage(900, 100))
            self.refused_turn("Hello", None)

        self.assertEqual(fake.asked, [])

    def test_they_do_not_count_toward_the_persons_turns(self):
        with self.limited(turns_per_person_per_day=1), \
                self.provider(FakeProvider(QUESTION)) as fake, self.on(2026, 11, 3, 9):
            for _ in range(3):
                spending.record(self.organization(), Usage(10, 10))
            self.say("Hello")

        self.assertEqual(len(fake.asked), 1)

    def test_a_turn_with_a_fix_attempt_records_both_calls_and_counts_one_turn(self):
        with self.limited(turns_per_person_per_day=2), \
                self.provider(FakeProvider(fenced(BROKEN), fenced(a_mod()), QUESTION)) as fake, \
                self.on(2026, 11, 3, 9):
            page = self.say("Write it")
            self.say("Thanks", page)

        self.assertEqual(len(fake.asked), 3)
        with tenancy.acting_as(organization=self.organization()):
            self.assertEqual(TokenUsage.objects.get().tokens, 3 * Usage(100, 20).total)


class FailedCalls(SpendingTest):
    """A call that fails, or is refused, after the provider has reported its
    tokens still spent them."""

    def test_the_tokens_a_failed_call_reported_are_recorded(self):
        failed = ProviderError("The LLM declined to answer that.", usage=Usage(300, 40))
        with self.provider(FakeProvider(failed)), self.on(2026, 11, 3, 9):
            page = self.say("Hello")

        self.assertIn("declined", page)
        with tenancy.acting_as(organization=self.organization()):
            self.assertEqual(TokenUsage.objects.get().tokens, 340)

    def test_a_failure_with_no_tokens_reported_records_none(self):
        with self.provider(FakeProvider(ProviderError("Busy."))), self.on(2026, 11, 3, 9):
            self.say("Hello")

        with tenancy.acting_as(organization=self.organization()):
            self.assertFalse(TokenUsage.objects.exists())


class KeptPerOrganization(SpendingTest):
    def test_usage_is_hidden_from_other_organizations_by_the_database(self):
        mine = self.organization()
        spending.record(mine, Usage(70, 30))
        theirs = self.another_organization()

        with tenancy.acting_as(organization=theirs):
            self.assertEqual(TokenUsage.objects.count(), 0)
        with tenancy.acting_as(organization=mine):
            self.assertEqual(TokenUsage.objects.get().tokens, 100)
        with tenancy.acting_as():
            self.assertEqual(TokenUsage.objects.count(), 0)

    def test_a_row_cannot_be_written_into_another_organization(self):
        mine = self.organization()
        theirs = self.another_organization()

        with self.assertRaises(ProgrammingError), transaction.atomic():
            with tenancy.acting_as(organization=theirs):
                TokenUsage.objects.create(organization_id=mine, month=date(2026, 11, 1),
                                          tokens=1)


@override_settings(OPEN_SIGN_UP=True)
class RecordingOutsideARequestsTransaction(TransactionTestCase):
    """A turn streams after its request's transaction has ended, so its
    tokens are recorded with no transaction open."""

    def test_the_tokens_are_kept(self):
        sign_in("mira@example.com")
        with tenancy.acting_as(user=User.objects.get(email="mira@example.com")):
            organization = Membership.objects.get().organization_id

        spending.record(organization, Usage(70, 30))
        spending.record(organization, Usage(1, 2))

        with tenancy.acting_as(organization=organization):
            self.assertEqual(TokenUsage.objects.get().tokens, 103)


class RevisingADraft(SpendingTest):
    """A revise Interview spends from the same limits as a new-Mod one."""

    def test_its_turns_count_and_a_paused_one_offers_its_own_paste_path(self):
        self.submit_mod(a_mod())
        revise = f"{self.mod_page(NEW)}interview/"
        with self.limited(turns_per_person_per_day=1, tokens_per_organization_per_month=100), \
                self.provider(FakeProvider(QUESTION)) as fake, self.on(2026, 11, 3, 9):
            first = self.sam.post(revise, {"said": "Hello", "transcript": ""})
            b"".join(first.streaming_content)
            refused = self.sam.post(revise, {"said": "More", "transcript": ""})
            self.assertFalse(refused.streaming)

        self.assertEqual(len(fake.asked), 1)
        self.assertContains(refused, f'href="{self.mod_page(NEW)}revise/"')
        with tenancy.acting_as(organization=self.organization()):
            self.assertEqual(TokenUsage.objects.get().tokens, 120)


class WritingAReport(SpendingTest):
    """A report Interview spends from the same limits as the Mod ones."""

    def test_its_turns_count_and_a_paused_one_offers_pasting_a_report(self):
        report = f"{self.mod_page('storm-moon-vigil')}report/"
        with self.limited(turns_per_person_per_day=1), \
                self.provider(FakeProvider(QUESTION)) as fake, self.on(2026, 11, 3, 9):
            first = self.rhea.post(f"{report}interview/", {"transcript": ""})
            page = b"".join(first.streaming_content).decode()
            refused = self.rhea.post(f"{report}interview/",
                                     {"said": "More", "transcript": hidden(page, "transcript")})
            self.assertFalse(refused.streaming)

        self.assertEqual(len(fake.asked), 1)
        self.assertContains(refused, "This Interview is paused.")
        self.assertContains(refused, f'href="{report}"')
        self.assertContains(refused, ">More</textarea>")
