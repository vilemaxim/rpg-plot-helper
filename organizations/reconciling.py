"""Whether a World's draft Mods are reconciled when they are submitted.

An Organization Admin sets it for the whole Organization, off by default, and
may set it on or off for one World, which then wins. Both are kept in the
database, not in `world.yml`: they decide what the app spends on the LLM, not
anything about the World's Canon. Plot Masters see it but cannot change it.
"""

from dataclasses import dataclass

from django.db import models

from .models import Organization, ReconcilingOverride


class Choice(models.TextChoices):
    """What an Organization Admin may say for one World."""

    FOLLOW = "follow", "Follow the Organization's setting"
    ON = "on", "On for this World"
    OFF = "off", "Off for this World"


@dataclass(frozen=True)
class Setting:
    """The setting in force for a World, and where it comes from."""

    reconciles: bool
    # Whether the World follows the Organization's setting, rather than an
    # Organization Admin having set it for the World.
    follows_organization: bool

    @property
    def choice(self):
        if self.follows_organization:
            return Choice.FOLLOW
        return Choice.ON if self.reconciles else Choice.OFF


def setting_of(world):
    """The setting in force for this World: its own, if an Organization Admin
    has set one, and otherwise its Organization's."""
    override = ReconcilingOverride.objects.filter(world=world).first()
    if override is not None:
        return Setting(reconciles=override.reconciles, follows_organization=False)
    reconciles = (Organization.objects.filter(pk=world.organization_id)
                  .values_list("reconciles_on_submission", flat=True).get())
    return Setting(reconciles=reconciles, follows_organization=True)


def reconciles_on_submission(world):
    """Whether a draft Mod in this World is reconciled when it is submitted or
    revised."""
    return setting_of(world).reconciles


def set_for_world(world, choice):
    """Set this World on or off, or back to following its Organization. Only
    an Organization Admin may; the caller checks."""
    if choice == Choice.FOLLOW:
        ReconcilingOverride.objects.filter(world=world).delete()
        return
    ReconcilingOverride.objects.update_or_create(
        world=world, defaults={"organization_id": world.organization_id,
                               "reconciles": choice == Choice.ON})
