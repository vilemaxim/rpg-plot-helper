"""What a person may read in a World: the read-access function (ADR-0010).

`readable_documents(world, person)` is the one answer to "what may this
person read in this World". Every page, download, Twine file, Dry Run,
Interview and check error takes World content from it, and from nothing
else.

- The **plot team** (the World's Plot Masters and its Organization's Admins)
  reads every document in full.
- Anyone else with a role in the World reads every `public` and
  `player-known` document, and every Campaign and Event (whose files have no
  `visibility`), with its `## GM Notes` removed; and in full, what their part
  gives them: a Mod Writer their own Mods (`writers.writer_of`), a Mod
  Runner the Mods they hold a live Assignment for (`assignments`), and
  either of them what they have been granted (`granted_in_full`). An
  After-Action Report is read as its Mod is.
- Anyone else reads nothing.

Each document `readable_documents` returns says whether it is read in full
(`in_full`). `as_read` gives a document as the person reads it, which is the
only form its text may reach them in. `reading` gives all of it at once, for
a request (`Reading`), with the documents they may not read (`Hiding`);
`through_link` gives what a Private link reads.
"""

import copy
import re
from functools import cached_property

import plotcanon
from django.db.models import BooleanField, Case, Q, Value, When

from organizations.models import Membership, Role, WorldRole

from . import assignments, grants, writers
from .models import Document
from .storing import settings_file_of

# What anyone with a role in a World reads, without its GM Notes.
OPEN_VISIBILITY = ("public", "player-known")
# The kinds whose files have no `visibility`, the World's calendar, read as
# open ones are.
OPEN_KINDS = ("campaign", "event")
REPORT = "after-action"  # the kind of an After-Action Report


def documents_in(world):
    """Every document of the World. The filter on the Organization repeats
    what the database already enforces."""
    return Document.objects.filter(organization=world.organization, world=world)


def is_plot_team(world, person):
    """Whether this person reads everything in the World: they are one of its
    Plot Masters, or an Admin of its Organization."""
    return (WorldRole.objects.filter(world=world, user=person, role=Role.PLOT_MASTER).exists()
            or Membership.objects.filter(organization=world.organization, user=person,
                                         is_admin=True).exists())


def granted_in_full(world, person):
    """The ids of the documents a Plot Master has given this person a live
    Grant for (see **Grant** in GLOSSARY.md)."""
    return grants.granted_ids(world, person)


def in_full_by_part(world, person):
    """The ids of the documents this person's part in the World gives them in
    full: their own Mods if they write Mods, the Mods they hold a live
    Assignment for if they run them, and what they have been granted."""
    roles = set(WorldRole.objects.filter(world=world, user=person)
                .values_list("role", flat=True))
    ids = set(granted_in_full(world, person))
    if Role.MOD_WRITER in roles:
        handles = writers.handles_in(world)
        ids |= {mod.pk for mod in documents_in(world).filter(kind="mod")
                .select_related("writer", "submitted_by")
                if writers.is_writer_of(mod, person, handles)}
    if Role.MOD_RUNNER in roles:
        ids |= {row.assignment.mod_id for row in assignments.live_for(world, person)}
    return ids


def readable_documents(world, person):
    """The World's documents this person may read, as a queryset, each with
    `in_full`: True if they read the whole of it, and False if they read it
    without its GM Notes (`as_read`)."""
    documents = documents_in(world)
    if is_plot_team(world, person):
        return documents.annotate(in_full=Value(True, output_field=BooleanField()))
    if not WorldRole.objects.filter(world=world, user=person).exists():
        return documents.none().annotate(in_full=Value(False, output_field=BooleanField()))
    full_ids = in_full_by_part(world, person)
    opened = Q(fields__visibility__in=OPEN_VISIBILITY) | Q(kind__in=OPEN_KINDS)
    full_mods = list(documents.filter(pk__in=full_ids, kind="mod")
                     .values_list("slug", flat=True))
    open_mods = list(documents.filter(opened, kind="mod").values_list("slug", flat=True))
    in_full = Q(pk__in=full_ids) | Q(kind=REPORT, fields__mod__in=full_mods)
    readable = in_full | opened | Q(kind=REPORT, fields__mod__in=open_mods)
    return documents.filter(readable).annotate(in_full=Case(
        When(in_full, then=Value(True)), default=Value(False), output_field=BooleanField()))


class ReadOnly(Exception):
    """A document as someone reads it (`as_read`) was saved or deleted. It may
    lack its GM Notes, so it is never written back."""


def _read_only(*args, **kwargs):
    raise ReadOnly("A document as someone reads it cannot be saved or deleted.")


