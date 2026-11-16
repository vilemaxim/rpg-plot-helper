"""Writing an After-Action Report in an Interview that starts from the Dry Run
Path, through web requests, with a fake provider in place of the real one:
the tests never call an LLM."""

import html
from unittest import mock

import plotcanon

from interviews import config
from interviews.test_interviews import QUESTION, FakeProvider, InterviewTest, hidden

BELL = "the-bell-beneath"          # approved, with a Dry Run and a Contest
NO_DRY_RUN = "storm-moon-vigil"    # approved, with no Dry Run
SISTER = "The sister asks them to close what was opened"
CONTEST = "stop her before the last stroke"


class ReportInterviewTest(InterviewTest):
    def report_page(self, mod):
        return f"{self.mod_page(mod)}report/"

    def report_interview(self, mod):
        return f"{self.report_page(mod)}interview/"

    def walk(self, mod):
        return f"{self.report_interview(mod)}walk/"


class StartingAReport(ReportInterviewTest):
    def test_the_report_page_offers_the_interview_first_and_pasting_second(self):
        with self.provider(FakeProvider()):
            page = self.rhea.get(self.report_page(BELL)).content.decode()

        interview = page.index(f'href="{self.report_interview(BELL)}"')
        self.assertLess(interview, page.index("<textarea"))

    def test_with_the_report_interview_off_only_pasting_is_offered(self):
        with mock.patch.object(config, "llm_for", lambda kind, loaded=None: None):
            page = self.rhea.get(self.report_page(BELL))
            start = self.rhea.get(self.report_interview(BELL))

        self.assertNotContains(page, self.report_interview(BELL))
        self.assertContains(page, "<textarea")
        self.assertRedirects(start, self.report_page(BELL))

    def test_only_the_report_interview_being_off_is_what_counts(self):
        def all_but_reports(kind, loaded=None):
            return None if kind == config.Kind.REPORT else config.Llm(None, FakeProvider())

        with mock.patch.object(config, "llm_for", all_but_reports):
            page = self.rhea.get(self.report_page(BELL))

        self.assertNotContains(page, self.report_interview(BELL))


DESCENT = "The descent"
WHO = "Who rings it"
SILENCED = "The bell is silenced"
# The choices, by place, that walk from the Premise by the sister's Hook down
# the rope, let the bell ring and win the Contest: Hook, exit, exit, result.
TO_SILENCED = [0, 1, 0, 1]
PATH_TO_SILENCED = [{"hook": SISTER}, DESCENT, "The bell", WHO,
                    {"contest": CONTEST, "result": "win"}, SILENCED]


class WalkingThePath(ReportInterviewTest):
    def walk_to(self, mod, choices, start=None, by=None):
        query = ([("from", start)] if start else []) + [("choice", c) for c in choices]
        response = (by or self.rhea).get(self.walk(mod), query)
        self.assertEqual(response.status_code, 200)
        return response

    def stop_at(self, mod, choices, start=None, by=None):
        """Say play stopped where these choices lead, and the report
        Interview's page it goes to."""
        data = {"choice": [str(c) for c in choices], **({"from": start} if start else {})}
        response = (by or self.rhea).post(self.walk(mod), data)
        self.assertRedirects(response, self.report_interview(mod),
                             fetch_redirect_response=False)
        return (by or self.rhea).get(self.report_interview(mod)).content.decode()

    def begin(self, mod, page, by=None):
        """Press Begin on the report Interview: the LLM speaks first."""
        response = (by or self.rhea).post(self.report_interview(mod),
                                          {"transcript": hidden(page, "transcript") or ""})
        self.assertEqual(response.status_code, 200)
        return b"".join(response.streaming_content).decode()

    def system_prompt_for(self, path, mod=BELL, continues_from=None):
        return plotcanon.interview_instructions(
            "report", "web", world=self.stored_files(), mod=self.stored(mod).text,
            path=path, continues_from=continues_from)


class TheWalk(WalkingThePath):
    def test_with_no_report_interview_in_progress_it_starts_with_the_walk(self):
        with self.provider(FakeProvider()) as fake:
            response = self.rhea.get(self.report_interview(BELL))

        self.assertRedirects(response, self.walk(BELL), fetch_redirect_response=False)
        self.assertEqual(fake.asked, [])

    def test_it_starts_at_the_hooks_of_a_mod_never_reported_on(self):
        with self.provider(FakeProvider()) as fake:
            page = self.walk_to(BELL, [])

        self.assertContains(page, html.escape(SISTER))
        self.assertNotContains(page, "Play stopped here")
        self.assertEqual(fake.asked, [])

    def test_each_choice_leads_on_and_a_contests_results_are_choices(self):
        with self.provider(FakeProvider()) as fake:
            page = self.walk_to(BELL, TO_SILENCED[:3])

        self.assertContains(page, f"<h2>{WHO}")
        self.assertContains(page, f"{CONTEST}: win")
        self.assertContains(page, f"{CONTEST}: lose")
        self.assertContains(page, "Play stopped here")
        self.assertEqual(fake.asked, [])

    def test_it_can_step_back(self):
        with self.provider(FakeProvider()):
            page = self.walk_to(BELL, [0, 1])

        self.assertContains(page, 'href="?choice=0"')

    def test_a_choice_that_is_not_there_is_not_found(self):
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.walk(BELL), {"choice": [0, 9]})

        self.assertEqual(response.status_code, 404)

    def test_walking_to_an_ending_with_a_contest_gives_a_path_plotcanon_accepts(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            page = self.stop_at(BELL, TO_SILENCED)
            self.begin(BELL, page)

        story = plotcanon.story(self.stored(BELL).text)
        walked = plotcanon.check_path(story, PATH_TO_SILENCED)
        self.assertTrue(walked.ok, walked.problems)
        self.assertTrue(walked.finished)
        system, messages = fake.asked[0]
        self.assertEqual(system, self.system_prompt_for(PATH_TO_SILENCED))
        self.assertEqual(messages[0].text, plotcanon.interview_report_opener(PATH_TO_SILENCED))

    def test_saying_play_stopped_at_a_scene_gives_a_path_ending_there(self):
        path = [{"hook": SISTER}, DESCENT]
        with self.provider(FakeProvider(QUESTION)) as fake:
            page = self.stop_at(BELL, [0])
            self.begin(BELL, page)

        self.assertEqual(fake.asked[0][0], self.system_prompt_for(path))
        walked = plotcanon.check_path(plotcanon.story(self.stored(BELL).text), path)
        self.assertTrue(walked.ok)
        self.assertFalse(walked.finished)

    def test_the_interview_page_shows_the_path_walked_before_it_begins(self):
        with self.provider(FakeProvider()) as fake:
            page = self.stop_at(BELL, TO_SILENCED)

        self.assertIn(f"Hook: {html.escape(SISTER)}", page)
        self.assertIn(f"{CONTEST}: win", page)
        self.assertIn(">Begin</button>", page)
        self.assertEqual(fake.asked, [])

    def test_play_cannot_stop_at_the_premise(self):
        with self.provider(FakeProvider()):
            response = self.rhea.post(self.walk(BELL), {})

        self.assertEqual(response.status_code, 400)

    def test_once_an_interview_is_in_progress_it_opens_on_that(self):
        with self.provider(FakeProvider(QUESTION)):
            self.begin(BELL, self.stop_at(BELL, [0]))
            page = self.rhea.get(self.report_interview(BELL))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, html.escape(QUESTION))
