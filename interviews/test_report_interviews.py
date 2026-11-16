"""Writing an After-Action Report in an Interview that starts from the Dry Run
Path, through web requests, with a fake provider in place of the real one:
the tests never call an LLM."""

import html
from unittest import mock

import plotcanon
import yaml

from canon.test_reports import VIGIL
from canon import access
from interviews import config
from interviews.providers import ProviderError
from interviews.test_interviews import (FIXING, QUESTION, FakeProvider, InterviewTest, fenced,
                                        file_in, hidden)

BELL = "the-bell-beneath"          # approved, with a Dry Run and a Contest
NO_DRY_RUN = "storm-moon-vigil"    # approved, with no Dry Run
SISTER = "The sister asks them to close what was opened"
CONTEST = "stop her before the last stroke"
CHAPEL_CHANGE = "The crypt stair is open again."


def a_report(path, finished, id="aa-the-bell-beneath"):
    """A report on the bell Mod at Second Lantern, as the LLM would write it,
    with `path` (its steps) and `finished` ("true" or "false")."""
    path_lines = yaml.safe_dump({"path": path}, sort_keys=False) if path else ""
    return (f"---\nid: {id}\ntype: after-action\nmod: the-bell-beneath\n"
            f"event: e04-second-lantern\nran: true\nfinished: {finished}\nmod_runner: sam\n"
            f"pcs: [pc-bram-tolliver]\n{path_lines}canon_changes:\n"
            f"  - entity: the-sunken-chapel\n    kind: narrative\n    decision: proposed\n"
            f"    summary: \"{CHAPEL_CHANGE}\"\n---\n\n## What Happened\n\nThey went down.\n\n"
            f"## Divergences From The Mod\n\nNone.\n\n## Loose Ends\n\n- The bell.\n")


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

    def test_the_walk_cannot_be_skipped_by_beginning_with_no_path(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            response = self.rhea.post(self.report_interview(BELL), {"transcript": ""})
            again = self.rhea.post(self.report_interview(BELL),
                                   {"said": "Hello", "transcript": ""})

        for skipped in (response, again):
            self.assertRedirects(skipped, self.walk(BELL), fetch_redirect_response=False)
        self.assertEqual(fake.asked, [])
        with self.provider(FakeProvider()):
            self.assertRedirects(self.rhea.get(self.report_interview(BELL)), self.walk(BELL),
                                 fetch_redirect_response=False)

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


class AModInProgress(WalkingThePath):
    """A first report on the bell Mod said play stopped at the descent."""

    def setUp(self):
        super().setUp()
        filed = self.rhea.post(self.report_page(BELL),
                               {"text": a_report([{"hook": SISTER}, DESCENT], "false")})
        self.assertEqual(filed.status_code, 302)

    def test_the_walk_starts_by_default_where_the_last_reports_path_stopped(self):
        with self.provider(FakeProvider()):
            page = self.walk_to(BELL, [])

        self.assertContains(page, f"<h2>{DESCENT}")
        self.assertContains(page, "Start from a Hook instead")

    def test_stopping_further_on_gives_a_path_from_there_that_plotcanon_accepts(self):
        path = [DESCENT, "The bell"]
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(BELL, self.stop_at(BELL, [1]))

        stop = plotcanon.last_stop(self.stored_files(), BELL)
        self.assertEqual(stop, plotcanon.LastStop(DESCENT))
        self.assertEqual(fake.asked[0][0], self.system_prompt_for(path, continues_from=stop))
        walked = plotcanon.check_path(plotcanon.story(self.stored(BELL).text), path,
                                      continues_from=stop)
        self.assertTrue(walked.ok, walked.problems)

    def test_the_mod_runner_can_start_from_a_hook_instead(self):
        path = [{"hook": SISTER}, DESCENT, "The bell"]
        with self.provider(FakeProvider(QUESTION)) as fake:
            page = self.walk_to(BELL, [], start="hook")
            self.assertContains(page, html.escape(SISTER))
            self.begin(BELL, self.stop_at(BELL, [0, 1], start="hook"))

        stop = plotcanon.last_stop(self.stored_files(), BELL)
        self.assertEqual(fake.asked[0][0], self.system_prompt_for(path, continues_from=stop))

    def test_a_scene_the_last_report_did_not_stop_at_cannot_be_a_start(self):
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.walk(BELL), {"from": WHO})

        self.assertEqual(response.status_code, 404)


