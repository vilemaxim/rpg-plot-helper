"""An Interview's transcript is kept in Postgres (#46): it survives a reload,
goes on Submit or after 30 days without activity, is never exported, and only
its person may read it. Through web requests, with a fake provider."""

import html
from datetime import timedelta

from django.db import IntegrityError, ProgrammingError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from canon.test_exporting import unzipped
from canon.test_mod_submissions import NEW, a_mod
from interviews.models import Interview
from interviews.providers import ProviderError
from canon.test_approving import DAUGHTER
from canon.test_resolving import WARRANT
from interviews.test_interviews import QUESTION, FakeProvider, InterviewTest, fenced, hidden
from interviews.test_revise_interviews import REASON, ReviseInterviewTest
from organizations import tenancy
from organizations.models import Membership, World
from organizations.tests import sign_in

ANSWER = "A debt owed to a lamplighter, for new players, at First Lantern."


class ResumingAnInterview(InterviewTest):
    def test_reloading_mid_interview_shows_every_turn_and_carries_on(self):
        with self.provider(FakeProvider(QUESTION, "And when does it run?", "Thanks")) as fake:
            page = self.say("Hello")
            self.say(ANSWER, page)

            reloaded = self.sam.get(self.interview).content.decode()
            for said in ("Hello", QUESTION, ANSWER, "And when does it run?"):
                self.assertIn(html.escape(said), reloaded)

            self.say("At the spring event", reloaded)

        self.assertEqual([m.text for m in fake.asked[2][1]],
                         ["Hello", QUESTION, ANSWER, "And when does it run?",
                          "At the spring event"])

    def test_it_can_be_abandoned_to_start_fresh(self):
        with self.provider(FakeProvider(QUESTION, "A new question")) as fake:
            page = self.say("Hello")
            reloaded = self.sam.get(self.interview)
            self.assertContains(reloaded, f'action="{self.interview}start-over/"')

            response = self.sam.post(f"{self.interview}start-over/",
                                     {"transcript": hidden(page, "transcript")})
            self.assertRedirects(response, self.interview)
            fresh = self.sam.get(self.interview)
            self.assertNotContains(fresh, html.escape(QUESTION))
            self.assertEqual(hidden(fresh.content.decode(), "transcript"), "")

            self.say("Something else", fresh.content.decode())

        self.assertEqual([m.text for m in fake.asked[1][1]], ["Something else"])

    def test_a_file_already_given_is_shown_again_with_submit(self):
        with self.provider(FakeProvider(fenced(a_mod()))):
            self.say("Write it")
            reloaded = self.sam.get(self.interview)

        self.assertContains(reloaded, 'name="text"')
        self.assertContains(reloaded, f'action="{self.interview}submit/"')


class AFailedTurn(InterviewTest):
    def test_leaves_the_stored_transcript_unchanged_and_can_be_tried_again(self):
        with self.provider(FakeProvider(QUESTION, ProviderError("The LLM is busy."),
                                        "And when does it run?")) as fake:
            first = self.say("Hello")
            failed = self.say(ANSWER, first)
            self.assertIn("That didn't go through. Try again.", failed)
            self.assertIn(f'href="{self.form}"', failed)

            reloaded = self.sam.get(self.interview).content.decode()
            self.assertIn(html.escape(QUESTION), reloaded)
            self.assertNotIn(html.escape(ANSWER), reloaded)
            self.assertNotIn("Half a thou", reloaded)

            self.say(ANSWER, failed)
            reloaded = self.sam.get(self.interview).content.decode()

        self.assertEqual([m.text for m in fake.asked[2][1]], ["Hello", QUESTION, ANSWER])
        self.assertIn(html.escape("And when does it run?"), reloaded)

    def test_a_first_turn_that_fails_keeps_no_interview(self):
        with self.provider(FakeProvider(ProviderError("The LLM is busy."))):
            failed = self.say("Hello")
            reloaded = self.sam.get(self.interview).content.decode()

        self.assertEqual(hidden(failed, "transcript"), "")
        self.assertNotIn("Hello", reloaded.split("<h1>", 1)[1])


