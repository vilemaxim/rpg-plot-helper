from django import template
from django.db.models import Count

from ..kinds import KINDS
from .. import access, assignments, writers
from ..models import CanonChange, Document, Flag

register = template.Library()


@register.inclusion_tag("canon/my_drafts.html")
def my_drafts(world, user):
    """The draft Mods this person is the Mod Writer of, each marked if it was
    sent back to them."""
    return {"world": world, "drafts": writers.drafts_of(world, user)}


@register.inclusion_tag("canon/my_assignments.html")
def my_assignments(world, user):
    """This person's live Assignments in the World."""
    return {"world": world, "assignments": assignments.live_for(world, user)}


@register.inclusion_tag("canon/contents.html")
def world_contents(world, user, is_plot_master=False, may_write_mods=False):
    """What a World holds, as far as this person may read it
    (`canon.access`): each kind of document with how many there are, and
    its open Flags; to the plot team, the Canon Changes waiting to be decided.
    To a Plot Master, a World with no Canon offers the import, and one with
    Canon the export. A World with Canon offers someone who may write a Mod
    an Interview to write one in, when Interviews are on, and pasting or
    uploading one."""
    counts = dict(access.readable_documents(world, user).order_by()
                  .values_list("kind").annotate(Count("pk")))
    kinds = [(address, label, counts.get(doc_type, 0))
             for address, (doc_type, label) in KINDS.items()]
    pending = (CanonChange.objects.pending(world).count()
               if access.is_plot_team(world, user) else 0)
    flags = access.readable_flags(world, user, Flag.objects.open_in(world)).count()
    has_canon = Document.objects.filter(organization=world.organization, world=world).exists()
    return {"world": world, "kinds": [k for k in kinds if k[2]], "total": has_canon,
            "is_plot_master": is_plot_master, "may_write_mods": may_write_mods,
            "pending": pending, "flags": flags}
