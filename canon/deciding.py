"""Approving or rejecting Canon Changes, one or several together, and undoing
either.

A decision is recorded in three places that must agree: the change's own row,
its `decision` in the report's stored file, and, for an approved change that
moves a field, the entity's stored file. All three are changed together, and
the World with the changes in it is checked by plotcanon before anything is
saved, so what is stored is always a World plotcanon accepts.

Approved changes to one field of one entity form a chain, in the order of the
Events they happened at: each takes the field from where the one before left
it. A change that does not fit the chain contradicts one already approved and
is turned down, with the other named, so that a Plot Master rejects one of the
two instead of having both stand.
"""

import re

import plotcanon
from django.db import transaction
from django.utils import timezone

from organizations.models import World

from . import editing, resolving
from .models import CanonChange, Document, Flag, Undo
from .storing import parsed_into

PROPOSED, APPROVED, REJECTED = "proposed", "approved", "rejected"


class DecisionRefused(Exception):
    """Nothing was decided. `str()` says why, for the Plot Master."""


def natural_key(text):
    """Sort key for an id that compares the numbers in it as numbers, as
    plotcanon orders reports at one Event: `aa-x`, `aa-x-2`, `aa-x-10`."""
    return [int(part) if part.isdigit() and len(part) <= 18 else part
            for part in re.split(r"([0-9]+)", str(text))]


class Ordering:
    """Where each report of a World falls in time: by its Event, then by id."""

    def __init__(self, documents):
        ordinals = {d.slug: d.fields.get("ordinal") for d in documents if d.kind == "event"}
        self.events = {slug: o for slug, o in ordinals.items()
                       if isinstance(o, int) and not isinstance(o, bool)}

    def of(self, report):
        ordinal = self.events.get(report.fields.get("event"), float("inf"))
        return (ordinal, natural_key(report.slug))

    def event_ordinal(self, event):
        return self.events.get(event)


def transitions():
    """Which kinds of change move a field, and which field each moves."""
    vocabulary = plotcanon.vocabularies()
    return {kind: vocabulary["canon_change_kind_fields"][kind]
            for kind in vocabulary["canon_change_transition_kinds"]}


def described(change):
    return f"“{change.summary}” in {change.report.name}"


def place_in_chain(change, ordering, world):
    """The approved changes just before and just after this one, to the same
    field of the same entity, in the order they happened: by Event, then
    report, then their place in the report. Either is None if there is none."""
    def when(other):
        return (ordering.of(other.report), other.position)

    others = sorted(
        (other for other in CanonChange.objects.approved(world).select_related("report")
         .filter(entity=change.entity, kind=change.kind).exclude(pk=change.pk)),
        key=when)
    here = when(change)
    before = [other for other in others if when(other) < here]
    after = [other for other in others if when(other) > here]
    return (before[-1] if before else None), (after[0] if after else None)


def contradiction(entity, other, which):
    return DecisionRefused(
        f"This change contradicts {described(other)}, which is already approved and says "
        f"{entity.name} went from {other.before or 'nothing'} to {other.after or 'nothing'} "
        f"{which}. Reject this change, or correct its report.")


def applied(entity, change, field, previous, following, ordering):
    """The entity's file with an approved change applied, or as it was if a
    later approved change already decides the field. Raises `DecisionRefused`
    if the change does not follow on from the approved change before it, or
    lead into the one after it."""
    def value(text):
        return text or None

    if field == "factions":
        # A change to a list of factions takes one out and puts one in, so
        # where it leaves the list depends on every change before it. They are
        # decided in the order they happened.
        if following is not None:
            raise DecisionRefused(
                f"{described(following)}, a later change to {entity.name}'s factions, is "
                f"already approved. Changes to factions are decided in the order they "
                f"happened: reject this change, or correct its report.")
        listed = entity.fields.get(field)
        listed = listed if isinstance(listed, list) else []
        if change.before and change.before not in listed:
            raise DecisionRefused(
                f"This change contradicts what is already Canon: {entity.name} is not a "
                f"member of {change.before}. Reject this change, or correct its report.")
        updated = [faction for faction in listed if faction != change.before]
        if change.after and change.after not in updated:
            updated.append(change.after)
        text = editing.set_field(entity.text, field, editing.flow_list(updated))
    else:
        if previous is not None and value(previous.after) != value(change.before):
            raise contradiction(entity, previous, "before it")
        if following is not None:
            if value(following.before) != value(change.after):
                raise contradiction(entity, following, "after it")
            # A later change already decides the field; this one fits between.
            return entity.text
        current = entity.fields.get(field)
        if value(current) != value(change.before):
            cause = f" since {described(previous)} was approved" if previous else ""
            raise DecisionRefused(
                f"This change contradicts what is already Canon: {entity.name}'s {field} is "
                f"{current or 'nothing'}{cause}, and this change expects "
                f"{change.before or 'nothing'}. Reject this change, or correct its report.")
        text = editing.set_field(entity.text, field, change.after or "null")

    # The entity's state is now as of this change's Event, unless it already
    # stood at a later one.
    event = change.report.fields.get("event")
    as_of = ordering.event_ordinal(entity.fields.get("as_of"))
    if as_of is None or as_of < (ordering.event_ordinal(event) or 0):
        text = editing.set_field(text, "as_of", event)
    return text


