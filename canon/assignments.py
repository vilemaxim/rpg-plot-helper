"""Assignments: a Plot Master's choice of a Mod Runner to run a Mod, for one
Event or until revoked (see **Assignment** in GLOSSARY.md).

An Assignment for one Event is live until that Event's last day has passed:
its `real_date_end`, or its `real_date` for a one-day Event. Nothing runs to
end it; it is a condition on the date. One that stands is live until a Plot
Master revokes it. Either is live only while its Mod Runner still holds the
Mod Runner role in the World. Revoked and ended ones are kept as history.

Assignments are never written into a file (ADR-0001), so an export leaves
them out.

`is_assigned` is the one answer to "is this person assigned to this Mod now".
"""

import datetime

from django.db import transaction
from django.utils import timezone

from organizations.models import Role, World

from .models import Assignment, Document
from .roles import chosen, people_holding
from .submitting import can_be_reported_on


class AssignmentRefused(Exception):
    """Nothing was changed. `str()` says why."""


def last_day(event):
    """The last day of an Event, as a date, or None if its file gives none."""
    for field in ("real_date_end", "real_date"):
        value = event.fields.get(field)
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                return None
    return None


def has_ended(event, on=None):
    """Whether an Event's last day has passed. One with no date is taken as
    ended, since nothing would ever end an Assignment for it."""
    day = last_day(event)
    return day is None or day < (on or timezone.localdate())


def events_of(world):
    """`{id: Event}` for the World's Events."""
    return {event.slug: event for event in
            Document.objects.filter(organization=world.organization, world=world,
                                    kind="event")}


def events_to_come(world, on=None):
    """The World's Events that have not ended, soonest to end first."""
    events = [event for event in events_of(world).values() if not has_ended(event, on)]
    return sorted(events, key=lambda event: (last_day(event), event.slug))


def may_run_mods_in(world):
    """The people who hold the Mod Runner role in this World, by email."""
    return people_holding(world, Role.MOD_RUNNER)


def assignments_in(world):
    """Every Assignment in the World, revoked and ended ones too."""
    return Assignment.objects.filter(organization=world.organization, world=world) \
        .select_related("runner", "assigned_by", "revoked_by", "mod")


class Shown:
    """One Assignment as a page shows it: `event` is the name of the Event
    it is for, and `ended` says why it is no longer live, or is empty while
    it is."""

    def __init__(self, assignment, event, ended):
        self.assignment, self.event, self.ended = assignment, event, ended

    @property
    def live(self):
        return not self.ended


# Why an Assignment is no longer live.
REVOKED = "revoked"
ENDED = "ended with the Event"
NOT_A_RUNNER = "no longer a Mod Runner here"


class Liveness:
    """What decides whether a World's Assignments are live, read once: its
    Events and who holds the Mod Runner role. `on` is the day to ask about,
    today if not given."""

    def __init__(self, world, on=None):
        self.events = events_of(world)
        self.runners = set(may_run_mods_in(world).values_list("pk", flat=True))
        self.on = on

    def ended(self, assignment):
        """Why an Assignment is not live, in words, or "" if it is."""
        if assignment.revoked_at is not None:
            return REVOKED
        if assignment.event:
            event = self.events.get(assignment.event)
            if event is None or has_ended(event, self.on):
                return ENDED
        if assignment.runner_id not in self.runners:
            return NOT_A_RUNNER
        return ""

    def shown(self, assignment):
        event = self.events.get(assignment.event)
        return Shown(assignment, event.name if event else assignment.event,
                     self.ended(assignment))


def shown(world, assignments, on=None):
    """Those of `assignments` (a queryset of the World's) as pages show
    them, live and past alike."""
    liveness = Liveness(world, on)
    return [liveness.shown(assignment) for assignment in assignments]


def live(world, assignments, on=None):
    """Those of `assignments` (a queryset of the World's) that are live."""
    return [row.assignment for row in shown(world, assignments.filter(revoked_at=None), on)
            if row.live]


def is_assigned(mod, person, event=None, on=None):
    """Whether this person has a live Assignment to this Mod: for this Event
    (its id) or standing, if `event` is given; for any Event or standing if
    not. `on` is the day to ask about, today if not given."""
    world = mod.world
    assignments = assignments_in(world).filter(mod=mod, runner=person)
    if event is not None:
        assignments = assignments.filter(event__in=[event, ""])
    return bool(live(world, assignments, on))


def live_for(world, person, on=None):
    """This person's live Assignments in the World, as `Shown`, by Mod."""
    mine = assignments_in(world).filter(runner=person, revoked_at=None) \
        .order_by("mod__name", "pk")
    return [row for row in shown(world, mine, on) if row.live]


def eligible_runner(world, user_id):
    """The person a Plot Master named to run a Mod, from the id a form sent.
    Refused unless they hold the Mod Runner role in this World."""
    person = chosen(may_run_mods_in(world), user_id)
    if person is None:
        raise AssignmentRefused("That person cannot be assigned to run a Mod here: only "
                                "someone with the Mod Runner role in this World can.")
    return person


def assign(world, mod, user_id, event, by, on=None):
    """Assign a Mod Runner to a Mod, for the Event with id `event`, or until
    revoked if `event` is empty. Returns the Assignment."""
    person = eligible_runner(world, user_id)
    event = (event or "").strip()
    with transaction.atomic():
        # One change at a time per World, as for every other change to it.
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(organization=world.organization, world=world, pk=mod.pk)
        if not can_be_reported_on(mod):
            raise AssignmentRefused(f"{mod.name} cannot be run in its present state, so nobody "
                                    f"can be assigned to it. A Mod can be assigned while it is "
                                    f"approved or in progress.")
        if event:
            found = events_of(world).get(event)
            if found is None:
                raise AssignmentRefused(f"{world.name} has no such Event.")
            if last_day(found) is None:
                raise AssignmentRefused(f"{found.name} has no date, so nothing would end an "
                                        f"Assignment for it. Give it a date, or assign until "
                                        f"revoked.")
            if has_ended(found, on):
                raise AssignmentRefused(f"{found.name} has ended, so nobody can be assigned "
                                        f"for it. Choose an Event still to come, or assign "
                                        f"until revoked.")
        duplicate = live(world, assignments_in(world).filter(mod=mod, runner=person,
                                                             event=event), on)
        if duplicate:
            raise AssignmentRefused(
                f"{person.email} is already assigned to {mod.name} "
                + (f"for {found.name}." if event else "until revoked."))
        return Assignment.objects.create(
            organization=world.organization, world=world, mod=mod, runner=person,
            event=event, assigned_by=by, assigned_at=timezone.now())


def revoke(world, mod, assignment_id, by, on=None):
    """Revoke a live Assignment to this Mod. Returns it."""
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        found = assignments_in(world).filter(mod=mod, pk=assignment_id).first()
        if found is None:
            raise AssignmentRefused(f"{mod.name} has no such Assignment.")
        row = Liveness(world, on).shown(found)
        if row.ended == REVOKED:
            raise AssignmentRefused(f"That Assignment of {found.runner.email} was already "
                                    f"revoked.")
        if row.ended == ENDED:
            raise AssignmentRefused(f"{row.event} has ended, and that Assignment of "
                                    f"{found.runner.email} with it, so there is nothing to "
                                    f"revoke.")
        found.revoked_by, found.revoked_at = by, timezone.now()
        found.save(update_fields=["revoked_by", "revoked_at"])
        return found
