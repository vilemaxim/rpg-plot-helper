"""Revising a sent-back draft in an Interview, through web requests, with a
fake provider in place of the real one: the tests never call an LLM."""

import html
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

import plotcanon

from canon import access
from canon.test_approving import DAUGHTER
from canon.test_mod_submissions import NEW, a_mod
from canon.test_resolving import WARRANT
from interviews import config
from interviews.providers import Message, ProviderError
from interviews.test_interviews import (FIXING, QUESTION, SETTINGS, FakeProvider,
                                        InterviewTest, fenced, file_in, hidden)

REASON = "The smuggler is dead; rewrite around his partner."


class ReviseInterviewTest(InterviewTest):
    def revise_interview(self, mod):
        return f"{self.mod_page(mod)}interview/"

    def reading_all_but(self, narrowed):
        """The person reads what `narrowed` leaves of what they read now."""
        everything = access.readable_documents
        return mock.patch.object(access, "readable_documents",
                                 lambda world, person: narrowed(everything(world, person)))

    def begin(self, mod, by=None):
        """Begin the revise Interview of `mod`: the LLM speaks first."""
        response = (by or self.mira).post(self.revise_interview(mod), {"transcript": ""})
        self.assertEqual(response.status_code, 200)
        return b"".join(response.streaming_content).decode()

    def say_about(self, mod, text, page=None, by=None):
        """Send the person's answer in the revise Interview of `mod`, and read
        the whole streamed page back."""
        transcript = hidden(page, "transcript") if page else ""
        response = (by or self.mira).post(self.revise_interview(mod),
                                          {"said": text, "transcript": transcript or ""})
        self.assertEqual(response.status_code, 200)
        return b"".join(response.streaming_content).decode()


