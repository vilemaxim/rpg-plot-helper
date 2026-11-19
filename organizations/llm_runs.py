"""Settings that decide whether the app's LLM runs by itself in a World:
reconciling each draft on submission (`reconciling.py`), and a World review
after each Event (`world_reviewing.py`).

Each is the same shape. An Organization Admin sets it for the whole
Organization, off by default, and may set it on or off for one World, which
then wins. Both are kept in the database, not in `world.yml`: they decide
what the app spends on the LLM, not anything about the World's Canon. Plot
Masters see it but cannot change it.
"""

from dataclasses import dataclass

from django.db import models

from .models import Organization, World


class Choice(models.TextChoices):
    """What an Organization Admin may say for one World."""

    FOLLOW = "follow", "Follow the Organization's setting"
    ON = "on", "On for this World"
    OFF = "off", "Off for this World"


@dataclass(frozen=True)
class Setting:
    """The setting in force for a World, and where it comes from."""

    on: bool
    # Whether the World follows the Organization's setting, rather than an
    # Organization Admin having set it for the World.
    follows_organization: bool

    @property
    def choice(self):
        if self.follows_organization:
            return Choice.FOLLOW
        return Choice.ON if self.on else Choice.OFF


@dataclass(frozen=True)
class RunsByItself:
    """One such setting: the Organization's field holding it, and the model
    holding a World's override, one row per World with the field `on`."""

    organization_field: str
    override: type[models.Model]

    def setting_of(self, world):
        """The setting in force for this World: its own, if an Organization
        Admin has set one, and otherwise its Organization's."""
        override = self.override.objects.filter(world=world).first()
        if override is not None:
            return Setting(on=override.on, follows_organization=False)
        on = (Organization.objects.filter(pk=world.organization_id)
              .values_list(self.organization_field, flat=True).get())
        return Setting(on=on, follows_organization=True)

    def is_on(self, world):
        return self.setting_of(world).on

    def set_for_world(self, world, choice):
        """Set this World on or off, or back to following its Organization.
        Only an Organization Admin may; the caller checks."""
        if choice == Choice.FOLLOW:
            self.override.objects.filter(world=world).delete()
            return
        self.override.objects.update_or_create(
            world=world, defaults={"organization_id": world.organization_id,
                                   "on": choice == Choice.ON})

    def worlds_on(self, organization_id):
        """The Worlds of the Organization with this id where it is on. Run
        as that Organization."""
        worlds = World.objects.filter(organization_id=organization_id)
        follows = worlds.exclude(**{f"{self.override_name}__isnull": False})
        own_on = worlds.filter(**{f"{self.override_name}__on": True})
        on = (Organization.objects.filter(pk=organization_id)
              .values_list(self.organization_field, flat=True).get())
        return (own_on | follows) if on else own_on

    @property
    def override_name(self):
        """The World's reverse name for its override row."""
        return self.override._meta.get_field("world").remote_field.related_name
