"""The new-Mod Interview's pages (ADR-0008).

A Mod Writer, or a Plot Master, answers the LLM's questions until it gives
them the Mod file, reads it, and submits it through the same intake as a
pasted file (`canon.intake.submit_mod`). The LLM never submits.

Each turn streams back inside the request that sent the person's answer, as
one HTML page written while the LLM writes, with no background worker
(ADR-0003) and no script, so it works on any phone. Everything that needs the
database (who is asking, what they may read, the page around the reply) is
done before the reply starts: the stream itself runs after the request's
transaction has ended, so anything it writes to the database must open its
own with `organizations.tenancy.acting_as`.
"""

import logging

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

from . import config, spending
from .conversation import Tampered, mod_file_in, opened, sealed
from .providers import Ended, Message, ProviderError, Text

log = logging.getLogger(__name__)

KIND = "new-mod"
SURFACE = "web"
# Where the streamed reply and what follows it go in the rendered page.
REPLY, AFTER = "<!--interview:reply-->", "<!--interview:after-->"


class AnswerForm(forms.Form):
    said = forms.CharField(label="Your answer", max_length=20000,
                           widget=forms.Textarea(attrs={"rows": 5}))
    transcript = forms.CharField(required=False, widget=forms.HiddenInput)


def interview_or_404(request, world_id):
    """The World and the LLM for a new-Mod Interview in it, for someone who
    may write Mods there once it has Canon. Anyone else is told there is no
    such page. The LLM is None when new-Mod Interviews are off."""
    world = world_or_404(request, world_id)
    if not may_write_mods(request, world) or not documents_of(world).exists():
        raise Http404("No such page")
    return world, config.llm_for(KIND)


def system_prompt(world, person):
    """plotcanon's instructions for a new-Mod Interview, given only what this
    person may read in the World."""
    return plotcanon.interview_instructions(
        KIND, SURFACE, world=access.readable_files(world, person))


@never_cache
@require_http_methods(["GET", "POST"])
def interview(request, world_id):
    """Start an Interview, or take the person's answer and stream the LLM's
    next turn."""
    world, llm = interview_or_404(request, world_id)
    if llm is None:
        return redirect("canon-submit-mod", world_id=world.pk)
    if request.method == "GET":
        return render(request, "interviews/interview.html",
                      {"world": world, "form": AnswerForm(), "transcript": ""})
    form = AnswerForm(request.POST)
    try:
        turns = opened(request.POST.get("transcript", ""), world, request.user)
    except Tampered:
        return HttpResponseBadRequest("That Interview cannot be carried on. Start a new one.")
    if not form.is_valid():
        return render(request, "interviews/interview.html",
                      {"world": world, "turns": turns, "form": form,
                       "transcript": request.POST.get("transcript", "")})
    said = form.cleaned_data["said"]
    paused = spending.turn_refused(request.user, world.organization_id)
    if paused:
        return render(request, "interviews/interview.html",
                      {"world": world, "turns": turns, "form": form, "said": said,
                       "paused": paused, "transcript": request.POST.get("transcript", "")})
    asked = [*turns, Message("user", said)]
    page = render_to_string("interviews/interview.html",
                            {"world": world, "turns": asked, "streaming": True}, request)
    head, rest = page.split(REPLY, 1)
    middle, foot = rest.split(AFTER, 1)
    after = {"world": world, "csrf_token": get_token(request)}

    def what_follows(**context):
        return middle + render_to_string("interviews/after.html", {**after, **context})

    response = StreamingHttpResponse(
        streamed(head, foot, what_follows, llm.provider, system_prompt(world, request.user),
                 turns, said, lambda messages: sealed(messages, world, request.user),
                 spent=lambda usage: spending.record(world.organization_id, usage)),
        content_type="text/html; charset=utf-8")
    # Ask proxies such as nginx to pass each piece on as it comes.
    response["X-Accel-Buffering"] = "no"
    return response


def streamed(head, foot, what_follows, provider, system, turns, said, seal,
             spent=lambda usage: None):
    """The page for one turn, piece by piece: everything up to the reply, the
    reply as the LLM writes it, then what follows it. A turn that fails is not
    kept: the page carries the conversation as it was before it, with the
    person's answer ready to send again. `spent` is given the tokens the turn
    used, when the provider reports them, whether or not it is kept."""
    yield head
    pieces, ended = [], None
    asked = [*turns, Message("user", said)]
    try:
        for event in provider.stream_turn(system, asked):
            if isinstance(event, Text):
                pieces.append(event.text)
                yield escape(event.text)
            elif isinstance(event, Ended):
                ended = event
                spent(event.usage)
        if not "".join(pieces).strip() or ended is None:
            raise ProviderError("The LLM gave no answer.")
    except ProviderError as error:
        yield what_follows(failed=str(error), said=said, transcript=seal(turns))
    except Exception:  # noqa: BLE001 - the page has started; say so rather than stop dead
        log.exception("An Interview turn failed")
        yield what_follows(failed="Something went wrong with that turn.", said=said,
                           transcript=seal(turns))
    else:
        reply = "".join(pieces)
        yield what_follows(file=mod_file_in(reply), cut_off=ended.cut_off,
                           transcript=seal([*asked, Message("assistant", reply)]))
    yield foot


