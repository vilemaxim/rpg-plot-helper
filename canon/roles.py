"""The people who hold given roles in a World, its plot team, and choosing
one of them from the id a form sent, for the forms that name a person: a
Mod's Mod Writer (`writers.py`), its Mod Runners (`assignments.py`) and who
holds a Grant (`grants.py`)."""

from django.contrib.auth import get_user_model
from django.db.models import Q

from organizations.models import Membership, Role, WorldRole


def people_holding(world, *roles):
    """The people who hold any of these roles in this World, by email."""
    ids = WorldRole.objects.filter(world=world, role__in=roles).values("user_id")
    return get_user_model().objects.filter(pk__in=ids).order_by("email")


def plot_team(world):
    """The people who read everything in the World, by email: its Plot
    Masters and its Organization's Admins."""
    plot_masters = WorldRole.objects.filter(world=world, role=Role.PLOT_MASTER) \
        .values("user_id")  # noqa: TID251  with the Admins, below
    admins = Membership.objects.filter(organization=world.organization, is_admin=True) \
        .values("user_id")
    return get_user_model().objects.filter(Q(pk__in=plot_masters) | Q(pk__in=admins)) \
        .order_by("email")


def chosen(people, user_id):
    """The one of `people` (a queryset) whose id a form sent, or None if it
    sent none of theirs. Choosing only from `people` also keeps the choice
    inside the World's Organization."""
    try:
        return people.filter(pk=int(user_id)).first()
    except (TypeError, ValueError):
        return None