def as_read(document):
    """A document from `readable_documents` as its reader reads it: a copy,
    whole if they read it in full, and otherwise with `text` and `body`
    without the GM Notes. The copy is for showing only: saving or deleting
    it raises `ReadOnly`, and the document given is left as it was."""
    shown = copy.copy(document)
    shown.in_full = bool(getattr(document, "in_full", False))
    if not shown.in_full:
        shown.text = plotcanon.without_gm_notes(document.text)
        shown.body = plotcanon.without_gm_notes(document.body)
    shown.save = shown.delete = _read_only
    return shown


def read(documents):
    """`as_read` for each of `documents`, as a list."""
    return [as_read(document) for document in documents]


HIDDEN = "another document"


class Hiding:
    """The documents a reader may not read, from `(path, slug, name)` rows,
    and how a text names them: "another document". `hide` hides every
    mention, by path, id or name; `hide_links` only what a body links by, its
    paths and ids, and leaves its prose alone."""

    def __init__(self, rows=()):
        rows = list(rows)
        self.slugs = {slug for _, slug, _ in rows}
        self.paths = {path for path, _, _ in rows}
        self.hide = _hider(rows, names=True)
        self.hide_links = _hider(rows, names=False)


def _hider(rows, names):
    words = sorted({word for path, slug, name in rows
                    for word in (path, slug, name if names else "") if word},
                   key=len, reverse=True)
    if not words:
        return lambda text: text
    mention = re.compile("|".join(rf"(?<![\w/-]){re.escape(word)}(?![\w/-])"
                                  for word in words))
    return lambda text: mention.sub(HIDDEN, text) if text else text


NOT_SHOWN = ("There are more errors, about documents only the plot team may read. "
             "Ask a Plot Master to look at it.")


class Reading:
    """What one reader may read in a World, worked out once and asked as
    often as a request needs: `readable` is the queryset of
    `readable_documents`, and the rest follows from it."""

    def __init__(self, world, readable):
        self.world = world
        self.readable = readable

    @cached_property
    def ids(self):
        return set(self.readable.values_list("pk", flat=True))

    @cached_property
    def documents(self):
        """Every document they may read, as they read it (`as_read`)."""
        return read(self.readable)

    @cached_property
    def hiding(self):
        """The documents they may not read (`Hiding`)."""
        return Hiding(documents_in(self.world).exclude(pk__in=self.ids)
                      .values_list("path", "slug", "name"))

    def one(self, **lookup):
        """The one document matching `lookup` as they read it, or None if
        there is none they may read."""
        found = self.readable.filter(**lookup).first()
        return None if found is None else as_read(found)

    def files(self):
        """What they may read as `{path: text}`, the form plotcanon reads a
        World in: their documents as they read them, and the World's settings
        file, which holds no Canon, if it has one."""
        if not self.documents:
            return {}
        return {**{document.path: document.text for document in self.documents},
                **settings_file_of(self.world)}

    def flags(self, flags):
        """Those of `flags` (a queryset) they may read in full: on a Mod they
        may read, raised by a Canon Change from a report they may read, about
        a Feature they may read. Any other is left out whole, as a finding
        about a document they may not read is (`findings`)."""
        return (flags.filter(mod__in=self.ids, change__report__in=self.ids)
                .exclude(change__entity__in=self.hiding.slugs))

    def findings(self, findings):
        """plotcanon's findings, one to a line, or any message about the
        World, as they may read it. A finding about a document they may not
        read is left out, and saying so ends the text; any other mention of
        one, by path, id or name, reads "another document"."""
        lines, left_out = [], False
        for line in (findings or "").splitlines():
            if any(f" {path}: " in line for path in self.hiding.paths):
                left_out = True
                continue
            lines.append(self.hiding.hide(line))
        if left_out:
            lines.append(NOT_SHOWN)
        return "\n".join(lines)


def reading(world, person):
    """What this person may read in the World (`Reading`)."""
    return Reading(world, readable_documents(world, person))


def through_link(link):
    """What a Private link reads: its own Mod in full, and nothing else in
    the World (`Reading`)."""
    world = link.world
    return Reading(world, documents_in(world).filter(pk=link.mod_id)
                   .annotate(in_full=Value(True, output_field=BooleanField())))


def readable_files(world, person):
    """`Reading.files` for this person."""
    return reading(world, person).files()


def readable_flags(world, person, flags):
    """`Reading.flags` for this person."""
    return reading(world, person).flags(flags)


def readable_findings(world, person, findings):
    """`Reading.findings` for this person."""
    return reading(world, person).findings(findings)
