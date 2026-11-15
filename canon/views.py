from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from organizations.views import is_plot_master, world_or_404

from . import submitting
from .forms import ImportForm, ReportForm
from .importing import ImportRefused, import_world
from .kinds import KINDS
from .models import CanonChange, Document
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
        "can_be_reported_on": doc_type == "mod" and submitting.can_be_reported_on(document),
        "submitted_by": document.submitted_by,
        "submitted_at": document.submitted_at,
        "body": render_markdown(document.body),
    })


def mod_or_404(world, slug):
    mod = documents_of(world).filter(kind="mod", slug=slug).first()
    if mod is None:
        raise Http404("No such Mod")
    return mod


@require_http_methods(["GET", "POST"])
def report(request, world_id, slug):
    """File an After-Action Report on a Mod, pasted or uploaded. For anyone
    who can open the World."""
    world = world_or_404(request, world_id)
    mod = mod_or_404(world, slug)
    context = {"world": world, "mod": mod,
               "can_be_reported_on": submitting.can_be_reported_on(mod),
               "state": state_of(mod)}
    if not context["can_be_reported_on"] or request.method == "GET":
        return render(request, "canon/report.html", {**context, "form": ReportForm()})

    form = ReportForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "canon/report.html", {**context, "form": form})
    try:
        filed = submitting.submit(world, mod, form.cleaned_data["report"], request.user)
    except submitting.ReportRefused as refused:
        # Give back what was sent, so it can be corrected and sent again.
        again = ReportForm(initial={"text": form.cleaned_data["report"]})
        return render(request, "canon/report.html",
                      {**context, "form": again, "refused": str(refused),
                       "errors": refused.errors})
    return redirect("canon-detail", world_id=world.pk, kind="reports", slug=filed.slug)


@require_GET
def pending(request, world_id):
    """Every Canon Change in the World that is still only proposed."""
    world = world_or_404(request, world_id)
    index = Index(world, documents_of(world))
    changes = list(CanonChange.objects.pending(world).select_related("report__submitted_by")
                   .order_by("report__submitted_at", "report_id", "position"))
    rows = [{
        "entity": index.link(change.entity),
        "kind": wording(change.kind),
        "moved": bool(change.before or change.after),
        "before": change.before,
        "after": change.after,
        "summary": change.summary,
        "report": index.link(change.report.slug),
        "submitted_by": change.report.submitted_by,
        "submitted_at": change.report.submitted_at,
    } for change in changes]
    return render(request, "canon/pending.html", {"world": world, "changes": rows})
