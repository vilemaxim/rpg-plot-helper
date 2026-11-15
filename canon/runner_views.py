"""The pages a private link opens, for a Mod Runner with no account.

Each shows one Mod and nothing else in its World: no page here links to
another, and every one of them starts from the link (`links.opened`).
"""

from functools import wraps

from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods

from . import dry_runs, links, submitting
from .forms import ReportForm
from .models import Document, Flag
from .presenting import Index, render_markdown
from .views import flags_shown, state_of, twee_download


def refused_for_now(reason):
    return HttpResponse(reason, status=429, content_type="text/plain; charset=utf-8")


def through_a_link(view):
    """A public view that is given the link its secret opens, and answers
    "not found" if it opens none."""
    @login_not_required
    @wraps(view)
    def wrapper(request, secret):
        try:
            link = links.opened(request, secret)
        except links.TooMany as refused:
            return refused_for_now(str(refused))
        if link is None:
            raise Http404("No such page")
        response = view(request, link)
        # The page's address holds the secret; send it to no other site.
        response["Referrer-Policy"] = "no-referrer"
        return response
    return wrapper


def page(request, link, template, **extra):
    """A page about the link's Mod. Its Flags name what their changes touch,
    and only those documents are read to name them."""
    world, mod = link.world, link.mod
    flags = Flag.objects.open_in(world).filter(mod=mod)
    touched = set(flags.values_list("change__entity", flat=True))
    index = Index(world, Document.objects.filter(organization=world.organization, world=world,
                                                 slug__in=touched))
    return render(request, template, {
        "link": link, "mod": mod, "state": state_of(mod), "flags": flags_shown(index, flags),
        **extra})


@through_a_link
@require_GET
def mod(request, link):
    """The Mod, as its Mod Runner reads it."""
    return page(request, link, "canon/run_mod.html", body=render_markdown(link.mod.body))


@through_a_link
@require_GET
def dry_run(request, link):
    """The Mod's Dry Run, for its Mod Runner in the field. Its way back is to
    the Mod as the link shows it, never into the World."""
    return page(request, link, "canon/dry_run.html", full_mod="../",
                **dry_runs.step(link.mod, request))


@through_a_link
@require_GET
def mod_file(request, link):
    """The Mod's file, to read with no signal."""
    response = HttpResponse(link.mod.text, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(True, f"{link.mod.slug}.md")
    return response


@through_a_link
@require_GET
def mod_twee(request, link):
    """The Mod as a Twee file, to open in Twine."""
    return twee_download(link.mod)


def own_findings(world, errors, text):
    """plotcanon's findings on a refused report, as a link holder may see
    them: only those about the report itself, with any other document's path
    taken out. plotcanon checks the report against the whole World, and the
    World beyond this Mod is not theirs to see."""
    path = submitting.path_for(text)
    others = sorted(Document.objects.filter(organization=world.organization, world=world)
                    .values_list("path", flat=True), key=len, reverse=True)
    lines = []
    for line in errors.splitlines():
        if f" {path}: " not in line:
            continue
        for other in others:
            line = line.replace(other, "another document")
        lines.append(line)
    return "\n".join(lines)


@through_a_link
@require_http_methods(["GET", "POST"])
def report(request, link):
    """File an After-Action Report on the Mod, pasted or uploaded."""
    if request.method == "GET":
        return page(request, link, "canon/run_report.html", form=ReportForm())
    try:
        links.count_report(link)
    except links.TooMany as refused:
        return refused_for_now(str(refused))
    form = ReportForm(request.POST, request.FILES)
    if not form.is_valid():
        return page(request, link, "canon/run_report.html", form=form)
    text = form.cleaned_data["contents"]
    try:
        submitting.submit(link.world, link.mod, text, None, filed_through=link)
    except submitting.ReportRefused as refused:
        errors = own_findings(link.world, refused.errors, text) if refused.errors else ""
        if refused.errors and not errors:
            errors = ("It does not fit the World as it stands, in a way only a Plot Master "
                      "can see. Ask one to look at it.")
        return page(request, link, "canon/run_report.html",
                    form=ReportForm(initial={"text": text}), refused=str(refused),
                    errors=errors)
    mod = Document.objects.get(organization=link.organization_id, world=link.world,
                               pk=link.mod.pk)
    return page(request, link, "canon/run_filed.html",
                more_to_come=submitting.can_be_reported_on(mod))
