from django import template
from django.db.models import Count

from ..kinds import KINDS
from ..models import Document

register = template.Library()


@register.inclusion_tag("canon/contents.html")
def world_contents(world, may_import=False):
    """What a World holds: each kind of document with how many there are. A
    World with no Canon offers the import, to someone who may do it."""
    counts = dict(Document.objects.filter(organization=world.organization, world=world)
                  .values_list("kind").annotate(Count("pk")))
    kinds = [(address, label, counts.get(doc_type, 0))
             for address, (doc_type, label) in KINDS.items()]
    return {"world": world, "kinds": [k for k in kinds if k[2]], "total": sum(counts.values()),
            "may_import": may_import}
