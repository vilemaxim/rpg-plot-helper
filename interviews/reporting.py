"""The report Interview's pages (#43, ADR-0009): writing an After-Action
Report with the app's LLM.

When the Mod has a Dry Run, the Mod Runner first walks the Path the Stretch
took through it, with no LLM (`walking`): from a Hook, or by default from
where the last report's Path stopped, to the ending reached or the scene
where play stopped. Saying where play stopped starts the Interview from that
Path; on such a Mod there is no other way in. A Mod with no Dry Run skips the
walk, and the LLM asks what happened and where play stopped.

Before the walk, when the Mod has more than one live Assignment at one of
its Events, the Mod Runner says which Event and Group the report is for
(`groups`, ADR-0011), and the walk starts where that Group stopped.

From there it runs as the Mod Interviews do (`views.Interviewing`), with
plotcanon's report instructions. The report it writes is checked and fixed
as a pasted one is checked (`canon.submitting.check`), and must also give
the Path walked as its `path`, or no `path` when none was walked. The Path,
not the LLM, proposes `finished`; the Mod Runner confirms or changes it as
they file, through `canon.submitting.submit`, as a pasted report is filed.
"""

from dataclasses import dataclass
from functools import cached_property

import plotcanon
import yaml
from django.contrib import messages as notices
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from plotcanon import editing

from canon import access, submitting
from canon.forms import ReportForm
from canon.presenting import render_markdown
from canon.views import readable_mod_or_404
from organizations.views import world_or_404

from . import config, conversation, groups, walking
from .config import Kind
from .conversation import Tampered
from .views import SURFACE, Interviewing, a_turn, started_over, submitted

# The values the form to file a report may give for `finished`, as YAML.
FINISHED = {"true", "false"}


@dataclass
class Reporting(Interviewing):
    """A report Interview on `mod`. `walked` is the Path its Mod Runner
    walked through the Mod's Dry Run, or None when none was; it is taken up
    with the Interview's turns (`opened`, `in_progress`)."""

    walked: walking.Walked | None = None
    # The Event and Group the report is for, when they were asked
    # (`groups`): the Event's id, or "" when not asked, and the Group's
    # label, or "" for the whole Mod.
    event: str = ""
    group: str = ""

    pasted = "a report"
    intro = "interviews/intro_report.html"
    file_template = "interviews/report_file.html"

    @property
    def title(self):
        return f"Report on {self.mod.name}"

    @cached_property
    def story(self):
        """The Mod's Dry Run, as plotcanon reads it."""
        return plotcanon.story(self.mod.text)

    @property
    def path(self):
        return list(self.walked.path) if self.walked else None

    @property
    def finished(self):
        """What the Path walked proposes for `finished`, as YAML ("true" when
        it ends at an ending, "false" at a scene), or None with no Path."""
        if self.walked is None:
            return None
        ends = plotcanon.check_path(self.story, self.path,
                                    continues_from=self.walked.last_stop).finished
        return None if ends is None else ("true" if ends else "false")

    def context(self, turns=()):
        return {**super().context(turns), "path": self.path, "finished": self.finished,
                "group": self.group, "group_page": self.urls()["group"]}

    def urls(self):
        return {**super().urls(), "group": reverse("report-group",
                                                   args=[self.world.pk, self.mod.slug])}

    def stop(self, person):
        """Where play stopped on the Mod before this report, for its Group
        at its Event when they were asked, as this person may read the
        World."""
        return plotcanon.last_stop(access.readable_files(self.world, person), self.mod.slug,
                                   group=self.group or None, event=self.event or None)

    def in_progress(self, person):
        transcript, turns = super().in_progress(person)
        self._take_up_walk(transcript, person)
        return transcript, turns

    def opened(self, transcript, person):
        turns = super().opened(transcript, person)
        self._take_up_walk(transcript, person)
        return turns

    def _take_up_walk(self, transcript, person):
        kept = conversation.interview_named(transcript, self.world, person, self.mod)
        self.walked = walking.Walked.from_json(kept.walk if kept else None)
        self.event, self.group = (kept.event, kept.group) if kept else ("", "")

    def system_prompt(self, person):
        """plotcanon's report instructions, given the Mod, the Path walked if
        any and where play last stopped, with only what this person may read
        in the World."""
        world = access.readable_files(self.world, person)
        stop = self.walked.last_stop if self.walked else self.stop(person)
        return plotcanon.interview_instructions(
            self.kind, SURFACE, world=world, mod=self.mod.text, path=self.path,
            continues_from=stop, event=self.event or None,
            group=self.group if self.event else None)

    @property
    def opener(self):
        """plotcanon's."""
        return plotcanon.interview_report_opener(self.path)

    def agrees(self, report):
        """Refuse a report whose `path` is not the Path walked, or that has a
        `path` when none was walked; whose `group` is not the Group asked
        for, or that has one when none was; or whose `event` is not the
        Event asked for."""
        groups.agrees(report, self.mod, self.event, self.group)
        given = report.fields.get("path")
        if self.walked is None:
            if given not in (None, []):
                raise submitting.ReportRefused(
                    f"That report has a `path`, but no Path was walked for it, since "
                    f"{self.mod.name} has no Dry Run. Leave `path` out.")
        elif given != self.path:
            raise submitting.ReportRefused(
                "That report's `path` is not the Path the Mod Runner walked. Give it "
                "exactly as walked:",
                errors=yaml.safe_dump({"path": self.path}, sort_keys=False,
                                      allow_unicode=True).rstrip("\n"))

    def check(self, text):
        return lambda: submitting.check(self.world, self.mod, text, agrees=self.agrees)

    def file_form(self, data):
        return ReportForm(data)

    def as_given(self, text, data):
        """The report with `finished` as the Mod Runner confirmed or changed
        it on the form."""
        finished = data.get("finished", "")
        if finished not in FINISHED:
            return text
        try:
            return editing.set_field(text, "finished", finished)
        except editing.CannotEdit:
            return text  # plotcanon says what is wrong with the frontmatter

    def take_in(self, text, person):
        return submitting.submit(self.world, self.mod, text, person, agrees=self.agrees)

    def taken_in(self, request, saved, form):
        notices.success(request, "Report filed. Its Canon Changes are waiting to be decided.")
        return redirect("canon-detail", world_id=self.world.pk, kind="reports",
                        slug=saved.slug)

    def to_group(self):
        return redirect(self.urls()["group"])

    def to_walk(self):
        return redirect("report-walk", world_id=self.world.pk, slug=self.mod.slug)


