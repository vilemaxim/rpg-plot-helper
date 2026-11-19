"""World review (#61): the app's LLM looks across a whole World for drift,
Plots that lost their way, undecided history and chances to bring back
recurring NPCs and dormant Plots, and writes one report for the plot team.
It is advice only: nothing acts on it.

`review(world, by=...)` runs one and keeps it (`WorldReview`). The LLM reads
the World as the plot team does, whoever runs it (ADR-0013, as ADR-0012 for
a Reconciliation), and is given plotcanon's check findings on the World so it
does not repeat them. What it is told is plotcanon's
(`plotcanon.world_review_instructions`), and what it writes is read by
plotcanon (`plotcanon.read_world_review`). It is given the whole World or
nothing: a World too large for the configured model is refused.

After each Event, the plot team is offered one on the World's page
(`suggestion`), for the latest Event that has ended, until a review is run
or the suggestion dismissed. Where an Organization Admin has turned it on
(`organizations.world_reviewing`), the scheduled `run_world_reviews` command
runs it instead (`run_scheduled`): there is no background worker (ADR-0003).

A run is one LLM call, and its tokens count toward the Organization's
monthly cap (ADR-0008, `spending`): at the cap it does not run.
"""

import datetime
import logging
import re
from dataclasses import dataclass

import plotcanon
from django.db import IntegrityError, connection
from django.utils import timezone

from canon import access
from canon.assignments import last_day
from canon.interludes import is_interlude
from organizations import tenancy
from organizations.models import Organization, World
from organizations.world_reviewing import SETTING

from . import config, spending
from .models import WorldReview, WorldReviewDismissal
from .one_report import NotWritten, sections_of, written

SURFACE = "web"
# The one message the LLM is sent: its instructions say what to write.
ASKED = "Review the World."
CANCELLED = "cancelled"
# Roughly how many characters a token is, to tell before a call whether the
# World fits the model's context window. Text runs nearer four; three errs
# toward refusing a World that would only just have fitted.
CHARACTERS_PER_TOKEN = 3

OFF = "World review is not set up on this site."
TOO_LARGE = "This World is too large for a World review with the configured model."
# What providers say when a prompt is longer than the model can read.
PROMPT_TOO_LONG = re.compile(r"prompt is too long|context.length|context window|too many tokens",
                             re.IGNORECASE)

log = logging.getLogger(__name__)


class NotReviewed(NotWritten):
    """No World review was kept. `str()` is a sentence for the plot team
    saying why: it is off, the Organization has reached its monthly tokens,
    the World is too large, or the LLM failed."""


def today():
    return timezone.localdate()


@dataclass(frozen=True)
class EndedEvent:
    """An Event that has ended: its id, its name and its last day."""

    id: str
    name: str
    on: datetime.date


def latest_ended(world):
    """The latest Event of the World whose last day has passed, or None.
    Interludes and cancelled Events are passed over: a review follows play,
    and neither had any."""
    ended = []
    for event in access.documents_in(world).filter(kind="event"):
        day = last_day(event)
        if day is None or day >= today() or is_interlude(event) \
                or event.fields.get("status") == CANCELLED:
            continue
        ended.append(EndedEvent(event.slug, event.name, day))
    return max(ended, key=lambda event: (event.on, event.id), default=None)


def reviewed_after(world, event):
    """Whether the World has been reviewed since this Event ended."""
    return WorldReview.objects.filter(world=world, event=event).exists()


def suggestion(world):
    """The Event the plot team is offered a World review after, or None:
    World review is off, no Event has ended, or the latest has been reviewed
    since or its suggestion dismissed. Never more than the one."""
    if config.world_review_llm() is None:
        return None
    event = latest_ended(world)
    if event is None or reviewed_after(world, event.id) \
            or WorldReviewDismissal.objects.filter(world=world, event=event.id).exists():
        return None
    return event


def dismiss(world, event, by):
    """Stop suggesting a World review after this Event (its id)."""
    WorldReviewDismissal.objects.get_or_create(
        world=world, event=event,
        defaults={"organization_id": world.organization_id, "dismissed_by": by})


