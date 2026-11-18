"""Groups in the report Interview (#67, ADR-0011): it asks which Group a
report is for only when its Mod has more than one live Assignment at the
Event, and the Path walk follows that Group. Through web requests, with a
fake provider in place of the real one."""

import plotcanon

from django.utils import timezone

from accounts.models import User
from canon import access
from canon.models import Assignment, Document
from organizations.models import World
from interviews.test_interviews import FakeProvider, fenced, file_in, hidden
from interviews.test_report_interviews import (BELL, DESCENT, NO_DRY_RUN, QUESTION, SISTER,
                                               WHO, WalkingThePath, a_report)

SECOND_LANTERN = "e04-second-lantern"   # the bell Mod's only Event


def with_group(report, group):
    """A report, as `a_report` writes it, for a Group."""
    return report.replace("event: e04-second-lantern\n",
                          f"event: e04-second-lantern\ngroup: {group}\n")


class GroupTest(WalkingThePath):
    """Rhea runs the bell Mod, standing. Tom runs Mods in the World too."""

    def setUp(self):
        super().setUp()
        self.tom = self.join("tom@example.com")
        self.give("tom@example.com", "mod-runner")

    def assign_tom(self, mod=BELL, event=""):
        self.mira.post(f"{self.mod_page(mod)}assignments/",
                       {"user": self.user_id("tom@example.com"), "event": event})

    def files_read_by(self, email):
        with self.in_world():
            world = World.objects.get(pk=self.first_world.rstrip("/").rsplit("/", 1)[1])
            return access.readable_files(world, User.objects.get(email=email))

    def group_page(self, mod=BELL):
        return f"{self.report_interview(mod)}group/"

    def choose(self, group, event=SECOND_LANTERN, by=None, mod=BELL):
        """Say which Event and Group the report is for. Where it goes next."""
        with self.provider(FakeProvider()):
            response = (by or self.rhea).post(self.group_page(mod),
                                              {"event": event, "group": group, "asked": "1"})
        self.assertRedirects(response, self.report_interview(mod),
                             fetch_redirect_response=False)
        return response


class AskingForAGroup(GroupTest):
    def test_with_one_live_assignment_it_never_asks(self):
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.report_interview(BELL))

        self.assertRedirects(response, self.walk(BELL), fetch_redirect_response=False)

    def test_with_two_live_assignments_at_the_event_it_asks_first(self):
        self.assign_tom()
        with self.provider(FakeProvider()) as fake:
            start = self.rhea.get(self.report_interview(BELL))
            walk = self.rhea.get(self.walk(BELL))

        for response in (start, walk):
            self.assertRedirects(response, self.group_page(BELL),
                                 fetch_redirect_response=False)
        self.assertEqual(fake.asked, [])

    def test_it_suggests_the_filers_name_as_a_mod_writer_for_the_group(self):
        self.assign_tom()
        self.give("rhea@example.com", "mod-writer")
        self.mira.post(f"{self.first_world}mod-writers/",
                       {"handle": "kay", "user": self.user_id("rhea@example.com")})
        with self.provider(FakeProvider()):
            group = self.rhea.get(self.group_page())

        self.assertContains(group, 'name="group" value="kay"')

    def test_someone_not_assigned_is_suggested_no_label(self):
        self.assign_tom()
        with self.provider(FakeProvider()):
            group = self.mira.post(self.group_page(), {"event": SECOND_LANTERN})

        self.assertContains(group, 'name="group" value=""')

    def test_with_one_live_assignment_the_group_page_sends_the_person_on(self):
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.group_page())

        self.assertRedirects(response, self.report_interview(BELL),
                             fetch_redirect_response=False)

    def test_assignments_for_an_event_count_once_it_has_ended(self):
        # Assigned while Second Lantern was still to come; the report is
        # filed after it.
        self.move_second_lantern("2999-07-11")
        self.assign_tom(event=SECOND_LANTERN)
        self.move_second_lantern("2026-07-11")
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.report_interview(BELL))

        self.assertRedirects(response, self.group_page(BELL), fetch_redirect_response=False)

    def test_a_revoked_assignment_does_not_count(self):
        self.assign_tom()
        with self.in_world():
            Assignment.objects.filter(runner__email="tom@example.com") \
                .update(revoked_at=timezone.now())
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.report_interview(BELL))

        self.assertRedirects(response, self.walk(BELL), fetch_redirect_response=False)

    def move_second_lantern(self, day):
        with self.in_world():
            event = Document.objects.get(slug=SECOND_LANTERN)
            event.fields["real_date"] = day
            event.save(update_fields=["fields"])

    def test_a_mod_with_no_dry_run_is_asked_too_and_told_the_llm(self):
        self.assign_tom(mod=NO_DRY_RUN)
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.assertRedirects(self.rhea.get(self.report_interview(NO_DRY_RUN)),
                                 self.group_page(NO_DRY_RUN), fetch_redirect_response=False)
            self.choose("rhea", event="e03-storm-moon", mod=NO_DRY_RUN)
            page = self.rhea.get(self.report_interview(NO_DRY_RUN)).content.decode()
            self.begin(NO_DRY_RUN, page)

        self.assertIn("give `group: rhea`", fake.asked[0][1][0].text)