class AModWhoseLastReportHasNoPath(WalkingThePath):
    """A first report on the bell Mod was pasted with no Path, so where play
    stopped is not known."""

    def setUp(self):
        super().setUp()
        filed = self.rhea.post(self.report_page(BELL), {"text": a_report(None, "false")})
        self.assertEqual(filed.status_code, 302)

    def test_the_walk_offers_the_hooks_and_any_scene_to_pick_up_at(self):
        with self.provider(FakeProvider()):
            page = self.walk_to(BELL, [])

        self.assertContains(page, html.escape(SISTER))
        self.assertContains(page, 'href="?from=Who+rings+it"')

    def test_picking_up_at_a_scene_gives_a_path_from_there(self):
        path = [WHO, {"contest": CONTEST, "result": "lose"}, "The bell is rung"]
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(BELL, self.stop_at(BELL, [2], start=WHO))

        stop = plotcanon.last_stop(self.stored_files(), BELL)
        self.assertEqual(stop, plotcanon.LastStop(known=False))
        self.assertEqual(fake.asked[0][0], self.system_prompt_for(path, continues_from=stop))


class AModWithNoDryRun(WalkingThePath):
    def test_it_goes_straight_to_the_interview_which_asks_what_happened(self):
        with self.provider(FakeProvider(QUESTION)) as fake:
            page = self.rhea.get(self.report_interview(NO_DRY_RUN))
            self.assertEqual(page.status_code, 200)
            self.begin(NO_DRY_RUN, page.content.decode())

        system, messages = fake.asked[0]
        self.assertEqual(system, self.system_prompt_for(None, mod=NO_DRY_RUN))
        self.assertEqual(messages[0].text, plotcanon.interview_report_opener(None))

    def test_its_walk_page_sends_the_person_on_to_the_interview(self):
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.walk(NO_DRY_RUN))

        self.assertRedirects(response, self.report_interview(NO_DRY_RUN),
                             fetch_redirect_response=False)

    def test_the_filed_report_has_no_path(self):
        with self.provider(FakeProvider(fenced(VIGIL.text))):
            page = self.begin(NO_DRY_RUN, "")
            response = self.rhea.post(f"{self.report_interview(NO_DRY_RUN)}submit/",
                                      {"text": file_in(page), "finished": "false",
                                       "transcript": hidden(page, "transcript")})

        self.assertEqual(response.status_code, 302)
        filed = self.stored("aa-storm-moon-vigil")
        self.assertNotIn("path", filed.fields)

    def test_a_report_given_a_path_goes_back_to_the_llm_and_is_not_filed(self):
        with_path = VIGIL.text.replace("finished: false\n",
                                       "finished: false\npath:\n  - The vigil\n")
        with self.provider(FakeProvider(fenced(with_path), fenced(with_path)),
                           max_fix_attempts=1) as fake:
            page = self.begin(NO_DRY_RUN, "")
            response = self.rhea.post(f"{self.report_interview(NO_DRY_RUN)}submit/",
                                      {"text": file_in(page), "finished": "false",
                                       "transcript": hidden(page, "transcript")})

        self.assertEqual(len(fake.asked), 2)
        self.assertIn("path", fake.asked[1][1][-1].text)
        self.assertContains(response, "Nothing was saved.")
        self.assertFalse(self.exists("aa-storm-moon-vigil"))


