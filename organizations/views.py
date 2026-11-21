import uuid
from dataclasses import dataclass
from functools import wraps

from django.core.mail import send_mail
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User

from . import reconciling, signup, tenancy, world_reviewing
from .forms import (
    DryRunStructureForm,
    InvitationForm,
    NameForm,
    RunsByItselfForm,
    WorldForm,
    WorldRunsByItselfForm,
)
from .llm_runs import RunsByItself
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


def waiting_invitations(request):
    """The invitations this person has been sent and has not answered."""
    return (Invitation.objects.waiting_for(request.user)
            .select_related("organization", "invited_by").order_by("created_at"))


# ── Worlds ──────────────────────────────────────────────────────────────────

@require_GET
def home(request):
    """Send a person to their World, or let them choose if they have several."""
    # An invitation is shown before anything else. This is also where the link
    # in an invitation email brings someone who is already signed in. Someone
    # who would rather answer later can say so; the header keeps reminding them.
    if "later" not in request.GET and waiting_invitations(request).exists():
        return redirect("invitations")
    if request.membership is None:
        return render(request, "organizations/no_organization.html")
    worlds = list(worlds_open_to(request))
    if not worlds:
        return render(request, "organizations/no_worlds.html")
    if len(worlds) == 1:
        return redirect("world", world_id=worlds[0].pk)
    return render(request, "organizations/worlds.html", {"worlds": worlds})


def is_plot_master(request, world):
    """Whether the person may do what a Plot Master of this World does: they
    hold the role in it, or they are an Admin of its Organization, who has
    every right a Plot Master has in each of its Worlds."""
    membership = request.membership
    if membership is not None and membership.is_admin \
            and membership.organization_id == world.organization_id:
        return True
    return holds_role(request, world, Role.PLOT_MASTER)  # noqa: TID251  after the Admins, above


def holds_role(request, world, *roles):
    """Whether the person holds any of these roles in this World."""
    return WorldRole.objects.filter(world=world, user=request.user, role__in=roles).exists()


def may_write_mods(request, world):
    """Whether the person may write Mods in this World: they are a Mod
    Writer in it, or may do what a Plot Master does, which includes it."""
    return is_plot_master(request, world) or holds_role(request, world, Role.MOD_WRITER)


@require_GET
def world(request, world_id):
    world = world_or_404(request, world_id)
    roles = WorldRole.objects.filter(world=world, user=request.user)
    return render(request, "organizations/world.html", {
        "world": world,
        "roles": [role.get_role_display() for role in roles],
        "is_plot_master": is_plot_master(request, world),
        "may_write_mods": may_write_mods(request, world),
    })


@require_http_methods(["GET", "POST"])
def rename_world(request, world_id):
    """Rename a World. For its Plot Masters and its Organization's Admins;
    anyone else gets "not found". The World's address uses its id, so
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


@dataclass(frozen=True)
class RunsByItselfPage:
    """How the pages show one of the settings in `llm_runs.py`: on the
    Organization page, and on each World's own page for it."""

    setting: RunsByItself
    # What it is called, and the Organization page's anchor for it.
    title: str
    anchor: str
    # The checkbox and radio buttons' label: what it does when it is on.
    label: str
    about: str
    when_on: str
    when_off: str
    # The name of the World's page for it, and the Organization's form's.
    world_url: str
    organization_url: str


RECONCILING = RunsByItselfPage(
    reconciling.SETTING, "Reconciliation", "reconciliation",
    "Reconcile each draft when it's submitted",
    "Reconciliation checks a draft Mod against its World's Canon, and against the other "
    "drafts waiting for approval, with the LLM, for the plot team to read. With this on, it "
    "runs each time a draft is submitted or revised, and each run counts toward the "
    "Organization's monthly token limit.",
    "Drafts in this World are reconciled when they're submitted.",
    "Drafts in this World are not reconciled when they're submitted.",
    "world-reconciliation", "organization-reconciliation")

WORLD_REVIEWING = RunsByItselfPage(
    world_reviewing.SETTING, "World review", "world-review",
    "Run a World review after each Event",
    "A World review looks across a whole World for drift, dormant Plots and chances to bring "
    "NPCs and Plots back, with the LLM, for the plot team to read. With this on, one runs "
    "after each Event has ended, when the site's scheduled task next runs, and each run "
    "counts toward the Organization's monthly token limit.",
    "This World is reviewed after each Event.",
    "This World is not reviewed after each Event. Its plot team is offered a World review "
    "instead.",
    "world-review-setting", "organization-world-review")

