from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import plotcanon
from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from organizations.forms import DryRunStructureForm
from organizations.views import is_plot_master, may_write_mods, world_or_404

from . import (approving, deciding, exporting, intake, interludes, links, resolving,
               submitting, world_settings, writers)
from .forms import ChangeForm, ImportForm, InterludeForm, ModForm, RecordForm, ReportForm
from .importing import ImportRefused, import_world
from .kinds import KINDS
from .models import CanonChange, Decision, Document, Flag, ModLink
from .presenting import Index, render_markdown, wording


def documents_of(world):
    """This World's documents. The filter repeats what the database already
    enforces for the Organization, and adds the World."""
    return Document.objects.filter(organization=world.organization, world=world)


def plot_masters_only(view):
    """A view of one World for its Plot Masters, given the World. Anyone else
    is told there is no such page."""
    @wraps(view)
    def wrapper(request, world_id, *args, **kwargs):
        world = world_or_404(request, world_id)
        if not is_plot_master(request, world):
            raise Http404("No such page")
        return view(request, world, *args, **kwargs)
    return wrapper


@require_http_methods(["GET", "POST"])
@plot_masters_only
def import_page(request, world):
    """Import a World from a zip of its files. For the World's Plot Masters,
    and only while the World holds no Canon."""
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


@require_http_methods(["GET", "POST"])
@plot_masters_only
def dry_run_structure(request, world):
    """Change how strictly the World asks for Dry Run structure in its Mods.
    For its Plot Masters only."""
    current = world_settings.settings_of(world).dry_run_structure
    form = DryRunStructureForm(request.POST or None, initial={"structure": current})
    context = {"world": world, "form": form}
    if request.method == "POST" and form.is_valid():
        try:
            world_settings.set_dry_run_structure(world, form.cleaned_data["structure"])
        except world_settings.SettingRefused as refused:
            return render(request, "canon/dry_run_structure.html", {
                **context, "form": DryRunStructureForm(initial={"structure": current}),
                "refused": str(refused), "errors": refused.errors})
        messages.success(request, f"{world.name}'s Dry Run structure is now "
                                  f"`{form.cleaned_data['structure']}`.")
        return redirect("world", world_id=world.pk)
    return render(request, "canon/dry_run_structure.html", context)


@require_GET
@plot_masters_only
def export_page(request, world):
    """What an export holds, and the button to download it. For the World's
    Plot Masters."""
    return render(request, "canon/export.html", {
        "world": world, "has_canon": documents_of(world).exists(),
        "folder": exporting.folder_for(world)})


@never_cache
@require_GET
@plot_masters_only
def export_download(request, world):
    """The World as a zip of its files. For the World's Plot Masters."""
    if not documents_of(world).exists():
        return redirect("canon-export", world_id=world.pk)
    try:
        content, name = exporting.export(world)
    except exporting.ExportFailed as failed:
        return render(request, "canon/export_failed.html",
                      {"world": world, "errors": failed.errors}, status=500)
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = content_disposition_header(True, name)
    return response


@require_http_methods(["GET", "POST"])
@plot_masters_only
def add_interlude(request, world):
    """Add an Interlude to the World's order of Events. For its Plot Masters."""
    choices = {
        "events": [(event.slug, event.name) for event in interludes.events_of(world)],
        "campaigns": list(approving.campaigns_of(world).items())}
    if not choices["events"]:
        raise Http404("No such page")
    form = InterludeForm(request.POST or None, **choices)
    if request.method == "POST" and form.is_valid():
        try:
            event = interludes.add(world, user=request.user, **form.cleaned_data)
        except interludes.InterludeRefused as refused:
            messages.error(request, " ".join(filter(None, [str(refused), refused.errors])))
        else:
            messages.success(request, f"{event.name} is added to the order of Events. Record "
                                      f"the Canon Changes made during it from here.")
            return redirect("canon-detail", world_id=world.pk, kind="events", slug=event.slug)
    return render(request, "canon/add_interlude.html", {"world": world, "form": form})


