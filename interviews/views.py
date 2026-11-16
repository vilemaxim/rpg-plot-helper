"""The Interview's pages (ADR-0008): writing a new Mod, or revising a draft.

A Mod Writer, or a Plot Master, answers the LLM's questions until it gives
them the Mod file, reads it, and submits it through the same intake as a
pasted file (`canon.intake.submit_mod`, or `canon.intake.revise` for a
draft). The LLM never submits. Both kinds run the same way (`Interviewing`):
only where they start, what the LLM is told and which intake takes the file
in differ.

Each turn streams back inside the request that sent the person's answer, as
one HTML page written while the LLM writes, with no background worker
(ADR-0003) and no script, so it works on any phone. Everything that needs the
database (who is asking, what they may read, the page around the reply) is
done before the reply starts: the stream itself runs after the request's
transaction has ended, so anything it writes to the database must open its
own with `organizations.tenancy.acting_as`.
"""

import logging
from dataclasses import dataclass
from typing import Any

import plotcanon
from django import forms
from django.contrib import messages as notices
from django.http import Http404, HttpResponseBadRequest, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.html import escape
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from canon import access, intake
from canon.forms import ModForm
from canon.models import Flag
from canon.presenting import wording
from canon.storing import one_to_a_line
from canon.views import documents_of, is_draft, may_revise, mod_or_404, to_saved_mod
from organizations.views import may_write_mods, world_or_404

from . import config, conversation, fixing, spending
from .conversation import Tampered, mod_file_in, opened, sealed
from .providers import Ended, Message, ProviderError, Text

log = logging.getLogger(__name__)

KIND = "new-mod"
REVISE = "revise-mod"
SURFACE = "web"
# Where the streamed reply and what follows it go in the rendered page.
REPLY, AFTER = "<!--interview:reply-->", "<!--interview:after-->"


class AnswerForm(forms.Form):
    said = forms.CharField(label="Your answer", max_length=20000,
                           widget=forms.Textarea(attrs={"rows": 5}))
    transcript = forms.CharField(required=False, widget=forms.HiddenInput)


@dataclass
class Interviewing:
    """One kind of Interview in a World, as its pages run it: a new Mod, or a
    revision of the draft `mod`. `llm` is None when that kind is off."""

    kind: str
    world: Any
    llm: Any
    mod: Any = None

    def context(self):
        """What every page of it is rendered with."""
        if self.mod is None:
            return {"world": self.world}
        return {"world": self.world, "mod": self.mod}

    def system_prompt(self, person):
        """plotcanon's instructions for this Interview, given only what this
        person may read in the World; for a revision, also the draft, why it
        was sent back and its Flags (`flags_for_the_llm`)."""
        world = access.readable_files(self.world, person)
        if self.mod is None:
            return plotcanon.interview_instructions(self.kind, SURFACE, world=world)
        return plotcanon.interview_instructions(
            self.kind, SURFACE, world=world, draft=self.mod.text,
            sent_back_reason=self.mod.sent_back_reason,
            flags=flags_for_the_llm(self.world, self.mod))

    def problems(self, person, text):
        """What the intake would refuse in this file, as the person may read
        it (`fixing.problems`)."""
        return fixing.problems(self.world, person, text, self.mod)

    def take_in(self, text, person):
        """Submit the file through the intake a pasted one goes through."""
        if self.mod is None:
            return intake.submit_mod(self.world, text, person)
        return intake.revise(self.world, self.mod, text, person)

    def to_paste_path(self):
        """Where the Mod is pasted or uploaded instead, when this kind is off."""
        if self.mod is None:
            return redirect("canon-submit-mod", world_id=self.world.pk)
        return redirect("canon-revise", world_id=self.world.pk, slug=self.mod.slug)

    def to_start(self):
        """The Interview's page, to start it afresh."""
        if self.mod is None:
            return redirect("interview", world_id=self.world.pk)
        return redirect("revise-interview", world_id=self.world.pk, slug=self.mod.slug)


def interview_or_404(request, world_id):
    """A new-Mod Interview in a World, for someone who may write Mods there
    once it has Canon. Anyone else is told there is no such page."""
    world = world_or_404(request, world_id)
    if not may_write_mods(request, world) or not documents_of(world).exists():
        raise Http404("No such page")
    conversation.forget_idle()
    return Interviewing(KIND, world, config.llm_for(KIND))


def revise_interview_or_404(request, world_id, slug):
    """A revise Interview of a draft, for someone who may revise that Mod
    (`canon.views.may_revise`). Anyone else is told there is no such page."""
    world = world_or_404(request, world_id)
    mod = mod_or_404(world, slug)
    if not may_revise(request, world, mod):
        raise Http404("No such page")
    conversation.forget_idle()
    return Interviewing(REVISE, world, config.llm_for(REVISE), mod)


