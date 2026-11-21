"""Who a Mod's Mod Writer is, as a person who can sign in.

A Mod's file names its writer by a handle (`mod_writer: sam`), which is a word
in the file, not an account. The app ties a Mod to a person in one of three
ways, the first that applies winning:

- a Plot Master reassigned the draft to them;
- they submitted it here;
- a Plot Master linked its handle to them, which covers every Mod with it.

None of this is written into a file: accounts never appear in files
(ADR-0001). A Mod Writer is someone who may write Mods in the Mod's World.
"""

from django.db import transaction
from django.utils import timezone

from organizations.models import Role, World

from .models import Document, WriterHandle
from .roles import chosen, people_holding, plot_team
from .submitting import states


class WriterRefused(Exception):
    """Nothing was changed. `str()` says why."""


def handle_of(mod):
    """The handle a Mod's file gives its writer, or "" if it gives none."""
    handle = mod.fields.get("mod_writer")
    return handle.strip() if isinstance(handle, str) else ""


def handles_in(world):
    """`{handle: person or None}` for every handle the World's Mods use."""
    linked = {link.handle: link.user for link in
              WriterHandle.objects.filter(organization=world.organization, world=world)
              .select_related("user")}
    mods = Document.objects.filter(organization=world.organization, world=world, kind="mod")
    return {handle: linked.get(handle)
            for handle in sorted({handle_of(mod) for mod in mods} - {""})}


def writer_of(mod, handles=None):
    """The person who is this Mod's Mod Writer, or None if the app does not
    know. `handles` is `handles_in(world)`, to save asking again for each of
    many Mods."""
    if mod.writer_id is not None:
        return mod.writer
    if mod.submitted_by_id is not None:
        return mod.submitted_by
    if handles is None:
        link = WriterHandle.objects.filter(organization_id=mod.organization_id,
                                           world_id=mod.world_id, handle=handle_of(mod)) \
            .select_related("user").first()
        return link.user if link else None
    return handles.get(handle_of(mod))


def is_writer_of(mod, person, handles=None):
    """Whether this person is the Mod's Mod Writer."""
    writer = writer_of(mod, handles)
    return writer is not None and writer.pk == person.pk


def may_write_mods_in(world):
    """The people who may be a Mod Writer in this World, by email: its Mod
    Writers and its plot team, since a Plot Master or an Admin may write Mods."""
    return (people_holding(world, Role.MOD_WRITER) | plot_team(world)).order_by("email")


def still_writes(world, person):
    """Whether someone still holds a role that lets them write Mods here. A
    Mod's Mod Writer can lose it after being linked or assigned."""
    return may_write_mods_in(world).filter(pk=person.pk).exists()


def drafts_of(world, person):
    """The draft Mods this person is the Mod Writer of, as `(mod, sent_back)`
    pairs. `sent_back` says the draft was sent back while it was theirs: a
    draft reassigned to them since was not sent back to them."""
    drafts = list(Document.objects.filter(
        organization=world.organization, world=world, kind="mod",
        fields__state=states().draft).select_related("writer", "submitted_by"))
    if not drafts:
        return []
    handles = handles_in(world)
    return [(mod, mod.sent_back_at is not None
             and (mod.reassigned_at is None or mod.sent_back_at > mod.reassigned_at))
            for mod in drafts if is_writer_of(mod, person, handles)]


def eligible_writer(world, user_id):
    """The person a Plot Master named to be a Mod Writer here, from the id a
    form sent. Refused unless they may write Mods in this World."""
    person = chosen(may_write_mods_in(world), user_id)
    if person is None:
        raise WriterRefused("That person cannot be the Mod Writer of a Mod here: only "
                            "someone with the Mod Writer or Plot Master role in this World, "
                            "or an Admin of its Organization, can.")
    return person


def link(world, handle, user_id, by):
    """Link a handle to a person, or unlink it if `user_id` is empty."""
    with transaction.atomic():
        # One change at a time per World, as for every other change to it.
        World.objects.select_for_update().get(pk=world.pk)
        if handle not in handles_in(world):
            raise WriterRefused(f"No Mod in {world.name} names `{handle}` as its Mod Writer.")
        links = WriterHandle.objects.filter(organization=world.organization, world=world,
                                            handle=handle)
        if not user_id:
            links.delete()
            return None
        person = eligible_writer(world, user_id)
        WriterHandle.objects.update_or_create(
            organization=world.organization, world=world, handle=handle,
            defaults={"user": person, "linked_by": by})
    return person


def reassign(world, mod, user_id, by):
    """Make someone else the Mod Writer of a draft. The file is not changed."""
    person = eligible_writer(world, user_id)
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(pk=mod.pk)
        if mod.fields.get("state") != states().draft:
            raise WriterRefused(f"Only a draft can be reassigned, and {mod.name} is not one.")
        mod.writer, mod.reassigned_by, mod.reassigned_at = person, by, timezone.now()
        mod.save(update_fields=["writer", "reassigned_by", "reassigned_at"])
    return mod