def instructions(world):
    """plotcanon's instructions for reviewing the World as the plot team
    reads it, with plotcanon's findings on it."""
    files = access.as_plot_team(world).files()
    return plotcanon.world_review_instructions(
        SURFACE, world=files, findings=list(plotcanon.load_world(files).findings))


def fits(llm, system):
    """Whether `system`, and the most the LLM may write, fit the model's
    context window, by an estimate that errs toward no."""
    settings = llm.settings
    return len(system) / CHARACTERS_PER_TOKEN + settings.max_tokens <= settings.context_tokens


def review(world, *, by):
    """Review the World and keep the report. `by` is the person who asked,
    or None for the scheduled command. Returns the `WorldReview`. Raises
    `NotReviewed` having kept nothing, though the tokens of a call that
    failed are counted all the same.

    Runs as the World's Organization, as a request does: the caller checks
    that `by` may (a Plot Master, `organizations.views.is_plot_master`)."""
    llm = config.world_review_llm()
    if llm is None:
        raise NotReviewed(OFF)
    refused = spending.tokens_refused(world.organization_id, "World reviews")
    if refused:
        raise NotReviewed(refused)
    system = instructions(world)
    if not fits(llm, system):
        raise NotReviewed(TOO_LARGE)
    event = latest_ended(world)
    try:
        text = written(llm, system, ASKED,
                       lambda usage: spending.record(world.organization_id, usage), NotReviewed)
    except NotReviewed as failed:
        if PROMPT_TOO_LONG.search(str(failed)):
            raise NotReviewed(TOO_LARGE) from None
        raise
    read = plotcanon.read_world_review(text)
    return WorldReview.objects.create(
        organization_id=world.organization_id, world=world, ran_by=by, scheduled=by is None,
        event=event.id if event else "", model=llm.settings.model, text=text,
        sections=sections_of(read), problems=list(read.problems))


def of(world):
    """The World's reviews, latest first."""
    return WorldReview.objects.filter(world=world).select_related("ran_by")


# ── Run by the scheduled command ────────────────────────────────────────────

@dataclass(frozen=True)
class Outcome:
    """What the scheduled command did with one World: `said` names it, and
    the Event when it was `reviewed`; `why` says why not."""

    said: str
    reviewed: bool
    why: str = ""


def run_scheduled():
    """Review every World whose setting is on and whose latest ended Event
    has no review since. Returns an `Outcome` for each World it tried. Safe
    to run again at once, or alongside another run: a World another run is
    reviewing is passed over, and none is reviewed twice for an Event."""
    if config.world_review_llm() is None:
        return []
    with tenancy.all_organizations():
        organizations = list(Organization.objects.values_list("pk", flat=True))
    outcomes = []
    for organization in organizations:
        with tenancy.acting_as(organization=organization):
            worlds = list(SETTING.worlds_on(organization).values_list("pk", flat=True))
        for world in worlds:
            outcome = _scheduled(organization, world)
            if outcome is not None:
                outcomes.append(outcome)
    return outcomes


def _claimed(world_id):
    """Claim the World for this run until its transaction ends, or say
    another run has. An advisory lock, not the World's row, so that the
    plot team can still rename the World while the LLM writes."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                       [f"world-review:{world_id}"])
        return cursor.fetchone()[0]


def _scheduled(organization, world_id):
    """Review one World for the scheduled command if it is due. A World
    another run has claimed is passed over. None if it was not due."""
    try:
        with tenancy.acting_as(organization=organization):
            world = World.objects.filter(pk=world_id).first()
            if world is None or not _claimed(world_id):
                return None
            event = latest_ended(world)
            if event is None or reviewed_after(world, event.id):
                return None
            try:
                # Not in a savepoint of its own: a failed call's tokens
                # must be counted, and nothing else is written before it.
                review(world, by=None)
            except NotReviewed as refused:
                log.info("The World %s was not reviewed after %s: %s", world.pk, event.id,
                         refused)
                return Outcome(world.name, False, str(refused))
            return Outcome(f"{world.name}, after {event.name}", True)
    except IntegrityError:
        # Another run kept one for this Event first.
        return None