@require_http_methods(["GET", "POST"])
@plot_masters_only
def record_changes(request, world, slug):
    """Record Canon Changes made during an Interlude, one entered here or a
    pasted file of them. For the World's Plot Masters."""
    event = documents_of(world).filter(kind="event", slug=slug).first()
    if event is None or not interludes.is_interlude(event):
        raise Http404("No such page")
    vocabulary = plotcanon.vocabularies()["vocabularies"]["canon_change_kind"]
    entity_kinds = ("npc", "faction", "location", "plot", "pc")
    choices = {
        "entities": [(d.slug, f"{d.name} ({d.kind})") for d in
                     documents_of(world).filter(kind__in=entity_kinds).order_by("name")],
        "kinds": [(kind, wording(kind)) for kind in vocabulary]}
    context = {"world": world, "event": event}
    change_form, file_form = ChangeForm(**choices), RecordForm()
    if request.method == "POST":
        pasting = "text" in request.POST or "file" in request.FILES
        if pasting:
            file_form = RecordForm(request.POST, request.FILES)
            text = file_form.cleaned_data["contents"] if file_form.is_valid() else None
        else:
            change_form = ChangeForm(request.POST, **choices)
            text = interludes.change_file(world, event, **change_form.cleaned_data) \
                if change_form.is_valid() else None
        if text is not None:
            try:
                record = interludes.record(world, event, text, request.user)
            except interludes.InterludeRefused as refused:
                context.update(refused=str(refused), errors=refused.errors)
                if pasting:
                    file_form = RecordForm(initial={"text": text})
            else:
                count = len(record.fields.get("canon_changes") or [])
                messages.success(request, f"{count} change{'' if count == 1 else 's'} recorded "
                                          f"during {event.name}, and Canon now.")
                return redirect("canon-detail", world_id=world.pk, kind="events",
                                slug=event.slug)
    return render(request, "canon/record.html",
                  {**context, "change_form": change_form, "file_form": file_form})


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
                  {"world": world, "kind": kind, "label": label, "documents": documents,
                   "may_add_interlude": doc_type == "event" and is_plot_master(request, world)})