# plotcanon's warnings that mean an entity's file disagrees with its approved
# changes. A decision that would cause one is refused, like an error.
DISAGREEMENT = ("approved but not applied", "advance `as_of`")


def disagreement_in(whole, entity):
    """plotcanon's first warning that `entity`'s file disagrees with the
    changes approved to it, or None. None too if there is no entity."""
    if entity is None:
        return None
    return next((w.message for w in whole.warnings if w.path == entity.path
                 and any(sign in w.message for sign in DISAGREEMENT)), None)


def unapplied(entity, change, field, previous, following, ordering, remaining):
    """The entity's file with an approved change taken out. The field goes
    back to where the approved change before it left it, or to what this one
    changed it from if there is none; a list of factions goes back to what
    the approval replaced. "As of" goes back too, if this change was what put
    it where it is: to what the approval replaced, or to the latest remaining
    approved change if that is later. `remaining` are the entity's other
    approved changes that move a field. Raises `DecisionRefused` if a later
    approved change follows on from this one."""
    if following is not None:
        raise DecisionRefused(
            f"{described(following)} was approved after this change and follows on from "
            f"it. Undo that one first.")
    replaced = change.replaced or {}
    if field == "factions":
        # Changes to factions are decided in order, so this is the latest.
        if field in replaced:
            listed = replaced[field] if isinstance(replaced[field], list) else []
        else:
            # Approved before what it replaced was kept: take back out the
            # faction it put in, and put back the one it took out.
            listed = entity.fields.get(field)
            listed = [faction for faction in (listed if isinstance(listed, list) else [])
                      if faction != change.after or change.after == change.before]
            if change.before and change.before not in listed:
                listed.append(change.before)
        text = editing.set_field(entity.text, field, editing.flow_list(listed))
    else:
        restored = previous.after if previous is not None else change.before
        text = editing.set_field(entity.text, field, restored or "null")

    event = change.report.fields.get("event")
    if entity.fields.get("as_of") == event:
        candidates = [other.report.fields.get("event") for other in remaining]
        if replaced.get("as_of"):
            candidates.append(replaced["as_of"])
        # With neither, it stays: the field held its restored value then too.
        known = [c for c in candidates if ordering.event_ordinal(c) is not None]
        if known:
            latest = max(known, key=ordering.event_ordinal)
            if latest != event:
                text = editing.set_field(text, "as_of", latest)
    return text


def decide(world, change_id, decision, user):
    """Approve or reject one proposed Canon Change of `world`. Returns it.
    Raises `DecisionRefused`, having changed nothing, if it cannot be done."""
    with transaction.atomic():
        # One decision at a time per World, and never while a report is being
        # filed: each is checked against the World as stored.
        World.objects.select_for_update().get(pk=world.pk)
        change = (CanonChange.objects.in_world(world).select_related("report")
                  .filter(pk=change_id).first())
        if change is None:
            raise DecisionRefused("There is no such Canon Change.")
        if change.decision != PROPOSED:
            raise DecisionRefused(f"This change has already been {change.decision}.")

        documents = list(Document.objects.filter(world=world))
        files = {d.path: d.text for d in documents}
        report = change.report
        try:
            files[report.path] = editing.replace(
                report.text, ["canon_changes", change.position, "decision"], decision)
        except editing.CannotEdit as error:
            raise DecisionRefused(f"The report's stored file could not be updated: {error}.")

        entity = None
        field = transitions().get(change.kind)
        if decision == APPROVED and field:
            entity = next((d for d in documents if d.slug == change.entity), None)
            if entity is None:
                raise DecisionRefused(f"There is no {change.entity} in this World.")
            ordering = Ordering(documents)
            previous, following = place_in_chain(change, ordering, world)
            files[entity.path] = applied(entity, change, field, previous, following, ordering)

        whole = plotcanon.load_world(files)
        if not whole.ok:
            raise DecisionRefused("Deciding that would leave the World with errors: "
                                  + " ".join(str(e) for e in whole.errors[:3]))
        disagreement = disagreement_in(whole, entity)
        if disagreement:
            raise DecisionRefused(
                f"Approving this would leave {entity.name}'s file disagreeing with the "
                f"changes approved to it: {disagreement}. Reject this change, or correct "
                f"its report.")

        parsed_into(report, whole.world.get(report.slug), whole.world).save()
        if entity is not None:
            change.replaced = {field: entity.fields.get(field),
                               "as_of": entity.fields.get("as_of")}
            if files[entity.path] != entity.text:
                parsed_into(entity, whole.world.get(entity.slug), whole.world).save()
        change.decision = decision
        change.decided_by = user
        change.decided_at = timezone.now()
        change.save(update_fields=["decision", "decided_by", "decided_at", "replaced"])
        if decision == REJECTED:
            # A rejected change did not happen, so nothing it touched is in
            # question any more.
            resolving.resolve(Flag.objects.filter(change=change),
                              Flag.Resolution.CHANGE_REJECTED, user)
    return change


