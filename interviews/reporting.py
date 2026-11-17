"""The report Interview's pages (#43, ADR-0009): writing an After-Action
Report with the app's LLM.

When the Mod has a Dry Run, the Mod Runner first walks the Path the Stretch
took through it, with no LLM (`walking`): from a Hook, or by default from
where the last report's Path stopped, to the ending reached or the scene
where play stopped. Saying where play stopped starts the Interview from that
Path; on such a Mod there is no other way in. A Mod with no Dry Run skips the
walk, and the LLM asks what happened and where play stopped.

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
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from plotcanon import editing

from canon import access, submitting
from canon.forms import ReportForm
from canon.presenting import render_markdown
from canon.views import readable_mod_or_404
from organizations.views import world_or_404

from . import config, conversation, walking
from .config import Kind
from .conversation import Tampered
from .views import (SURFACE, Interviewing, a_turn, started_over,
                    submitted)

# The values the form to file a report may give for `finished`, as YAML.
FINISHED = {"true", "false"}


@dataclass
class Reporting(Interviewing):
    """A report Interview on `mod`. `walked` is the Path its Mod Runner
    walked through the Mod's Dry Run, or None when none was; it is taken up
    with the Interview's turns (`opened`, `in_progress`)."""

    walked: walking.Walked | None = None

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
        return {**super().context(turns), "path": self.path, "finished": self.finished}

    def in_progress(self, person):
        transcript, turns = super().in_progress(person)
        self._take_up_walk(transcript, person)
        return transcript, turns

    def opened(self, transcript, person):
        turns = super().opened(transcript, person)
        self._take_up_walk(transcript, person)
        return turns

    def _take_up_walk(self, transcript, person):
        self.walked = walking.Walked.from_json(
            conversation.walk_of(transcript, self.world, person, self.mod))

    def system_prompt(self, person):
        """plotcanon's report instructions, given the Mod, the Path walked if
        any and where play last stopped, with only what this person may read
        in the World."""
        world = access.readable_files(self.world, person)
        stop = (self.walked.last_stop if self.walked
                else plotcanon.last_stop(world, self.mod.slug))
        return plotcanon.interview_instructions(
            self.kind, SURFACE, world=world, mod=self.mod.text, path=self.path,
            continues_from=stop)

    @property
    def opener(self):
        return plotcanon.interview_report_opener(self.path)

    def agrees(self, report):
        """Refuse a report whose `path` is not the Path walked, or that has a
        `path` when none was walked."""
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


def not_walked(request, reporting):
    """Whether this request would open a report Interview with no Path on a
    Mod that has a Dry Run: none in progress, or one with no Path walked."""
    if not reporting.story.playable:
        return False
    if request.method == "GET":
        transcript, _ = reporting.in_progress(request.user)
    else:
        transcript = request.POST.get("transcript", "")
        try:
            reporting.opened(transcript, request.user)
        except Tampered:
            return False  # refused as tampered with when the turn is taken
    return not transcript or reporting.walked is None


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
    if not_walked(request, reporting):
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
    stop = plotcanon.last_stop(access.readable_files(world, request.user), mod.slug)
    try:
        so_far = walking.walk_from(story, stop,
                                   request.POST if request.method == "POST" else request.GET)
    except walking.NoSuchWalk:
        raise Http404("No such step") from None
    if request.method == "POST":
        if not so_far.stoppable:
            return HttpResponseBadRequest("Play stops at a scene or an ending.")
        conversation.begin_from_walk(so_far.walked().to_json(), world, request.user,
                                     reporting.kind, mod)
        return reporting.to_start()
    return render(request, "interviews/walk.html", {
        **reporting.context(), "walk": so_far,
        "prose": render_markdown(so_far.here.prose),
        "scenes": walking.scenes_to_pick_up_at(story, stop) if so_far.at_premise else [],
        "names": {"from": walking.FROM, "choice": walking.CHOICE}})


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