@require_GET
def detail(request, world_id, kind, slug):
    world = world_or_404(request, world_id)
    doc_type, label = kind_or_404(kind)
    index = Index(world, documents_of(world))
    document = index.by_slug.get(slug)
    if document is None or document.kind != doc_type:
        raise Http404("No such document")
    entities = document.fields.get("entities")
    draft = doc_type == "mod" and is_draft(document)
    report_changes = [{**change_row(index, c), "undos": c.undos.all()} for c in
                      CanonChange.objects.in_world(world).filter(report=document)
                      .select_related("report__submitted_by", "decided_by")
                      .prefetch_related("undos__decided_by", "undos__undone_by")] \
        if doc_type in ("after-action", interludes.RECORD) else []
    selected, refused_change_id = selection(request)
    return render(request, "canon/detail.html", {
        "world": world,
        "kind": kind,
        "label": label,
        "document": document,
        "state": state_of(document),
        "aliases": [str(a) for a in aliases_of(document) if str(a) != document.name],
        "facts": index.facts(document),
        "features": index.grouped(document),
        "plot_mods": index.mods_of(document),
        "plot_entities": index.links(entities) if isinstance(entities, list) else [],
        "referred_to_by": index.referred_to_by(document),
        "flags": flags_shown(index, Flag.objects.open_in(world).filter(mod=document))
        if doc_type == "mod" else [],
        "resolved_flags": flags_shown(index, Flag.objects.filter(
            organization=world.organization, world=world, mod=document).exclude(resolution=""))
        if doc_type == "mod" else [],
        "sent_back": draft and document.sent_back_at is not None,
        "may_approve": draft,
        "needs_campaign": doc_type == "mod" and approving.needs_campaign(document),
        "campaigns": approving.campaigns_of(world) if draft else {},
        "approved_by": document.approved_by,
        "approved_at": document.approved_at,
        "may_revise": draft and may_revise(request, world, document),
        "writer": writers.writer_of(document) if doc_type == "mod" else None,
        "may_reassign": draft and is_plot_master(request, world),
        "mod_links": ModLink.objects.filter(organization=world.organization, world=world,
                                            mod=document).select_related("created_by")
        if doc_type == "mod" and is_plot_master(request, world) else None,
        "may_link": doc_type == "mod" and submitting.can_be_reported_on(document),
        "filed_through": document.filed_through,
        "mod_writers": writers.may_write_mods_in(world) if draft else [],
        "may_send_back": doc_type == "mod"
        and document.fields.get("state") in submitting.states().reportable
        and not reported_on(world, document),
        "can_be_reported_on": doc_type == "mod" and submitting.can_be_reported_on(document),
        "report_changes": report_changes,
        "report_waiting": any(c["proposed"] for c in report_changes),
        "selected": selected,
        "refused_change_id": refused_change_id,
        "may_record": doc_type == "event" and interludes.is_interlude(document)
        and is_plot_master(request, world),
        "history": history(index, world, document),
        "rejected": rejected_changes(index, world, document),
        "waiting_for_it": [change_row(index, c) for c in
                           CanonChange.objects.pending(world).filter(entity=document.slug)
                           .select_related("report__submitted_by")],
        "may_decide": is_plot_master(request, world),
        "note_length": deciding.NOTE_LENGTH,
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
        filed = submitting.submit(world, mod, form.cleaned_data["contents"], request.user)
    except submitting.ReportRefused as refused:
        # Give back what was sent, so it can be corrected and sent again.
        again = ReportForm(initial={"text": form.cleaned_data["contents"]})
        return render(request, "canon/report.html",
                      {**context, "form": again, "refused": str(refused),
                       "errors": refused.errors})
    messages.success(request, "Report filed. Its Canon Changes are waiting to be decided.")
    return redirect("canon-detail", world_id=world.pk, kind="reports", slug=filed.slug)


def is_draft(mod):
    """Whether a Mod is a draft: submitted, and not yet approved to run."""
    return mod.fields.get("state") == submitting.states().draft


def may_revise(request, world, mod):
    """Whether this person may revise this Mod while it is a draft: they are
    a Plot Master, or its Mod Writer."""
    if is_plot_master(request, world):
        return True
    return writers.is_writer_of(mod, request.user) and may_write_mods(request, world)


def show_warnings(request, warnings):
    """plotcanon's warnings about a Mod that was saved anyway, one to a line,
    to copy for the Mod Writer's LLM."""
    if warnings:
        messages.warning(request, "plotcanon noted these about it. They do not stop it, "
                                  "but are worth a look:")
        messages.warning(request, warnings, extra_tags="findings")


def mod_form(request, context, save):
    """Show the form for a Mod file, or take one in with `save(text)`, which
    returns the stored Mod and plotcanon's warnings about it. What was sent is
    given back if it is refused."""
    if request.method == "GET":
        return render(request, "canon/mod_form.html", {**context, "form": ModForm()})
    form = ModForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "canon/mod_form.html", {**context, "form": form})
    try:
        saved, warnings = save(form.cleaned_data["contents"])
    except intake.ModRefused as refused:
        again = ModForm(initial={"text": form.cleaned_data["contents"]})
        return render(request, "canon/mod_form.html",
                      {**context, "form": again, "refused": str(refused),
                       "errors": refused.errors})
    messages.success(request, f"{saved.name} is saved as a draft. A Plot Master approves it "
                              f"before it can be run.")
    show_warnings(request, warnings)
    return redirect("canon-detail", world_id=saved.world_id, kind="mods", slug=saved.slug)


@require_http_methods(["GET", "POST"])
def submit_mod(request, world_id):
    """Submit a new Mod, pasted or uploaded. For the World's Mod Writers and
    Plot Masters, once it has Canon."""
    world = world_or_404(request, world_id)
    if not may_write_mods(request, world) or not documents_of(world).exists():
        raise Http404("No such page")
    return mod_form(request, {"world": world},
                    lambda text: intake.submit_mod(world, text, request.user))


@require_http_methods(["GET", "POST"])
def revise(request, world_id, slug):
    """Replace a draft Mod with a revised file. For the Mod Writer who
    submitted it and the World's Plot Masters."""
    world = world_or_404(request, world_id)
    mod = mod_or_404(world, slug)
    if not may_revise(request, world, mod):
        raise Http404("No such page")
    if not is_draft(mod):
        messages.error(request, f"{mod.name} is not a draft, and only a draft can be revised.")
        return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)
    return mod_form(request, {"world": world, "mod": mod},
                    lambda text: intake.revise(world, mod, text, request.user))


