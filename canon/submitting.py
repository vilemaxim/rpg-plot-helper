"""Submitting one After-Action Report for a Mod.

A report is checked by plotcanon against the World as it is stored. A valid
one is saved, its Canon Changes go on record as proposed, and its Mod's state
is brought up to date: finished if the report says the Mod finished, and in
progress if it ran and there is more to play. The Mod's stored file is changed
to say so, and the World with both changes in it is checked again before
anything is saved, so what is stored is always a World plotcanon accepts.
"""

import re
from collections import namedtuple

import plotcanon
import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from organizations.models import World

from . import editing
from .models import CanonChange, Document, Flag
from .storing import canon_changes_of, new_row, parsed_into

REPORT = "after-action"
PROPOSED = "proposed"

# The block of fields at the top of a file. plotcanon reads files; this app
# reads a submitted report's fields itself only to find where in the World it
# belongs before plotcanon can be asked about it, and edits one field of a
# Mod's file. Both read the block as YAML does, without building its values,
# so nothing in it can cost more than its length. If plotcanon comes to offer
# either, this should go (see #23).
FRONTMATTER = re.compile(r"\A\ufeff?---\r?\n(.*?)\r?\n---", re.S)
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class ReportRefused(Exception):
    """The report was not saved. `str()` says why. `errors` holds plotcanon's
    findings, if that was the reason, as text to paste back into an LLM."""

    def __init__(self, reason, errors=""):
        super().__init__(reason)
        self.errors = errors


def top_level(text):
    """The top-level fields of a file's frontmatter as `{name: node}`, where
    each node is the YAML node holding the value, with its place in the text.
    Empty if there is no frontmatter or it cannot be read; plotcanon will say
    why. Where a name appears twice, the last one counts, as it does in YAML.

    Composing builds the nodes without building the values from them, so an
    alias is a reference to an existing node, not a copy of it.
    """
    block = FRONTMATTER.match(text)
    if block is None:
        return {}, None
    try:
        root = yaml.compose(block.group(1), Loader=yaml.SafeLoader)
    except Exception:  # noqa: BLE001 - unreadable frontmatter is plotcanon's to report
        return {}, None
    if not isinstance(root, yaml.MappingNode):
        return {}, None
    fields = {}
    for key, value in root.value:
        if isinstance(key, yaml.ScalarNode):
            fields[key.value] = value
    return fields, block.start(1)


def said(text, field):
    """What a file's frontmatter gives for one top-level field, if it is a
    single plain value, and otherwise None."""
    node = top_level(text)[0].get(field)
    return node.value if isinstance(node, yaml.ScalarNode) else None


def path_for(text):
    """Where a submitted report belongs in the World: under its Event, named
    by its id. plotcanon needs a path to check a file against, and checks that
    the file agrees with it."""
    def slug(value, otherwise):
        return value if value and SLUG.fullmatch(value) and len(value) <= 200 else otherwise

    return f"after-actions/{slug(said(text, 'event'), 'unknown-event')}/" \
           f"{slug(said(text, 'id'), 'unnamed')}.md"


def with_state(text, state):
    """A Mod's file with the value of its `state` field replaced, and every
    other character, line endings included, left as it was."""
    try:
        return editing.replace(text, ["state"], state)
    except editing.CannotEdit:
        raise ReportRefused("The Mod's stored file has no state that can be updated.") from None


States = namedtuple("States", "draft finished in_progress reportable")


def states():
    """The Mod states this module moves between, by what they mean. The names
    themselves are plotcanon's."""
    vocabulary = plotcanon.vocabularies()
    finished = vocabulary["mod_state_finished"]
    in_progress = next(s for s in vocabulary["mod_states_that_have_run"] if s != finished)
    # A draft is the unfinished state kept in the inbox. A Mod can be reported
    # on once it is approved to run and until it is finished: an unfinished
    # state that is not a draft.
    unfinished = vocabulary["mod_states_unfinished"]
    draft = next(state for state in unfinished
                 if "inbox" in vocabulary["mod_state_dirs"].get(state, []))
    reportable = [state for state in unfinished if state != draft]
    return States(draft, finished, in_progress, reportable)


def can_be_reported_on(mod):
    return mod.fields.get("state") in states().reportable


def state_after(mod, report):
    """The state a Mod should be in once this report is filed: finished if the
    report says so; in progress if it was played and there is more to come;
    and as it was if it was not played."""
    if report.fields.get("finished") is True:
        return states().finished
    if report.fields.get("ran") is True:
        return states().in_progress
    return mod.fields.get("state")


