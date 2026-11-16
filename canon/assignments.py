"""Assignments: a Plot Master's choice of a Mod Runner to run a Mod, for one
Event or until revoked (see **Assignment** in GLOSSARY.md).

An Assignment for one Event is live until that Event's last day has passed:
its `real_date_end`, or its `real_date` for a one-day Event. Nothing runs to
end it; it is a condition on the date. One that stands is live until a Plot
Master revokes it. Revoked and ended ones are kept as history.

Assignments are never written into a file (ADR-0001), so an export leaves
them out.

`is_assigned` is the one answer to "is this person assigned to this Mod now".
"""

import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from organizations.models import Role, World, WorldRole

from .models import Assignment, Document
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
    """The World's Events that have not ended, soonest first."""
    events = [event for event in events_of(world).values() if not has_ended(event, on)]
    return sorted(events, key=lambda event: (event.fields.get("real_date"), event.slug))


def may_run_mods_in(world):
    """The people who hold the Mod Runner role in this World, by email."""
    ids = WorldRole.objects.filter(world=world, role=Role.MOD_RUNNER).values("user_id")
    return get_user_model().objects.filter(pk__in=ids).order_by("email")


def of(world):
    """Every Assignment in the World, revoked and ended ones too."""
    return Assignment.objects.filter(organization=world.organization, world=world) \
        .select_related("runner", "assigned_by", "revoked_by", "mod")


def is_live(assignment, events, on=None):
    """Whether an Assignment is live. `events` is `events_of(world)`."""
    if assignment.revoked_at is not None:
        return False
    if not assignment.event:
        return True
    event = events.get(assignment.event)
    return event is not None and not has_ended(event, on)


def live(world, assignments, on=None):
    """Those of `assignments` (a queryset of the World's) that are live."""
    events = events_of(world)
    return [a for a in assignments.filter(revoked_at=None) if is_live(a, events, on)]


def is_assigned(mod, person, event=None, on=None):
    """Whether this person has a live Assignment to this Mod: for this Event
    (its id) or standing, if `event` is given; for any Event or standing if
    not. `on` is the day to ask about, today if not given."""
    world = mod.world
    assignments = of(world).filter(mod=mod, runner=person)
    if event is not None:
        assignments = assignments.filter(event__in=[event, ""])
    return bool(live(world, assignments, on))


def eligible_runner(world, user_id):
    """The person a Plot Master named to run a Mod, from the id a form sent.
    Refused unless they hold the Mod Runner role in this World."""
    try:
        person = may_run_mods_in(world).filter(pk=int(user_id)).first()
    except (TypeError, ValueError):
        person = None
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
            if has_ended(found, on):
                raise AssignmentRefused(f"{found.name} has ended, so nobody can be assigned "
                                        f"for it. Choose an Event still to come, or assign "
                                        f"until revoked.")
        duplicate = live(world, of(world).filter(mod=mod, runner=person, event=event), on)
        if duplicate:
            raise AssignmentRefused(
                f"{person.email} is already assigned to {mod.name} "
                + (f"for {events_of(world)[event].name}." if event else "until revoked."))
        return Assignment.objects.create(
            organization=world.organization, world=world, mod=mod, runner=person,
            event=event, assigned_by=by, assigned_at=timezone.now())


def revoke(world, mod, assignment_id, by, on=None):
    """Revoke a live Assignment. Returns whether one was revoked."""
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        found = of(world).filter(mod=mod, pk=assignment_id).first()
        if found is None or not is_live(found, events_of(world), on):
            return False
        found.revoked_by, found.revoked_at = by, timezone.now()
        found.save(update_fields=["revoked_by", "revoked_at"])
        return True
