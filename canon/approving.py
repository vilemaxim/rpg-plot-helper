"""Approving a draft Mod, so that it can be run.

An approved Mod is Canon: in plotcanon's file format its file moves out of
the inbox into its Campaign's folder, and says `state: approved` and
`canon: approved` (ADR-0004). A Mod that does not name its Campaign has one
chosen for it, which is written into its file. The World with the approved
Mod in it is checked again before anything is saved, so what is stored is
always a World plotcanon accepts.

A Mod's open Flags stay open: approving it does not say the changes they warn
about have been dealt with.
"""

import plotcanon
from django.db import transaction
from django.utils import timezone
from plotcanon import editing

from organizations.models import World

from .models import Document
from .storing import SavedMod, files_of, one_to_a_line, parsed_into
from .submitting import Refused, mod_path, said, states

CANON = "approved"


class ApprovalRefused(Refused):
    """Nothing was approved."""


def campaigns_of(world):
    """The World's Campaigns, as `{id: name}`."""
    return dict(Document.objects.filter(organization=world.organization, world=world,
                                        kind="campaign").values_list("slug", "name"))


def needs_campaign(mod):
    """Whether a Mod must have its Campaign chosen to be approved."""
    return not said(mod.text, "campaign")


def approve(world, mod, user, campaign=None):
    """Approve a draft Mod. `campaign` is used only if the Mod names none, and
    must then be one of the World's. Returns a `SavedMod`: the Mod and plotcanon's warnings
    about it as approved, as text: those it already had as a draft, such as
    the Dry Run convention's under `encouraged`. Raises `ApprovalRefused`,
    having saved nothing, if it cannot be approved."""
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(pk=mod.pk)
        if mod.fields.get("state") != states().draft:
            raise ApprovalRefused(f"{mod.name} is not a draft, so there is nothing to approve.")

        text = mod.text
        named = said(text, "campaign")
        if not named:
            if campaign not in campaigns_of(world):
                raise ApprovalRefused(f"{mod.name} does not say which Campaign it belongs to. "
                                      f"Choose the Campaign it will be run in.")
            named = campaign
            text = editing.set_field(text, "campaign", campaign)
        try:
            text = editing.replace(text, ["state"], states().approved)
            text = editing.replace(text, ["canon"], CANON)
        except editing.CannotEdit as error:
            raise ApprovalRefused(f"The Mod's stored file could not be updated: {error}.") \
                from None

        files = files_of(world)
        # A draft may already be warned about, for naming something the World
        # does not have yet; that is an error once it is Canon. A warning about
        # anything else that is new once it is approved stops it. A finding's
        # message does not include its path, so one found before and after
        # the move reads the same.
        before = {w.message for w in plotcanon.load_world(files).warnings
                  if w.path == mod.path}
        del files[mod.path]
        path = mod_path(states().approved, mod.slug, named)
        files[path] = text
        whole = plotcanon.load_world(files)
        if not whole.ok:
            raise ApprovalRefused(f"{mod.name} cannot be approved as it stands.",
                                  errors=one_to_a_line(whole.errors))
        new = [w for w in whole.warnings if w.path == path and w.message not in before]
        if new:
            raise ApprovalRefused(f"{mod.name} cannot be approved as it stands.",
                                  errors=one_to_a_line(new))

        mod = parsed_into(mod, whole.world.get(mod.slug), whole.world)
        mod.approved_by, mod.approved_at = user, timezone.now()
        mod.save()
    return SavedMod(mod, one_to_a_line(w for w in whole.warnings if w.path == path))
