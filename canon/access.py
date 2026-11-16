"""What a person may read in a World: the read-access function.

`readable_documents(world, person)` is the one answer to "what may this
person read in this World". Anything that hands World content to someone else
on a person's behalf, such as the LLM in an Interview (ADR-0008), takes it from
here and from nothing else, so that narrowing access (Plot-scoped roles, #42)
is a change to this file alone.

Today everyone who may open a World reads all of it: anyone with a role in
it, and its Organization's Admins. Anyone else reads nothing.
"""

import re

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


def readable_flags(world, person, flags):
    """Those of `flags` (a queryset) this person may read in full: on a Mod
    they may read, raised by a Canon Change from a report they may read, about
    a Feature they may read. Any other is left out whole, as a finding about a
    document they may not read is (`readable_findings`)."""
    readable = readable_documents(world, person)
    hidden = (Document.objects.filter(organization=world.organization, world=world)
              .exclude(pk__in=readable.values("pk")).values("slug"))
    return (flags.filter(mod__in=readable.values("pk"),
                         change__report__in=readable.values("pk"))
            .exclude(change__entity__in=hidden))


HIDDEN = "another document"
NOT_SHOWN = ("There are more errors, about documents only a Plot Master may read. "
             "Ask one to look at it.")


def readable_findings(world, person, findings):
    """plotcanon's findings, one to a line, or any message about the World, as
    this person may read them: the rule the report page applies for a private
    link (`canon.runner_views.own_findings`), with what they may read taken
    from `readable_documents`. A finding about a document they may not read is
    left out, and saying so ends the text; any other mention of one, by path,
    id or name, reads "another document"."""
    hidden = (Document.objects.filter(organization=world.organization, world=world)
              .exclude(pk__in=readable_documents(world, person).values("pk"))
              .values_list("path", "slug", "name"))
    paths = {path for path, _, _ in hidden}
    words = sorted({word for row in hidden for word in row if word}, key=len, reverse=True)
    mention = (re.compile("|".join(rf"(?<![\w/-]){re.escape(word)}(?![\w/-])"
                                   for word in words)) if words else None)
    lines, left_out = [], False
    for line in findings.splitlines():
        if any(f" {path}: " in line for path in paths):
            left_out = True
            continue
        lines.append(mention.sub(HIDDEN, line) if mention else line)
    if left_out:
        lines.append(NOT_SHOWN)
    return "\n".join(lines)
