import uuid
from functools import wraps

from django.core.mail import send_mail
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User

from . import signup, tenancy
from .forms import InvitationForm, NameForm, WorldForm
from .models import Invitation, Membership, Role, World, WorldRole


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


def world_or_404(request, world_id):
    world = worlds_open_to(request).filter(pk=world_id).first()
    if world is None:
        # The same answer whether the World does not exist, belongs to another
        # Organization, or is one this person has no role in.
        raise Http404("No such World")
    return world


def organization_admin_only(view):
    """Answer "not found" to anyone who is not an Organization Admin of the
    Organization they are working in, so the page's existence is not revealed."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.membership is None or not request.membership.is_admin:
            raise Http404("No such page")
        return view(request, *args, **kwargs)
    return wrapper


# ── Worlds ──────────────────────────────────────────────────────────────────

@require_GET
def home(request):
    """Send a person to their World, or let them choose if they have several."""
    # Someone invited while already signed in joins here, where an invitation
    # link brings them, without having to sign out and in again.
    joined = signup.accept_invitations(request.user)
    if joined:
        request.session[tenancy.SESSION_KEY] = str(joined[-1])
        tenancy.activate(request, request.user)
    if request.membership is None:
        return render(request, "organizations/no_organization.html")
    worlds = list(worlds_open_to(request))
    if not worlds:
        return render(request, "organizations/no_worlds.html")
    if len(worlds) == 1:
        return redirect("world", world_id=worlds[0].pk)
    return render(request, "organizations/worlds.html", {"worlds": worlds})


def is_plot_master(request, world):
    return WorldRole.objects.filter(world=world, user=request.user,
                                    role=Role.PLOT_MASTER).exists()


@require_GET
def world(request, world_id):
    world = world_or_404(request, world_id)
    roles = WorldRole.objects.filter(world=world, user=request.user)
    return render(request, "organizations/world.html", {
        "world": world,
        "roles": [role.get_role_display() for role in roles],
        "is_plot_master": any(role.role == Role.PLOT_MASTER for role in roles),
    })


@require_http_methods(["GET", "POST"])
def rename_world(request, world_id):
    """Rename a World. For its Plot Masters only; anyone else, an Organization
    Admin included, gets "not found". The World's address uses its id, so
    renaming does not change it."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    if request.method == "POST":
        form = NameForm(request.POST)
        if form.is_valid():
            world.name = form.cleaned_data["name"]
            world.save(update_fields=["name"])
            return redirect("world", world_id=world.pk)
    else:
        form = NameForm(initial={"name": world.name})
    return render(request, "organizations/rename_world.html", {"world": world, "form": form})


# ── The Organization: its Worlds, its people, invitations ───────────────────

def organization_page(request, *, name_form=None, world_form=None, invitation_form=None):
    organization = request.organization
    return render(request, "organizations/organization.html", {
        "name_form": name_form or NameForm(initial={"name": organization.name}),
        "worlds": World.objects.filter(organization=organization),
        "memberships": (Membership.objects.filter(organization=organization)
                        .select_related("user").order_by("user__email")),
        "invitations": Invitation.objects.filter(organization=organization,
                                                 accepted_at__isnull=True),
        "world_form": world_form or WorldForm(),
        "invitation_form": invitation_form or InvitationForm(),
    })


@organization_admin_only
@require_GET
def organization(request):
    return organization_page(request)


@organization_admin_only
@require_POST
def rename_organization(request):
    form = NameForm(request.POST)
    if not form.is_valid():
        return organization_page(request, name_form=form)
    request.organization.name = form.cleaned_data["name"]
    request.organization.save(update_fields=["name"])
    return redirect("organization")


@organization_admin_only
@require_POST
def create_world(request):
    form = WorldForm(request.POST)
    if not form.is_valid():
        return organization_page(request, world_form=form)
    world = World.objects.create(organization=request.organization,
                                 name=form.cleaned_data["name"])
    return redirect("world", world_id=world.pk)