def undo(world, change_id, user):
    """Return one decided Canon Change of `world` to proposed. Returns it.
    Raises `DecisionRefused`, having changed nothing, if it cannot be done."""
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        change = (CanonChange.objects.in_world(world).select_related("report")
                  .filter(pk=change_id).first())
        if change is None:
            raise DecisionRefused("There is no such Canon Change.")
        if change.decision == PROPOSED:
            raise DecisionRefused("This change has not been decided, so there is nothing to "
                                  "undo.")

        documents = list(Document.objects.filter(world=world))
        files = {d.path: d.text for d in documents}
        report = change.report
        try:
            files[report.path] = editing.replace(
                report.text, ["canon_changes", change.position, "decision"], PROPOSED)
        except editing.CannotEdit as error:
            raise DecisionRefused(f"The report's stored file could not be updated: {error}.")

        entity = None
        field = transitions().get(change.kind)
        if change.decision == APPROVED and field:
            entity = next((d for d in documents if d.slug == change.entity), None)
            if entity is None:
                raise DecisionRefused(f"There is no {change.entity} in this World.")
            ordering = Ordering(documents)
            previous, following = place_in_chain(change, ordering, world)
            remaining = list(CanonChange.objects.approved(world).select_related("report")
                             .filter(entity=change.entity, kind__in=transitions())
                             .exclude(pk=change.pk))
            files[entity.path] = unapplied(entity, change, field, previous, following,
                                           ordering, remaining)

        whole = plotcanon.load_world(files)
        if not whole.ok:
            raise DecisionRefused("Undoing that would leave the World with errors: "
                                  + " ".join(str(e) for e in whole.errors[:3]))
        disagreement = disagreement_in(whole, entity)
        if disagreement:
            raise DecisionRefused(
                f"Undoing this would leave {entity.name}'s file disagreeing with the changes "
                f"approved to it: {disagreement}.")
        parsed_into(report, whole.world.get(report.slug), whole.world).save()
        if entity is not None and files[entity.path] != entity.text:
            parsed_into(entity, whole.world.get(entity.slug), whole.world).save()
        if change.decision == REJECTED:
            # The change may have happened after all, so what it touched is
            # in question again. Flags resolved some other way stay resolved.
            resolving.reopen(Flag.objects.filter(change=change),
                             Flag.Resolution.CHANGE_REJECTED)
        Undo.objects.create(organization=world.organization, world=world, change=change,
                            decision=change.decision, decided_by=change.decided_by,
                            decided_at=change.decided_at, undone_by=user,
                            undone_at=timezone.now())
        change.decision, change.decided_by, change.decided_at = PROPOSED, None, None
        change.replaced = {}
        change.save(update_fields=["decision", "decided_by", "decided_at", "replaced"])
    return change


class SelectionRefused(DecisionRefused):
    """Nothing of a selection was decided, because of `change`."""

    def __init__(self, message, change):
        super().__init__(message)
        self.change = change


def decide_all(world, change_ids, decision, user):
    """Approve or reject several Canon Changes of `world` together, in the
    order they happened, so a chain of changes to one field can be approved
    at once. Returns them in that order. All are decided, or none: raises
    `SelectionRefused`, having changed nothing, naming the change that could
    not be decided and why."""
    if not change_ids:
        raise DecisionRefused("Select the Canon Changes to decide.")
    with transaction.atomic():
        # Held for the whole selection, so the World each change is checked
        # against holds the ones decided before it, and nothing else.
        World.objects.select_for_update().get(pk=world.pk)
        changes = list(CanonChange.objects.in_world(world).select_related("report")
                       .filter(pk__in=change_ids))
        if len(changes) != len(set(change_ids)):
            raise DecisionRefused("Nothing was decided. There is no such Canon Change.")
        ordering = Ordering(Document.objects.filter(world=world, kind="event"))
        changes.sort(key=lambda c: (ordering.of(c.report), c.position))
        decided = []
        for change in changes:
            try:
                decided.append(decide(world, change.pk, decision, user))
            except DecisionRefused as refused:
                raise SelectionRefused(f"Nothing was decided. {described(change)}: {refused}",
                                       change)
    return decided
