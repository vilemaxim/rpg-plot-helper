"""Putting documents plotcanon has parsed into the database."""

import datetime
import math

import plotcanon

from .models import CanonChange, Document


def storable(value):
    """A frontmatter value in a form the database can hold as JSON. YAML allows
    values JSON does not: dates, not-a-number, binary data, sets."""
    if isinstance(value, dict):
        return {str(key): storable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [storable(inner) for inner in items]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def files_of(world):
    """A World's stored files as `{path: text}`, which is what plotcanon checks."""
    return dict(Document.objects.filter(organization=world.organization, world=world)
                .values_list("path", "text"))


def parsed_into(row, document, plot_world):
    """Fill a `Document` row from what plotcanon parsed. `plot_world` is the
    plotcanon World the document was parsed in, which holds its text."""
    row.path = document.path
    row.kind = document.type
    row.slug = str(document.id)
    row.name = plotcanon.name_of(plot_world, document)[:300]
    row.fields = storable(dict(document.fields))
    row.body = document.body
    row.text = plot_world.files[document.path]
    return row


def new_row(world, document, plot_world, **extra):
    return parsed_into(Document(organization=world.organization, world=world, **extra),
                       document, plot_world)


def canon_changes_of(row):
    """The `CanonChange` rows for a stored document, unsaved. Only an
    After-Action Report has any; each keeps its place in the report's list."""
    listed = row.fields.get("canon_changes")
    width = {name: CanonChange._meta.get_field(name).max_length
             for name in ("entity", "kind", "decision")}
    rows = []
    for position, change in enumerate(listed if isinstance(listed, list) else []):
        if not isinstance(change, dict):
            continue
        rows.append(CanonChange(
            organization_id=row.organization_id, world_id=row.world_id, report=row,
            position=position,
            entity=str(change.get("entity") or "")[:width["entity"]],
            kind=str(change.get("kind") or "")[:width["kind"]],
            decision=str(change.get("decision") or "")[:width["decision"]],
            before="" if change.get("from") is None else str(change["from"]),
            after="" if change.get("to") is None else str(change["to"]),
            summary=str(change.get("summary") or ""),
        ))
    return rows
