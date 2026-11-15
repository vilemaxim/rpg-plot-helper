"""Resolving Flags: dismissing one, or sending its Mod back to its Mod Writer.

Rejecting the Canon Change that raised a Flag also resolves it; that happens
where the change is decided (`deciding.py`).

A resolved Flag stays on record with how it was resolved, by whom and when.
"""

import plotcanon
from django.db import transaction
from django.utils import timezone

from organizations.models import World

from . import editing
from .models import Document, Flag
from .storing import parsed_into
from .submitting import states


class ResolutionRefused(Exception):
    """Nothing was resolved. `str()` says why, for the Plot Master."""


def resolve(flags, how, user, note=""):
    """Mark open Flags resolved. Returns how many were."""
    return flags.filter(resolution="").update(
        resolution=how, resolved_by=user, resolved_at=timezone.now(), note=note)


def dismiss(world, flag_id, user):
    """Dismiss one Flag: the change does not matter to the Mod after all."""
    with transaction.atomic():
        flag = Flag.objects.select_for_update().filter(
            organization=world.organization, world=world, pk=flag_id).first()
        if flag is None:
            raise ResolutionRefused("There is no such Flag.")
        if flag.resolution:
            raise ResolutionRefused("That Flag has already been resolved.")
        resolve(Flag.objects.filter(pk=flag.pk), Flag.Resolution.DISMISSED, user)
    return flag


def draft_path(mod):
    """Where a draft lives in the World: its inbox. plotcanon's rule."""
    folder = plotcanon.vocabularies()["mod_state_dirs"][states().draft][0]
    return f"{folder}/{mod.slug}.md"


# A reason is a line or two for the Mod Writer, not a rewrite of the Mod.
MAX_REASON = 2000


def send_back(world, mod, reason, user):
    """Return a Mod to its Mod Writer: it becomes a draft again, and every open
    Flag on it is resolved with the reason given. A draft is not Canon, so its
    file moves to the inbox and says `canon: proposed`."""
    reason = reason.strip()
    if not reason:
        raise ResolutionRefused("Say why the Mod is being sent back, so its Mod Writer knows "
                                "what to change.")
    if len(reason) > MAX_REASON:
        raise ResolutionRefused(f"Keep the reason to {MAX_REASON:,} characters.")
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(pk=mod.pk)
        state = mod.fields.get("state")
        if state == states().draft:
            raise ResolutionRefused(f"{mod.name} is already a draft.")
        if state not in states().reportable:
            raise ResolutionRefused(f"{mod.name} is {state}, so it is not sent back.")

        try:
            text = editing.replace(mod.text, ["state"], states().draft)
            text = editing.replace(text, ["canon"], "proposed")
        except editing.CannotEdit as error:
            raise ResolutionRefused(f"The Mod's stored file could not be updated: {error}.")
        files = dict(Document.objects.filter(world=world).values_list("path", "text"))
        del files[mod.path]
        files[draft_path(mod)] = text
        whole = plotcanon.load_world(files)
        if not whole.ok:
            raise ResolutionRefused("Sending it back would leave the World with errors: "
                                    + " ".join(str(e) for e in whole.errors[:3]))
        if any(w.path == draft_path(mod) for w in whole.warnings):
            # A Mod whose reports say it has been played cannot also be a
            # draft that has not; plotcanon warns that the two disagree.
            raise ResolutionRefused(
                f"{mod.name} has already been played: its reports say so, and a draft has "
                f"not been. Dismiss its Flags instead, and handle the rest of it in the "
                f"reports still to come.")

        parsed_into(mod, whole.world.get(mod.slug), whole.world).save()
        resolve(Flag.objects.filter(organization=world.organization, world=world, mod=mod),
                Flag.Resolution.SENT_BACK, user, note=reason)
    return mod
