"""Interludes: the periods between Events, in which Canon changes with no Mod
run.

An Interlude is an Event with `period_type: interlude`. Adding one gives it
the place after the Event chosen, and every later Event moves up one: plotcanon
requires the order to have no gaps, and everything refers to an Event by its
id, so nothing else moves.

Canon Changes made during an Interlude are recorded in an `interlude-changes`
document (plotcanon's format, ADR-0004). A Plot Master records them, so they
are approved as they are recorded, each through the same decision as a
reported change (`deciding.decide`), which keeps each field's chain of changes
in order. They raise Flags like any proposed change. If any one of them cannot
be approved, nothing is saved.

Who recorded the changes is kept here, never in the file (ADR-0001): a file
recorded through a form says `recorded_by: plot-master`.
"""

import json

import plotcanon
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from organizations.models import World

from . import deciding, editing
from .models import CanonChange, Decision, Document
from .storing import canon_changes_of, files_of, new_row, parsed_into
from .submitting import SLUG, Refused, raise_flags, said, unreadable

INTERLUDE = "interlude"
RECORD = "interlude-changes"
RECORDED_BY = "plot-master"


class InterludeRefused(Refused):
    """Nothing was saved."""


def events_of(world):
    """The World's Events, in order."""
    events = Document.objects.filter(organization=world.organization, world=world,
                                     kind="event")
    return sorted(events, key=lambda event: (ordinal_of(event), event.slug))


def ordinal_of(event):
    ordinal = event.fields.get("ordinal")
    return ordinal if isinstance(ordinal, int) and not isinstance(ordinal, bool) \
        else float("inf")


def is_interlude(document):
    return document.kind == "event" and document.fields.get("period_type") == INTERLUDE


def unused_id(world, wanted):
    """`wanted`, or `wanted-2`, `wanted-3` and so on: the first the World does
    not use. Ids are unique across a whole World."""
    taken = set(Document.objects.filter(organization=world.organization, world=world)
                .values_list("slug", flat=True))
    candidate, n = wanted, 1
    while candidate in taken:
        n += 1
        candidate = f"{wanted}-{n}"
    return candidate


def one_line(text):
    return " ".join(str(text).split())


def quoted(text):
    """Text as a YAML value that is only ever read back as that text. Every
    character outside ASCII is escaped, since YAML refuses some of them raw."""
    return json.dumps(one_line(text))


def checked_world(files, refused):
    whole = plotcanon.load_world(files)
    if not whole.ok:
        raise InterludeRefused(refused, errors="\n".join(str(e) for e in whole.errors))
    return whole


def add(world, name, campaign, after, in_world, real_date, user):
    """Add an Interlude after the Event `after`, in `campaign`. Returns the
    new Event's `Document`. Raises `InterludeRefused`, having saved nothing."""
    name = one_line(name)
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        events = events_of(world)
        before = next((event for event in events if event.slug == after), None)
        if before is None or ordinal_of(before) == float("inf"):
            raise InterludeRefused("Choose the Event the Interlude comes after.")
        ordinal = ordinal_of(before) + 1
        slug = unused_id(world, slugify(name)[:150].strip("-") or INTERLUDE)
        files = files_of(world)
        moved = []
        for event in events:
            if ordinal_of(event) >= ordinal and ordinal_of(event) != float("inf"):
                try:
                    files[event.path] = editing.replace(event.text, ["ordinal"],
                                                        str(ordinal_of(event) + 1))
                except editing.CannotEdit as error:
                    raise InterludeRefused(f"{event.name}'s stored file could not be "
                                           f"moved along: {error}.") from None
                moved.append(event)
        status = "complete" if real_date <= timezone.localdate() else "planned"
        path = f"canon/events/{slug}.md"
        files[path] = (
            f"---\nid: {slug}\ntype: event\ncampaign: {campaign}\nordinal: {ordinal}\n"
            f"period_type: {INTERLUDE}\naliases: [{quoted(name)}]\n"
            f"real_date: {real_date.isoformat()}\nin_world: {quoted(in_world)}\n"
            f"status: {status}\n---\n")
        whole = checked_world(files, "That Interlude would leave the World with errors.")
        for event in moved:
            parsed_into(event, whole.world.get(event.slug), whole.world).save()
        row = new_row(world, whole.world.get(slug), whole.world, submitted_by=user,
                      submitted_at=timezone.now())
        row.save()
    return row


def record_path(event, record_id):
    return f"interludes/{event.slug}/{record_id}.md"


def value_at(world, event, entity, kind):
    """What Canon says an entity's field was at the start of this Interlude:
    the result of the last approved change to it before, or failing that
    what the first approved change after it moved it from, or failing both
    its file's current value. Empty if that is not a single value."""
    documents = list(Document.objects.filter(organization=world.organization, world=world,
                                             kind="event"))
    ordering = deciding.Ordering(documents)
    here = ordering.event_ordinal(event.slug)
    changes = sorted(
        CanonChange.objects.approved(world).filter(entity=entity, kind=kind)
        .select_related("report"),
        key=lambda change: (ordering.of(change.report), change.position))
    earlier = [c for c in changes if (ordering.event_ordinal(c.report.fields.get("event"))
                                      or 0) <= here]
    later = [c for c in changes if c not in earlier]
    if earlier:
        return earlier[-1].after
    if later:
        return later[0].before
    current = Document.objects.filter(organization=world.organization, world=world,
                                      slug=entity).first()
    value = current.fields.get(deciding.transitions()[kind]) if current else None
    return value if isinstance(value, str) else ""


