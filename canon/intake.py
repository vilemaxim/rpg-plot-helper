"""Taking in a Mod a Mod Writer has written: a new one, or a revision of a
draft.

Mods are written in the Mod Writer's own LLM and submitted as a file
(ADR-0002). A submitted Mod is a draft, kept in the World's inbox, and is not
Canon until a Plot Master approves it (`approving.py`). Whatever the file says
about its own state, it is taken in as `state: draft` and `canon: proposed`:
those are the Plot Master's to change, never the Mod Writer's.

A draft may name people, places and factions the World does not have yet;
plotcanon allows that in the inbox and warns about it. Everything else about
the file is checked by plotcanon against the World as stored, and the World
with the draft in it is checked before anything is saved.

Submitting a draft raises no Flags: a Flag warns about a change to Canon, and
a draft changes none.
"""

import plotcanon
from django.db import transaction
from django.utils import timezone
from plotcanon import editing

from organizations.models import World

from .models import Document
from .storing import SavedMod, files_of, new_row, one_to_a_line, parsed_into
from .submitting import SLUG, Refused, mod_path, said, states, unreadable

MOD = "mod"
PROPOSED = "proposed"


class ModRefused(Refused):
    """The Mod was not saved."""


def taken_in(text):
    """The file as a draft: `state: draft` and `canon: proposed`, and every
    other character as it was. A file whose fields cannot be read is left as
    it is, for plotcanon to say why."""
    try:
        text = editing.set_field(text, "state", states().draft)
        return editing.set_field(text, "canon", PROPOSED)
    except editing.CannotEdit:
        return text


def screened(text):
    """Refuse a file that cannot be a Mod before plotcanon is asked about it."""
    reason = unreadable(text, "Mod", MOD, "a Mod")
    if reason:
        raise ModRefused(reason)


def checked(files, path, text):
    """plotcanon's verdict on the World with `text` at `path`, which must be a
    Mod, and its warnings about the Mod, as text. Raises `ModRefused` if it is
    not valid. How strictly the Mod must follow the Dry Run convention is the
    World's setting, in its settings file among `files`: under `encouraged`
    the convention's findings are warnings, under `required` errors."""
    try:
        report = plotcanon.check_file(files, path, text)
    except (ValueError, TypeError) as error:
        raise ModRefused(f"That Mod cannot be read: {error}.") from None
    if not report.ok:
        raise ModRefused("That Mod has errors.",
                         errors=one_to_a_line(report.errors))
    if report.document.type != MOD:
        raise ModRefused(f"That file is a `{report.document.type}`. It is not a Mod.")
    whole = plotcanon.load_world({**files, path: text})
    if not whole.ok:
        raise ModRefused("Saving that Mod would leave the World with errors.",
                         errors=one_to_a_line(whole.errors))
    return whole, one_to_a_line(report.warnings)


def submit_mod(world, text, user):
    """Take in a new Mod as a draft. Returns a `SavedMod`: its `Document`
    and plotcanon's warnings about it, as text to paste into an LLM. Raises
    `ModRefused`, having saved nothing, if it cannot be."""
    with transaction.atomic():
        whole, slug, warnings = _new_mod_checked(world, text)
        row = new_row(world, whole.world.get(slug), whole.world,
                      submitted_by=user, submitted_at=timezone.now())
        row.save()
    return SavedMod(row, warnings)


def check_new_mod(world, text):
    """Check a new Mod the way `submit_mod` would, saving nothing: raises
    `ModRefused` if it would be refused now. Used to check the file an LLM
    writes in an Interview before the person sees it."""
    with transaction.atomic():
        _new_mod_checked(world, text)


def _new_mod_checked(world, text):
    """Everything `submit_mod` checks, inside its transaction: the World as
    plotcanon reads it with the Mod in it, the Mod's id, and its warnings."""
    screened(text)
    slug = said(text, "id")
    if not slug or not SLUG.fullmatch(slug) or len(slug) > 200:
        raise ModRefused("That Mod has no id that can be used. Give it one of lower-case "
                         "letters, digits and hyphens, such as `id: the-lamplighters-debt`.")
    text = taken_in(text)
    # One change at a time per World, each checked against the World as
    # stored.
    World.objects.select_for_update().get(pk=world.pk)
    existing = Document.objects.filter(world=world, slug=slug).first()
    if existing is not None:
        if existing.kind == MOD and existing.fields.get("state") == states().draft:
            raise ModRefused(f"{existing.name} is already a draft with the id `{slug}`. "
                             f"To change it, revise it from its page.")
        raise ModRefused(f"{world.name} already has something with the id `{slug}`: "
                         f"{existing.name}. Give the Mod an id of its own.")
    files = files_of(world)
    path = mod_path(states().draft, slug)
    if path in files:
        raise ModRefused(f"{world.name} already has a file at `{path}`. Give the Mod an "
                         f"id of its own.")
    whole, warnings = checked(files, path, text)
    return whole, slug, warnings


def revise(world, mod, text, user):
    """Replace a draft Mod's file with a revised one with the same id. The
    draft keeps its history: who submitted it, its Flags, and who sent it back
    and why. Returns a `SavedMod`: the Mod and plotcanon's warnings about it.
    Raises `ModRefused`, having saved nothing, if it cannot be."""
    with transaction.atomic():
        mod, whole, warnings = _revision_checked(world, mod, text)
        parsed_into(mod, whole.world.get(mod.slug), whole.world).save()
    return SavedMod(mod, warnings)


def check_revision(world, mod, text):
    """Check a revision of a draft the way `revise` would, saving nothing:
    raises `ModRefused` if it would be refused now. Used to check the file an
    LLM writes in a revise Interview before the person sees it."""
    with transaction.atomic():
        _revision_checked(world, mod, text)


def _revision_checked(world, mod, text):
    """Everything `revise` checks, inside its transaction: the draft as
    stored, the World as plotcanon reads it with the revision in it, and the
    revision's warnings."""
    screened(text)
    if said(text, "id") != mod.slug:
        raise ModRefused(f"That file is the Mod `{said(text, 'id')}`, not {mod.name}, "
                         f"whose id is `{mod.slug}`. A revision keeps its Mod's id.")
    text = taken_in(text)
    World.objects.select_for_update().get(pk=world.pk)
    mod = Document.objects.get(pk=mod.pk)
    if mod.fields.get("state") != states().draft:
        raise ModRefused(f"{mod.name} is not a draft, and only a draft can be revised.")
    files = files_of(world)
    whole, warnings = checked(files, mod.path, text)
    return mod, whole, warnings
