"""World review (#61): the plot team runs a review of the whole World,
suggested after each Event. Through web requests, with a fake provider in
place of the real one: the tests never call an LLM. The sample World's
Events have all ended; the latest is Second Lantern, on 11 July 2026."""

import datetime
from contextlib import contextmanager
from datetime import UTC
from unittest import mock

import plotcanon

from accounts.models import User
from canon.storing import files_of
from canon.tests import CanonTest
from interviews import config, world_reviewing
from interviews.models import TokenUsage, WorldReview
from interviews.providers import ProviderError, Usage
from interviews.test_interviews import FakeProvider
from organizations import tenancy
from organizations.models import Membership, World

REVIEWING = config.WorldReviewSettings(provider="anthropic", model="fake-model",
                                       context_tokens=1_000_000)

NOTICE = "Second Lantern ended on 11 July 2026. Run a World review?"

REVIEW = """\
## State of the World

The lanterns are lit and the tide is turning.

## Drift

- `harrow-dunmore`: his debt to the guild is never mentioned after Low Tide.

## Watch list

None.

## Weaving

- `the-tidemother`: bring her back at the next Tideward Event.

## Coverage

None.
"""


class WorldReviewTest(CanonTest):
    """Mira is Organization Admin and Plot Master of a World holding the
    sample World. Pat is a Plot Master and Sam a Mod Writer there."""

    def world_files(self):
        """The World Mira imports."""
        return plotcanon.sample_world()

    def setUp(self):
        super().setUp()
        self.import_files(self.world_files())
        self.pat = self.join("pat@example.com")
        self.give("pat@example.com", "plot-master")
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        self.reviews = f"{self.first_world}world-reviews/"

    @contextmanager
    def reviewing(self, fake, **settings):
        """World review is on, with `fake` as its LLM."""
        chosen = config.WorldReviewSettings(**{**REVIEWING.__dict__, **settings})
        with mock.patch.object(config, "world_review_llm",
                               lambda loaded=None: config.Llm(chosen, fake)):
            yield fake

    @contextmanager
    def not_reviewing(self):
        with mock.patch.object(config, "world_review_llm", lambda loaded=None: None):
            yield

    def in_world(self):
        user = User.objects.get(email="mira@example.com")
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get().organization_id
        return tenancy.acting_as(user=user, organization=organization)

    def run_review(self, by=None):
        return (by or self.mira).post(f"{self.reviews}run/", follow=True)

    def dismiss(self, event="e04-second-lantern", by=None):
        return (by or self.mira).post(f"{self.reviews}dismiss/", {"event": event}, follow=True)

    @contextmanager
    def on(self, day):
        """As if today were `day`."""
        with mock.patch.object(world_reviewing, "today", lambda: day):
            yield

    def kept(self):
        with self.in_world():
            return list(WorldReview.objects.all())

    def plot_teams_world(self):
        with self.in_world():
            return files_of(World.objects.get())


