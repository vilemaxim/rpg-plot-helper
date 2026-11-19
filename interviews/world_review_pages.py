"""World review's pages (#61): the World's reviews, latest first, the way to
run one, the way to dismiss the suggestion after an Event, and each report
kept. For the World's Plot Masters only, Organization Admins among them
(`organizations.views.is_plot_master`): anyone else is told there is no such
page."""

from django.contrib import messages as notices
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from organizations.views import is_plot_master, world_or_404

from . import config, world_reviewing
from .models import WorldReview


def plot_masters_world_or_404(request, world_id):
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    return world


@require_GET
def reviews(request, world_id):
    """The World's reviews, latest first, and the Run button when World
    review is on."""
    world = plot_masters_world_or_404(request, world_id)
    return render(request, "interviews/world_reviews.html", {
        "world": world, "reviews": list(world_reviewing.of(world)),
        "on": config.world_review_llm() is not None})


@require_POST
def run(request, world_id):
    """Review the World, and show the report, or say why there is none."""
    world = plot_masters_world_or_404(request, world_id)
    try:
        kept = world_reviewing.review(world, by=request.user)
    except world_reviewing.NotReviewed as refused:
        notices.error(request, f"{world.name} was not reviewed. {refused}")
        return redirect("world-reviews", world_id=world.pk)
    return redirect("world-review", world_id=world.pk, review_id=kept.pk)


@require_POST
def dismiss(request, world_id):
    """Stop suggesting a World review after the Event the form names."""
    world = plot_masters_world_or_404(request, world_id)
    event = request.POST.get("event", "").strip()
    if event:
        world_reviewing.dismiss(world, event, request.user)
    return redirect("world", world_id=world.pk)


@require_GET
def review(request, world_id, review_id):
    """One World review, kept as the World's history."""
    world = plot_masters_world_or_404(request, world_id)
    kept = WorldReview.objects.filter(world=world, pk=review_id).select_related("ran_by").first()
    if kept is None:
        raise Http404("No such World review")
    return render(request, "interviews/world_review.html", {"world": world, "review": kept})