@never_cache
@require_http_methods(["GET", "POST"])
def interview(request, world_id):
    """Start an Interview, or take the person's answer and stream the LLM's
    next turn."""
    return a_turn(request, interview_or_404(request, world_id))


@never_cache
@require_POST
def submit(request, world_id):
    """Submit the Mod file the LLM gave."""
    return submitted(request, interview_or_404(request, world_id))


@never_cache
@require_POST
def start_over(request, world_id):
    """Abandon the Interview in progress and start a new one."""
    return started_over(request, interview_or_404(request, world_id))


@never_cache
@require_http_methods(["GET", "POST"])
def revise_interview(request, world_id, slug):
    """Start an Interview to revise a draft, or take the person's answer and
    stream the LLM's next turn."""
    interviewing = revise_interview_or_404(request, world_id, slug)
    mod = interviewing.mod
    if interviewing.llm is not None and not is_draft(mod):
        notices.error(request, f"{mod.name} is not a draft, and only a draft can be revised.")
        return redirect("canon-detail", world_id=interviewing.world.pk, kind="mods",
                        slug=mod.slug)
    return a_turn(request, interviewing)


@never_cache
@require_POST
def revise_submit(request, world_id, slug):
    """Submit the revised file the LLM gave, through the same revise intake as
    a pasted one, so the id rule and the draft's history hold as they do
    there."""
    return submitted(request, revise_interview_or_404(request, world_id, slug))


@never_cache
@require_POST
def revise_start_over(request, world_id, slug):
    """Abandon the revise Interview in progress and start a new one."""
    return started_over(request, revise_interview_or_404(request, world_id, slug))


def a_turn(request, interviewing):
    """The Interview as it stands, or, for an answer, the LLM's next turn
    streamed back. With its kind off, the paste path instead."""
    if interviewing.llm is None:
        return interviewing.to_paste_path()
    world, mod, llm = interviewing.world, interviewing.mod, interviewing.llm
    person, base = request.user, interviewing.context()
    if request.method == "GET":
        transcript, turns = conversation.in_progress(world, person, interviewing.kind, mod)
        replies = [turn.text for turn in turns if turn.role == "assistant"]
        return render(request, "interviews/interview.html",
                      {**base, "form": AnswerForm(), "transcript": transcript,
                       "turns": turns, "file": mod_file_in(replies[-1]) if replies else None})
    transcript = request.POST.get("transcript", "")
    form = AnswerForm(request.POST)
    try:
        turns = opened(transcript, world, person, mod)
    except Tampered:
        return HttpResponseBadRequest("That Interview cannot be carried on. Start a new one.")
    if not form.is_valid():
        return render(request, "interviews/interview.html",
                      {**base, "turns": turns, "form": form, "transcript": transcript})
    said = form.cleaned_data["said"]
    paused = spending.turn_refused(person, world.organization_id)
    if paused:
        return render(request, "interviews/interview.html",
                      {**base, "turns": turns, "form": form, "said": said, "paused": paused,
                       "transcript": transcript})
    page = render_to_string("interviews/interview.html",
                            {**base, "turns": [*turns, Message("user", said)],
                             "streaming": True}, request)
    head, rest = page.split(REPLY, 1)
    middle, foot = rest.split(AFTER, 1)
    after = {**base, "csrf_token": get_token(request)}

    def what_follows(**context):
        return middle + render_to_string("interviews/after.html", {**after, **context})

    response = StreamingHttpResponse(
        streamed(head, foot, what_follows, llm.provider, interviewing.system_prompt(person),
                 turns, said,
                 lambda kept: sealed(kept, world, person, interviewing.kind, transcript, mod),
                 check=lambda text: interviewing.problems(person, text),
                 max_fix_attempts=llm.settings.max_fix_attempts,
                 spent=lambda usage: spending.record(world.organization_id, usage)),
        content_type="text/html; charset=utf-8")
    # Ask proxies such as nginx to pass each piece on as it comes.
    response["X-Accel-Buffering"] = "no"
    return response


