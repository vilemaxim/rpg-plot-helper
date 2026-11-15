from django import template
from django.db.models import Count

from ..kinds import KINDS
from .. import writers
from ..models import CanonChange, Document, Flag

register = template.Library()


@register.inclusion_tag("canon/my_drafts.html")
def my_drafts(world, user):
    """The draft Mods this person is the Mod Writer of, each marked if it was
    sent back to them."""
    return {"world": world, "drafts": writers.drafts_of(world, user)}


@register.inclusion_tag("canon/contents.html")
def world_contents(world, is_plot_master=False, may_write_mods=False):
    """What a World holds: each kind of document with how many there are. To
    a Plot Master, a World with no Canon offers the import, and one with Canon
    the export. A World with Canon offers submitting a Mod to someone who may
    write one."""
    counts = dict(Document.objects.filter(organization=world.organization, world=world)
                  .values_list("kind").annotate(Count("pk")))
    kinds = [(address, label, counts.get(doc_type, 0))
             for address, (doc_type, label) in KINDS.items()]
    pending = CanonChange.objects.pending(world).count()
    flags = Flag.objects.open_in(world).count()
    return {"world": world, "kinds": [k for k in kinds if k[2]], "total": sum(counts.values()),
            "is_plot_master": is_plot_master, "may_write_mods": may_write_mods, "pending": pending, "flags": flags}
