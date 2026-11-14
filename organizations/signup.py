"""What happens the first time a person signs in: they get an Organization of
one and a first World, so they can start without learning about Organizations."""

import uuid

from django.contrib.auth.signals import user_logged_in
from django.db import transaction
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


@receiver(user_logged_in)
def set_up_on_sign_in(sender, request, user, **kwargs):
    """On every sign-in, make sure the person has an Organization and that the
    rest of this request works in it."""
    # Usually this runs inside the request's own transaction. `login()` can
    # also be called from outside one, so open one here either way.
    with transaction.atomic():
        tenancy.set_context(user)
        if not Membership.objects.filter(user=user).exists():
            create_first_organization(user)
        tenancy.activate(request, user)