def change_row(index, change):
    """A Canon Change as a row a page can show."""
    return {
        "id": change.pk,
        "entity": index.link(change.entity),
        "kind": wording(change.kind),
        "decision": wording(change.decision),
        "proposed": change.decision == Decision.PROPOSED,
        "moved": bool(change.before or change.after),
        "before": change.before,
        "after": change.after,
        "summary": change.summary,
        "report": index.link(change.report.slug),
        "submitted_by": change.report.submitted_by,
        "submitted_at": change.report.submitted_at,
        "decided_by": change.decided_by,
        "decided_at": change.decided_at,
        "note": change.note,
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
                   .exclude(decision=Decision.PROPOSED)
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
    selected, refused_change_id = selection(request)
    return render(request, "canon/pending.html", {
        "world": world, "groups": groups, "count": len(waiting),
        "may_decide": is_plot_master(request, world),
        "note_length": deciding.NOTE_LENGTH,
        "selected": selected, "refused_change_id": refused_change_id,
    })


# What a Plot Master's button says, and the decision it makes.
DECISIONS = {"approve": Decision.APPROVED, "reject": Decision.REJECTED}


@require_POST
def decide(request, world_id, change_id, decision):
    """Approve or reject one Canon Change, or undo its decision, then go back
    to the page it was decided on. For the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    undoing = decision == "undo"
    if not (undoing or decision in DECISIONS) or not is_plot_master(request, world):
        raise Http404("No such page")
    try:
        if undoing:
            change = deciding.undo(world, change_id, request.user)
        else:
            change = deciding.decide(world, change_id, DECISIONS[decision], request.user,
                                     note=request.POST.get("note", ""))
    except deciding.DecisionRefused as refused:
        messages.error(request, str(refused))
    else:
        done = "Undone, and proposed again" if undoing else wording(change.decision)
        messages.success(request, f"{done}: {change.summary}")
    back = back_to(request, reverse("canon-pending", args=[world.pk]))
    return redirect(without_selected(back))


@require_POST
def decide_selected(request, world_id):
    """Approve or reject the selected Canon Changes together, or every waiting
    change of one report, then go back to the page they were decided on. All
    are decided or none; if none, the page says which could not be and why,
    with the rest still selected. For the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    decision = DECISIONS.get(request.POST.get("decision"))
    if decision is None or not is_plot_master(request, world):
        raise Http404("No such page")
    chosen = [int(i) for i in request.POST.getlist("change") if i.isdigit()]
    report = request.POST.get("report")
    if report:
        chosen = list(CanonChange.objects.pending(world).filter(report__slug=report)
                      .values_list("pk", flat=True))
    back = back_to(request, reverse("canon-pending", args=[world.pk]))
    try:
        decided = deciding.decide_all(world, chosen, decision, request.user,
                                     note=request.POST.get("note", ""))
    except deciding.SelectionRefused as refused:
        messages.error(request, str(refused))
        return redirect(with_selected(back, [i for i in chosen if i != refused.change.pk],
                                      refused.change.pk))
    except deciding.DecisionRefused as refused:
        messages.error(request, str(refused))
    else:
        count = len(decided)
        messages.success(request, f"{wording(decision)} {count} Canon "
                                  f"Change{'' if count == 1 else 's'}.")
    return redirect(without_selected(back))


def without_selected(address):
    """`address` without the selection a refused one left on it."""
    parts = urlsplit(address)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("selected", "refused")]
    return urlunsplit(parts._replace(query=urlencode(query)))


