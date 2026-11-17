"""Writing a new Mod in an Interview, through web requests, with a fake
provider in place of the real one: the tests never call an LLM."""

import dataclasses
import html
import re
from contextlib import contextmanager
from unittest import mock

import plotcanon

from canon import access
from canon.test_mod_submissions import NEW, SubmissionTest, a_mod
from interviews import config, fixing
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
    def provider(self, fake, max_fix_attempts=None):
        settings = SETTINGS if max_fix_attempts is None else \
            dataclasses.replace(SETTINGS, max_fix_attempts=max_fix_attempts)
        with mock.patch.object(config, "llm_for",
                               lambda kind, loaded=None: config.Llm(settings, fake)):
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
        # Given the whole World, as the plot team reads it.
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.say("Hello", by=self.mira)

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

    def test_a_mod_writer_with_no_mods_of_their_own_gives_it_no_gm_only_facts(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.say("Hello")

        system = fake.asked[0][0]
        self.assertIn("the-ferryman", system)
        self.assertIn("Rows the harbour mouth", system)
        self.assertNotIn("A good NPC to bring back.", system)
        self.assertNotIn("the-tidemother", system)
        self.assertNotIn("a-warrant-for-dunmore", system)

    def test_their_own_mods_are_given_in_full(self):
        self.mira.post(f"{self.first_world}mod-writers/",
                       {"handle": "sam", "user": self.user_id("sam@example.com")})
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.say("Hello")

        system = fake.asked[0][0]
        self.assertIn("a-warrant-for-dunmore", system)
        self.assertIn("Pointless if the smuggler is already dead or gone when it runs.", system)


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

    def test_the_errors_go_back_in_plotcanons_fix_request(self):
        with self.provider(FakeProvider(fenced(BROKEN), fenced(a_mod()))) as fake, \
                mock.patch.object(plotcanon, "interview_fix_request",
                                  side_effect=lambda errors: f"PLOTCANON FIX\n{errors}"):
            self.say("Write it")

        fix = fake.asked[1][1][2].text
        self.assertTrue(fix.startswith("PLOTCANON FIX\n"))
        self.assertIn("nonsense", fix)

    def test_errors_the_person_may_not_read_at_all_do_not_go_back(self):
        with self.provider(FakeProvider(fenced(BROKEN), fenced(a_mod()))) as fake, \
                mock.patch.object(fixing, "problems", return_value=""):
            page = self.say("Write it")

        self.assertEqual(len(fake.asked), 1)
        self.assertNotIn(FIXING, page)
        self.assertEqual(file_in(page), BROKEN)

    def test_after_max_fix_attempts_the_person_sees_the_file_and_its_errors(self):
        for attempts in (3, 1, 0):
            with self.subTest(attempts), \
                    self.provider(FakeProvider(*[fenced(BROKEN)] * 5), attempts) as fake:
                page = self.say("Write it")

                self.assertEqual(len(fake.asked), 1 + attempts)
                self.assertEqual(page.count(FIXING), attempts)
                self.assertEqual(file_in(page), BROKEN)
                self.assertIn("still has errors", page)
                self.assertIn("nonsense", page)
                self.assertIn("Submit the Mod", page)

    def test_the_person_can_keep_talking_after_the_attempts_run_out(self):
        with self.provider(FakeProvider(fenced(BROKEN), QUESTION), 0) as fake:
            page = self.say("Write it")
            self.say("Make it a nicer one", page)

        self.assertEqual([m.role for m in fake.asked[1][1]], ["user", "assistant", "user"])
        self.assertEqual(fake.asked[1][1][1].text, fenced(BROKEN))

    def test_a_fixed_file_keeps_only_the_persons_answer_and_the_last_reply(self):
        with self.provider(FakeProvider(fenced(BROKEN), fenced(a_mod()), QUESTION)) as fake:
            page = self.say("Write it")
            self.say("Thanks", page)

        self.assertEqual([m.text for m in fake.asked[2][1]],
                         ["Write it", fenced(a_mod()), "Thanks"])

    def test_a_reply_with_no_file_is_not_checked(self):
        with self.provider(FakeProvider(QUESTION)) as fake, \
                mock.patch("canon.intake.check_new_mod") as check:
            page = self.say("Hello")

        check.assert_not_called()
        self.assertEqual(len(fake.asked), 1)
        self.assertNotIn(FIXING, page)


LEFT_OUT = "the-wardens-ball"
# The LLM names a Mod as an NPC: plotcanon's error names that Mod.
NAMES_IT = a_mod(**{"npcs: [mirelle-vale, tobren-vale, ysolde-marr]":
                    f"npcs: [mirelle-vale, tobren-vale, ysolde-marr, {LEFT_OUT}]"})


class FixingWithinWhatThePersonMayRead(InterviewTest):
    def test_an_error_naming_a_document_the_person_may_not_read_is_never_sent_or_shown(self):
        everything = access.readable_documents

        def without_one(world, person):
            return everything(world, person).exclude(slug=LEFT_OUT)

        with self.provider(FakeProvider(fenced(NAMES_IT), fenced(NAMES_IT)), 1) as fake, \
                mock.patch.object(access, "readable_documents", without_one):
            page = self.say("Write it")

        fix = fake.asked[1][1][2].text
        self.assertIn("points at a `mod`", fix)
        self.assertNotIn(LEFT_OUT, fix)
        self.assertIn("points at a `mod`", page)
        self.assertNotIn(LEFT_OUT, page.replace(html.escape(NAMES_IT), ""))

    def test_submitting_shows_the_intakes_errors_only_as_the_person_may_read_them(self):
        everything = access.readable_documents

        def without_one(world, person):
            return everything(world, person).exclude(slug=LEFT_OUT)

        with self.provider(FakeProvider()), \
                mock.patch.object(access, "readable_documents", without_one):
            response = self.sam.post(f"{self.interview}submit/",
                                     {"text": NAMES_IT, "transcript": ""})

        page = response.content.decode()
        self.assertIn("Nothing was saved.", page)
        self.assertIn("points at a `mod`", html.unescape(page))
        self.assertNotIn(LEFT_OUT, page.replace(html.escape(NAMES_IT), ""))
        self.assertFalse(self.exists(NEW))

    def test_an_error_naming_a_gm_only_document_reads_another_document(self):
        names_gm_only = a_mod(**{"npcs: [mirelle-vale, tobren-vale, ysolde-marr]":
                                 "npcs: [mirelle-vale, tobren-vale, ysolde-marr, "
                                 "a-warrant-for-dunmore]"})
        with self.provider(FakeProvider(fenced(names_gm_only), fenced(names_gm_only)), 1) \
                as fake:
            page = self.say("Write it")

        fix = fake.asked[1][1][2].text
        self.assertIn("points at a `mod`", fix)
        self.assertNotIn("a-warrant-for-dunmore", fix)
        self.assertIn(access.HIDDEN, fix)
        self.assertNotIn("a-warrant-for-dunmore",
                         page.replace(html.escape(names_gm_only), ""))

    def test_the_same_error_names_a_document_the_person_may_read(self):
        self.mira.post(f"{self.first_world}mod-writers/",
                       {"handle": "kay", "user": self.user_id("sam@example.com")})
        with self.provider(FakeProvider(fenced(NAMES_IT), fenced(a_mod()))) as fake:
            self.say("Write it")

        self.assertIn(LEFT_OUT, fake.asked[1][1][2].text)

    def test_a_finding_about_a_document_the_person_may_not_read_is_left_out(self):
        from django.contrib.auth import get_user_model
        from organizations.models import World

        everything = access.readable_documents
        findings = ("ERROR  inbox/new.md: `features.npcs: the-wardens-ball` points at a `mod`\n"
                    "ERROR  mods/shelved/the-wardens-ball.md: `requires` does not resolve\n"
                    "ERROR  canon/npcs/the-ferryman.md: something about the-ferryman")
        with self.in_world(), mock.patch.object(
                access, "readable_documents",
                lambda world, person: everything(world, person).exclude(slug=LEFT_OUT)):
            world = World.objects.get(pk=self.first_world.rstrip("/").rsplit("/", 1)[1])
            sam = get_user_model().objects.get(email="sam@example.com")
            shown = access.readable_findings(world, sam, findings)

        self.assertEqual(shown.splitlines(), [
            "ERROR  inbox/new.md: `features.npcs: another document` points at a `mod`",
            "ERROR  canon/npcs/the-ferryman.md: something about the-ferryman",
            access.NOT_SHOWN])


class HoldingTheFileBack(InterviewTest):
    def test_other_code_blocks_in_a_reply_are_shown_as_they_come(self):
        reply = "Like this:\n\n```\nkey: value\n```\n\nAnd so on."
        with self.provider(FakeProvider(reply)):
            page = self.say("Hello")

        self.assertIn(html.escape(reply), page)

    def test_the_file_in_a_reply_is_replaced_by_a_note_in_the_reply(self):
        with self.provider(FakeProvider(fenced(a_mod()))):
            page = self.say("Write it")

        self.assertIn("Here it is.\n\n[The file is shown below", page)
        self.assertIn("checked.]\n\nTell me what to change.", page)
        self.assertEqual(page.count("id: the-lamplighters-debt"), 1)
