"""Exporting a World as one zip of its files, so that nobody is locked in and
a World can move to larp-llm (ADR-0001).

Each document's file is stored exactly as it stands, kept in step with every
decision (ADR-0006), so an export writes those files out under their paths.
The zip opens to one folder named after the World, which importing accepts.
It is made in memory: nothing is written to the app's disk.

What lives only in the app, such as who submitted or decided what, Flags and
their resolutions, Mod Writers and private links, and accounts, is not in the
files, and so not in an export.
"""

import io
import logging
import zipfile

import plotcanon
from django.utils.text import slugify

from .storing import files_of, one_to_a_line

logger = logging.getLogger(__name__)


class ExportFailed(Exception):
    """The World's stored files are not a World plotcanon accepts. That should
    never happen, since every change is checked before it is saved, so it is a
    fault to report, not a zip to hand over. `errors` holds plotcanon's
    findings."""

    def __init__(self, world, errors):
        super().__init__(f"plotcanon finds errors in World {world.pk} as stored")
        self.errors = errors


def folder_for(world):
    """The name of the folder a World's files go in: its name, as a path."""
    return slugify(world.name, allow_unicode=True) or "world"


def export(world):
    """The World as zip bytes, and the zip's file name. Raises `ExportFailed`
    if plotcanon does not accept the World as stored."""
    try:
        report = plotcanon.load_world(files_of(world))
    except (ValueError, TypeError) as error:
        # plotcanon refuses a path that would leave the World's folder, such
        # as `../x` or `/x`, by raising.
        failed = ExportFailed(world, str(error))
    else:
        failed = None if report.ok else \
            ExportFailed(world, one_to_a_line(report.errors))
    if failed is not None:
        logger.error("%s:\n%s", failed, failed.errors)
        raise failed
    # The paths plotcanon read, which it has checked stay inside the World.
    files = report.world.files
    folder = folder_for(world)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(f"{folder}/{path}", files[path])
    return buffer.getvalue(), f"{folder}.zip"