class TheNotice(WorldReviewTest):
    def test_the_plot_team_sees_it_once_the_latest_event_has_ended(self):
        with self.reviewing(FakeProvider()):
            for browser in (self.mira, self.pat):
                self.assertContains(browser.get(self.first_world), NOTICE)

    def test_a_mod_writer_does_not(self):
        with self.reviewing(FakeProvider()):
            self.assertNotContains(self.sam.get(self.first_world), "World review")

    def test_with_no_config_entry_there_is_no_notice_and_no_way_to_run_one(self):
        with self.not_reviewing():
            world = self.mira.get(self.first_world)
            reviews = self.mira.get(self.reviews)
            refused = self.run_review()

        self.assertNotContains(world, "Run a World review?")
        self.assertNotContains(world, self.reviews)
        self.assertNotContains(reviews, f"{self.reviews}run/")
        self.assertContains(refused, "World review is not set up on this site.")
        self.assertEqual(self.kept(), [])

    def test_not_before_the_events_last_day_has_passed(self):
        with self.reviewing(FakeProvider()), self.on(datetime.date(2026, 7, 11)):
            page = self.mira.get(self.first_world)

        self.assertNotContains(page, "Second Lantern ended")
        self.assertContains(page, "Storm Moon ended on 21 June 2026. Run a World review?")

    def test_only_the_latest_ended_event_is_suggested(self):
        with self.reviewing(FakeProvider()):
            page = self.mira.get(self.first_world)

        self.assertNotContains(page, "Storm Moon ended")
        self.assertNotContains(page, "First Lantern ended")

    def test_an_interlude_after_it_does_not_take_its_place(self):
        self.mira.post(f"{self.first_world}add-interlude/", {
            "name": "The Quiet Month", "after": "e04-second-lantern",
            "campaign": "lanternlight", "in_world": "the month after the dark",
            "real_date": "2026-08-01"}, follow=True)

        with self.reviewing(FakeProvider()):
            page = self.mira.get(self.first_world)

        self.assertContains(page, NOTICE)
        self.assertNotContains(page, "The Quiet Month ended")

    def test_running_one_clears_it(self):
        with self.reviewing(FakeProvider(REVIEW)):
            self.run_review(by=self.pat)
            page = self.mira.get(self.first_world)

        self.assertNotContains(page, "Run a World review?")

    def test_dismissing_it_clears_it_for_that_event_only(self):
        with self.reviewing(FakeProvider()), self.on(datetime.date(2026, 7, 11)):
            self.dismiss("e03-storm-moon")
            self.assertNotContains(self.mira.get(self.first_world), "Run a World review?")
        with self.reviewing(FakeProvider()):
            self.assertContains(self.pat.get(self.first_world), NOTICE)

    def test_a_mod_writer_cannot_dismiss_it(self):
        with self.reviewing(FakeProvider()):
            refused = self.dismiss(by=self.sam)

            self.assertEqual(refused.status_code, 404)
            self.assertContains(self.mira.get(self.first_world), NOTICE)


class ACancelledEvent(WorldReviewTest):
    def world_files(self):
        files = plotcanon.sample_world()
        path = "canon/events/e04-second-lantern.md"
        files[path] = files[path].replace("status: running", "status: cancelled")
        return files

    def test_is_never_suggested(self):
        with self.reviewing(FakeProvider()):
            page = self.mira.get(self.first_world)

        self.assertNotContains(page, "Second Lantern ended")
        self.assertContains(page, "Storm Moon ended on 21 June 2026. Run a World review?")


