from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from organizations.views import is_plot_master, world_or_404

from .forms import ImportForm
from .importing import ImportRefused, import_world
from .kinds import KINDS
from .models import Document
from .presenting import Index, render_markdown, wording


def documents_of(world):
    """This World's documents. The filter repeats what the database already
    enforces for the Organization, and adds the World."""
    return Document.objects.filter(organization=world.organization, world=world)


@require_http_methods(["GET", "POST"])
def import_page(request, world_id):
    """Import a World from a zip of its files. For the World's Plot Masters,
    and only while the World holds no Canon."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    context = {"world": world, "has_canon": documents_of(world).exists()}
    if context["has_canon"] or request.method == "GET":
        return render(request, "canon/import.html", {**context, "form": ImportForm()})

    form = ImportForm(request.POST, request.FILES)
    too_large = int(request.META.get("CONTENT_LENGTH") or 0) > settings.FILE_UPLOAD_MAX_MEMORY_SIZE
    if too_large:
        megabytes = settings.FILE_UPLOAD_MAX_MEMORY_SIZE // (1024 * 1024)
        form.errors.clear()
        form.add_error("archive", f"That file is too large. The limit is {megabytes} MB.")
    if not form.is_valid():
        return render(request, "canon/import.html", {**context, "form": form})

    try:
        report = import_world(world, form.cleaned_data["archive"])
    except ImportRefused as refused:
        return render(request, "canon/import.html",
                      {**context, "form": ImportForm(), "refused": str(refused),
                       "errors": refused.errors})
    noted = (f" plotcanon noted {len(report.warnings)} thing"
             f"{'' if len(report.warnings) == 1 else 's'} worth a look."
             if report.warnings else "")
    count = report.document_count
    messages.success(request, f"Imported {count} document{'' if count == 1 else 's'}.{noted}")
    return redirect("world", world_id=world.pk)


def state_of(document):
    """A document's state or status, as words, or nothing if it has neither."""
    value = document.fields.get("state") or document.fields.get("status")
    return wording(value) if isinstance(value, str) else ""


def aliases_of(document):
    aliases = document.fields.get("aliases")
    return aliases if isinstance(aliases, list) else []


def kind_or_404(kind):
    if kind not in KINDS:
        raise Http404("No such page")
    return KINDS[kind]


@require_GET
def listing(request, world_id, kind):
    world = world_or_404(request, world_id)
    doc_type, label = kind_or_404(kind)
    documents = list(documents_of(world).filter(kind=doc_type))
    for document in documents:
        document.state = state_of(document)
    return render(request, "canon/list.html",
                  {"world": world, "kind": kind, "label": label, "documents": documents})


@require_GET
def detail(request, world_id, kind, slug):
    world = world_or_404(request, world_id)
    doc_type, label = kind_or_404(kind)
    index = Index(world, documents_of(world))
    document = index.by_slug.get(slug)
    if document is None or document.kind != doc_type:
        raise Http404("No such document")
    entities = document.fields.get("entities")
    return render(request, "canon/detail.html", {
        "world": world,
        "kind": kind,
        "label": label,
        "document": document,
        "state": state_of(document),
        "aliases": [str(a) for a in aliases_of(document) if str(a) != document.name],
        "facts": index.facts(document),
        "features": index.grouped(document.fields.get("features")
                                  or document.fields.get("involves")),
        "plot_mods": index.mods_of(document),
        "plot_entities": index.links(entities) if isinstance(entities, list) else [],
        "canon_changes": index.canon_changes(document),
        "referred_to_by": index.referred_to_by(document),
        "body": render_markdown(document.body),
    })
