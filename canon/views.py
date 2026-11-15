from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from organizations.views import is_plot_master, world_or_404

from . import deciding

from . import submitting
from .forms import ImportForm, ReportForm
from .importing import ImportRefused, import_world
from .kinds import KINDS
from .models import CanonChange, Document, Flag
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
        "referred_to_by": index.referred_to_by(document),
        "flags": flags_shown(index, Flag.objects.open_in(world).filter(mod=document))
        if doc_type == "mod" else [],
        "can_be_reported_on": doc_type == "mod" and submitting.can_be_reported_on(document),
        "report_changes": [change_row(index, c) for c in
                           CanonChange.objects.in_world(world).filter(report=document)
                           .select_related("report__submitted_by", "decided_by")]
        if doc_type == "after-action" else [],
        "history": history(index, world, document),
        "waiting_for_it": [change_row(index, c) for c in
                           CanonChange.objects.pending(world).filter(entity=document.slug)
                           .select_related("report__submitted_by")],
        "may_decide": is_plot_master(request, world),
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
    messages.success(request, "Report filed. Its Canon Changes are waiting to be decided.")
    return redirect("canon-detail", world_id=world.pk, kind="reports", slug=filed.slug)


def change_row(index, change):
    """A Canon Change as a row a page can show."""
    return {
        "id": change.pk,
        "entity": index.link(change.entity),
        "kind": wording(change.kind),
        "decision": wording(change.decision),
        "proposed": change.decision == deciding.PROPOSED,
        "moved": bool(change.before or change.after),
        "before": change.before,
        "after": change.after,
        "summary": change.summary,
        "report": index.link(change.report.slug),
        "submitted_by": change.report.submitted_by,
        "submitted_at": change.report.submitted_at,
        "decided_by": change.decided_by,
        "decided_at": change.decided_at,
    }


# How many decided changes to show beside each entity's pending ones.
RECENTLY_DECIDED = 5


def mark_disagreements(rows):
    """Mark the waiting changes in one group that cannot all be approved:
    two that move the same field from the same value to different ones."""
    for row in rows:
        row["disagrees_with"] = [
            other["report"] for other in rows
            if other is not row and other["moved"] and row["moved"]
            and other["kind"] == row["kind"] and other["before"] == row["before"]
            and other["after"] != row["after"]]
    return rows


@require_GET
def pending(request, world_id):
    """The review screen: every Canon Change still to be decided, grouped by
    what it changes, with the changes to it already approved alongside, so two
    reports that disagree sit side by side."""
    world = world_or_404(request, world_id)
    documents = list(documents_of(world))
    index = Index(world, documents)
    ordering = deciding.Ordering(documents)
    waiting = list(CanonChange.objects.pending(world)
                   .select_related("report__submitted_by"))
    entities = sorted({c.entity for c in waiting},
                      key=lambda slug: index.link(slug)["text"].lower())
    decided = {}
    for change in (CanonChange.objects.in_world(world).filter(entity__in=entities)
                   .exclude(decision=deciding.PROPOSED)
                   .select_related("report__submitted_by", "decided_by")):
        decided.setdefault(change.entity, []).append(change)
    groups = []
    for slug in entities:
        mine = sorted((c for c in waiting if c.entity == slug),
                      key=lambda c: (ordering.of(c.report), c.position))
        recent = sorted(decided.get(slug, []), key=lambda c: ordering.of(c.report))
        groups.append({
            "entity": index.link(slug),
            "waiting": mark_disagreements([change_row(index, c) for c in mine]),
            "recent": [change_row(index, c) for c in recent[-RECENTLY_DECIDED:]],
        })
    return render(request, "canon/pending.html", {
        "world": world, "groups": groups, "count": len(waiting),
        "may_decide": is_plot_master(request, world),
    })


@require_POST
def decide(request, world_id, change_id, decision):
    """Approve or reject one Canon Change, then go back to the page it was
    decided on. For the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    chosen = {"approve": deciding.APPROVED, "reject": deciding.REJECTED}.get(decision)
    if chosen is None or not is_plot_master(request, world):
        raise Http404("No such page")
    try:
        change = deciding.decide(world, change_id, chosen, request.user)
    except deciding.DecisionRefused as refused:
        messages.error(request, str(refused))
    else:
        messages.success(request, f"{wording(change.decision)}: {change.summary}")
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        back = reverse("canon-pending", args=[world.pk])
    return redirect(back)


def flags_shown(index, flags):
    """Flags as rows a page can show: the Mod, the Feature the change touches,
    what the change says, and the report it came from."""
    return [{
        "mod": index.link(flag.mod.slug),
        "entity": index.link(flag.change.entity),
        "kind": wording(flag.change.kind),
        "moved": bool(flag.change.before or flag.change.after),
        "before": flag.change.before,
        "after": flag.change.after,
        "summary": flag.change.summary,
        "report": index.link(flag.change.report.slug),
    } for flag in flags.select_related("mod", "change__report")
        .order_by("mod__name", "change__report__submitted_at", "change__position")]


@require_GET
def flags(request, world_id):
    """Every open Flag in the World, by Mod."""
    world = world_or_404(request, world_id)
    index = Index(world, documents_of(world))
    return render(request, "canon/flags.html", {
        "world": world, "flags": flags_shown(index, Flag.objects.open_in(world))})


def history(index, world, document):
    """The approved Canon Changes to one document, in the order they happened,
    each with the report it came from."""
    changes = list(CanonChange.objects.approved(world).filter(entity=document.slug)
                   .select_related("report__submitted_by", "decided_by"))
    if not changes:
        return []
    ordering = deciding.Ordering(documents_of(world).filter(kind="event"))
    changes.sort(key=lambda change: (ordering.of(change.report), change.position))
    return [change_row(index, change) for change in changes]
