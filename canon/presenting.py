"""Turning a stored document into what a page shows.

plotcanon decides what is valid, and says which values name other documents
and which hold a word from a vocabulary; nothing here decides either. A value
is shown as a link when plotcanon says it is a reference and the document it
names is in the World, and as text otherwise. This module only knows which
fields a page lays out in its own way.
"""

import markdown
import nh3
import plotcanon
from django.urls import reverse
from django.utils.safestring import mark_safe

from .access import HIDDEN, REPORT, Hiding
from .kinds import ADDRESS_OF, KINDS

# Frontmatter that a page shows in its own way, or not at all.
NOT_PLAIN_FACTS = {"id", "type", "title", "aliases", "state", "status", "features", "involves",
                   "canon_changes", "requires", "expected_changes", "mods", "entities", "group"}

LABELS = {"mod_writer": "Mod Writer", "mod_runner": "Mod Runner", "pcs": "PCs", "npcs": "NPCs",
          "as_of": "As of", "canon": "In Canon", "recorded_by": "Recorded by"}


def group_label(value):
    """plotcanon's `group_label`, with "" for no Group."""
    return plotcanon.group_label(value) or ""


def group_of(document):
    """The Group a report covers (ADR-0011), or nothing for a report with no
    `group`, or any other document."""
    return group_label(document.fields.get("group")) if document.kind == REPORT else ""


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


def as_parsed(document):
    """A stored document as the `plotcanon.Document` it was parsed into."""
    return plotcanon.Document(document.path, document.kind, document.slug, document.fields,
                              document.body)


class Index:
    """The documents of one World a person may read, looked up by id.
    `hiding` (`canon.access.Hiding`) holds those they may not, each of which
    reads "another document" wherever it is named (ADR-0010)."""

    def __init__(self, world, documents, hiding=None):
        self.world = world
        self.hiding = hiding or Hiding()
        self.hidden = self.hiding.slugs
        self.hide = self.hiding.hide
        self.hide_links = self.hiding.hide_links
        self.by_slug = {document.slug: document for document in documents}
        self.parsed = {slug: as_parsed(document) for slug, document in self.by_slug.items()}

    @classmethod
    def of(cls, reading):
        """What a `canon.access.Reading` reads, as an Index."""
        return cls(reading.world, reading.documents, reading.hiding)

    def references(self, document):
        """Where in the document plotcanon says a value names another
        document, as a set of `(field, position, part)`."""
        return {(ref.field, ref.position, ref.part)
                for ref in plotcanon.references(self.parsed[document.slug])}

    def address(self, document):
        return reverse("canon-detail", args=[self.world.pk, ADDRESS_OF[document.kind],
                                             document.slug])

    def link(self, value):
        """`{"text", "url"}` for a value: a link if it is another document's
        id, and plain text if not."""
        if isinstance(value, str) and value in self.hidden:
            return plain(HIDDEN)
        document = self.by_slug.get(value) if isinstance(value, str) else None
        if document is None or document.kind not in ADDRESS_OF:
            return plain(value)
        shown = {"text": document.name, "url": self.address(document)}
        group = group_of(document)
        if group:
            shown["group"] = group
        return shown

    def links(self, values):
        values = values if isinstance(values, list) else [values]
        return [self.link(value) for value in values]

    def facts(self, document):
        """The document's plain frontmatter, as `(label, [links])` rows."""
        references = self.references(document)
        vocabulary = plotcanon.vocabulary_fields(self.parsed[document.slug])
        rows = []
        for field, value in document.fields.items():
            if field in NOT_PLAIN_FACTS or value in ("", [], {}):
                continue
            if field in vocabulary:
                rows.append((label(field), [{"text": wording(value), "url": None}]))
            elif isinstance(value, dict):
                continue
            elif isinstance(value, list):
                rows.append((label(field), [self.link(item) if (field, position, None) in references
                                            else plain(item)
                                            for position, item in enumerate(value)]))
            else:
                rows.append((label(field), [self.link(value) if (field, None, None) in references
                                            else plain(value)]))
        return rows

    def grouped(self, document):
        """A Mod's `features` or a timeline entry's `involves` as
        `(label, [links])` rows, one per group, in the order the file lists
        them."""
        groups = {}
        for ref in plotcanon.references(self.parsed[document.slug]):
            if ref.field in ("features", "involves"):
                groups.setdefault(ref.part, []).append(self.link(ref.id))
        return [(label(group), links) for group, links in groups.items()]

    def mods_of(self, document):
        """A Plot's Mods, in the order the Plot lists them, each with its state."""
        listed = document.fields.get("mods")
        return [(self.link(mod), wording(self.by_slug[mod].fields.get("state", ""))
                 if mod in self.by_slug else "")
                for mod in (listed if isinstance(listed, list) else [])
                if isinstance(mod, str) and (mod in self.by_slug or mod in self.hidden)]

    def referred_to_by(self, document):
        """Every other document that names this one anywhere in its
        frontmatter, as `(label, [links])` rows, one row per kind.

        This is what lets a Campaign show its Events and Mods, an Event the
        Mods run at it, an NPC the Mods that feature them and the reports that
        changed them, and a PC the reports they took part in.
        """
        world = plotcanon.World(self.parsed.values(), {})
        referring = {other.id for other in plotcanon.referrers(world, document.slug)}
        rows = []
        for address, (doc_type, kind_label) in KINDS.items():
            found = sorted((other for other in self.by_slug.values()
                            if other.kind == doc_type and other.slug != document.slug
                            and other.slug in referring),
                           key=lambda other: (other.name, other.slug))
            if found:
                rows.append((kind_label, [self.link(other.slug) for other in found]))
        return rows