class WhenAnInterviewGoes(InterviewTest):
    def test_submitting_its_mod_deletes_it(self):
        with self.provider(FakeProvider(fenced(a_mod()))):
            page = self.say("Write it")
            self.sam.post(f"{self.interview}submit/",
                          {"text": a_mod(), "transcript": hidden(page, "transcript")})
            fresh = self.sam.get(self.interview).content.decode()
            stale = self.sam.post(self.interview, {"said": "More",
                                                   "transcript": hidden(page, "transcript")})

        self.assertTrue(self.exists(NEW))
        self.assertNotIn("Write it", fresh.split("<h1>", 1)[1])
        self.assertEqual(hidden(fresh, "transcript"), "")
        self.assertEqual(stale.status_code, 400)

    def test_a_refused_submit_keeps_it(self):
        broken = a_mod(**{"type: mod": "type: nonsense"})
        with self.provider(FakeProvider(fenced(broken)), max_fix_attempts=0):
            page = self.say("Write it")
            self.sam.post(f"{self.interview}submit/",
                          {"text": broken, "transcript": hidden(page, "transcript")})
            reloaded = self.sam.get(self.interview)

        self.assertContains(reloaded, "Write it")

    def idle_for(self, days):
        """Sam's Interview, left `days` days without activity; then whether
        it is still there after the next Interview request."""
        with self.provider(FakeProvider(QUESTION)):
            self.say("Hello")
            with self.in_world():
                Interview.objects.update(active_at=timezone.now() - timedelta(days=days))
            return "Hello" in self.sam.get(self.interview).content.decode().split("<h1>", 1)[1]

    def test_thirty_days_without_activity_deletes_it(self):
        self.assertFalse(self.idle_for(30))

    def test_twenty_nine_days_without_activity_does_not(self):
        self.assertTrue(self.idle_for(29))

    def test_anyone_elses_interview_request_clears_idle_ones_too(self):
        with self.provider(FakeProvider(QUESTION)):
            self.say("Hello")
            with self.in_world():
                Interview.objects.update(active_at=timezone.now() - timedelta(days=31))
            self.mira.get(self.interview)
            with self.in_world():
                self.assertEqual(Interview.objects.count(), 0)


class WhoMayReadATranscript(InterviewTest):
    def test_a_world_export_holds_no_transcript(self):
        secret = "The lamplighter is secretly the Warden's sister"
        with self.provider(FakeProvider(QUESTION)):
            self.say(secret)
        files = unzipped(self.mira.get(f"{self.first_world}export/download/").content)

        self.assertTrue(files)
        for name, text in files.items():
            self.assertNotIn("lamplighter is secretly", text, name)
            self.assertNotIn("interview", name.lower())

    def test_a_plot_master_in_the_same_world_cannot_read_it_or_end_it(self):
        with self.provider(FakeProvider(QUESTION)):
            page = self.say("Hello, only for Sam")
            theirs = self.mira.get(self.interview)
            carried = self.mira.post(self.interview, {"said": "Peek",
                                                      "transcript": hidden(page, "transcript")})
            self.mira.post(f"{self.interview}start-over/",
                           {"transcript": hidden(page, "transcript")})
            still = self.sam.get(self.interview)

        self.assertNotContains(theirs, "only for Sam")
        self.assertEqual(hidden(theirs.content.decode(), "transcript"), "")
        self.assertEqual(carried.status_code, 400)
        self.assertContains(still, "only for Sam")

    def test_another_mod_writer_in_the_same_world_cannot_read_it(self):
        other = self.join("tess@example.com")
        self.give("tess@example.com", "mod-writer")
        with self.provider(FakeProvider(QUESTION)):
            self.say("Hello, only for Sam")
            theirs = other.get(self.interview)

        self.assertEqual(theirs.status_code, 200)
        self.assertNotContains(theirs, "only for Sam")


