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
from plotcanon import editing

from organizations.models import World

from . import resolving
from .models import CanonChange, Decision, Document, Flag, Undo
from .storing import parsed_into

# The longest note a Plot Master may give with a decision: a line or two.
NOTE_LENGTH = 500


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


def event_of(change):
    """The Event at which a Canon Change happened: its report's."""
    return change.report.fields.get("event")


def as_change(change):
    """A change as plotcanon takes it, or None for no change."""
    if change is None:
        return None
    return plotcanon.Change(before=change.before, after=change.after,
                            event=event_of(change),
                            replaced=change.replaced or None)


def refused(refusal, entity, field, change, previous, following):
    """The Plot Master's reason a decision was turned down, from plotcanon's
    neutral reason for not applying or undoing the change."""
    reason = refusal.reason
    if reason == "factions-out-of-order":
        return DecisionRefused(
            f"{described(following)}, a later change to {entity.name}'s factions, is "
            f"already approved. Changes to factions are decided in the order they "
            f"happened: reject this change, or correct its report.")
    if reason == "not-a-member":
        return DecisionRefused(
            f"This change contradicts what is already Canon: {entity.name} is not a "
            f"member of {change.before}. Reject this change, or correct its report.")
    if reason == "contradicts-previous":
        return contradiction(entity, previous, "before it")
    if reason == "contradicts-following":
        return contradiction(entity, following, "after it")
    if reason == "contradicts-current":
        current = entity.fields.get(field)
        cause = f" since {described(previous)} was approved" if previous else ""
        return DecisionRefused(
            f"This change contradicts what is already Canon: {entity.name}'s {field} is "
            f"{current or 'nothing'}{cause}, and this change expects "
            f"{change.before or 'nothing'}. Reject this change, or correct its report.")
    if reason == "followed-on":
        return DecisionRefused(
            f"{described(following)} was approved after this change and follows on from "
            f"it. Undo that one first.")
    raise refusal


def applied(entity, change, field, previous, following, ordering):
    """The entity's file with an approved change applied, or as it was if a
    later approved change already decides the field. The rules are
    plotcanon's (`plotcanon.applied`). Raises `DecisionRefused` if the change
    does not follow on from the approved change before it, or lead into the
    one after it."""
    try:
        return plotcanon.applied(entity.text, field, as_change(change),
                                 previous=as_change(previous), following=as_change(following),
                                 event_ordinal=ordering.event_ordinal)
    except plotcanon.ChangeRefused as refusal:
        raise refused(refusal, entity, field, change, previous, following) from None


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
    """The entity's file with an approved change taken out, by plotcanon's
    rules (`plotcanon.unapplied`): the field goes back to where the approved
    change before it left it, and "as of" goes back if this change put it
    where it is. `remaining` are the entity's other approved changes that move
    a field. Raises `DecisionRefused` if a later approved change follows on
    from this one."""
    try:
        return plotcanon.unapplied(
            entity.text, field, as_change(change),
            previous=as_change(previous), following=as_change(following),
            remaining_events=[event_of(other) for other in remaining],
            event_ordinal=ordering.event_ordinal)
    except plotcanon.ChangeRefused as refusal:
        raise refused(refusal, entity, field, change, previous, following) from None


def cleaned_note(note):
    """A Plot Master's note as it is kept: without spaces around it. Raises
    `DecisionRefused` if it is too long."""
    note = note.strip()
    if len(note) > NOTE_LENGTH:
        raise DecisionRefused(f"A note can be at most {NOTE_LENGTH} characters; this one is "
                              f"{len(note)}. Nothing was decided.")
    return note


def locked_change(world, change_id):
    """One Canon Change of `world`, with the World locked until the
    transaction ends: one decision at a time per World, and never while a
    report is being filed, so each is checked against the World as stored.
    Raises `DecisionRefused` if there is no such change."""
    World.objects.select_for_update().get(pk=world.pk)
    change = (CanonChange.objects.in_world(world).select_related("report")
              .filter(pk=change_id).first())
    if change is None:
        raise DecisionRefused("There is no such Canon Change.")
    return change


def rewrite(world, change, report_text, entity_text, doing, acting, advice=""):
    """Rewrite the stored files a decision touches, check the World with them
    in it, and save them. The report's file becomes `report_text(text)`. If
    `entity_text` is given, the entity the change moves becomes
    `entity_text(entity, field, ordering)`. `doing` and `acting` begin what a
    refusal says ("Deciding", "Approving"), and `advice` ends it. Returns the
    entity's fields as they were before, or None if it was not rewritten. Raises `DecisionRefused`, having saved
    nothing, if the files cannot be rewritten or plotcanon does not accept the
    World."""
    documents = list(Document.objects.filter(world=world))
    files = {d.path: d.text for d in documents}
    report = change.report
    try:
        files[report.path] = report_text(report.text)
    except editing.CannotEdit as error:
        raise DecisionRefused(f"The report's stored file could not be updated: {error}.")

    entity = None
    if entity_text is not None:
        entity = next((d for d in documents if d.slug == change.entity), None)
        if entity is None:
            raise DecisionRefused(f"There is no {change.entity} in this World.")
        files[entity.path] = entity_text(entity, transitions()[change.kind],
                                         Ordering(documents))

    whole = plotcanon.load_world(files)
    if not whole.ok:
        raise DecisionRefused(f"{doing} that would leave the World with errors: "
                              + " ".join(str(e) for e in whole.errors[:3]))
    disagreement = disagreement_in(whole, entity)
    if disagreement:
        raise DecisionRefused(
            f"{acting} this would leave {entity.name}'s file disagreeing with the changes "
            f"approved to it: {disagreement}.{advice}")

    parsed_into(report, whole.world.get(report.slug), whole.world).save()
    if entity is None:
        return None
    before = dict(entity.fields)
    if files[entity.path] != entity.text:
        parsed_into(entity, whole.world.get(entity.slug), whole.world).save()
    return before


