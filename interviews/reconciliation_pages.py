"""Reconciliation's pages (#59): the Reconcile button on a draft's page, and
each report kept. For the World's Plot Masters only, Organization Admins
among them (`organizations.views.is_plot_master`): anyone else is told there
is no such page."""

from django.contrib import messages as notices
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from canon.views import mod_or_404
from organizations.views import is_plot_master, world_or_404

from . import reconciling
from .models import Reconciliation


def plot_masters_mod_or_404(request, world_id, slug):
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    return world, mod_or_404(world, slug)


@require_POST
def reconcile(request, world_id, slug):
    """Reconcile a draft, and go back to its page, which shows the report,
    or says why there is none."""
    world, mod = plot_masters_mod_or_404(request, world_id, slug)
    try:
        reconciling.reconcile(mod, by=request.user)
    except reconciling.NotReconciled as refused:
        notices.error(request, f"{mod.name} was not reconciled. {refused}")
    else:
        notices.success(request, f"{mod.name} is reconciled. The report is below.")
    return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)


@require_GET
def reconciliation(request, world_id, slug, reconciliation_id):
    """One Reconciliation of a Mod, kept as its history."""
    world, mod = plot_masters_mod_or_404(request, world_id, slug)
    kept = Reconciliation.objects.filter(world=world, mod=mod, pk=reconciliation_id) \
        .select_related("ran_by").first()
    if kept is None:
        raise Http404("No such Reconciliation")
    return render(request, "interviews/reconciliation.html",
                  {"world": world, "mod": mod, "reconciliation": kept})