class RevisingADraftInAnInterview(ReviseInterviewTest):
    def test_the_first_prompt_holds_the_draft_the_reason_and_each_open_flag(self):
        self.send_back(WARRANT, reason=REASON)
        draft = self.stored(WARRANT).text
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(WARRANT)

        system = fake.asked[0][0]
        self.assertIn(draft, system)
        self.assertIn(REASON, system)

    def test_each_open_flag_is_in_the_first_prompt_with_the_feature_it_touches(self):
        flags = self.flags_on(DAUGHTER)
        self.assertTrue(flags)
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(DAUGHTER)

        system = fake.asked[0][0]
        for flag in flags:
            self.assertIn(flag.change.summary, system)
            self.assertIn(f"On `{flag.change.entity}`", system)

    def test_a_flag_on_a_feature_the_person_may_not_read_is_left_out(self):
        hidden, *kept = self.flags_on(WARRANT)
        self.assertTrue(kept)
        self.assertNotIn(hidden.change.entity, [flag.change.entity for flag in kept])
        self.send_back(WARRANT, reason=REASON)
        with self.provider(FakeProvider(QUESTION)) as fake, self.reading_all_but(
                lambda documents: documents.exclude(slug=hidden.change.entity)):
            self.begin(WARRANT)

        system = fake.asked[0][0]
        self.assertNotIn(f"On `{hidden.change.entity}`", system)
        for flag in kept:
            self.assertIn(f"On `{flag.change.entity}`", system)

    def test_a_flag_from_a_report_the_person_may_not_read_is_left_out(self):
        flags = self.flags_on(DAUGHTER)
        report = flags[0].change.report_id
        with self.provider(FakeProvider(QUESTION)) as fake, self.reading_all_but(
                lambda documents: documents.exclude(pk=report)):
            self.begin(DAUGHTER)

        system = fake.asked[0][0]
        for flag in flags:
            shown = f"On `{flag.change.entity}`" in system
            self.assertEqual(shown, flag.change.report_id != report, flag.change.entity)

    def test_a_draft_the_person_may_not_read_has_no_revise_interview(self):
        self.send_back(WARRANT, reason=REASON)
        with self.provider(FakeProvider(QUESTION)) as fake, self.reading_all_but(
                lambda documents: documents.exclude(slug=WARRANT)):
            self.assertEqual(self.mira.get(self.revise_interview(WARRANT)).status_code, 404)
            response = self.mira.post(self.revise_interview(WARRANT),
                                      {"said": "Hello", "transcript": ""})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(fake.asked, [])

    def test_the_flags_its_send_back_resolved_are_in_the_first_prompt(self):
        flags = self.flags_on(WARRANT)
        self.assertTrue(flags)
        self.send_back(WARRANT, reason=REASON)
        self.assertFalse(self.flags_on(WARRANT))
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(WARRANT)

        system = fake.asked[0][0]
        for flag in flags:
            self.assertIn(flag.change.summary, system)
            self.assertIn(f"On `{flag.change.entity}`", system)

    def test_a_flag_dismissed_before_the_send_back_is_not(self):
        dismissed, *kept = self.flags_on(WARRANT)
        self.assertTrue(kept)
        self.assertNotIn(dismissed.change.entity, [flag.change.entity for flag in kept])
        self.dismiss(dismissed)
        self.send_back(WARRANT, reason=REASON)
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(WARRANT)

        system = fake.asked[0][0]
        self.assertNotIn(f"On `{dismissed.change.entity}`", system)
        for flag in kept:
            self.assertIn(f"On `{flag.change.entity}`", system)

    def test_submitting_replaces_the_draft_through_the_revise_path(self):
        self.send_back(WARRANT, reason=REASON)
        draft = self.stored(WARRANT).text
        revised = draft.replace("duration_est: 90", "duration_est: 120")
        with self.provider(FakeProvider(fenced(revised))):
            page = self.begin(WARRANT)
            file = re.search(r'<textarea name="text"[^>]*>\n?(.*?)</textarea>', page, re.S)
            self.assertEqual(html.unescape(file.group(1)), revised)
            response = self.mira.post(f"{self.revise_interview(WARRANT)}submit/",
                                      {"text": revised, "transcript": hidden(page, "transcript")},
                                      follow=True)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(WARRANT))
        self.assertEqual(self.stored(WARRANT).text, revised)
        page = self.mira.get(self.mod_page(WARRANT))
        self.assertContains(page, REASON)
        self.assertTrue(self.flags_on(WARRANT, open_only=False))

    def test_a_revision_with_another_id_is_refused_and_keeps_the_conversation(self):
        self.submit_mod(a_mod())
        other = a_mod(slug="another-mod")
        # Submitted with its errors, once the fix attempts are used up.
        with self.provider(FakeProvider(QUESTION, fenced(other)), max_fix_attempts=0):
            page = self.say_about(NEW, "Write it", self.begin(NEW, by=self.sam), by=self.sam)
            response = self.sam.post(f"{self.revise_interview(NEW)}submit/",
                                     {"text": other, "transcript": hidden(page, "transcript")})

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "A revision keeps its Mod&#x27;s id.")
        self.assertContains(response, "Write it")
        self.assertEqual(self.stored(NEW).text, a_mod())
        self.assertFalse(self.exists("another-mod"))

    def test_the_drafts_page_offers_the_interview_first_and_the_paste_path_beside_it(self):
        self.submit_mod(a_mod())
        with self.provider(FakeProvider()):
            page = self.sam.get(self.mod_page(NEW))

        self.assertContains(page, f'href="{self.revise_interview(NEW)}"')
        self.assertContains(page, f'href="{self.mod_page(NEW)}revise/"')

    def test_the_paste_path_is_reachable_from_the_interview(self):
        self.submit_mod(a_mod())
        with self.provider(FakeProvider(QUESTION)):
            start = self.sam.get(self.revise_interview(NEW))
            page = self.begin(NEW, by=self.sam)

        self.assertContains(start, f'href="{self.mod_page(NEW)}revise/"')
        self.assertIn(f'href="{self.mod_page(NEW)}revise/"', page)

    def test_a_mod_that_is_not_a_draft_has_no_revise_interview(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            response = self.mira.get(self.revise_interview(WARRANT), follow=True)

        self.assertContains(response, "only a draft")
        self.assertEqual(fake.asked, [])


OPENING = "The Plot Master sent this back because the smuggler is dead."


class TheLlmSpeaksFirst(ReviseInterviewTest):
    """A revise Interview opens with plotcanon's first message, sent on the
    person's behalf, so the LLM starts on the send-back reason and the Flags.
    The person never sees that message as theirs."""

    def setUp(self):
        super().setUp()
        self.send_back(WARRANT, reason=REASON)

    def test_a_new_one_offers_to_begin_instead_of_asking_for_an_answer(self):
        with self.provider(FakeProvider()) as fake:
            page = self.mira.get(self.revise_interview(WARRANT))

        self.assertContains(page, "Begin")
        self.assertNotContains(page, 'name="said"')
        self.assertEqual(fake.asked, [])

    def test_beginning_sends_plotcanons_opener_and_streams_the_llms_first_turn(self):
        with self.provider(FakeProvider(OPENING)) as fake:
            page = self.begin(WARRANT)

        self.assertEqual(fake.asked[0][1], [Message("user", plotcanon.interview_revise_opener())])
        self.assertIn(OPENING, page)
        self.assertIn('name="said"', page)

    def test_the_opener_is_never_shown_as_the_persons(self):
        opener = html.escape(plotcanon.interview_revise_opener())
        with self.provider(FakeProvider(OPENING, QUESTION)) as fake:
            first = self.begin(WARRANT)
            later = self.say_about(WARRANT, "Rewrite it around the partner", first)
            again = self.mira.get(self.revise_interview(WARRANT)).content.decode()

        for page in (first, later, again):
            self.assertNotIn(opener[:40], page)
            self.assertEqual(re.search(r'class="turn (\w+)"', page).group(1), "llm")
        self.assertIn(OPENING, again)
        self.assertEqual([m.text for m in fake.asked[1][1]],
                         [plotcanon.interview_revise_opener(), OPENING,
                          "Rewrite it around the partner"])

    def test_an_answer_sent_before_it_has_begun_is_not_the_first_message(self):
        with self.provider(FakeProvider(OPENING)) as fake:
            self.say_about(WARRANT, "Hello")

        self.assertEqual(fake.asked[0][1], [Message("user", plotcanon.interview_revise_opener())])

    def test_a_failed_opening_offers_to_begin_again(self):
        with self.provider(FakeProvider(ProviderError("The LLM is busy."))):
            page = self.begin(WARRANT)

        self.assertIn("The LLM is busy.", page)
        self.assertIn("Begin", page)
        self.assertNotIn('name="said"', page)
        self.assertEqual(hidden(page, "transcript"), "")


class FixingTheLlmsRevision(ReviseInterviewTest):
    def setUp(self):
        super().setUp()
        self.send_back(WARRANT, reason=REASON)
        self.draft = self.stored(WARRANT).text
        self.revised = self.draft.replace("duration_est: 90", "duration_est: 120")
        self.broken = self.revised.replace("type: mod", "type: nonsense")

    def test_a_revision_with_errors_goes_back_to_the_llm_and_the_person_sees_the_fixed_one(self):
        with self.provider(FakeProvider(fenced(self.broken), fenced(self.revised))) as fake:
            page = self.begin(WARRANT)

        self.assertEqual(len(fake.asked), 2)
        sent = fake.asked[1][1]
        self.assertEqual([m.role for m in sent], ["user", "assistant", "user"])
        self.assertIn("nonsense", sent[2].text)
        self.assertEqual(page.count(FIXING), 1)
        self.assertEqual(file_in(page), self.revised)
        self.assertNotIn("nonsense", page)

    def test_it_is_checked_as_a_revision_of_its_draft_so_another_id_goes_back(self):
        other = self.revised.replace(f"id: {WARRANT}", "id: another-mod")
        with self.provider(FakeProvider(fenced(other), fenced(self.revised))) as fake:
            page = self.begin(WARRANT)

        self.assertEqual(len(fake.asked), 2)
        self.assertIn("keeps its Mod's id", fake.asked[1][1][2].text)
        self.assertEqual(file_in(page), self.revised)

    def test_a_good_revision_is_not_sent_back(self):
        with self.provider(FakeProvider(fenced(self.revised))) as fake:
            page = self.begin(WARRANT)

        self.assertEqual(len(fake.asked), 1)
        self.assertNotIn(FIXING, page)
        self.assertEqual(self.stored(WARRANT).text, self.draft)

    def test_after_max_fix_attempts_the_person_sees_the_revision_and_its_errors(self):
        with self.provider(FakeProvider(*[fenced(self.broken)] * 3), 1) as fake:
            page = self.begin(WARRANT)

        self.assertEqual(len(fake.asked), 2)
        self.assertEqual(file_in(page), self.broken)
        self.assertIn("still has errors", page)


class WhoMayReviseInAnInterview(ReviseInterviewTest):
    def setUp(self):
        super().setUp()
        self.submit_mod(a_mod())

    def test_another_mod_writer_cannot_open_or_submit_it(self):
        kay = self.join("kay@example.com")
        self.give("kay@example.com", "mod-writer")
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.assertEqual(kay.get(self.mod_page(NEW)).status_code, 404)
            self.assertEqual(kay.get(self.revise_interview(NEW)).status_code, 404)
            response = kay.post(self.revise_interview(NEW), {"said": "Hello", "transcript": ""})
            self.assertEqual(response.status_code, 404)
            response = kay.post(f"{self.revise_interview(NEW)}submit/",
                                {"text": a_mod(title="Mine Now")})
            self.assertEqual(response.status_code, 404)

        self.assertEqual(fake.asked, [])
        self.assertEqual(self.stored(NEW).text, a_mod())

    def test_a_mod_runner_cannot(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.assertEqual(self.rhea.get(self.revise_interview(NEW)).status_code, 404)
            response = self.rhea.post(self.revise_interview(NEW),
                                      {"said": "Hello", "transcript": ""})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(fake.asked, [])

    def test_a_mod_writer_cannot_revise_an_imported_draft_in_one(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.assertEqual(self.sam.get(self.revise_interview(DAUGHTER)).status_code, 404)

        self.assertEqual(fake.asked, [])

    def test_its_mod_writer_and_a_plot_master_may(self):
        with self.provider(FakeProvider(QUESTION, QUESTION)):
            self.assertIn(html.escape(QUESTION), self.begin(NEW, by=self.sam))
            self.assertIn(html.escape(QUESTION), self.begin(NEW, by=self.mira))


class WhenReviseInterviewsAreOff(ReviseInterviewTest):
    """`revise-mod` off and `new-mod` on: revising works exactly as before."""

    def setUp(self):
        super().setUp()
        self.submit_mod(a_mod())
        fake = FakeProvider()
        self.only_new = mock.patch.object(
            config, "llm_for",
            lambda kind, loaded=None: config.Llm(SETTINGS, fake) if kind == "new-mod" else None)
        self.only_new.start()
        self.addCleanup(self.only_new.stop)

    def test_the_drafts_page_offers_only_the_paste_path(self):
        page = self.sam.get(self.mod_page(NEW))

        self.assertNotContains(page, f'href="{self.revise_interview(NEW)}"')
        self.assertContains(page, f'href="{self.mod_page(NEW)}revise/"')
        self.assertContains(self.sam.get(self.first_world), f'href="{self.interview}"')

    def test_the_interview_leads_to_the_paste_path(self):
        self.assertRedirects(self.sam.get(self.revise_interview(NEW)),
                             f"{self.mod_page(NEW)}revise/")
        self.assertEqual(self.sam.post(f"{self.revise_interview(NEW)}submit/",
                                       {"text": a_mod()}).status_code, 404)

    def test_revising_by_pasting_works_as_before(self):
        revised = a_mod(title="The Lamplighter's Last Debt")

        response = self.revise(NEW, revised)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertEqual(self.stored(NEW).text, revised)


class TheCommittedConfig(SimpleTestCase):
    def test_it_sets_up_a_revise_interview_alongside_the_new_mod_one(self):
        loaded = config.load(Path(settings.BASE_DIR) / "interviews.toml")

        revise = loaded.interviews["revise-mod"]
        self.assertEqual(revise.provider, "anthropic")
        self.assertEqual(revise.model, "claude-opus-5-5")
        self.assertEqual(revise.effort, "high")
        self.assertEqual(revise.max_tokens, 32000)
        self.assertEqual(revise.max_fix_attempts, 3)
