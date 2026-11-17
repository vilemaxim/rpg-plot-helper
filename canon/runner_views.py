"""The pages a private link opens, for a Mod Runner with no account.

Each shows one Mod and nothing else in its World: no page here links to
another, and every one of them starts from the link (`links.opened`). What
a link opens is told under **Private link** in GLOSSARY.md.
"""

from functools import wraps

from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET
from django.views.defaults import page_not_found

from . import access, links
from .models import Document, Flag
from .presenting import Index, render_markdown
from .views import dry_run_page_or_404, flags_shown, state_of, twee_download


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
    """A page about the link's Mod. A link reads its own Mod and nothing else
    in the World (ADR-0010), so every other document its Flags name reads
    "another document"."""
    world, mod = link.world, link.mod
    flags = Flag.objects.open_in(world).filter(mod=mod)
    others = list(Document.objects.filter(organization=world.organization, world=world)
                  .exclude(pk=mod.pk).values_list("path", "slug", "name"))
    index = Index(world, [mod], hidden={slug for _, slug, _ in others},
                  hide=access.hiding(others))
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
                **dry_run_page_or_404(link.mod, request))


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


@login_not_required
def nothing_here(request, secret, other_page):
    """Any other address under a link: not found, and not sent to sign-in,
    which would carry the secret along in its address. It opens no link, so
    it counts as no guess and is never refused for guessing."""
    response = page_not_found(request, Http404("No such page"))
    response["Referrer-Policy"] = "no-referrer"
    return response
