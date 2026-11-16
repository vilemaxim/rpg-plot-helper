"""Submitting one After-Action Report for a Mod.

A report is checked by plotcanon against the World as it is stored. A valid
one is saved, its Canon Changes go on record as proposed, and its Mod's state
is brought up to date: finished if the report says the Mod finished, and in
progress if it ran and there is more to play. A report at an Event of the
Mod's Campaign that the Mod does not list yet adds that Event to the Mod's
`events`, since a Mod interrupted at one Event can go on at another. The Mod's
stored file is changed to say so, and the World with both changes in it is checked again before
anything is saved, so what is stored is always a World plotcanon accepts.
"""

import re
from collections import namedtuple

import plotcanon
import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from plotcanon import editing

from organizations.models import World

from .models import CanonChange, Decision, Document, Flag
from .storing import canon_changes_of, files_of, new_row, one_to_a_line, parsed_into

REPORT = "after-action"

# The block of fields at the top of a file. plotcanon reads files; this app
# reads a submitted report's fields itself only to find where in the World it
# belongs before plotcanon can be asked about it, and edits one field of a
# Mod's file. Both read the block as YAML does, without building its values,
# so nothing in it can cost more than its length. If plotcanon comes to offer
# either, this should go (see #23).
FRONTMATTER = re.compile(r"\A\ufeff?---\r?\n(.*?)\r?\n---", re.S)
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class Refused(Exception):
    """A submitted file was not saved. `str()` says why. `errors` holds
    plotcanon's findings, if that was the reason, as text to paste back into an
    LLM."""

    def __init__(self, reason, errors=""):
        super().__init__(reason)
        self.errors = errors


class ReportRefused(Refused):
    """The report was not saved."""


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


def with_event(text, event):
    """A Mod's file with `event` added to its `events`, and every other
    character, line endings included, left as it was."""
    try:
        return editing.add_to_list(text, "events", event)
    except editing.CannotEdit:
        raise ReportRefused("The Mod's stored file has no list of Events that can be "
                            "added to.") from None


def listing_its_event(world, mod, text, files):
    """The Mod's file as it should be stored once this report is filed: with
    the report's Event added to its `events` if it is not there yet, which is
    how a Mod that goes on at a later Event comes to list it. The Event must be
    one of the Mod's own Campaign. Returns the file unchanged if the report
    names no Event the app can read; plotcanon then says what is wrong."""
    event = said(text, "event")
    listed = mod.fields.get("events") or []
    if not event or not isinstance(listed, list) or event in listed:
        return files[mod.path]
    found = Document.objects.filter(world=world, kind="event", slug=event).first()
    if found is None:
        raise ReportRefused(f"There is no Event `{event}` in this World. Check the "
                            f"report's `event`: it should be the id of the Event where "
                            f"{mod.name} was run.")
    campaign = mod.fields.get("campaign")
    if found.fields.get("campaign") != campaign:
        raise ReportRefused(f"The Event `{event}` ({found.name}) is not one of "
                            f"{mod.name}'s Campaign, `{campaign}`, so the Mod cannot run "
                            f"there. Check the report's `event`.")
    return with_event(files[mod.path], event)


States = namedtuple("States", "draft approved finished in_progress reportable")


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
    approved = next(state for state in reportable
                    if state not in vocabulary["mod_states_that_have_run"])
    return States(draft, approved, finished, in_progress, reportable)


def mod_path(state, slug, campaign=None):
    """Where a Mod in this state lives in the World. plotcanon's rule: a draft
    in the inbox, and a Mod approved to run in its Campaign's folder. The
    folders are plotcanon's; filling in the Campaign is format knowledge it
    should come to offer (#23)."""
    folder = plotcanon.vocabularies()["mod_state_dirs"][state][0]
    if "<campaign>" in folder:
        if not campaign:
            raise ValueError(f"a Mod that is {state} lives in its Campaign's folder")
        folder = folder.replace("<campaign>", campaign)
    return f"{folder}/{slug}.md"


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


