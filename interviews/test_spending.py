"""Spend limits on Interviews (ADR-0008): turns per person per day and tokens
per Organization per month, set in `interviews.toml`. Through web requests,
with a fake provider; the tests never call an LLM."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest import mock

from interviews import config
from interviews.test_interviews import QUESTION, FakeProvider, InterviewTest, hidden


def at(*when):
    return datetime(*when, tzinfo=UTC)


class SpendingTest(InterviewTest):
    @contextmanager
    def limited(self, **limits):
        loaded = config.Config(limits=config.Limits(**limits))
        with mock.patch.object(config, "current", lambda: loaded):
            yield

    @contextmanager
    def on(self, *when):
        with mock.patch("django.utils.timezone.now", return_value=at(*when)):
            yield

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