class WhichEvent(GroupTest):
    """The bell Mod lists Second Lantern alone, unless a test gives it Storm
    Moon too."""

    def list_events(self, *events):
        with self.in_world():
            mod = Document.objects.get(slug=BELL)
            mod.fields["events"] = list(events)
            mod.save(update_fields=["fields"])

    def get_group_page(self):
        with self.provider(FakeProvider()):
            return self.rhea.get(self.group_page())

    def test_a_mod_with_one_event_is_asked_only_the_group_at_it(self):
        self.assign_tom()

        page = self.get_group_page()

        self.assertContains(page, 'name="group"')
        self.assertContains(page, f'name="event" value="{SECOND_LANTERN}"')
        self.assertNotContains(page, 'type="radio"')
        self.assertNotContains(page, "Another Event")

    def test_where_the_events_differ_it_asks_which_event_first(self):
        with self.in_world():
            lantern = Document.objects.get(slug=SECOND_LANTERN)
            lantern.fields["real_date"] = "2999-07-11"
            lantern.save(update_fields=["fields"])
        self.assign_tom(event=SECOND_LANTERN)
        self.list_events(SECOND_LANTERN, "e03-storm-moon")

        page = self.get_group_page()

        self.assertContains(page, f'value="{SECOND_LANTERN}" checked')
        self.assertContains(page, 'value="e03-storm-moon"')
        self.assertNotContains(page, 'name="group"')

    def test_where_every_event_needs_a_group_it_asks_which_event_for_where_play_stopped(self):
        # Each Group's walk starts where it stopped at the Event its report
        # is for, so the Event is still asked when there are several.
        self.assign_tom()
        self.list_events(SECOND_LANTERN, "e03-storm-moon")

        page = self.get_group_page()

        self.assertContains(page, 'value="e03-storm-moon"')
        self.assertNotContains(page, 'name="group"')


class FilingWithAGroup(GroupTest):
    def write(self, reply, choices=(0,), max_fix_attempts=None):
        """Walk, begin, and have the LLM give `reply`. The page it gives,
        and the fake provider."""
        with self.provider(FakeProvider(reply), max_fix_attempts=max_fix_attempts) as fake:
            page = self.begin(BELL, self.stop_at(BELL, list(choices)))
        return page, fake

    def file(self, page, finished="false"):
        with self.provider(FakeProvider()):
            return self.rhea.post(f"{self.report_interview(BELL)}submit/",
                                  {"text": file_in(page), "finished": finished,
                                   "transcript": hidden(page, "transcript")}, follow=True)

    def test_with_two_live_assignments_the_group_is_written_into_the_report(self):
        self.assign_tom()
        self.choose("rhea")
        report = with_group(a_report([{"hook": SISTER}, DESCENT], "false"), "rhea")
        page, fake = self.write(fenced(report))
        self.file(page)

        self.assertIn("my Group: give `group: rhea`", fake.asked[0][1][0].text)
        self.assertEqual(self.stored("aa-the-bell-beneath").fields["group"], "rhea")

    def test_a_report_without_the_group_asked_for_goes_back_to_the_llm(self):
        self.assign_tom()
        self.choose("rhea")
        without = a_report([{"hook": SISTER}, DESCENT], "false")
        page, _ = self.write(fenced(without), max_fix_attempts=0)
        response = self.file(page)

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "group: rhea")
        self.assertFalse(self.exists("aa-the-bell-beneath"))

    def test_with_one_live_assignment_no_group_is_written(self):
        report = with_group(a_report([{"hook": SISTER}, DESCENT], "false"), "rhea")
        page, fake = self.write(fenced(report), max_fix_attempts=0)
        response = self.file(page)

        self.assertEqual(fake.asked[0][1][0].text,
                         plotcanon.interview_report_opener([{"hook": SISTER}, DESCENT]))
        self.assertContains(response, "Leave `group` out")
        self.assertFalse(self.exists("aa-the-bell-beneath"))

    def test_the_llm_is_told_the_event_asked_for(self):
        self.assign_tom()
        self.choose("rhea")
        _, fake = self.write(QUESTION)

        self.assertIn(f"**`event`** is `{SECOND_LANTERN}`", fake.asked[0][0])


THE_BELL = "The bell"


class SplitTest(GroupTest):
    """At Second Lantern, with Rhea and Tom both assigned, play stopped at
    the descent for the whole Mod; then the players split, and Rhea's Group
    went on to the bell."""

    def setUp(self):
        super().setUp()
        self.assign_tom()
        self.paste(a_report([{"hook": SISTER}, DESCENT], "false"))
        self.paste(with_group(a_report([DESCENT, THE_BELL], "false",
                                       id="aa-the-bell-beneath-2"), "rhea"))

    def paste(self, report):
        filed = self.rhea.post(self.report_page(BELL), {"text": report})
        self.assertEqual(filed.status_code, 302)


