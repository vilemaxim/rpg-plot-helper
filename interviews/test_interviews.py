"""Writing a new Mod in an Interview, through web requests, with a fake
provider in place of the real one: the tests never call an LLM."""

import html
import re
from contextlib import contextmanager
from unittest import mock

import plotcanon

from canon import access
from canon.test_mod_submissions import NEW, SubmissionTest, a_mod
from interviews import config
from interviews.providers import Ended, Provider, ProviderError, Text, Usage

SETTINGS = config.InterviewSettings(kind="new-mod", provider="anthropic", model="fake-model")
QUESTION = "What is the Mod about, who is it for, and when does it run?"


class FakeProvider(Provider):
    """Answers each turn with the next of `replies`, in pieces. A reply that
    is an exception is raised instead. Keeps what each turn was asked."""

    def __init__(self, *replies):
        super().__init__("sk-fake", SETTINGS)
        self.replies = list(replies)
        self.asked = []

    def stream_turn(self, system, messages):
        self.asked.append((system, list(messages)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            yield Text("Half a thou")
            raise reply
        for piece in re.findall(r".{1,40}", reply, re.S):
            yield Text(piece)
        yield Ended(Usage(100, 20))


def fenced(text):
    return f"Here it is.\n\n```markdown\n{text}```\n\nTell me what to change."


def hidden(page, name):
    """The value of a hidden field in a page."""
    found = re.search(rf'<input type="hidden" name="{name}" value="([^"]*)"', page)
    return html.unescape(found.group(1)) if found else None


class InterviewTest(SubmissionTest):
    def setUp(self):
        super().setUp()
        self.interview = f"{self.first_world}interview/"

    @contextmanager
    def provider(self, fake):
        with mock.patch.object(config, "llm_for",
                               lambda kind, loaded=None: config.Llm(SETTINGS, fake)):
            yield fake

    def say(self, text, page=None, by=None):
        """Send the person's answer from a page of the Interview (or start
        one), and read the whole streamed page back."""
        transcript = hidden(page, "transcript") if page else ""
        response = (by or self.sam).post(self.interview,
                                         {"said": text, "transcript": transcript or ""})
        self.assertEqual(response.status_code, 200)
        return b"".join(response.streaming_content).decode()


class WritingAModInAnInterview(InterviewTest):
    def test_a_whole_interview_a_question_an_answer_a_file_and_submit(self):
        with self.provider(FakeProvider(QUESTION, fenced(a_mod()))) as fake:
            page = self.say("Hello")
            self.assertIn(html.escape(QUESTION), page)
            self.assertNotIn('name="text"', page)

            page = self.say("A debt owed to a lamplighter, for new players, at First Lantern.",
                            page)
            self.assertEqual([m.role for m in fake.asked[1][1]], ["user", "assistant", "user"])
            self.assertEqual(fake.asked[1][1][1].text, QUESTION)
            file = re.search(r'<textarea name="text"[^>]*>\n?(.*?)</textarea>', page, re.S)
            self.assertEqual(html.unescape(file.group(1)), a_mod())

            response = self.sam.post(f"{self.interview}submit/",
                                     {"text": html.unescape(file.group(1)),
                                      "transcript": hidden(page, "transcript")}, follow=True)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        stored = self.stored(NEW)
        self.assertEqual(stored.text, a_mod())
        self.assertEqual(stored.path, f"inbox/{NEW}.md")
        self.assertEqual(stored.submitted_by.email, "sam@example.com")

    def test_the_system_prompt_is_plotcanons_new_mod_instructions_for_the_web(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.say("Hello")

        system, messages = fake.asked[0]
        expected = plotcanon.interview_instructions(
            "new-mod", "web", world=self.stored_files())
        self.assertEqual(system, expected)
        self.assertEqual([(m.role, m.text) for m in messages], [("user", "Hello")])

    def test_a_refused_file_shows_the_intakes_errors_and_keeps_the_conversation(self):
        # A file the person edited by hand, or submitted with its errors.
        broken = a_mod(**{"type: mod": "type: nonsense"})
        with self.provider(FakeProvider(QUESTION)):
            page = self.say("Write it")
            response = self.sam.post(f"{self.interview}submit/",
                                     {"text": broken, "transcript": hidden(page, "transcript")})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "Write it")
        self.assertFalse(self.exists(NEW))

    def test_the_paste_path_is_reachable_from_the_interview(self):
        with self.provider(FakeProvider(QUESTION)):
            start = self.sam.get(self.interview)
            page = self.say("Hello")

        self.assertContains(start, f'href="{self.form}"')
        self.assertIn(f'href="{self.form}"', page)

    def test_the_world_page_offers_the_interview_first_and_the_paste_path_beside_it(self):
        with self.provider(FakeProvider()):
            page = self.sam.get(self.first_world)

        self.assertContains(page, f'href="{self.interview}"')
        self.assertContains(page, f'href="{self.form}"')

    def test_a_plot_master_may_start_one(self):
        with self.provider(FakeProvider(QUESTION)):
            self.assertIn(html.escape(QUESTION), self.say("Hello", by=self.mira))

    def test_a_provider_failure_keeps_the_last_good_turn_to_try_again(self):
        with self.provider(FakeProvider(QUESTION, ProviderError("The LLM is busy."))):
            first = self.say("Hello")
            page = self.say("A debt", first)

        self.assertIn("The LLM is busy.", page)
        self.assertEqual(hidden(page, "transcript"), hidden(first, "transcript"))
        self.assertIn(">A debt</textarea>", page)

    def test_a_forged_transcript_is_refused(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            response = self.sam.post(self.interview, {"said": "Hi", "transcript": "forged"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(fake.asked, [])

    def test_an_answer_is_needed(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            response = self.sam.post(self.interview, {"said": "  ", "transcript": ""})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.asked, [])


class WhoMayInterview(InterviewTest):
    def test_a_mod_runner_cannot_start_or_view_one(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.assertEqual(self.rhea.get(self.interview).status_code, 404)
            response = self.rhea.post(self.interview, {"said": "Hello", "transcript": ""})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(self.rhea.post(f"{self.interview}submit/",
                                            {"text": a_mod()}).status_code, 404)

        self.assertEqual(fake.asked, [])
        self.assertFalse(self.exists(NEW))

    def test_someone_with_no_role_in_the_world_cannot(self):
        stranger = self.join("stranger@example.com")
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.assertEqual(stranger.get(self.interview).status_code, 404)
            response = stranger.post(self.interview, {"said": "Hello", "transcript": ""})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(fake.asked, [])

    def test_one_persons_transcript_does_not_work_for_another(self):
        with self.provider(FakeProvider(QUESTION, QUESTION)) as fake:
            page = self.say("Hello")
            response = self.mira.post(self.interview, {"said": "More",
                                                       "transcript": hidden(page, "transcript")})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(fake.asked), 1)


class WhenInterviewsAreOff(InterviewTest):
    def test_the_world_page_offers_only_the_paste_path(self):
        with mock.patch.object(config, "llm_for", lambda kind, loaded=None: None):
            page = self.sam.get(self.first_world)
            start = self.sam.get(self.interview)

        self.assertNotContains(page, f'href="{self.interview}"')
        self.assertContains(page, f'href="{self.form}"')
        self.assertRedirects(start, self.form)


class WhatTheLlmMayRead(InterviewTest):
    def test_the_system_prompt_holds_only_what_the_read_access_function_returns(self):
        everything = access.readable_documents
        left_out = "the-wardens-ball"

        def without_one(world, person):
            return everything(world, person).exclude(slug=left_out)

        with self.provider(FakeProvider(QUESTION)) as fake, \
                mock.patch.object(access, "readable_documents", without_one):
            self.say("Hello")

        system = fake.asked[0][0]
        self.assertNotIn(left_out, system)
        self.assertIn("clerk-pell", system)

    def test_today_a_mod_writer_may_read_the_whole_world(self):
        with self.in_world():
            from canon.models import Document
            from django.contrib.auth import get_user_model
            from organizations.models import World
            world = World.objects.get(pk=self.first_world.rstrip("/").rsplit("/", 1)[1])
            sam = get_user_model().objects.get(email="sam@example.com")
            self.assertEqual(set(access.readable_documents(world, sam)),
                             set(Document.objects.filter(world=world)))


BROKEN = a_mod(**{"type: mod": "type: nonsense"})
FIXING = "is fixing it"


def file_in(page):
    """The Mod file a page offers to submit, or None."""
    found = re.search(r'<textarea name="text"[^>]*>\n?(.*?)</textarea>', page, re.S)
    return html.unescape(found.group(1)) if found else None


class FixingTheLlmsFile(InterviewTest):
    def test_a_file_with_errors_goes_back_to_the_llm_and_the_person_sees_only_the_fixed_one(self):
        with self.provider(FakeProvider(fenced(BROKEN), fenced(a_mod()))) as fake:
            page = self.say("Write it")

        self.assertEqual(len(fake.asked), 2)
        sent = fake.asked[1][1]
        self.assertEqual([m.role for m in sent], ["user", "assistant", "user"])
        self.assertIn("nonsense", sent[2].text)
        self.assertEqual(page.count(FIXING), 1)
        self.assertEqual(file_in(page), a_mod())
        self.assertNotIn("nonsense", page)
