"""Importing a World from a zip of its files.

Everything is done in memory: the upload is never written to disk (ADR-0003).
The zip is not trusted. It is bounded before and while it is unpacked, and
whatever goes wrong reading it is reported to the person, not raised.
"""

import datetime
import io
import math
import zipfile
import zlib

import plotcanon
from django.conf import settings
from django.db import transaction

from organizations.models import World

from .models import Document

MAX_ID = Document._meta.get_field("slug").max_length
MAX_PATH = Document._meta.get_field("path").max_length

class ImportRefused(Exception):
    """The upload cannot be imported. `str()` says why, for the person who
    uploaded it. `errors` holds validation errors, if that was the reason."""

    def __init__(self, reason, errors=""):
        super().__init__(reason)
        self.errors = errors


def megabytes(size):
    return f"{size / (1024 * 1024):g} MB"


def read_bounded(archive, member, room):
    """One member of the zip, read a piece at a time so that a file which
    unpacks far larger than it claims is caught before it fills memory.
    `room` is how many more bytes the whole import may still unpack."""
    limit = min(settings.IMPORT_MAX_FILE_BYTES, room)
    with archive.open(member) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        if limit < settings.IMPORT_MAX_FILE_BYTES:
            raise ImportRefused("That zip is too large once unpacked.")
        raise ImportRefused(f"{member.filename} is larger than "
                            f"{megabytes(settings.IMPORT_MAX_FILE_BYTES)}, which is more "
                            "than one document should need.")
    return data


def files_in(upload):
    """The markdown files in an uploaded zip, as `{path: text}`."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(upload.read()))
        members = [m for m in archive.infolist() if not m.is_dir()]
    except (zipfile.BadZipFile, ValueError):
        raise ImportRefused("That file is not a zip. Zip the World's folder and upload "
                            "the .zip file.") from None
    if len(members) > settings.IMPORT_MAX_FILES:
        raise ImportRefused(f"That zip has more than {settings.IMPORT_MAX_FILES} files, "
                            "which is more than a World should need.")
    if sum(m.file_size for m in members) > settings.IMPORT_MAX_UNPACKED_BYTES:
        raise ImportRefused("That zip is too large once unpacked.")

    files = {}
    room = settings.IMPORT_MAX_UNPACKED_BYTES
    for member in members:
        path = member.filename
        if not path.endswith(".md"):
            continue
        try:
            data = read_bounded(archive, member, room)
        except (zipfile.BadZipFile, zlib.error, EOFError):
            raise ImportRefused(f"{path} could not be unpacked. The zip may be damaged; "
                                "make it again and upload that.") from None
        except (NotImplementedError, RuntimeError):
            raise ImportRefused(f"{path} is encrypted or packed in a way that cannot be "
                                "read here. Make an ordinary zip with no password.") from None
        room -= len(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ImportRefused(f"{path} is not UTF-8 text, so it cannot be read.") from None
        if "\x00" in text:
            raise ImportRefused(f"{path} contains a null character, which text files do "
                                "not have. It may be damaged, or not really text.")
        files[path] = text
    return files


def unwrapped(files):
    """Zipping a folder puts everything inside one top-level folder. If every
    file shares one, return the files with that folder taken off their paths,
    and otherwise None."""
    tops = {path.split("/", 1)[0] for path in files}
    if len(tops) != 1 or not all("/" in path for path in files):
        return None
    (top,) = tops
    return {path[len(top) + 1:]: text for path, text in files.items()}


def validated(files):
    """plotcanon's report on the World in these files. If nothing in them
    reads as a World, it may be a World zipped as a folder; plotcanon decides
    what a World's files are, so it is asked again with the one wrapping
    folder taken off."""
    try:
        report = plotcanon.load_world(files)
        if report.document_count == 0 and not report.errors:
            inside = unwrapped(files)
            if inside is not None:
                report = plotcanon.load_world(inside)
    except (ValueError, TypeError, RecursionError) as error:
        raise ImportRefused(f"That zip cannot be imported: {error}.") from None
    return report


def storable(value):
    """A frontmatter value in a form the database can hold as JSON. YAML allows
    values JSON does not: dates, not-a-number, binary data, sets."""
    if isinstance(value, dict):
        return {str(key): storable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [storable(inner) for inner in items]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def name_of(document, world):
    """What to call a document on a page: its title, or the first of its
    names, or failing both its id. An After-Action Report has neither, so it
    is called after its Mod and Event."""
    if document.type == "after-action":
        mod = world.get(document.fields.get("mod"))
        event = world.get(document.fields.get("event"))
        if mod is not None and event is not None:
            return f"{name_of(mod, world)} at {name_of(event, world)}"
    title = document.fields.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    aliases = document.fields.get("aliases")
    if isinstance(aliases, list) and aliases and str(aliases[0]).strip():
        return str(aliases[0]).strip()
    return str(document.id)


def import_world(world, upload):
    """Import the World in an uploaded zip into `world`, which must hold no
    Canon yet. Returns the plotcanon report. Raises `ImportRefused`, having
    imported nothing, if the zip cannot be read, the World in it is not valid,
    or `world` has gained Canon in the meantime.
    """
    report = validated(files_in(upload))
    if report.document_count == 0 and not report.errors:
        raise ImportRefused("There are no World files in that zip. A World's files are "
                            "markdown under folders such as canon/ and mods/.")
    if not report.ok:
        raise ImportRefused("That World has errors.",
                            errors="\n".join(str(error) for error in report.errors))
    for document in report.world.documents:
        if len(str(document.id)) > MAX_ID:
            raise ImportRefused(f"The id in {document.path} is longer than {MAX_ID} characters.")
        if len(document.path) > MAX_PATH:
            raise ImportRefused(f"The path {document.path[:80]}… is longer than "
                                f"{MAX_PATH} characters.")

    with transaction.atomic():
        # Two imports into one World at the same moment would otherwise both
        # find it empty. The second waits here, then finds it is not.
        World.objects.select_for_update().get(pk=world.pk)
        if Document.objects.filter(world=world).exists():
            raise ImportRefused(f"{world.name} already has Canon. Someone may have "
                                "imported into it a moment ago.")
        Document.objects.bulk_create([
            Document(
                organization=world.organization,
                world=world,
                path=document.path,
                kind=document.type,
                slug=str(document.id),
                name=name_of(document, report.world)[:300],
                fields=storable(dict(document.fields)),
                body=document.body,
                text=report.world.files[document.path],
            )
            for document in report.world.documents
        ])
    return report