def report_interview_or_404(request, world_id, slug):
    """A report Interview on a Mod, for anyone who may file a report on it
    (anyone who can open the World, #41) and may read it. Anyone else is told
    there is no such page."""
    world = world_or_404(request, world_id)
    mod = readable_mod_or_404(access.reading(world, request.user), slug)
    conversation.forget_idle()
    return Reporting(Kind.REPORT, world, config.llm_for(Kind.REPORT), mod)


def elsewhere(reporting):
    """Where to send the person instead of a report Interview, or None: the
    report page when the Interview is off, or when the Mod cannot be reported
    on, which that page says."""
    if reporting.llm is None or not submitting.can_be_reported_on(reporting.mod):
        return reporting.to_paste_path()
    return None


def transcript_and_turns(request, reporting):
    """The report Interview this request is about, taken up into
    `reporting`, as its transcript and turns: the one in progress for a
    page, or the one a posted transcript names. None for one tampered with,
    which is refused when the turn is taken."""
    if request.method == "GET":
        return reporting.in_progress(request.user)
    transcript = request.POST.get("transcript", "")
    try:
        return transcript, reporting.opened(transcript, request.user)
    except Tampered:
        return None


def not_walked(reporting, transcript):
    """Whether a report Interview would open with no Path on a Mod that has a
    Dry Run: none in progress, or one with no Path walked."""
    if not reporting.story.playable:
        return False
    return not transcript or reporting.walked is None


def group_still_to_ask(reporting, turns):
    """Whether the person is to be asked which Event and Group the report is
    for before it goes on: the Mod has more than one live Assignment at one
    of its Events (`groups`), and the Interview in hand has not been told,
    nor begun. One begun before it was needed goes on without."""
    if reporting.event or turns or reporting.walked is not None:
        return False
    return bool(groups.events_needing_a_group(reporting.mod))