def submit(world, mod, text, user):
    """File a report on `mod`, a stored Mod of `world`. Returns the report's
    `Document`. Raises `ReportRefused`, having saved nothing, if it cannot be."""
    if len(text.encode("utf-8", errors="replace")) > settings.IMPORT_MAX_FILE_BYTES:
        megabytes = settings.IMPORT_MAX_FILE_BYTES / (1024 * 1024)
        raise ReportRefused(f"That report is too large. The limit is {megabytes:g} MB.")
    if "\x00" in text:
        raise ReportRefused("That report contains a null character, which text does not "
                            "have. It may be damaged, or not really text.")
    kind = said(text, "type")
    if kind and kind != REPORT:
        raise ReportRefused(f"That file is a `{kind}`. It is not an After-Action Report, "
                            f"which has `type: {REPORT}`.")

    with transaction.atomic():
        # One submission at a time per World: each is checked against the
        # World as stored, and must not be checked against a World another
        # submission is in the middle of changing.
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(pk=mod.pk)
        if not can_be_reported_on(mod):
            raise ReportRefused(f"{mod.name} cannot be reported on in its present state.")
        files = dict(Document.objects.filter(world=world).values_list("path", "text"))
        path = path_for(text)
        if path in files:
            # plotcanon would take this as a new version of the stored file. A
            # report is not edited by filing it again.
            raise ReportRefused(f"A report with the id `{said(text, 'id')}` has already "
                                f"been filed for that Event. If this is a further report on "
                                f"the Mod, give it an id of its own.")
        try:
            checked = plotcanon.check_file(files, path, text)
        except (ValueError, TypeError) as error:
            raise ReportRefused(f"That report cannot be read: {error}.") from None
        if not checked.ok:
            raise ReportRefused("That report has errors.",
                                errors="\n".join(str(e) for e in checked.errors))
        report = checked.document
        if report.type != REPORT:
            raise ReportRefused(f"That file is a `{report.type}`. It is not an "
                                f"After-Action Report.")
        decided = [i for i, change in enumerate(report.fields.get("canon_changes") or [])
                   if isinstance(change, dict) and change.get("decision") != PROPOSED]
        if decided:
            raise ReportRefused(
                "Every Canon Change in a report is filed as `decision: proposed`: only a Plot "
                "Master approves or rejects one, and that is done here once the report is in. "
                f"Change the decision of canon_changes[{decided[0]}]"
                f"{' and the others' if len(decided) > 1 else ''} to `proposed`.")
        if report.fields.get("mod") != mod.slug:
            raise ReportRefused(f"That report is for the Mod `{report.fields.get('mod')}`, "
                                f"not for {mod.name}. File it from that Mod's page.")

        files[path] = text
        state = state_after(mod, report)
        if state != mod.fields.get("state"):
            files[mod.path] = with_state(mod.text, state)
        whole = plotcanon.load_world(files)
        if not whole.ok:
            raise ReportRefused("Saving that report would leave the World with errors.",
                                errors="\n".join(str(e) for e in whole.errors))

        row = new_row(world, whole.world.get(report.id), whole.world,
                      submitted_by=user, submitted_at=timezone.now())
        row.save()
        changes = CanonChange.objects.bulk_create(canon_changes_of(row))
        if files[mod.path] != mod.text:
            parsed_into(mod, whole.world.get(mod.slug), whole.world).save()
        raise_flags(world, whole, report.id, changes)
    return row


def raise_flags(world, whole, report_id, changes):
    """Flag every unfinished Mod that a change in the report touches, in any
    Campaign. `whole` is plotcanon's report on the World with the new report
    in it and its Mod's state brought up to date, which is the World the Flags
    are worked out in. Which Mods a change flags is plotcanon's rule.

    Every Flag plotcanon names is stored. One that names a Mod or a change
    this app does not have would be a fault, and fails the whole submission
    rather than being quietly left out."""
    by_position = {change.position: change for change in changes}
    mods = dict(Document.objects.filter(world=world, kind="mod").values_list("slug", "pk"))
    Flag.objects.bulk_create([
        Flag(organization=world.organization, world=world, mod_id=mods[flag.mod],
             change=by_position[flag.change])
        for flag in plotcanon.flags(whole.world, whole.world.get(report_id))
    ])
