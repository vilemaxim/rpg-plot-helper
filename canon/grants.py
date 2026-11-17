"""Grants: a Plot Master's choice to let one Mod Writer or Mod Runner read one
document in full, GM Notes included, until revoked (see **Grant** in
GLOSSARY.md, ADR-0010).

Only someone who holds the Mod Writer or Mod Runner role in the World, and
is not on its plot team, can be given one: the plot team reads everything
already, and anyone else with no such role reads only what is open. A Grant
is live only while its holder still may be given one, and one made for an
Assignment, which is for that Assignment's Mod Runner, only while the
Assignment is live too (`assignments.Liveness`). Revoked and ended ones are
kept as history.

Grants are never written into a file (ADR-0001), so an export leaves them
out. `granted_ids` is the one answer to "which documents has this person
been granted now"; `access.py` reads it.
"""

from functools import cached_property

import plotcanon
from django.db import transaction
from django.utils import timezone

from organizations.models import Role, World

from . import assignments, writers
from .kinds import ADDRESS_OF
from .models import Document, Grant
from .roles import chosen, people_holding, plot_team


class GrantRefused(Exception):
    """Nothing was changed. `str()` says why."""


# Why a Grant is not live (`Liveness.ended`): codes to branch on, not words
# to show. It was revoked; its Assignment ended; its holder may not hold one.
REVOKED, ENDED, NOT_GRANTABLE = "revoked", "ended", "not-grantable"


def grants_in(world):
    """Every Grant in the World, revoked and ended ones too."""
    return Grant.objects.filter(organization=world.organization, world=world) \
        .select_related("person", "granted_by", "revoked_by", "document", "assignment")


def may_be_granted(world):
    """The people who can be given a Grant in this World, by email: those
    holding the Mod Writer or Mod Runner role, but not the plot team (its
    Plot Masters and its Organization's Admins)."""
    return people_holding(world, Role.MOD_WRITER, Role.MOD_RUNNER) \
        .exclude(pk__in=plot_team(world).values("pk"))


class Liveness:
    """What decides whether a World's Grants are live, read once: who may be
    given one, and the liveness of its Assignments. `on` is the day to ask about, today if not
    given."""

    def __init__(self, world, on=None):
        self.world, self.on = world, on

    def ended(self, grant):
        """Why a Grant is not live, as REVOKED, ENDED or NOT_GRANTABLE, or ""
        if it is."""
        if grant.revoked_at is not None:
            return REVOKED
        if grant.assignment_id is not None and self.assignments.ended(grant.assignment):
            return ENDED
        if grant.person_id not in self.may_be_granted:
            return NOT_GRANTABLE
        return ""

    @cached_property
    def may_be_granted(self):
        return set(may_be_granted(self.world).values_list("pk", flat=True))

    @cached_property
    def assignments(self):
        return assignments.Liveness(self.world, self.on)


def live(world, grants, on=None):
    """Those of `grants` (a queryset of the World's) that are live."""
    liveness = Liveness(world, on)
    return [grant for grant in grants.filter(revoked_at=None) if not liveness.ended(grant)]


def live_for(world, person, on=None):
    """This person's live Grants in the World, by document name."""
    return live(world, grants_in(world).filter(person=person)
                .order_by("document__name", "pk"), on)


def live_on(document, on=None):
    """The live Grants of this document, by holder's email."""
    world = document.world
    return live(world, grants_in(world).filter(document=document)
                .order_by("person__email", "pk"), on)


def granted_ids(world, person, on=None):
    """The ids of the documents this person holds a live Grant for."""
    return {grant.document_id for grant in live_for(world, person, on)}


def granted_documents(world, person, on=None):
    """The documents this person holds a live Grant of, each once, by name."""
    documents = {}
    for grant in live_for(world, person, on):
        documents.setdefault(grant.document_id, grant.document)
    return list(documents.values())


def features_of(world, mod):
    """The documents a Mod features: every id under its `features`, in the
    order its file lists them, that names a document of the World."""
    features = mod.fields.get("features")
    ids = []
    for group in (features.values() if isinstance(features, dict) else []):
        for id in (group if isinstance(group, list) else []):
            if isinstance(id, str) and id not in ids:
                ids.append(id)
    found = {document.slug: document for document in
             Document.objects.filter(organization=world.organization, world=world, slug__in=ids)}
    return [found[id] for id in ids if id in found]


def ties_of(world, plot):
    """Every other document tied to a Plot, either way: each one that names
    it anywhere in its frontmatter (NPCs, factions and Locations by `plots`,
    Mods by `features`, reports that changed it, ...) and each one it names
    (its `entities`, `mods`, `as_of`, ...). In the order the World's pages
    list kinds, then by name."""
    # Imported here: presenting reads access, which reads this module.
    from .presenting import as_parsed

    documents = list(Document.objects.filter(organization=world.organization, world=world))
    canon = plotcanon.World([as_parsed(document) for document in documents], {})
    tied = {other.id for other in plotcanon.referrers(canon, plot.slug)}
    tied |= {ref.id for ref in plotcanon.references(as_parsed(plot))}
    tied.discard(plot.slug)
    order = {doc_type: position for position, doc_type in enumerate(ADDRESS_OF)}
    return sorted((document for document in documents
                   if document.slug in tied and document.kind in order),
                  key=lambda document: (order[document.kind], document.name, document.slug))


def ties_to_offer(world, plot_grant, on=None):
    """Everything tied to the Plot of this Grant, to offer to grant its
    holder as well, as `(document, held)`: `held` when they already hold a
    live Grant of it."""
    held = granted_ids(world, plot_grant.person, on)
    return [(document, document.pk in held)
            for document in ties_of(world, plot_grant.document)]