def send_invitation(request, invitation):
    link = request.build_absolute_uri(
        f"{reverse('sign-in')}?{urlencode({'email': invitation.email})}")
    send_mail(
        # An email subject must be one line. Names are stored that way now, but
        # one saved before that rule would otherwise stop every invitation.
        subject=" ".join(
            f"You are invited to {invitation.organization.name} on RPG Plot Helper".split()),
        message=render_to_string("organizations/invitation_email.txt", {
            "invited_by": invitation.invited_by.email,
            "organization": invitation.organization.name,
            "email": invitation.email,
            "link": link,
        }),
        from_email=None,
        recipient_list=[invitation.email],
    )


@organization_admin_only
@require_POST
def invite(request):
    """Invite an email address to the Organization. Inviting the same address
    again sends the email again."""
    form = InvitationForm(request.POST)
    if form.is_valid():
        email = User.objects.tidy(form.cleaned_data["email"])
        if Membership.objects.filter(organization=request.organization,
                                     user__email=email).exists():
            form.add_error("email", f"{email} already belongs to this Organization.")
    if not form.is_valid():
        return organization_page(request, invitation_form=form)

    # One row per address. Inviting again, including someone who joined and has
    # since left, puts the invitation back to waiting.
    invitation, _ = Invitation.objects.update_or_create(
        organization=request.organization, email=email,
        defaults={"invited_by": request.user, "accepted_at": None})
    send_invitation(request, invitation)
    return redirect("organization")


@require_POST
def switch_organization(request):
    """Work in another Organization this person belongs to. Anything else is
    ignored, and they stay where they were."""
    try:
        wanted = uuid.UUID(request.POST.get("organization", ""))
    except ValueError:
        wanted = None
    if wanted and Membership.objects.filter(user=request.user, organization_id=wanted).exists():
        request.session[tenancy.SESSION_KEY] = str(wanted)
    return redirect("home")


# ── Roles in one World ──────────────────────────────────────────────────────

@organization_admin_only
@require_GET
def people(request, world_id):
    """Who holds which role in this World."""
    world = world_or_404(request, world_id)
    held = {}
    for role in WorldRole.objects.filter(world=world):
        held.setdefault(role.user_id, []).append(role)
    memberships = (Membership.objects.filter(organization=request.organization)
                   .select_related("user").order_by("user__email"))
    return render(request, "organizations/people.html", {
        "world": world,
        "people": [(m, sorted(held.get(m.user_id, []), key=lambda r: r.role))
                   for m in memberships],
        "roles": Role.choices,
    })


def role_being_changed(request, world_id):
    """The World, person and role a give-or-remove form names. Returns None for
    the last two if the form names a role that does not exist or a person who
    does not belong to this Organization."""
    world = world_or_404(request, world_id)
    role = request.POST.get("role")
    try:
        user_id = int(request.POST.get("user", ""))
    except ValueError:
        return world, None, None
    is_member = Membership.objects.filter(organization=request.organization,
                                          user_id=user_id).exists()
    if role not in Role.values or not is_member:
        return world, None, None
    return world, user_id, role


@organization_admin_only
@require_POST
def give_role(request, world_id):
    world, user_id, role = role_being_changed(request, world_id)
    if user_id is None:
        return HttpResponseBadRequest("No such person or role.")
    WorldRole.objects.get_or_create(organization=request.organization, world=world,
                                    user_id=user_id, role=role)
    return redirect("world-people", world_id=world.pk)


@organization_admin_only
@require_POST
def remove_role(request, world_id):
    world, user_id, role = role_being_changed(request, world_id)
    if user_id is None:
        return HttpResponseBadRequest("No such person or role.")
    WorldRole.objects.filter(world=world, user_id=user_id, role=role).delete()
    return redirect("world-people", world_id=world.pk)