@override_settings(OPEN_SIGN_UP=True)
class TheDatabaseKeepsItInItsOrganization(TestCase):
    """Row-level security on Interviews, with no help from the app."""

    def setUp(self):
        sign_in("mira@example.com")
        sign_in("sam@example.com")
        self.mira = User.objects.get(email="mira@example.com")
        self.sam = User.objects.get(email="sam@example.com")
        with tenancy.acting_as(user=self.mira):
            self.miras_org = Membership.objects.get().organization_id
        with tenancy.acting_as(user=self.sam):
            self.sams_org = Membership.objects.get().organization_id
        with tenancy.acting_as(user=self.mira, organization=self.miras_org):
            self.miras_world = World.objects.get()
            Interview.objects.create(organization_id=self.miras_org, world=self.miras_world,
                                     person=self.mira, kind="new-mod",
                                     turns=[{"role": "user", "text": "Hello"}])

    def test_another_organization_sees_none(self):
        with tenancy.acting_as(user=self.sam, organization=self.sams_org):
            self.assertEqual(Interview.objects.count(), 0)
        with tenancy.acting_as():
            self.assertEqual(Interview.objects.count(), 0)

    def test_another_organization_cannot_change_or_delete_it(self):
        with tenancy.acting_as(user=self.sam, organization=self.sams_org):
            changed = Interview.objects.update(turns=[])
            deleted, _ = Interview.objects.all().delete()

        self.assertEqual((changed, deleted), (0, 0))
        with tenancy.acting_as(user=self.mira, organization=self.miras_org):
            self.assertEqual(Interview.objects.get().turns, [{"role": "user", "text": "Hello"}])

    def test_one_cannot_be_written_into_another_organization(self):
        with self.assertRaises(ProgrammingError), transaction.atomic():
            with tenancy.acting_as(user=self.sam, organization=self.sams_org):
                Interview.objects.create(organization_id=self.miras_org,
                                         world=self.miras_world, person=self.sam,
                                         kind="new-mod")

    def test_one_cannot_point_at_another_organizations_world(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            with tenancy.acting_as(user=self.sam, organization=self.sams_org):
                Interview.objects.create(organization_id=self.sams_org,
                                         world_id=self.miras_world.pk, person=self.sam,
                                         kind="new-mod")


class ARevisingInterview(ReviseInterviewTest):
    """A revise Interview (#47) is kept the same way, as its own kind, for
    its own draft."""

    def setUp(self):
        super().setUp()
        self.send_back(WARRANT, reason=REASON)

    def test_it_is_kept_as_a_revise_interview_of_its_draft_and_resumes(self):
        with self.provider(FakeProvider(QUESTION)):
            self.say_about(WARRANT, "Hello")
            reloaded = self.mira.get(self.revise_interview(WARRANT)).content.decode()
            other = self.mira.get(self.revise_interview(DAUGHTER)).content.decode()

        self.assertIn(html.escape(QUESTION), reloaded)
        self.assertNotIn(html.escape(QUESTION), other)
        with self.in_world():
            interview = Interview.objects.get()
        self.assertEqual(interview.kind, "revise-mod")
        self.assertEqual(interview.mod_id, self.stored(WARRANT).pk)

    def test_its_transcript_does_not_carry_over_to_a_new_mod_interview(self):
        with self.provider(FakeProvider(QUESTION)):
            page = self.say_about(WARRANT, "Hello")
            response = self.mira.post(self.interview, {"said": "More",
                                                       "transcript": hidden(page, "transcript")})

        self.assertEqual(response.status_code, 400)

    def test_submitting_the_revision_deletes_it(self):
        draft = self.stored(WARRANT).text
        revised = draft.replace("duration_est: 90", "duration_est: 120")
        with self.provider(FakeProvider(fenced(revised))):
            page = self.say_about(WARRANT, "Make it longer")
            self.mira.post(f"{self.revise_interview(WARRANT)}submit/",
                           {"text": revised, "transcript": hidden(page, "transcript")})

        self.assertEqual(self.stored(WARRANT).text, revised)
        with self.in_world():
            self.assertFalse(Interview.objects.exists())

    def test_it_can_be_started_over(self):
        with self.provider(FakeProvider(QUESTION)):
            page = self.say_about(WARRANT, "Hello")
            response = self.mira.post(f"{self.revise_interview(WARRANT)}start-over/",
                                      {"transcript": hidden(page, "transcript")})

        self.assertRedirects(response, self.revise_interview(WARRANT),
                             fetch_redirect_response=False)
        with self.in_world():
            self.assertFalse(Interview.objects.exists())