def with_selected(address, selected, refused):
    """`address` showing the changes still selected, and the one refused, so
    the Plot Master can untick it and try again."""
    parts = urlsplit(without_selected(address))
    query = parse_qsl(parts.query) + [("selected", i) for i in selected] + [("refused", refused)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def selection(request):
    """The changes a refused selection left selected, and the one refused."""
    selected = {int(i) for i in request.GET.getlist("selected") if i.isdigit()}
    refused = request.GET.get("refused", "")
    return selected, int(refused) if refused.isdigit() else None


def flags_shown(index, flags):
    """Flags as rows a page can show: the Mod, the Feature the change touches,
    what the change says, and the report it came from."""
    return [{
        "id": flag.pk,
        "resolution": flag.get_resolution_display(),
        "resolved_by": flag.resolved_by,
        "resolved_at": flag.resolved_at,
        "note": flag.note,
        "mod": index.link(flag.mod.slug),
        "entity": index.link(flag.change.entity),
        "kind": wording(flag.change.kind),
        "moved": bool(flag.change.before or flag.change.after),
        "before": flag.change.before,
        "after": flag.change.after,
        "summary": flag.change.summary,
        "report": index.link(flag.change.report.slug),
    } for flag in flags.select_related("mod", "change__report", "resolved_by")
        .order_by("mod__name", "change__report__submitted_at", "change__position")]


@require_GET
def flags(request, world_id):
    """Every open Flag in the World, by Mod."""
    world = world_or_404(request, world_id)
    index = Index(world, documents_of(world))
    return render(request, "canon/flags.html", {
        "world": world, "flags": flags_shown(index, Flag.objects.open_in(world)),
        "may_decide": is_plot_master(request, world)})


def back_to(request, otherwise):
    """The page to return to after an action: the one the form named, if it
    is on this site, and `otherwise` if not."""
    back = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return back
    return otherwise


@require_POST
def dismiss_flag(request, world_id, flag_id):
    """Dismiss one Flag. For the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    try:
        resolving.dismiss(world, flag_id, request.user)
    except resolving.ResolutionRefused as refused:
        messages.error(request, str(refused))
    else:
        messages.success(request, "Flag dismissed.")
    return redirect(back_to(request, reverse("canon-flags", args=[world.pk])))


@require_POST
def send_back(request, world_id, slug):
    """Send a Mod back to its Mod Writer. For the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    mod = mod_or_404(world, slug)
    try:
        mod = resolving.send_back(world, mod, request.POST.get("reason", ""), request.user)
    except resolving.ResolutionRefused as refused:
        messages.error(request, str(refused))
        return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)
    # The World stays locked until this request's transaction ends, so the
    # Mod Writer read here is the one it was sent back to.
    writer = writers.writer_of(mod)
    if writer is not None and not writers.still_writes(world, writer):
        messages.success(request, f"{mod.name} is a draft again. Its Mod Writer, "
                                  f"{writer.email}, no longer writes Mods here, so nobody "
                                  f"was emailed; a Plot Master can reassign it from its page.")
    elif writer is None:
        messages.success(request, f"{mod.name} is a draft again. No Mod Writer is known for "
                                  f"it, so nobody was emailed; a Plot Master can reassign it "
                                  f"from its page.")
    else:
        tell_sent_back(request, world, mod, writer, mod.sent_back_reason)
        messages.success(request, f"{mod.name} is a draft again, back with its Mod Writer, "
                                  f"{writer.email}, who has been emailed why.")
    return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)


def tell_sent_back(request, world, mod, writer, reason):
    """Email a Mod's Mod Writer that it has been sent back, once that is saved."""
    link = request.build_absolute_uri(reverse("canon-detail", args=[world.pk, "mods", mod.slug]))
    message = render_to_string("canon/sent_back_email.txt", {
        "mod": mod.name, "world": world.name, "by": request.user.email, "reason": reason,
        "link": link})
    # An email subject must be one line.
    subject = " ".join(f"{mod.name} has been sent back to you".split())
    transaction.on_commit(lambda: send_mail(subject=subject, message=message, from_email=None,
                                            recipient_list=[writer.email]))