class FilingTheReport(WalkingThePath):
    def write(self, choices, report, max_fix_attempts=None):
        """Walk, begin, and have the LLM give `report`. The page it gives."""
        with self.provider(FakeProvider(fenced(report)), max_fix_attempts=max_fix_attempts):
            return self.begin(BELL, self.stop_at(BELL, choices))

    def file(self, page, finished=None, text=None):
        data = {"text": file_in(page) if text is None else text,
                "transcript": hidden(page, "transcript")}
        if finished is not None:
            data["finished"] = finished
        with self.provider(FakeProvider()):
            return self.rhea.post(f"{self.report_interview(BELL)}submit/", data, follow=True)

    def test_reaching_an_ending_proposes_finished_whatever_the_llm_wrote(self):
        page = self.write(TO_SILENCED, a_report(PATH_TO_SILENCED, "false"))

        self.assertIn('name="finished" value="true" checked', page)
        self.assertNotIn('name="finished" value="false" checked', page)

    def test_stopping_at_a_scene_proposes_not_finished_whatever_the_llm_wrote(self):
        page = self.write([0], a_report([{"hook": SISTER}, DESCENT], "true"))

        self.assertIn('name="finished" value="false" checked', page)
        self.assertNotIn('name="finished" value="true" checked', page)

    def test_the_path_proposes_finished_when_the_llm_left_it_out_or_wrote_nonsense(self):
        left_out = a_report(PATH_TO_SILENCED, "true").replace("finished: true\n", "")
        for report in (left_out, a_report(PATH_TO_SILENCED, "yes")):
            with self.subTest(report=report[:200]):
                page = self.write(TO_SILENCED, report, max_fix_attempts=0)
                self.assertIn('name="finished" value="true" checked', page)
                self.assertNotIn('name="finished" value="false" checked', page)

    def test_a_path_other_than_the_one_walked_goes_back_to_the_llm(self):
        # Valid to plotcanon, but not where the Mod Runner said play stopped.
        further = a_report([{"hook": SISTER}, DESCENT, "The bell"], "false")
        walked = a_report([{"hook": SISTER}, DESCENT], "false")
        with self.provider(FakeProvider(fenced(further), fenced(walked))) as fake:
            page = self.begin(BELL, self.stop_at(BELL, [0]))

        self.assertIn(FIXING, page)
        self.assertIn("path", fake.asked[1][1][-1].text)
        self.assertEqual(file_in(page), walked)

    def test_a_path_other_than_the_one_walked_is_not_filed(self):
        page = self.write([0], a_report([{"hook": SISTER}, DESCENT], "false"))
        response = self.file(page, "false",
                             text=a_report([{"hook": SISTER}, DESCENT, "The bell"], "false"))

        self.assertContains(response, "Nothing was saved.")
        self.assertFalse(self.exists("aa-the-bell-beneath"))

    def test_a_report_with_no_path_is_not_filed_when_a_path_was_walked(self):
        page = self.write([0], a_report([{"hook": SISTER}, DESCENT], "false"))
        response = self.file(page, "false", text=a_report(None, "false"))

        self.assertContains(response, "Nothing was saved.")
        self.assertFalse(self.exists("aa-the-bell-beneath"))

    def test_the_report_is_filed_through_the_same_path_as_a_pasted_one(self):
        page = self.write(TO_SILENCED, a_report(PATH_TO_SILENCED, "true"))
        response = self.file(page, "true")

        self.assertEqual(response.redirect_chain[-1][0],
                         f"{self.first_world}reports/aa-the-bell-beneath/")
        self.assertContains(response, "Its Canon Changes are waiting to be decided")
        filed = self.stored("aa-the-bell-beneath")
        self.assertEqual(filed.fields["path"], PATH_TO_SILENCED)
        self.assertEqual(filed.submitted_by.email, "rhea@example.com")
        self.assertEqual(self.stored(BELL).fields["state"], "finished")
        self.assertContains(self.mira.get(self.pending), CHAPEL_CHANGE)

    def test_the_mod_runner_can_change_finished_before_filing(self):
        page = self.write(TO_SILENCED, a_report(PATH_TO_SILENCED, "true"))
        self.file(page, "false")

        self.assertIs(self.stored("aa-the-bell-beneath").fields["finished"], False)
        self.assertEqual(self.stored(BELL).fields["state"], "in-progress")

    def test_the_interview_is_gone_once_filed(self):
        page = self.write([0], a_report([{"hook": SISTER}, DESCENT], "false"))
        self.file(page, "false")

        with self.provider(FakeProvider()):
            response = self.rhea.get(self.report_interview(BELL))
        self.assertRedirects(response, self.walk(BELL), fetch_redirect_response=False)

    def test_a_refused_report_keeps_the_conversation_and_says_why(self):
        page = self.write([0], a_report([{"hook": SISTER}, DESCENT], "false"))
        response = self.file(page, "false", text=a_report([{"hook": SISTER}, WHO], "false"))

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "That report has errors.")
        self.assertFalse(self.exists("aa-the-bell-beneath"))

    def test_a_report_with_errors_goes_back_to_the_llm_before_the_person_sees_it(self):
        broken = a_report([{"hook": SISTER}, WHO], "false")
        good = a_report([{"hook": SISTER}, DESCENT], "false")
        with self.provider(FakeProvider(fenced(broken), fenced(good))) as fake:
            page = self.begin(BELL, self.stop_at(BELL, [0]))

        self.assertIn(FIXING, page)
        self.assertEqual(len(fake.asked), 2)
        self.assertIn(WHO, fake.asked[1][1][-1].text)
        self.assertEqual(file_in(page), good)

    def test_a_provider_failure_keeps_the_walk_and_offers_pasting(self):
        with self.provider(FakeProvider(ProviderError("The LLM is busy."))):
            page = self.begin(BELL, self.stop_at(BELL, [0]))

        self.assertIn("The LLM is busy.", page)
        self.assertIn(">Begin</button>", page)
        self.assertIn(f'href="{self.report_page(BELL)}"', page)


