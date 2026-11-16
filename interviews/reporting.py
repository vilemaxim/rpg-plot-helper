"""The report Interview's pages (#43, ADR-0009): writing an After-Action
Report with the app's LLM.

When the Mod has a Dry Run, the Mod Runner first walks the Path the Stretch
took through it, with no LLM (`walking`): from a Hook, or by default from
where the last report's Path stopped, to the ending reached or the scene
where play stopped. Saying where play stopped starts the Interview from that
Path. A Mod with no Dry Run skips the walk, and the LLM asks what happened
and where play stopped.

From there it runs as the Mod Interviews do (`views.Interviewing`), with
plotcanon's report instructions, and the report it writes is checked, fixed
and filed through `canon.submitting`, as a pasted one is. The Path proposes
`finished`, and the Mod Runner confirms or changes it as they file.
"""

from dataclasses import dataclass

import plotcanon
from django.contrib import messages as notices
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from plotcanon import editing

from canon import access, submitting
from canon.forms import ReportForm
from canon.presenting import render_markdown
from organizations.views import world_or_404

from . import config, conversation, walking
from .config import Kind
from .views import Interviewing, a_turn, readable_mod_or_404, started_over, submitted

SURFACE = "web"
# The values the form to file a report may give for `finished`, as YAML.
FINISHED = {"true": "true", "false": "false"}


@dataclass
class Reporting(Interviewing):
    """A report Interview on `mod`. `walk` is the Path its Mod Runner walked
    through the Mod's Dry Run and where play had stopped before it, as
    `Interview.walk` keeps them, or None when no Path was walked."""

    walk: dict | None = None

    @property
    def path(self):
        return self.walk["path"] if self.walk else None

    def context(self, turns=()):
        return {**super().context(turns), "path": self.path}

    def carry_on(self, transcript, person):
        self.walk = conversation.walk_of(transcript, self.world, person, self.mod)

    def system_prompt(self, person):
        """plotcanon's report instructions, given the Mod, the Path walked if
        any and where play last stopped, with only what this person may read
        in the World."""
        world = access.readable_files(self.world, person)
        stop = (plotcanon.LastStop(**self.walk["last_stop"]) if self.walk
                else plotcanon.last_stop(world, self.mod.slug))
        return plotcanon.interview_instructions(
            self.kind, SURFACE, world=world, mod=self.mod.text, path=self.path,
            continues_from=stop)

    @property
    def opener(self):
        return plotcanon.interview_report_opener(self.path)

    def check(self, text):
        return lambda: submitting.check(self.world, self.mod, text)

    def file_form(self, data):
        return ReportForm(data)

    def as_given(self, text, data):
        """The report with `finished` as the Mod Runner confirmed or changed
        it on the form."""
        finished = FINISHED.get(data.get("finished", ""))
        if finished is None:
            return text
        try:
            return editing.set_field(text, "finished", finished)
        except editing.CannotEdit:
            return text  # plotcanon says what is wrong with the frontmatter

    def take_in(self, text, person):
        return submitting.submit(self.world, self.mod, text, person)

    def taken_in(self, request, saved, form):
        notices.success(request, "Report filed. Its Canon Changes are waiting to be decided.")
        return redirect("canon-detail", world_id=self.world.pk, kind="reports",
                        slug=saved.slug)


def report_interview_or_404(request, world_id, slug):
    """A report Interview on a Mod, for anyone who may file a report on it
    (anyone who can open the World, #41) and may read it. Anyone else is told
    there is no such page."""
    world = world_or_404(request, world_id)
    mod = readable_mod_or_404(request, world, slug)
    conversation.forget_idle()
    return Reporting(Kind.REPORT, world, config.llm_for(Kind.REPORT), mod)


def elsewhere(reporting):
    """Where to send the person instead of a report Interview, or None: the
    report page when the Interview is off, or when the Mod cannot be reported
    on, which that page says."""
    if reporting.llm is None or not submitting.can_be_reported_on(reporting.mod):
        return reporting.to_paste_path()
    return None


def has_dry_run(mod):
    return plotcanon.story(mod.text).playable


@never_cache
@require_http_methods(["GET", "POST"])
def interview(request, world_id, slug):
    """A report Interview: the walk first, when the Mod has a Dry Run and none
    is in progress; otherwise the Interview as it stands, or, for an answer,
    the LLM's next turn."""
    reporting = report_interview_or_404(request, world_id, slug)
    away = elsewhere(reporting)
    if away is not None:
        return away
    if request.method == "GET" and has_dry_run(reporting.mod):
        transcript, _ = conversation.in_progress(reporting.world, request.user,
                                                 reporting.kind, reporting.mod)
        if not transcript:
            return redirect("report-walk", world_id=reporting.world.pk,
                            slug=reporting.mod.slug)
    return a_turn(request, reporting)


@never_cache
@require_http_methods(["GET", "POST"])
def walk(request, world_id, slug):
    """Walk the Path the Stretch took through the Mod's Dry Run, a step a
    page, with no LLM. Posted, it says play stopped where the walk is, and
    starts the report Interview from that Path, in place of any in
    progress."""
    reporting = report_interview_or_404(request, world_id, slug)
    away = elsewhere(reporting)
    if away is not None:
        return away
    world, mod = reporting.world, reporting.mod
    story = plotcanon.story(mod.text)
    if not story.playable:
        return reporting.to_start()
    stop = plotcanon.last_stop(access.readable_files(world, request.user), mod.slug)
    try:
        walked = walking.walk(story, stop,
                              request.POST if request.method == "POST" else request.GET)
    except walking.NoSuchWalk:
        raise Http404("No such step") from None
    if request.method == "POST":
        if not walked.stoppable:
            return HttpResponseBadRequest("Play stops at a scene or an ending.")
        conversation.walked(walked.kept(), world, request.user, reporting.kind, mod)
        return reporting.to_start()
    return render(request, "interviews/walk.html", {
        **reporting.context(), "walk": walked,
        "prose": render_markdown(walked.here.prose),
        "scenes": walking.scenes_to_pick_up_at(story, stop) if walked.at_premise else [],
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