def referred_to(world, mod):
    """The documents of the World a Mod refers to, each once, in the order
    plotcanon's `references` finds them."""
    # Imported here: presenting reads access, which reads this module.
    from .presenting import as_parsed

    ids = list(dict.fromkeys(ref.id for ref in plotcanon.references(as_parsed(mod))
                             if isinstance(ref.id, str) and ref.id != mod.slug))
    found = {document.slug: document for document in
             Document.objects.filter(organization=world.organization, world=world, slug__in=ids)}
    return [found[id] for id in ids if id in found]


def not_granted_to_writer(world, draft):
    """What a draft Mod refers to that its Mod Writer may not read in full,
    for the plot team to grant them if they choose: `(writer, documents)`.
    No documents if the app knows no Mod Writer of it, or they cannot be
    given a Grant."""
    # Imported here: access reads this module.
    from .access import readable_documents

    writer = writers.writer_of(draft)
    if writer is None or not may_be_granted(world).filter(pk=writer.pk).exists():
        return writer, []
    in_full = set(readable_documents(world, writer).filter(in_full=True)
                  .values_list("pk", flat=True))
    return writer, [document for document in referred_to(world, draft)
                    if document.pk not in in_full]


def grant(world, document, user_id, by, assignment=None, on=None):
    """Grant a document of the World to the person whose id a form sent, on
    its own, or for one of their live Assignments. Returns the Grant."""
    person = chosen(may_be_granted(world), user_id)
    if person is None:
        raise GrantRefused("That person cannot be granted a document here: only someone "
                           "with the Mod Writer or Mod Runner role in this World, and not "
                           "on its plot team, can.")
    with transaction.atomic():
        # One change at a time per World, as for every other change to it.
        World.objects.select_for_update().get(pk=world.pk)
        document = Document.objects.filter(organization=world.organization, world=world,
                                           pk=document.pk).first()
        if document is None:
            raise GrantRefused(f"{world.name} has no such document.")
        if assignment is not None:
            assignment = assignments.assignments_in(world).filter(pk=assignment.pk).first()
            if assignment is None or assignment.runner_id != person.pk:
                raise GrantRefused(f"{person.email} holds no such Assignment.")
            if assignments.Liveness(world, on).ended(assignment):
                raise GrantRefused(f"That Assignment of {person.email} is no longer live, so "
                                   f"nothing can be granted for it.")
        duplicate = live(world, grants_in(world).filter(document=document, person=person,
                                                        assignment=assignment), on)
        if duplicate:
            raise GrantRefused(f"{person.email} already holds a Grant for {document.name}"
                               + (" for that Assignment." if assignment else "."))
        return Grant.objects.create(
            organization=world.organization, world=world, document=document, person=person,
            assignment=assignment, granted_by=by, granted_at=timezone.now())


def grant_features(world, assignment, ids, by, on=None):
    """Grant the Assignment's Mod Runner these Features of its Mod, by id,
    each Grant belonging to the Assignment so that it ends when the
    Assignment does. Returns the Grants: none for a Mod Runner on the plot
    team, who reads every document already. Refused, with nothing granted, if
    an id is not one of the Mod's Features."""
    with transaction.atomic():
        features = {document.slug: document for document in features_of(world, assignment.mod)}
        for id in ids:
            if id not in features:
                raise GrantRefused(f"{assignment.mod.name} has no Feature {id!r}, so nothing "
                                   f"was assigned or granted.")
        if not may_be_granted(world).filter(pk=assignment.runner_id).exists():
            return []
        return [grant(world, features[id], assignment.runner_id, by, assignment=assignment, on=on)
                for id in dict.fromkeys(ids)]


def refuse_unless_live(world, plot_grant, on=None):
    """Refuse to grant anything more along with a Plot's Grant that is no
    longer live."""
    if Liveness(world, on).ended(plot_grant):
        raise GrantRefused(f"{plot_grant.person.email}'s Grant of {plot_grant.document.name} "
                           f"is no longer live, so nothing more was granted.")


def grant_ties(world, plot_grant, ids, by, on=None):
    """Grant the holder of a Plot's live Grant these documents tied to the
    Plot as well, by id, each on its own and until revoked, passing over any
    they already hold a live Grant of. Returns the new Grants. All or none:
    refused if the Plot's Grant is no longer live or an id is not tied to the
    Plot."""
    with transaction.atomic():
        refuse_unless_live(world, plot_grant, on)
        ties = {document.slug: document for document in ties_of(world, plot_grant.document)}
        for id in ids:
            if id not in ties:
                raise GrantRefused(f"{id!r} is not tied to {plot_grant.document.name}, so "
                                   f"nothing more was granted.")
        held = granted_ids(world, plot_grant.person, on)
        return [grant(world, ties[id], plot_grant.person_id, by, on=on)
                for id in dict.fromkeys(ids) if ties[id].pk not in held]


def revoke(world, document, grant_id, by, on=None):
    """Revoke a live Grant of this document. Returns it."""
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        found = grants_in(world).filter(document=document, pk=grant_id).first()
        if found is None:
            raise GrantRefused(f"{document.name} has no such Grant.")
        ended = Liveness(world, on).ended(found)
        if ended == REVOKED:
            raise GrantRefused(f"That Grant to {found.person.email} was already revoked.")
        if ended == ENDED:
            raise GrantRefused(f"That Grant to {found.person.email} ended with its "
                               f"Assignment, so there is nothing to revoke.")
        found.revoked_by, found.revoked_at = by, timezone.now()
        found.save(update_fields=["revoked_by", "revoked_at"])
        return found
