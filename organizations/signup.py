"""What happens when a person signs in and belongs to no Organization.

If they may create one, they get an Organization of one and a first World, so
they can start without learning about Organizations. Whether they may is decided
by the open sign-up setting (ADR-0005).
"""

import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.db import connection, transaction
from django.dispatch import receiver

from . import tenancy
from .models import Membership, Organization, Role, World, WorldRole

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


def may_create_an_organization(user):
    """Whether this person, who belongs to no Organization, gets one of their
    own. With open sign-up, always. Without it, only if they are the first
    person ever to sign in to this copy of the app.
    """
    if settings.OPEN_SIGN_UP:
        return True
    # Two people signing in at the same moment must not both count as first.
    # The lock is held until this request's transaction ends, by which time the
    # winner's sign-in is recorded for the other to see.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('first-organization'))")
    # People are asked about, not Organizations: row-level security hides other
    # Organizations from this query, but the list of people is not hidden.
    others = get_user_model().objects.exclude(pk=user.pk)
    return not others.filter(last_login__isnull=False).exists()


@receiver(user_logged_in)
def set_up_on_sign_in(sender, request, user, **kwargs):
    """On every sign-in, give the person an Organization if they have none and
    may create one, and make the rest of this request work in theirs."""
    # Usually this runs inside the request's own transaction. `login()` can
    # also be called from outside one, so open one here either way.
    with transaction.atomic():
        tenancy.set_context(user)
        if (not Membership.objects.filter(user=user).exists()
                and may_create_an_organization(user)):
            create_first_organization(user)
        tenancy.activate(request, user)