def decide(world, change_id, decision, user, note=""):
    """Approve or reject one proposed Canon Change of `world`, with the Plot
    Master's `note` on why, if any. Returns it. Raises `DecisionRefused`,
    having changed nothing, if it cannot be done."""
    note = cleaned_note(note)
    with transaction.atomic():
        change = locked_change(world, change_id)
        if change.decision != Decision.PROPOSED:
            raise DecisionRefused(f"This change has already been {change.decision}.")

        def report_text(text):
            text = editing.replace(text, ["canon_changes", change.position, "decision"],
                                   decision)
            if note:
                text = editing.set_key(text, ["canon_changes", change.position], "note",
                                       editing.quoted(note), after="decision")
            return text

        def entity_text(entity, field, ordering):
            previous, following = place_in_chain(change, ordering, world)
            return applied(entity, change, field, previous, following, ordering)

        moves = decision == Decision.APPROVED and change.kind in transitions()
        before = rewrite(world, change, report_text, entity_text if moves else None,
                         "Deciding", "Approving",
                         " Reject this change, or correct its report.")
        replaced = None
        if before is not None:
            field = transitions()[change.kind]
            replaced = {field: before.get(field), "as_of": before.get("as_of")}
        change.record_decision(decision, by=user, at=timezone.now(), note=note,
                               replaced=replaced)
        if decision == Decision.REJECTED:
            # A rejected change did not happen, so nothing it touched is in
            # question any more.
            resolving.resolve(Flag.objects.filter(change=change),
                              Flag.Resolution.CHANGE_REJECTED, user)
    return change


def undo(world, change_id, user):
    """Return one decided Canon Change of `world` to proposed. Returns it.
    Raises `DecisionRefused`, having changed nothing, if it cannot be done."""
    with transaction.atomic():
        change = locked_change(world, change_id)
        if change.decision == Decision.PROPOSED:
            raise DecisionRefused("This change has not been decided, so there is nothing to "
                                  "undo.")

        def report_text(text):
            # The note was on the decision, which is undone; it is kept with
            # the record of the undoing instead.
            return editing.remove_key(
                editing.replace(text, ["canon_changes", change.position, "decision"],
                                Decision.PROPOSED),
                ["canon_changes", change.position], "note")

        def entity_text(entity, field, ordering):
            previous, following = place_in_chain(change, ordering, world)
            remaining = list(CanonChange.objects.approved(world).select_related("report")
                             .filter(entity=change.entity, kind__in=transitions())
                             .exclude(pk=change.pk))
            return unapplied(entity, change, field, previous, following, ordering, remaining)

        moves = change.decision == Decision.APPROVED and change.kind in transitions()
        rewrite(world, change, report_text, entity_text if moves else None,
                "Undoing", "Undoing")
        if change.decision == Decision.REJECTED:
            # The change may have happened after all, so what it touched is
            # in question again. Flags resolved some other way stay resolved.
            resolving.reopen(Flag.objects.filter(change=change),
                             Flag.Resolution.CHANGE_REJECTED)
        Undo.objects.create(organization=world.organization, world=world, change=change,
                            **change.decision_made(), undone_by=user,
                            undone_at=timezone.now())
        change.record_decision(Decision.PROPOSED)
    return change


class SelectionRefused(DecisionRefused):
    """Nothing of a selection was decided, because of `change`."""

    def __init__(self, message, change):
        super().__init__(message)
        self.change = change


def decide_all(world, change_ids, decision, user, note=""):
    """Approve or reject several Canon Changes of `world` together, in the
    order they happened, so a chain of changes to one field can be approved
    at once, each with the same `note` on why, if any. Returns them in that
    order. All are decided, or none: raises `SelectionRefused`, having changed
    nothing, naming the change that could not be decided and why."""
    if not change_ids:
        raise DecisionRefused("Select the Canon Changes to decide.")
    note = cleaned_note(note)
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
                decided.append(decide(world, change.pk, decision, user, note=note))
            except DecisionRefused as refused:
                raise SelectionRefused(f"Nothing was decided. {described(change)}: {refused}",
                                       change)
    return decided
