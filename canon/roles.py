"""The people who hold given roles in a World, and choosing one of them from
the id a form sent, for the forms that name a person: a Mod's Mod Writer
(`writers.py`) and its Mod Runners (`assignments.py`)."""

from django.contrib.auth import get_user_model

from organizations.models import WorldRole


def people_holding(world, *roles):
    """The people who hold any of these roles in this World, by email."""
    ids = WorldRole.objects.filter(world=world, role__in=roles).values("user_id")
    return get_user_model().objects.filter(pk__in=ids).order_by("email")


def chosen(people, user_id):
    """The one of `people` (a queryset) whose id a form sent, or None if it
    sent none of theirs. Choosing only from `people` also keeps the choice
    inside the World's Organization."""
    try:
        return people.filter(pk=int(user_id)).first()
    except (TypeError, ValueError):
        return None
