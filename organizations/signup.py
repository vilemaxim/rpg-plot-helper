"""What happens when a person signs in and belongs to no Organization.

If they may create one, they get an Organization of one and a first World, so
they can start without learning about Organizations. Whether they may is decided
by the open sign-up setting (ADR-0005). Someone who has been invited to an
Organization decides on that first.

Also here: accepting and declining an invitation.
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
                             role=Role.PLOT_MASTER)  # noqa: TID251  gives the role
    return organization


def accept(invitation, user):
    """Join the Organization that sent this invitation. Returns its id."""
    tenancy.set_context(user, invitation.organization_id)
    Membership.objects.get_or_create(organization_id=invitation.organization_id, user=user)
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    tenancy.set_context(user)
    return invitation.organization_id


def decline(invitation, user):
    """Turn this invitation down. The Organization can see that, and may
    invite the address again."""
    tenancy.set_context(user, invitation.organization_id)
    invitation.declined_at = timezone.now()
    invitation.save(update_fields=["declined_at"])
    tenancy.set_context(user)


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


def give_an_organization_if_due(user):
    """Give this person an Organization of their own if they belong to none,
    may create one, and are not still deciding on an invitation. Someone who
    has been invited answers that first: joining may be all they wanted."""
    tenancy.set_context(user)
    if Membership.objects.filter(user=user).exists():
        return
    if Invitation.objects.waiting_for(user).exists():
        return
    if may_create_an_organization():
        create_first_organization(user)


@receiver(user_logged_in)
def set_up_on_sign_in(sender, request, user, **kwargs):
    """On every sign-in: give the person an Organization of their own if one
    is due, and make the rest of this request work in theirs."""
    # Usually this runs inside the request's own transaction. `login()` can
    # also be called from outside one, so open one here either way.
    with transaction.atomic():
        give_an_organization_if_due(user)
        tenancy.activate(request, user)
