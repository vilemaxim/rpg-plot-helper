from django.http import Http404
from django.shortcuts import redirect, render

from .models import World, WorldRole


def worlds_open_to(request):
    """The Worlds this person may open: all of them for an Organization Admin,
    and otherwise the ones they hold a role in. The filter on the Organization
    repeats what the database already enforces; both are meant to hold."""
    if request.membership is None:
        return World.objects.none()
    worlds = World.objects.filter(organization=request.organization)
    if request.membership.is_admin:
        return worlds
    return worlds.filter(roles__user=request.user).distinct()


def home(request):
    """Send a person to their World."""
    if request.membership is None:
        return render(request, "organizations/no_organization.html")
    world = worlds_open_to(request).first()
    if world is None:
        return render(request, "organizations/no_worlds.html")
    return redirect("world", world_id=world.pk)


def world(request, world_id):
    world = worlds_open_to(request).filter(pk=world_id).first()
    if world is None:
        # The same answer whether the World does not exist, belongs to another
        # Organization, or is one this person has no role in.
        raise Http404("No such World")
    roles = WorldRole.objects.filter(world=world, user=request.user)
    return render(request, "organizations/world.html", {
        "world": world,
        "roles": [role.get_role_display() for role in roles],
    })
