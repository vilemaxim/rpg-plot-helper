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
only form its text may reach them in.
"""

import re

import plotcanon
from django.db.models import BooleanField, Case, Q, Value, When

from organizations.models import Membership, Role, WorldRole

from . import assignments, writers
from .models import Document
from .storing import settings_file_of

# What anyone with a role in a World reads, without its GM Notes.
OPEN_VISIBILITY = ("public", "player-known")
# The kinds whose files have no `visibility`, the World's calendar, read as
# open ones are.
OPEN_KINDS = ("campaign", "event")
REPORT = "after-action"


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
    """The ids of the documents a Plot Master has given this person a Grant
    for (see **Grant** in GLOSSARY.md). Grants are not built yet, so none."""
    return set()


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


def as_read(document):
    """A document from `readable_documents` as its reader reads it: whole if
    they read it in full, and otherwise with `text` and `body` without the
    GM Notes. The document is changed in place, for showing only, and must
    never be saved."""
    if not getattr(document, "in_full", False):
        document.text = plotcanon.without_gm_notes(document.text)
        document.body = plotcanon.without_gm_notes(document.body)
        document.in_full = False
    return document


def read(documents):
    """`as_read` for each of `documents`, as a list."""
    return [as_read(document) for document in documents]


def readable_one(world, person, **lookup):
    """The one document matching `lookup` as this person reads it, or None if
    there is none they may read."""
    found = readable_documents(world, person).filter(**lookup).first()
    return None if found is None else as_read(found)


def unreadable_documents(world, person):
    """The World's documents this person may not read at all."""
    return documents_in(world).exclude(pk__in=readable_documents(world, person).values("pk"))


def readable_files(world, person):
    """What this person may read in the World as `{path: text}`, the form
    plotcanon reads a World in: their readable documents as they read them,
    and the World's settings file, which holds no Canon, if it has one."""
    documents = read(readable_documents(world, person))
    if not documents:
        return {}
    return {**{document.path: document.text for document in documents},
            **settings_file_of(world)}


def readable_flags(world, person, flags):
    """Those of `flags` (a queryset) this person may read in full: on a Mod
    they may read, raised by a Canon Change from a report they may read, about
    a Feature they may read. Any other is left out whole, as a finding about a
    document they may not read is (`readable_findings`)."""
    readable = readable_documents(world, person)
    hidden = unreadable_documents(world, person).values("slug")
    return (flags.filter(mod__in=readable.values("pk"),
                         change__report__in=readable.values("pk"))
            .exclude(change__entity__in=hidden))


HIDDEN = "another document"
NOT_SHOWN = ("There are more errors, about documents only a Plot Master may read. "
             "Ask one to look at it.")


def readable_findings(world, person, findings):
    """plotcanon's findings, one to a line, or any message about the World, as
    this person may read them, with what they may read taken from
    `readable_documents`. A finding about a document they may not read is
    left out, and saying so ends the text; any other mention of one, by path,
    id or name, reads "another document"."""
    hidden = unreadable_documents(world, person).values_list("path", "slug", "name")
    paths = {path for path, _, _ in hidden}
    words = sorted({word for row in hidden for word in row if word}, key=len, reverse=True)
    mention = (re.compile("|".join(rf"(?<![\w/-]){re.escape(word)}(?![\w/-])"
                                   for word in words)) if words else None)
    lines, left_out = [], False
    for line in findings.splitlines():
        if any(f" {path}: " in line for path in paths):
            left_out = True
            continue
        lines.append(mention.sub(HIDDEN, line) if mention else line)
    if left_out:
        lines.append(NOT_SHOWN)
    return "\n".join(lines)
