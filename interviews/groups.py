"""Which Group a report Interview's report is for (#67, ADR-0011).

A Mod's players may split into Groups at one Event, each with its own Mod
Runner, and each Group's Mod Runner files their own report, labelled with
its `group`. The report Interview asks for a Group only when it is needed:
when the Mod has more than one live Assignment at the Event the report is
for (`canon.assignments.live_at`). With one Assignment or none it never
asks, and the report has no `group`.

The Group is in the report's file alone. It is never linked to an
Assignment in the database: the Assignments only decide whether to ask.
"""

from canon import assignments, submitting
from canon.models import WriterHandle

# The longest a Group's label may be, as plotcanon reads it.
LONGEST = 60


def events_of_mod(mod):
    """The Events a report on the Mod may be for, the Mod's `events` that
    the World has, as `(id, name)` in the Mod's order."""
    listed = mod.fields.get("events")
    known = assignments.events_of(mod.world)
    return [(event, known[event].name) for event in
            (listed if isinstance(listed, list) else [])
            if isinstance(event, str) and event in known]


def needs_a_group(mod, event):
    """Whether a report on the Mod at the Event with id `event` is asked
    which Group it is for."""
    return len(assignments.live_at(mod, event)) > 1


def events_needing_a_group(mod):
    """The ids of the Mod's Events at which a report is asked for a Group."""
    return [event for event, _ in events_of_mod(mod) if needs_a_group(mod, event)]


def suggested(mod, event, person):
    """The Group label suggested to `person` for a report at the Event: their
    handle in the World when they are one of the Mod Runners assigned there,
    and nothing otherwise."""
    if not any(a.runner_id == person.pk for a in assignments.live_at(mod, event)):
        return ""
    link = WriterHandle.objects.filter(organization_id=mod.organization_id,
                                       world_id=mod.world_id, user=person) \
        .order_by("handle").first()
    return link.handle[:LONGEST] if link else ""


def label(value):
    """A `group` as plotcanon reads a label: its text stripped, or "" for
    none."""
    return value.strip() if isinstance(value, str) else ""


def agrees(report, mod, event, group):
    """Refuse a report whose `group` is not `group` (a label, or "" for
    none), or, when `event` was asked, whose `event` is not it."""
    given = report.fields.get("group")
    if group and label(given) != group:
        raise submitting.ReportRefused(
            f"That report's `group` must be `{group}`, the Group its Mod Runner said it "
            f"is for. Give `group: {group}`.")
    if not group and given is not None:
        raise submitting.ReportRefused(
            f"That report has a `group`, but it covers the whole of {mod.name}: its "
            f"players were not split into Groups for it. Leave `group` out.")
    if event and report.fields.get("event") != event:
        raise submitting.ReportRefused(
            f"That report's `event` must be `{event}`, the Event its Mod Runner said it "
            f"is for.")