class RunningOne(WorldReviewTest):
    def test_a_plot_master_runs_one_and_reads_its_sections(self):
        with self.reviewing(FakeProvider(REVIEW)) as fake:
            page = self.run_review(by=self.pat)

        self.assertEqual(len(fake.asked), 1)
        kept = self.kept()[0]
        self.assertEqual(page.redirect_chain[-1][0], f"{self.reviews}{kept.pk}/")
        for heading in plotcanon.WORLD_REVIEW_SECTIONS:
            self.assertContains(page, f"<h3>{heading}</h3>")
        self.assertContains(page, "<code>harrow-dunmore</code>: his debt to the guild")
        self.assertContains(page, "by pat@example.com")
        self.assertContains(page, "fake-model")
        self.assertEqual(kept.event, "e04-second-lantern")

    def test_the_llm_is_given_plotcanons_instructions_for_the_whole_world(self):
        files = self.plot_teams_world()
        with self.reviewing(FakeProvider(REVIEW)) as fake:
            self.run_review(by=self.pat)

        system, messages = fake.asked[0]
        self.assertEqual(system, plotcanon.world_review_instructions(
            "web", world=files, findings=list(plotcanon.load_world(files).findings)))
        self.assertIn(files["canon/npcs/harrow-dunmore.md"].split("## GM Notes")[1]
                      .strip().splitlines()[0], system)
        self.assertEqual([m.role for m in messages], ["user"])

    def test_it_can_be_run_at_any_time_not_only_when_suggested(self):
        with self.reviewing(FakeProvider(REVIEW, REVIEW)):
            self.run_review()
            self.run_review()

        self.assertEqual(len(self.kept()), 2)

    def test_earlier_reviews_are_kept_as_history(self):
        with self.reviewing(FakeProvider(REVIEW, REVIEW)):
            self.run_review(by=self.pat)
            self.run_review()
            page = self.mira.get(self.reviews)

        earlier, latest = sorted(self.kept(), key=lambda review: review.pk)
        self.assertContains(page, f"{self.reviews}{earlier.pk}/")
        self.assertContains(page, f"{self.reviews}{latest.pk}/")
        self.assertContains(page, "by pat@example.com")
        self.assertEqual(self.mira.get(f"{self.reviews}{earlier.pk}/").status_code, 200)

    def test_only_the_plot_team_may_run_or_read_them(self):
        with self.reviewing(FakeProvider(REVIEW)) as fake:
            self.run_review()
            kept = self.kept()[0]
            for address in (self.reviews, f"{self.reviews}{kept.pk}/"):
                with self.subTest(address):
                    self.assertEqual(self.sam.get(address).status_code, 404)
            self.assertEqual(self.sam.post(f"{self.reviews}run/").status_code, 404)

        self.assertEqual(len(fake.asked), 1)

    def test_a_provider_failure_keeps_nothing_and_says_so(self):
        with self.reviewing(FakeProvider(ProviderError("The LLM is busy just now."))):
            page = self.run_review()

        self.assertContains(page, "was not reviewed")
        self.assertContains(page, "busy")
        self.assertEqual(self.kept(), [])


class TooLarge(WorldReviewTest):
    def test_a_world_that_does_not_fit_the_model_is_refused_before_anything_is_spent(self):
        with self.reviewing(FakeProvider(REVIEW), context_tokens=40_000) as fake:
            page = self.run_review()

        self.assertContains(page, "This World is too large for a World review with the "
                                  "configured model")
        self.assertEqual(fake.asked, [])
        self.assertEqual(self.kept(), [])

    def test_so_is_one_the_provider_says_is_too_long(self):
        too_long = ProviderError("The LLM's provider turned the request down: prompt is too "
                                 "long: 250000 tokens > 200000 maximum")
        with self.reviewing(FakeProvider(too_long)):
            page = self.run_review()

        self.assertContains(page, "This World is too large for a World review with the "
                                  "configured model")
        self.assertEqual(self.kept(), [])


class Spending(WorldReviewTest):
    @contextmanager
    def capped_at(self, tokens):
        loaded = config.Config(limits=config.Limits(tokens_per_organization_per_month=tokens))
        with mock.patch.object(config, "current", lambda: loaded), \
                mock.patch("interviews.spending._now",
                           return_value=datetime.datetime(2026, 11, 3, 9, tzinfo=UTC)):
            yield

    def used(self):
        with self.in_world():
            return TokenUsage.objects.values_list("tokens", flat=True).first() or 0

    def test_a_runs_tokens_count_toward_the_cap(self):
        with self.capped_at(1000), self.reviewing(FakeProvider(REVIEW)):
            self.run_review()

        self.assertEqual(self.used(), 120)

    def test_at_the_cap_it_does_not_run_and_the_page_says_why(self):
        with self.capped_at(120), self.reviewing(FakeProvider(REVIEW, REVIEW)) as fake:
            self.run_review()
            page = self.run_review()

        self.assertEqual(len(fake.asked), 1)
        self.assertEqual(len(self.kept()), 1)
        self.assertContains(page, "was not reviewed")
        self.assertContains(page, "used this month&#x27;s tokens for World reviews")

    def test_a_failed_runs_tokens_count_all_the_same(self):
        with self.capped_at(1000), self.reviewing(
                FakeProvider(ProviderError("busy", usage=Usage(30, 0)))):
            self.run_review()

        self.assertEqual(self.used(), 30)