class WhoMayWriteAReport(WalkingThePath):
    def test_anyone_with_a_role_in_the_world_may_as_they_may_file_one(self):
        with self.provider(FakeProvider(QUESTION, QUESTION)) as fake:
            self.begin(BELL, self.stop_at(BELL, [0], by=self.sam), by=self.sam)
            self.begin(BELL, self.stop_at(BELL, [0], by=self.mira), by=self.mira)

        self.assertEqual(len(fake.asked), 2)

    def test_someone_with_no_role_in_the_world_cannot(self):
        stranger = self.join("stranger@example.com")
        with self.provider(FakeProvider(QUESTION)) as fake:
            for address in (self.report_interview(BELL), self.walk(BELL)):
                self.assertEqual(stranger.get(address).status_code, 404)
            self.assertEqual(stranger.post(self.walk(BELL), {"choice": "0"}).status_code, 404)

        self.assertEqual(fake.asked, [])

    def test_a_mod_that_cannot_be_reported_on_sends_the_person_to_the_report_page(self):
        with self.provider(FakeProvider()) as fake:
            response = self.rhea.get(self.report_interview("the-wardens-ball"))

        self.assertRedirects(response, self.report_page("the-wardens-ball"),
                             fetch_redirect_response=False)
        self.assertEqual(fake.asked, [])

    def test_one_persons_walk_is_not_anothers(self):
        with self.provider(FakeProvider()):
            page = self.stop_at(BELL, [0])
            response = self.sam.post(self.report_interview(BELL),
                                     {"transcript": hidden(page, "transcript")})

        self.assertEqual(response.status_code, 400)


class WhatTheLlmMayRead(WalkingThePath):
    def reading_all_but(self, slug):
        everything = access.readable_documents
        return mock.patch.object(access, "readable_documents", lambda world, person:
                                 everything(world, person).exclude(slug=slug))

    def test_the_system_prompt_holds_only_what_the_read_access_function_returns(self):
        with self.provider(FakeProvider(QUESTION)) as fake, \
                self.reading_all_but("the-wardens-ball"):
            self.begin(BELL, self.stop_at(BELL, [0]))

        system = fake.asked[0][0]
        self.assertNotIn("the-wardens-ball", system)
        self.assertIn("clerk-pell", system)

    def test_a_mod_the_person_may_not_read_has_no_report_interview(self):
        with self.provider(FakeProvider()) as fake, self.reading_all_but(BELL):
            self.assertEqual(self.rhea.get(self.walk(BELL)).status_code, 404)
            self.assertEqual(self.rhea.get(self.report_interview(BELL)).status_code, 404)

        self.assertEqual(fake.asked, [])