class ASplit(SplitTest):
    def test_each_groups_walk_starts_where_that_group_stopped(self):
        self.choose("rhea")
        with self.provider(FakeProvider()):
            page = self.walk_to(BELL, [])

        self.assertContains(page, f"<h2>{THE_BELL}")

    def test_a_groups_first_walk_starts_where_the_mod_stopped_before_the_split(self):
        self.choose("tom", by=self.tom)
        with self.provider(FakeProvider()):
            page = self.walk_to(BELL, [], by=self.tom)

        self.assertContains(page, f"<h2>{DESCENT}")

    def test_the_groups_walk_is_what_the_llm_is_told_and_what_is_filed(self):
        self.choose("tom", by=self.tom)
        path = [DESCENT, THE_BELL, WHO]
        report = with_group(a_report(path, "false", id="aa-the-bell-beneath-3"), "tom")
        told = plotcanon.interview_instructions(
            "report", "web", world=self.files_read_by("tom@example.com"),
            mod=self.stored(BELL).text,
            path=path, continues_from=plotcanon.LastStop(DESCENT), event=SECOND_LANTERN)
        with self.provider(FakeProvider(fenced(report))) as fake:
            page = self.begin(BELL, self.stop_at(BELL, [1, 0], by=self.tom), by=self.tom)
        with self.provider(FakeProvider()):
            self.tom.post(f"{self.report_interview(BELL)}submit/",
                          {"text": file_in(page), "finished": "false",
                           "transcript": hidden(page, "transcript")})

        self.assertEqual(fake.asked[0][0], told)
        self.assertEqual(self.stored("aa-the-bell-beneath-3").fields["group"], "tom")


class ComingBackTogether(SplitTest):
    """Then Tom's Group went on from the descent to who rings it."""

    def setUp(self):
        super().setUp()
        self.paste(with_group(a_report([DESCENT, THE_BELL, WHO], "false",
                                       id="aa-the-bell-beneath-3"), "tom"))

    def test_a_report_with_no_group_starts_where_either_group_stopped(self):
        self.choose("")
        with self.provider(FakeProvider()):
            page = self.walk_to(BELL, [])
            other = self.walk_to(BELL, [], start=WHO)

        self.assertContains(page, f"<h2>{THE_BELL}")
        self.assertContains(page, 'href="?from=Who+rings+it"')
        self.assertNotContains(page, "Start from a Hook instead")
        self.assertContains(other, f"<h2>{WHO}")
        self.assertContains(other, 'href="?from=The+bell"')

    def test_it_cannot_start_at_a_hook(self):
        self.choose("")
        with self.provider(FakeProvider()):
            response = self.rhea.get(self.walk(BELL), {"from": "hook"})

        self.assertEqual(response.status_code, 404)

    def test_either_stop_gives_a_path_the_llm_is_told_comes_back_together(self):
        self.choose("")
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(BELL, self.stop_at(BELL, [1], start=WHO))

        stop = plotcanon.LastStop(among=(THE_BELL, WHO))
        self.assertEqual(fake.asked[0][0], plotcanon.interview_instructions(
            "report", "web", world=self.files_rhea_reads(), mod=self.stored(BELL).text,
            path=[WHO, {"contest": "stop her before the last stroke", "result": "win"},
                  "The bell is silenced"],
            continues_from=stop, event=SECOND_LANTERN))
        self.assertIn("leave `group` out", fake.asked[0][1][0].text)

    def test_the_llm_is_told_the_players_came_back_together_after_the_split(self):
        self.choose("")
        with self.provider(FakeProvider(QUESTION)) as fake:
            self.begin(BELL, self.stop_at(BELL, [1], start=WHO))

        opener = fake.asked[0][1][0].text
        self.assertIn("came back together after splitting into Groups", opener)
        self.assertNotIn("not split", opener)

    def test_a_report_with_a_group_is_refused_as_come_back_together(self):
        self.choose("")
        path = [WHO, {"contest": "stop her before the last stroke", "result": "win"},
                "The bell is silenced"]
        report = with_group(a_report(path, "false", id="aa-the-bell-beneath-4"), "tom")
        with self.provider(FakeProvider(fenced(report)), max_fix_attempts=0):
            page = self.begin(BELL, self.stop_at(BELL, [1], start=WHO))
        with self.provider(FakeProvider()):
            response = self.rhea.post(f"{self.report_interview(BELL)}submit/",
                                      {"text": file_in(page), "finished": "false",
                                       "transcript": hidden(page, "transcript")}, follow=True)

        self.assertContains(response, "came back together after splitting into Groups")
        self.assertNotContains(response, "not split")
        self.assertFalse(self.exists("aa-the-bell-beneath-4"))