@never_cache
@require_http_methods(["GET", "POST"])
def interview(request, world_id, slug):
    """A report Interview: the walk first, when the Mod has a Dry Run and no
    Interview begun from a walk is in progress; otherwise the Interview as it
    stands, or, for an answer, the LLM's next turn."""
    reporting = report_interview_or_404(request, world_id, slug)
    away = elsewhere(reporting)
    if away is not None:
        return away
    found = transcript_and_turns(request, reporting)
    if found is not None:
        transcript, turns = found
        if group_still_to_ask(reporting, turns):
            return reporting.to_group()
        if not_walked(reporting, transcript):
            return reporting.to_walk()
    return a_turn(request, reporting)


@never_cache
@require_http_methods(["GET", "POST"])
def walk_page(request, world_id, slug):
    """Walk the Path the Stretch took through the Mod's Dry Run, a step a
    page, with no LLM. Posted, it says play stopped where the walk is, and
    starts the report Interview from that Path, in place of any in
    progress."""
    reporting = report_interview_or_404(request, world_id, slug)
    away = elsewhere(reporting)
    if away is not None:
        return away
    world, mod, story = reporting.world, reporting.mod, reporting.story
    if not story.playable:
        return reporting.to_start()
    _, turns = reporting.in_progress(request.user)
    if group_still_to_ask(reporting, turns):
        return reporting.to_group()
    stop = reporting.stop(request.user)
    try:
        so_far = walking.walk_from(story, stop,
                                   request.POST if request.method == "POST" else request.GET)
    except walking.NoSuchWalk:
        raise Http404("No such step") from None
    if request.method == "POST":
        if not so_far.stoppable:
            return HttpResponseBadRequest("Play stops at a scene or an ending.")
        conversation.begin_from_walk(so_far.walked().to_json(), world, request.user,
                                     reporting.kind, mod, reporting.event, reporting.group)
        return reporting.to_start()
    return render(request, "interviews/walk.html", {
        **reporting.context(), "walk": so_far,
        "prose": render_markdown(so_far.here.prose),
        "scenes": walking.scenes_to_pick_up_at(story, stop) if so_far.at_premise else [],
        "names": {"from": walking.FROM, "choice": walking.CHOICE}})


@never_cache
@require_http_methods(["GET", "POST"])
def group_page(request, world_id, slug):
    """Ask which Group the report is for, at an Event where the Mod has more
    than one live Assignment (`groups`), first asking which Event when the
    Mod lists several. Posted, it starts the report Interview for them, in
    place of any in progress, from the walk if the Mod has a Dry Run. A Mod
    for which no Event needs a Group sends the person on to the Interview."""
    reporting = report_interview_or_404(request, world_id, slug)
    away = elsewhere(reporting)
    if away is not None:
        return away
    mod, person = reporting.mod, request.user
    needing = groups.events_needing_a_group(mod)
    if not needing:
        return reporting.to_start()
    events = dict(groups.events_of_mod(mod))

    def page(status=200, **shown):
        return render(request, "interviews/group.html", {
            **reporting.context(), "events": events, "one_event": len(events) == 1,
            "longest": plotcanon.MAX_GROUP_CHARACTERS, **shown}, status=status)

    if request.method == "GET":
        reporting.in_progress(person)
        if len(events) > 1:
            return page(chosen=reporting.event or needing[0])
        event = next(iter(events))
    else:
        event = request.POST.get("event", "")
        if event not in events:
            return HttpResponseBadRequest("That is not one of the Mod's Events.")
    group = ""
    if event in needing:
        asked = request.POST.get("asked")
        group = groups.group_label(request.POST.get("group", "")) if asked else ""
        # A blank label is no Group: the players played, or came back, together.
        problem = plotcanon.group_label_problem(group) if group else None
        if not asked or problem:
            return page(400 if problem else 200, event=event, event_name=events[event],
                        suggested=group[:plotcanon.MAX_GROUP_CHARACTERS] if problem
                        else groups.suggested(mod, event, person),
                        refused=problem or "")
    conversation.begin_from_walk(None, reporting.world, person, reporting.kind, mod,
                                 event, group)
    return reporting.to_start()


@never_cache
@require_POST
def submit(request, world_id, slug):
    """File the report the LLM gave, through the same `submitting.submit` as a
    pasted one."""
    return submitted(request, report_interview_or_404(request, world_id, slug))


@never_cache
@require_POST
def start_over(request, world_id, slug):
    """Abandon the report Interview in progress and start a new one, from the
    walk if the Mod has a Dry Run."""
    return started_over(request, report_interview_or_404(request, world_id, slug))