def streamed(head, foot, what_follows, provider, system, turns, said, seal, check=None,
             max_fix_attempts=0, spent=lambda usage: None):
    """The page for one turn, piece by piece: everything up to the reply, the
    reply as the LLM writes it, then what follows it. A turn that fails is not
    kept: the page carries the conversation as it was before it, with the
    person's answer ready to send again.

    A Mod file in the reply is held back and `check`ed (`fixing`): if it has
    problems, they go back to the LLM, up to `max_fix_attempts` times, and its
    next reply follows a note saying so. The conversation kept is the
    person's answer and the last reply; the fixing in between is the app's.

    `spent` is given the tokens each LLM call used, the person's turn and
    each fix attempt alike, when the provider reports them, whether or not
    the turn is kept."""
    yield head
    asked = [*turns, Message("user", said)]
    conversation, fixes = asked, 0
    try:
        while True:
            shown = fixing.FilesHeldBack()
            reply, ended = yield from one_turn(provider, system, conversation, shown, spent)
            file = mod_file_in(reply)
            problems = check(file) if file and check else None
            if problems is None or fixes == max_fix_attempts:
                break
            fixes += 1
            yield render_to_string("interviews/fixing.html")
            conversation = [*conversation, Message("assistant", reply),
                            Message("user", fixing.fix_request(problems))]
    except ProviderError as error:
        yield what_follows(failed=str(error), said=said, transcript=seal(turns))
    except Exception:  # noqa: BLE001 - the page has started; say so rather than stop dead
        log.exception("An Interview turn failed")
        yield what_follows(failed="Something went wrong with that turn.", said=said,
                           transcript=seal(turns))
    else:
        yield what_follows(file=file, problems=problems, fixes=fixes, cut_off=ended.cut_off,
                           transcript=seal([*asked, Message("assistant", reply)]))
    yield foot


def one_turn(provider, system, messages, shown, spent=lambda usage: None):
    """Stream one reply from the LLM, as `shown` lets the person read it.
    Returns the whole reply and its `Ended`."""
    pieces, ended = [], None
    for event in provider.stream_turn(system, messages):
        if isinstance(event, Text):
            pieces.append(event.text)
            yield escape(shown.feed(event.text))
        elif isinstance(event, Ended):
            ended = event
            spent(event.usage)
    yield escape(shown.end())
    if not "".join(pieces).strip() or ended is None:
        raise ProviderError("The LLM gave no answer.")
    return "".join(pieces), ended


def submitted(request, interviewing):
    """Submit the Mod file the LLM gave, through the same intake as a pasted
    one. A refusal shows the Interview again, with the intake's errors and the
    conversation as it was."""
    if interviewing.llm is None:
        raise Http404("No such page")
    world, mod = interviewing.world, interviewing.mod
    transcript = request.POST.get("transcript", "")
    try:
        turns = opened(transcript, world, request.user, mod)
    except Tampered:
        return HttpResponseBadRequest("That Interview cannot be carried on. Start a new one.")
    form = ModForm(request.POST)
    context = {**interviewing.context(), "turns": turns, "transcript": transcript,
               "form": AnswerForm(), "file": request.POST.get("text", "")}
    if not form.is_valid():
        return render(request, "interviews/interview.html",
                      {**context, "refused": " ".join(form.errors.get("__all__", []))
                       or "There was no Mod file to submit."})
    try:
        saved = interviewing.take_in(form.cleaned_data["contents"], request.user)
    except intake.ModRefused as refused:
        return render(request, "interviews/interview.html",
                      {**context, "refused": str(refused), "errors": refused.errors})
    conversation.forget(transcript, world, request.user, mod)
    return to_saved_mod(request, saved, one_to_a_line(form.cleaned_data["twine_warnings"]))


def started_over(request, interviewing):
    """Abandon the Interview in progress, deleting its turns, and start a new
    one."""
    conversation.forget(request.POST.get("transcript", ""), interviewing.world, request.user,
                        interviewing.mod)
    return interviewing.to_start()


def flags_for_the_llm(world, mod):
    """The Flags the revision should answer, as plotcanon takes them: the
    Feature each touches, and what the change does to it. They are the
    draft's open Flags and those its latest send-back resolved
    (`canon.resolving.send_back`), which the Plot Master sent it back over."""
    flags = Flag.objects.open_in(world).filter(mod=mod)
    if mod.sent_back_at is not None:
        # Sending back resolves the Mod's open Flags just after it notes when
        # it was sent back; an earlier send-back resolved its own before that.
        flags = flags | Flag.objects.filter(
            organization=world.organization, world=world, mod=mod,
            resolution=Flag.Resolution.SENT_BACK, resolved_at__gte=mod.sent_back_at)
    pairs = []
    for flag in flags.select_related("change").order_by("pk"):
        change = flag.change
        message = wording(change.kind)
        if change.before or change.after:
            message += f", from {change.before or 'nothing'} to {change.after or 'nothing'}"
        if change.summary:
            message += f": {change.summary}"
        pairs.append((change.entity, message))
    return pairs