RUNS_BY_ITSELF = (RECONCILING, WORLD_REVIEWING)


@require_http_methods(["GET", "POST"])
def world_runs_by_itself(request, world_id, page):
    """Whether one of the settings in `llm_runs.py` is on for this World,
    and where that comes from. Its Plot Masters see it; only an Admin of its
    Organization may change it. Anyone else gets "not found"."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    may_change = request.membership.is_admin
    if request.method == "POST" and not may_change:
        raise Http404("No such page")
    form = None
    if request.method == "POST":
        form = WorldRunsByItselfForm(request.POST, label=page.label)
        if form.is_valid():
            page.setting.set_for_world(world, form.cleaned_data["choice"])
            return redirect(page.world_url, world_id=world.pk)
    setting = page.setting.setting_of(world)
    if may_change and form is None:
        form = WorldRunsByItselfForm(initial={"choice": setting.choice}, label=page.label)
    return render(request, "organizations/world_runs_by_itself.html",
                  {"world": world, "page": page, "setting": setting, "form": form})


# ── The Organization: its Worlds, its people, invitations ───────────────────

def organization_page(request, *, name_form=None, world_form=None, invitation_form=None,
                      structure_form=None, runs_by_itself_form=None, refused=None):
    organization = request.organization

    def form_for(page):
        """The form for one of the settings in `llm_runs.py`: the one sent
        back with errors, or one showing the Organization's setting."""
        refused_page, form = runs_by_itself_form or (None, None)
        if refused_page == page:
            return form
        return RunsByItselfForm(
            initial={"on": getattr(organization, page.setting.organization_field)},
            label=page.label)

    return render(request, "organizations/organization.html", {
        "refused": refused,
        "name_form": name_form or NameForm(initial={"name": organization.name}),
        "structure_form": structure_form or DryRunStructureForm(
            initial={"structure": organization.dry_run_structure}),
        "runs_by_itself": [(page, form_for(page)) for page in RUNS_BY_ITSELF],
        "worlds": World.objects.filter(organization=organization),
        "memberships": (Membership.objects.filter(organization=organization)
                        .select_related("user").order_by("user__email")),
        "invitations": Invitation.objects.filter(organization=organization).waiting(),
        "declined": Invitation.objects.filter(organization=organization).declined(),
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
def set_dry_run_structure(request):
    """Change the Dry Run structure new Worlds are given. Worlds that already
    exist keep their own."""
    form = DryRunStructureForm(request.POST)
    if not form.is_valid():
        return organization_page(request, structure_form=form)
    request.organization.dry_run_structure = form.cleaned_data["structure"]
    request.organization.save(update_fields=["dry_run_structure"])
    return redirect("organization")


@organization_admin_only
@require_POST
def set_runs_by_itself(request, page):
    """Turn one of the settings in `llm_runs.py` on or off for every World
    that does not say otherwise."""
    form = RunsByItselfForm(request.POST, label=page.label)
    if not form.is_valid():
        return organization_page(request, runs_by_itself_form=(page, form))
    field = page.setting.organization_field
    setattr(request.organization, field, form.cleaned_data["on"])
    request.organization.save(update_fields=[field])
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

    # One row per address. Inviting again, including someone who declined, or
    # who joined and has since left, puts the invitation back to waiting.
    invitation, _ = Invitation.objects.update_or_create(
        organization=request.organization, email=email,
        defaults={"invited_by": request.user, "accepted_at": None, "declined_at": None})
    send_invitation(request, invitation)
    return redirect("organization")


@organization_admin_only
@require_POST
def withdraw_invitation(request, invitation_id):
    """Take back an invitation nobody has answered yet. The row goes, so
    signing in with the address no longer offers it, and the address can be
    invited again later."""
    withdrawn, _ = (Invitation.objects.filter(organization=request.organization, pk=invitation_id)
                    .waiting().delete())
    if not withdrawn:
        raise Http404("No such invitation")
    return redirect("organization")


def membership_or_404(request, membership_id):
    """A Membership of the Organization being worked in."""
    membership = (Membership.objects.filter(organization=request.organization)
                  .select_related("user").filter(pk=membership_id).first())
    if membership is None:
        raise Http404("No such member")
    return membership


@organization_admin_only
@require_POST
def remove_member(request, membership_id):
    """Remove someone from the Organization. Their roles in its Worlds go with
    the Membership (see migration 0004); their account and any other
    Organization they belong to are untouched. An Organization Admin may
    remove themselves, as long as another remains."""
    membership = membership_or_404(request, membership_id)
    if is_only_admin(membership):
        return refuse_last_admin(request, membership)
    membership.delete()
    if membership.user_id == request.user.pk:
        request.session.pop(tenancy.SESSION_KEY, None)
        signup.give_an_organization_if_due(request.user)
        return redirect("home")
    return redirect("organization")


@organization_admin_only
@require_POST
def make_admin(request, membership_id):
    membership = membership_or_404(request, membership_id)
    membership.is_admin = True
    membership.save(update_fields=["is_admin"])
    return redirect("organization")


@organization_admin_only
@require_POST
def stop_admin(request, membership_id):
    membership = membership_or_404(request, membership_id)
    if is_only_admin(membership):
        return refuse_last_admin(request, membership)
    membership.is_admin = False
    membership.save(update_fields=["is_admin"])
    if membership.user_id == request.user.pk:
        # The Organization page is no longer theirs to open.
        return redirect("home")
    return redirect("organization")


def refuse_last_admin(request, membership):
    """An Organization always keeps one Organization Admin, or nobody could run
    it, and with sign-up closed nobody could get in to fix it (ADR-0005)."""
    who = "You are" if membership.user_id == request.user.pk else f"{membership.user.email} is"
    return organization_page(
        request, refused=f"{who} the only Organization Admin of {request.organization.name}. "
                "Make someone else Organization Admin first.")


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


# ── Being invited, and leaving ──────────────────────────────────────────────

@require_GET
def invitations(request):
    """The invitations waiting for this person, each with Accept and Decline."""
    return render(request, "organizations/invitations.html",
                  {"invitations": waiting_invitations(request)})


def invitation_or_404(request, invitation_id):
    """A waiting invitation sent to this person's own address. Anyone else's,
    or one already answered, is "not found"."""
    # The row is locked until this request ends, so two answers sent at the
    # same moment are taken one after the other, and the second finds the
    # invitation no longer waiting.
    invitation = (waiting_invitations(request).select_for_update(of=("self",))
                  .filter(pk=invitation_id).first())
    if invitation is None:
        raise Http404("No such invitation")
    return invitation


@require_POST
def accept_invitation(request, invitation_id):
    invitation = invitation_or_404(request, invitation_id)
    joined = signup.accept(invitation, request.user)
    # Work in the Organization just joined.
    request.session[tenancy.SESSION_KEY] = str(joined)
    return redirect("home")


@require_POST
def decline_invitation(request, invitation_id):
    invitation = invitation_or_404(request, invitation_id)
    signup.decline(invitation, request.user)
    # With nothing left to decide, someone who belongs nowhere may now be due
    # an Organization of their own.
    signup.give_an_organization_if_due(request.user)
    return redirect("home")


def is_only_admin(membership):
    """Whether this person is the one Organization Admin their Organization has.
    An Organization must always keep one, or nobody could run it."""
    if not membership.is_admin:
        return False
    # The Organization Admins' rows are locked until this request ends, so two
    # of them leaving at the same moment cannot each see the other still there.
    admins = (Membership.objects.select_for_update()
              .filter(organization=membership.organization, is_admin=True))
    return len(admins) == 1


@require_http_methods(["GET", "POST"])
def leave_organization(request):
    """Leave the Organization this person is working in. Asks first.

    The button names the Organization it was shown for. If the person has
    since switched to another, nothing is left and they are asked again.
    """
    membership = request.membership
    if membership is None:
        raise Http404("No such page")
    only_admin = is_only_admin(membership)
    named = request.POST.get("organization")
    switched = bool(named) and named != str(membership.organization_id)
    if request.method == "POST" and named and not switched and not only_admin:
        # Their roles in its Worlds go with the Membership (see migration 0004).
        membership.delete()
        request.session.pop(tenancy.SESSION_KEY, None)
        # Someone who now belongs nowhere may be due an Organization of their own.
        signup.give_an_organization_if_due(request.user)
        return redirect("home")
    return render(request, "organizations/leave.html",
                  {"only_admin": only_admin, "switched": switched})


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