def unreadable(text, noun, doc_type, called):
    """Why a submitted file cannot be taken in, before plotcanon is asked
    about it, or None. It must be text of a size that can be stored, and if it
    says what type of document it is, that must be `doc_type`. `noun` and
    `called` are what to call such a file in the reason."""
    if len(text.encode("utf-8", errors="replace")) > settings.IMPORT_MAX_FILE_BYTES:
        megabytes = settings.IMPORT_MAX_FILE_BYTES / (1024 * 1024)
        return f"That {noun} is too large. The limit is {megabytes:g} MB."
    if "\x00" in text:
        return (f"That {noun} contains a null character, which text does not have. It may "
                f"be damaged, or not really text.")
    kind = said(text, "type")
    if kind and kind != doc_type:
        return f"That file is a `{kind}`. It is not {called}, which has `type: {doc_type}`."
    return None


def submit(world, mod, text, user, *, agrees=None):
    """File a report on `mod`, a stored Mod of `world`, as `user`. Returns the
    report's `Document`. Raises `ReportRefused`, having saved nothing, if it
    cannot be.

    `agrees`, if given, is called with the report as plotcanon read it once
    it is otherwise fit to file, and raises `ReportRefused` if the report
    does not agree with what its caller knows: a report Interview's Path."""
    with transaction.atomic():
        # One submission at a time per World: each is checked against the
        # World as stored, and must not be checked against a World another
        # submission is in the middle of changing.
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(pk=mod.pk)
        files, report, whole = checked_in(world, mod, text, agrees)
        row = new_row(world, whole.world.get(report.id), whole.world,
                      submitted_by=user, submitted_at=timezone.now())
        row.save()
        changes = CanonChange.objects.bulk_create(canon_changes_of(row))
        if files[mod.path] != mod.text:
            parsed_into(mod, whole.world.get(mod.slug), whole.world).save()
        raise_flags(world, whole, report.id, changes)
    return row


def check(world, mod, text, *, agrees=None):
    """Check a report on `mod` the way `submit` would, saving nothing: raises
    `ReportRefused` if it would be refused now. Used to check the report an
    LLM writes in an Interview before the person sees it."""
    with transaction.atomic():
        checked_in(world, Document.objects.get(pk=mod.pk), text, agrees)


def checked_in(world, mod, text, agrees=None):
    """The World's files with the report filed on `mod` as `submit` would
    file it, the report as plotcanon read it, and plotcanon's report on that
    World. Raises `ReportRefused` if it cannot be filed."""
    reason = unreadable(text, "report", REPORT, "an After-Action Report")
    if reason:
        raise ReportRefused(reason)
    if not can_be_reported_on(mod):
        raise ReportRefused(f"{mod.name} cannot be reported on in its present state.")
    files = files_of(world)
    path = path_for(text)
    if path in files:
        # plotcanon would take this as a new version of the stored file. A
        # report is not edited by filing it again.
        raise ReportRefused(f"A report with the id `{said(text, 'id')}` has already "
                            f"been filed for that Event. If this is a further report on "
                            f"the Mod, give it an id of its own.")
    files[mod.path] = listing_its_event(world, mod, text, files)
    try:
        checked = plotcanon.check_file(files, path, text)
    except (ValueError, TypeError) as error:
        raise ReportRefused(f"That report cannot be read: {error}.") from None
    if not checked.ok:
        raise ReportRefused("That report has errors.",
                            errors=one_to_a_line(checked.errors))
    report = checked.document
    if report.type != REPORT:
        raise ReportRefused(f"That file is a `{report.type}`. It is not an "
                            f"After-Action Report.")
    decided = [i for i, change in enumerate(report.fields.get("canon_changes") or [])
               if isinstance(change, dict) and change.get("decision") != Decision.PROPOSED]
    if decided:
        raise ReportRefused(
            "Every Canon Change in a report is filed as `decision: proposed`: only a Plot "
            "Master approves or rejects one, and that is done here once the report is in. "
            f"Change the decision of canon_changes[{decided[0]}]"
            f"{' and the others' if len(decided) > 1 else ''} to `proposed`.")
    if report.fields.get("mod") != mod.slug:
        raise ReportRefused(f"That report is for the Mod `{report.fields.get('mod')}`, "
                            f"not for {mod.name}. File it from that Mod's page.")

    if agrees is not None:
        agrees(report)

    files[path] = text
    state = state_after(mod, report)
    if state != mod.fields.get("state"):
        files[mod.path] = with_state(files[mod.path], state)
    whole = plotcanon.load_world(files)
    if not whole.ok:
        raise ReportRefused("Saving that report would leave the World with errors.",
                            errors=one_to_a_line(whole.errors))
    return files, report, whole


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