@require_POST
def create_link(request, world_id, slug):
    """Create a private link to a Mod for a Mod Runner, and show it once. For
    the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    mod = mod_or_404(world, slug)
    try:
        link, secret = links.create(world, mod, request.POST.get("label", ""), request.user)
    except links.LinkRefused as refused:
        messages.error(request, str(refused))
        return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)
    # Shown on this page alone, never put in a message, which would keep it
    # in a cookie or the session.
    response = render(request, "canon/link_created.html", {
        "world": world, "mod": mod, "link": link,
        "address": request.build_absolute_uri(reverse("run-mod", args=[secret]))})
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def turn_off_link(request, world_id, slug, link_id):
    """Turn a private link off. For the World's Plot Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    mod = mod_or_404(world, slug)
    if links.turn_off(world, mod, link_id, request.user):
        messages.success(request, "The link is turned off, and opens nothing now.")
    return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)


@require_POST
def reassign(request, world_id, slug):
    """Make someone else the Mod Writer of a draft. For the World's Plot
    Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    mod = mod_or_404(world, slug)
    try:
        writers.reassign(world, mod, request.POST.get("user", ""), request.user)
    except writers.WriterRefused as refused:
        messages.error(request, str(refused))
    else:
        messages.success(request, f"{mod.name} is reassigned.")
    return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)


@require_http_methods(["GET", "POST"])
def mod_writers(request, world_id):
    """Link each Mod Writer handle in the World's files to a person. For the
    World's Plot Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    if request.method == "POST":
        handle = request.POST.get("handle", "")
        try:
            person = writers.link(world, handle, request.POST.get("user", ""), request.user)
        except writers.WriterRefused as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, f"`{handle}` is {person.email}." if person
                             else f"`{handle}` is linked to nobody.")
        return redirect("canon-mod-writers", world_id=world.pk)
    return render(request, "canon/mod_writers.html", {
        "world": world, "handles": writers.handles_in(world).items(),
        "people": writers.may_write_mods_in(world)})


@require_POST
def approve(request, world_id, slug):
    """Approve a draft Mod, so that it can be run. For the World's Plot
    Masters only."""
    world = world_or_404(request, world_id)
    if not is_plot_master(request, world):
        raise Http404("No such page")
    mod = mod_or_404(world, slug)
    try:
        _, warnings = approving.approve(world, mod, request.user,
                                        campaign=request.POST.get("campaign"))
    except approving.ApprovalRefused as refused:
        messages.error(request, str(refused))
        if refused.errors:
            # plotcanon's findings, one to a line, to copy for the Mod Writer.
            messages.error(request, refused.errors, extra_tags="findings")
    else:
        messages.success(request, f"{mod.name} is approved, and can be run.")
        show_warnings(request, warnings)
    return redirect("canon-detail", world_id=world.pk, kind="mods", slug=mod.slug)


def history(index, world, document):
    """The approved Canon Changes to one document, in the order they happened,
    each with the report it came from."""
    return decided_changes(index, world, document, Decision.APPROVED)


def rejected_changes(index, world, document):
    """The rejected Canon Changes to one document, in the order they happened,
    each with the report it came from."""
    return decided_changes(index, world, document, Decision.REJECTED)


def decided_changes(index, world, document, decision):
    changes = list(CanonChange.objects.in_world(world)
                   .filter(entity=document.slug, decision=decision)
                   .select_related("report__submitted_by", "decided_by"))
    if not changes:
        return []
    ordering = deciding.Ordering(documents_of(world).filter(kind="event"))
    changes.sort(key=lambda change: (ordering.of(change.report), change.position))
    return [change_row(index, change) for change in changes]


def reported_on(world, mod):
    """Whether any After-Action Report has been filed on this Mod."""
    return documents_of(world).filter(kind="after-action", fields__mod=mod.slug).exists()
