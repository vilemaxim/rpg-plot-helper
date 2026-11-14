"""What happens when a person signs in and belongs to no Organization.

If they may create one, they get an Organization of one and a first World, so
they can start without learning about Organizations. Whether they may is decided
by the open sign-up setting (ADR-0005).
"""

import uuid

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db import connection, transaction
from django.dispatch import receiver
from django.utils import timezone

from . import tenancy
from .models import Invitation, Membership, Organization, Role, World, WorldRole

FIRST_ORGANIZATION_NAME = "My Organization"
FIRST_WORLD_NAME = "My first World"


def create_first_organization(user):
    """Give this person an Organization and a World of their own. They are its
    Organization Admin and the World's Plot Master."""
    # The id is chosen here, before the row exists, so that the database can be
    # told about the new Organization first: row-level security only accepts
    # rows for the Organization that is set.
    organization_id = uuid.uuid4()
    tenancy.set_context(user, organization_id)
    organization = Organization.objects.create(id=organization_id, name=FIRST_ORGANIZATION_NAME)
    Membership.objects.create(organization=organization, user=user, is_admin=True)
    world = World.objects.create(organization=organization, name=FIRST_WORLD_NAME)
    WorldRole.objects.create(organization=organization, world=world, user=user,
                             role=Role.PLOT_MASTER)
    return organization


def accept_invitations(user):
    """Join every Organization that has invited this person's address and that
    they have not joined yet. Signing in is what proves the address is theirs.
    Returns the Organizations joined, oldest invitation first. If there are
    none, nothing changes, including which Organization the request works in."""
    joined = []
    waiting = Invitation.objects.filter(email=user.email, accepted_at__isnull=True)
    for invitation in waiting.order_by("created_at"):
        tenancy.set_context(user, invitation.organization_id)
        Membership.objects.get_or_create(organization_id=invitation.organization_id, user=user)
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
        joined.append(invitation.organization_id)
    if joined:
        # Joining moved the database's attention from one Organization to the
        # next. Leave none chosen; the caller picks where the person works now.
        tenancy.set_context(user)
    return joined


def may_create_an_organization():
    """Whether a person who belongs to no Organization gets one of their own.
    With open sign-up, always. Without it, only while this copy of the app has
    no Organization at all, so the first person to sign in creates the one.
    """
    if settings.OPEN_SIGN_UP:
        return True
    with connection.cursor() as cursor:
        # Two people signing in at the same moment must not both find there is
        # none. The lock is held until this request's transaction ends, by
        # which time the winner's Organization is there for the other to see.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('first-organization'))")
        # Row-level security hides other Organizations from an ordinary query,
        # so the database keeps this count for us (see migration 0005).
        cursor.execute("SELECT total FROM organizations_total")
        return cursor.fetchone()[0] == 0


@receiver(user_logged_in)
def set_up_on_sign_in(sender, request, user, **kwargs):
    """On every sign-in: join any Organization that has invited the person,
    give them one of their own if they still have none and may create one, and
    make the rest of this request work in theirs."""
    # Usually this runs inside the request's own transaction. `login()` can
    # also be called from outside one, so open one here either way.
    with transaction.atomic():
        tenancy.set_context(user)
        joined = accept_invitations(user)
        if joined:
            # Start them in the Organization they were just invited to.
            request.session[tenancy.SESSION_KEY] = str(joined[-1])
        if (not Membership.objects.filter(user=user).exists()
                and may_create_an_organization()):
            create_first_organization(user)
        tenancy.activate(request, user)