def change_file(world, event, entity, kind, before, after, summary):
    """A record of one change, as a Plot Master entered it in a form."""
    fields = [f"  - entity: {entity}", f"    kind: {kind}"]
    if kind in deciding.transitions():
        if not before and kind != "affiliation":
            # Left empty, it changes from what Canon says at this point. A
            # change of faction names the one left, which is not inferred.
            before = value_at(world, event, entity, kind)
        fields += [f"    from: {quoted(before) if before else 'null'}",
                   f"    to: {quoted(after) if after else 'null'}"]
    fields += ["    decision: proposed", f"    summary: {quoted(summary)}"]
    record_id = unused_id(world, f"ic-{event.slug}")
    return (f"---\nid: {record_id}\ntype: {RECORD}\nevent: {event.slug}\n"
            f"recorded_by: {RECORDED_BY}\ncanon_changes:\n" + "\n".join(fields) + "\n---\n")


def record(world, event, text, user):
    """Record the Canon Changes in an `interlude-changes` file, made during
    the Interlude `event`, and approve each. Returns the record's `Document`.
    Raises `InterludeRefused`, having saved nothing, if any cannot be."""
    reason = unreadable(text, "record", RECORD, "a record of an Interlude's changes")
    if reason:
        raise InterludeRefused(reason)
    record_id = said(text, "id")
    if not record_id or not SLUG.fullmatch(record_id) or len(record_id) > 200:
        raise InterludeRefused("That record has no id that can be used. Give it one, such as "
                               f"`id: ic-{event.slug}`.")
    if said(text, "event") != event.slug:
        raise InterludeRefused(f"That record is for `{said(text, 'event')}`, not for "
                               f"{event.name}, whose id is `{event.slug}`.")
    try:
        with transaction.atomic():
            return saved_and_approved(world, event, text, record_id, user)
    except deciding.DecisionRefused as refused:
        # Its wording is for a reported change; this one is being recorded.
        reason = str(refused).replace("Reject this change, or correct its report.",
                                      "Correct the change.") \
            .replace("reject this change, or correct its report.", "correct the change.")
        raise InterludeRefused(f"A change could not be approved: {reason}") from None


def saved_and_approved(world, event, text, record_id, user):
    World.objects.select_for_update().get(pk=world.pk)
    event = Document.objects.get(organization=world.organization, world=world, pk=event.pk)
    if not is_interlude(event):
        raise InterludeRefused(f"{event.name} is not an Interlude.")
    if Document.objects.filter(organization=world.organization, world=world,
                               slug=record_id).exists():
        raise InterludeRefused(f"{world.name} already has something with the id "
                               f"`{record_id}`. Give the record an id of its own.")
    files = files_of(world)
    path = record_path(event, record_id)
    try:
        checked = plotcanon.check_file(files, path, text)
    except (ValueError, TypeError) as error:
        raise InterludeRefused(f"That record cannot be read: {error}.") from None
    if not checked.ok:
        raise InterludeRefused("That record has errors.",
                               errors="\n".join(str(e) for e in checked.errors))
    if checked.document.type != RECORD:
        raise InterludeRefused(f"That file is a `{checked.document.type}`, not a record of "
                               f"an Interlude's changes.")
    # A Plot Master records changes they are making, so each is approved. A
    # file that says one was rejected says it did not happen: that is not a
    # change to record.
    listed = checked.document.fields.get("canon_changes") or []
    rejected = [i for i, change in enumerate(listed) if isinstance(change, dict)
                and change.get("decision") == Decision.REJECTED]
    if rejected:
        raise InterludeRefused(
            f"canon_changes[{rejected[0]}] says it was rejected. Every change recorded here "
            f"is approved as it is recorded; take out any that did not happen.")
    # Each goes on record as proposed and is then approved, as a reported
    # change would be, so that it is checked against its field's chain of
    # changes.
    for position in range(len(listed)):
        try:
            text = editing.replace(text, ["canon_changes", position, "decision"],
                                   Decision.PROPOSED)
        except editing.CannotEdit as error:
            raise InterludeRefused(f"That record could not be read: {error}.") from None
    files[path] = text
    whole = checked_world(files, "Saving that record would leave the World with errors.")
    row = new_row(world, whole.world.get(record_id), whole.world, submitted_by=user,
                  submitted_at=timezone.now())
    row.save()
    changes = CanonChange.objects.bulk_create(canon_changes_of(row))
    raise_flags(world, whole, record_id, changes)
    for change in changes:
        deciding.decide(world, change.pk, Decision.APPROVED, user)
    row.refresh_from_db()
    return row
