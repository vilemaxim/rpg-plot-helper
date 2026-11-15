"""Turning a stored document into what a page shows.

plotcanon decides what is valid; nothing here does. But to lay a page out this
module has to know the names of some fields: which hold a state, which hold a
Mod's Features or a report's Canon Changes, and which hold a person's name and
so are never links. A value is otherwise shown as a link when it is the id of
another document in the same World, and as text when it is not. plotcanon does
not yet say which fields are references; when it does, the lists here can go.
"""

import markdown
import nh3
from django.urls import reverse
from django.utils.safestring import mark_safe

from .kinds import ADDRESS_OF, KINDS

# Frontmatter that a page shows in its own way, or not at all.
NOT_PLAIN_FACTS = {"id", "type", "title", "aliases", "state", "status", "features", "involves",
                   "canon_changes", "requires", "expected_changes", "mods", "entities"}

LABELS = {"mod_writer": "Mod Writer", "mod_runner": "Mod Runner", "pcs": "PCs", "npcs": "NPCs",
          "as_of": "As of", "canon": "In Canon"}

# Fields that hold a person's handle, a date, a number or free text. Their
# values are never another document's id, so they are never shown as links,
# even when a document happens to have that id.
NEVER_LINKS = {"mod_writer", "mod_runner", "owner", "player", "tags", "in_world", "region",
               "real_date", "real_date_end", "ordinal", "slot", "duration_est", "sort_hint",
               "ran", "era"}

# The kinds of Canon Change whose `from` and `to` name other documents.
CHANGES_BETWEEN_DOCUMENTS = {"location", "affiliation"}

# Values from a vocabulary, shown as words: "in-progress" becomes "In progress".
VOCABULARY_FIELDS = {"state", "status", "decision", "canon", "visibility", "period_type", "kind"}


def label(field):
    return LABELS.get(field) or field.replace("_", " ").capitalize()


def wording(value):
    """A vocabulary value as words a person reads."""
    return str(value).replace("-", " ").capitalize()


# Everything nh3 allows by default, less pictures: loading one from another
# site would tell that site who is reading the page.
SAFE_TAGS = nh3.ALLOWED_TAGS - {"img"}


def render_markdown(text):
    """A document's markdown as HTML that is safe to put on a page. The file
    came from an upload, so anything that could run in the browser, or call
    out to another site, is removed."""
    return mark_safe(nh3.clean(markdown.markdown(text, extensions=["tables"]), tags=SAFE_TAGS))


def plain(value):
    return {"text": "—" if value is None else str(value), "url": None}


def names(value, slug):
    """Whether a frontmatter value names the document with this id, at any
    depth: as the value itself, in a list, or in a mapping."""
    if isinstance(value, str):
        return value == slug
    if isinstance(value, dict):
        return any(names(inner, slug) for inner in value.values())
    if isinstance(value, list):
        return any(names(inner, slug) for inner in value)
    return False


class Index:
    """Every document of one World, looked up by id."""

    def __init__(self, world, documents):
        self.world = world
        self.by_slug = {document.slug: document for document in documents}

    def address(self, document):
        return reverse("canon-detail", args=[self.world.pk, ADDRESS_OF[document.kind],
                                             document.slug])

    def link(self, value):
        """`{"text", "url"}` for a value: a link if it is another document's
        id, and plain text if not."""
        document = self.by_slug.get(value) if isinstance(value, str) else None
        if document is None or document.kind not in ADDRESS_OF:
            return plain(value)
        return {"text": document.name, "url": self.address(document)}

    def links(self, values):
        values = values if isinstance(values, list) else [values]
        return [self.link(value) for value in values]

    def facts(self, document):
        """The document's plain frontmatter, as `(label, [links])` rows."""
        rows = []
        for field, value in document.fields.items():
            if field in NOT_PLAIN_FACTS or value in ("", [], {}):
                continue
            if field in VOCABULARY_FIELDS:
                rows.append((label(field), [{"text": wording(value), "url": None}]))
            elif isinstance(value, dict):
                continue
            elif field in NEVER_LINKS:
                values = value if isinstance(value, list) else [value]
                rows.append((label(field), [plain(v) for v in values]))
            else:
                rows.append((label(field), self.links(value)))
        return rows

    def grouped(self, mapping):
        """A `features` or `involves` block as `(label, [links])` rows."""
        if not isinstance(mapping, dict):
            return []
        return [(label(str(group)), self.links(ids)) for group, ids in mapping.items() if ids]

    def mods_of(self, document):
        """A Plot's Mods, in the order the Plot lists them, each with its state."""
        listed = document.fields.get("mods")
        return [(self.link(mod), wording(self.by_slug[mod].fields.get("state", "")))
                for mod in (listed if isinstance(listed, list) else [])
                if isinstance(mod, str) and mod in self.by_slug]

    def referred_to_by(self, document):
        """Every other document that names this one anywhere in its
        frontmatter, as `(label, [links])` rows, one row per kind.

        This is what lets a Campaign show its Events and Mods, an Event the
        Mods run at it, an NPC the Mods that feature them and the reports that
        changed them, and a PC the reports they took part in.
        """
        rows = []
        for address, (doc_type, kind_label) in KINDS.items():
            found = sorted((other for other in self.by_slug.values()
                            if other.kind == doc_type and other.slug != document.slug
                            and names(other.fields, document.slug)),
                           key=lambda other: (other.name, other.slug))
            if found:
                rows.append((kind_label, [self.link(other.slug) for other in found]))
        return rows

    def canon_changes(self, document):
        changes = document.fields.get("canon_changes")
        rows = []
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict):
                continue
            between = self.link if change.get("kind") in CHANGES_BETWEEN_DOCUMENTS else plain
            rows.append({
                "entity": self.link(change.get("entity")),
                "kind": wording(change.get("kind", "")),
                "decision": wording(change.get("decision", "")),
                "moved": "from" in change or "to" in change,
                "before": between(change.get("from")),
                "after": between(change.get("to")),
                "summary": change.get("summary", ""),
            })
        return rows
