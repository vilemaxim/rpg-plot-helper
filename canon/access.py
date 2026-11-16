"""What a person may read in a World: the read-access function.

`readable_documents(world, person)` is the one answer to "what may this
person read in this World". Anything that hands World content to someone else
on a person's behalf, such as the LLM in an Interview (ADR-0008), takes it from
here and from nothing else, so that narrowing access (Plot-scoped roles, #42)
is a change to this file alone.

Today everyone who may open a World reads all of it: anyone with a role in
it, and its Organization's Admins. Anyone else reads nothing.
"""

from organizations.models import Membership, WorldRole

from .models import Document
from .storing import settings_file_of


def readable_documents(world, person):
    """The World's documents this person may read, as a queryset."""
    documents = Document.objects.filter(organization=world.organization, world=world)
    may_open = (WorldRole.objects.filter(world=world, user=person).exists()
                or Membership.objects.filter(organization=world.organization, user=person,
                                             is_admin=True).exists())
    return documents if may_open else documents.none()


def readable_files(world, person):
    """What this person may read in the World as `{path: text}`, the form
    plotcanon reads a World in: their readable documents, and the World's
    settings file, which holds no Canon, if it has one."""
    documents = readable_documents(world, person)
    if not documents.exists():
        return {}
    return {**dict(documents.values_list("path", "text")), **settings_file_of(world)}