@never_cache
@require_POST
def submit(request, world_id):
    """Submit the Mod file the LLM gave, through the same intake as a pasted
    one. A refusal shows the Interview again, with the intake's errors and the
    conversation as it was."""
    world, llm = interview_or_404(request, world_id)
    if llm is None:
        raise Http404("No such page")
    transcript = request.POST.get("transcript", "")
    try:
        turns = opened(transcript, world, request.user)
    except Tampered:
        return HttpResponseBadRequest("That Interview cannot be carried on. Start a new one.")
    form = ModForm(request.POST)
    context = {"world": world, "turns": turns, "transcript": transcript,
               "form": AnswerForm(), "file": request.POST.get("text", "")}
    if not form.is_valid():
        return render(request, "interviews/interview.html",
                      {**context, "refused": " ".join(form.errors.get("__all__", []))
                       or "There was no Mod file to submit."})
    try:
        saved = intake.submit_mod(world, form.cleaned_data["contents"], request.user)
    except intake.ModRefused as refused:
        return render(request, "interviews/interview.html",
                      {**context, "refused": str(refused), "errors": refused.errors})
    return to_saved_mod(request, saved, one_to_a_line(form.cleaned_data["twine_warnings"]))


# Revising a draft (#47): the same Interview, started from the draft, why it
# was sent back and its open Flags, and submitted through the revise intake.

REVISE = "revise-mod"


def revise_interview_or_404(request, world_id, slug):
    """The World, the draft and the LLM for a revise Interview, for someone
    who may revise that Mod (`canon.views.may_revise`). Anyone else is told
    there is no such page. The LLM is None when revise Interviews are off."""
    world = world_or_404(request, world_id)
    mod = mod_or_404(world, slug)
    if not may_revise(request, world, mod):
        raise Http404("No such page")
    return world, mod, config.llm_for(REVISE)


def flags_for_the_llm(world, mod):
    """The draft's open Flags as plotcanon takes them: the Feature each
    touches, and what the change does to it."""
    pairs = []
    for flag in Flag.objects.open_in(world).filter(mod=mod).select_related("change"):
        change = flag.change
        message = wording(change.kind)
        if change.before or change.after:
            message += f", from {change.before or 'nothing'} to {change.after or 'nothing'}"
        if change.summary:
            message += f": {change.summary}"
        pairs.append((change.entity, message))
    return pairs


def revise_system_prompt(world, mod, person):
    """plotcanon's instructions for revising this draft, given only what this
    person may read in the World."""
    return plotcanon.interview_instructions(
        REVISE, SURFACE, world=access.readable_files(world, person), draft=mod.text,
        sent_back_reason=mod.sent_back_reason, flags=flags_for_the_llm(world, mod))


@never_cache
@require_http_methods(["GET", "POST"])
def revise_interview(request, world_id, slug):
    """Start an Interview to revise a draft, or take the person's answer and
    stream the LLM's next turn."""
    world, mod, llm = revise_interview_or_404(request, world_id, slug)
    if llm is None:
        return redirect("canon-revise", world_id=world.pk, slug=mod.slug)
    if not is_draft(mod):
        notices.error(request, f"{mod.name} is not a draft, and only a draft can be revised.")
        return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)
    base = {"world": world, "mod": mod}
    if request.method == "GET":
        return render(request, "interviews/interview.html",
                      {**base, "form": AnswerForm(), "transcript": ""})
    form = AnswerForm(request.POST)
    try:
        turns = opened(request.POST.get("transcript", ""), world, request.user)
    except Tampered:
        return HttpResponseBadRequest("That Interview cannot be carried on. Start a new one.")
    if not form.is_valid():
        return render(request, "interviews/interview.html",
                      {**base, "turns": turns, "form": form,
                       "transcript": request.POST.get("transcript", "")})
    said = form.cleaned_data["said"]
    page = render_to_string("interviews/interview.html",
                            {**base, "turns": [*turns, Message("user", said)],
                             "streaming": True}, request)
    head, rest = page.split(REPLY, 1)
    middle, foot = rest.split(AFTER, 1)
    after = {**base, "csrf_token": get_token(request)}

    def what_follows(**context):
        return middle + render_to_string("interviews/after.html", {**after, **context})

    response = StreamingHttpResponse(
        streamed(head, foot, what_follows, llm.provider,
                 revise_system_prompt(world, mod, request.user), turns, said,
                 lambda kept: sealed(kept, world, request.user)),
        content_type="text/html; charset=utf-8")
    response["X-Accel-Buffering"] = "no"
    return response


@never_cache
@require_POST
def revise_submit(request, world_id, slug):
    """Submit the revised file the LLM gave through the same revise intake as
    a pasted one, so the id rule and the draft's history hold as they do there.
    A refusal shows the Interview again, with the intake's errors."""
    world, mod, llm = revise_interview_or_404(request, world_id, slug)
    if llm is None:
        raise Http404("No such page")
    transcript = request.POST.get("transcript", "")
    try:
        turns = opened(transcript, world, request.user)
    except Tampered:
        return HttpResponseBadRequest("That Interview cannot be carried on. Start a new one.")
    form = ModForm(request.POST)
    context = {"world": world, "mod": mod, "turns": turns, "transcript": transcript,
               "form": AnswerForm(), "file": request.POST.get("text", "")}
    if not form.is_valid():
        return render(request, "interviews/interview.html",
                      {**context, "refused": " ".join(form.errors.get("__all__", []))
                       or "There was no Mod file to submit."})
    try:
        saved = intake.revise(world, mod, form.cleaned_data["contents"], request.user)
    except intake.ModRefused as refused:
        return render(request, "interviews/interview.html",
                      {**context, "refused": str(refused), "errors": refused.errors})
    return to_saved_mod(request, saved, one_to_a_line(form.cleaned_data["twine_warnings"]))
