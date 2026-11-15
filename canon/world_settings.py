"""A World's settings, kept in its settings file, `world.yml`.

The file is one of the World's files and its format is plotcanon's
(ADR-0004), so changing a setting is changing that file. Its one setting is
how strictly the World asks for Dry Run structure in its Mods: `off`,
`encouraged` or `required` (ADR-0007). plotcanon checks every Mod in the
World against it, so a change that would leave the World with errors, such
as requiring structure while some Mods have none, is refused with
plotcanon's findings, and the World keeps the setting it had.
"""

import plotcanon
from django.db import transaction

from organizations.models import World

from .storing import files_of
from .submitting import Refused


class SettingRefused(Refused):
    """The setting was not changed."""


def settings_of(world):
    """The World's settings, as its settings file says. plotcanon's defaults
    apply to a World with no settings file."""
    stored = World.objects.filter(pk=world.pk).values_list("settings_file", flat=True).first()
    return plotcanon.world_settings({plotcanon.WORLD_SETTINGS_FILE: stored} if stored else {})


def settings_file_for(structure):
    """The whole text of a settings file giving this Dry Run structure."""
    return plotcanon.WorldSettings(dry_run_structure=structure).text()


def set_dry_run_structure(world, structure):
    """Rewrite the World's settings file with this Dry Run structure. Raises
    `SettingRefused`, having changed nothing, if plotcanon would then find
    errors in the World."""
    text = settings_file_for(structure)
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        files = files_of(world)
        files[plotcanon.WORLD_SETTINGS_FILE] = text
        report = plotcanon.load_world(files)
        if not report.ok:
            raise SettingRefused(
                f"{world.name} cannot be set to `{structure}`: plotcanon would then find "
                f"these errors in its Mods. Revise them first.",
                errors="\n".join(str(error) for error in report.errors))
        World.objects.filter(pk=world.pk).update(settings_file=text)
