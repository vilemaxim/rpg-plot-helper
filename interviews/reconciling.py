"""Reconciliation (#59): the app's LLM checks a draft Mod against the whole
World's Canon, and against the other drafts waiting for approval, and writes
one report for the plot team to read before approving the Mod or sending it
back. It is advice only: nothing waits on it.

`reconcile(mod, by=...)` runs one and keeps it (`Reconciliation`). The LLM
reads the World as the plot team does (ADR-0010), whoever runs it, and is
given plotcanon's check findings on the draft so it does not repeat them.
What it is told is plotcanon's (`plotcanon.reconciliation_instructions`), and
what it writes is read by plotcanon (`plotcanon.read_reconciliation`).

A run is one LLM call inside the request that asks for it, with no
background worker (ADR-0003). Its tokens count toward the Organization's
monthly cap (ADR-0008, `spending`): at the cap it does not run.

Where its World says so (`organizations.reconciling`), a draft is reconciled
on submission: inside the request that submits or revises it, once it is
saved (`on_submission`, sent by `canon.intake.submitted`). A run that is
refused or fails leaves the draft saved and not reconciled, and its page
tells the plot team so, with the Reconcile button (`not_reconciled`).
"""

import logging

import plotcanon

from canon import access
from canon.submitting import states
from organizations.reconciling import reconciles_on_submission

from . import config, spending
from .models import Reconciliation
from .providers import Ended, Message, ProviderError, Text

SURFACE = "web"
# The one message the LLM is sent: its instructions say what to write.
ASKED = "Reconcile the draft."

OFF = "Reconciliation is not set up on this site."
NOT_A_DRAFT = "{} is not a draft, so there is nothing to reconcile."

log = logging.getLogger(__name__)


class NotReconciled(Exception):
    """No Reconciliation was kept. `str()` is a sentence for the plot team
    saying why: it is off, the Organization has reached its monthly tokens,
    the Mod is not a draft, or the LLM failed."""


def other_drafts_of(mod):
    """The World's other draft Mods, waiting for approval, by id."""
    return (access.documents_in(mod.world).filter(kind="mod", fields__state=states().draft)
            .exclude(pk=mod.pk).order_by("slug"))


def findings_on(mod):
    """plotcanon's check findings on the draft, as the World now stands."""
    report = plotcanon.load_world(access.as_plot_team(mod.world).files())
    return [finding for finding in report.findings if finding.path == mod.path]


def instructions(mod, others):
    """plotcanon's instructions for reconciling the draft `mod` against the
    World as the plot team reads it and the other drafts `others`."""
    return plotcanon.reconciliation_instructions(
        SURFACE, draft=mod.text, world=access.as_plot_team(mod.world).files(),
        other_drafts=[other.text for other in others], findings=findings_on(mod))


def reconcile(mod, *, by):
    """Reconcile the draft `mod` (a `canon.models.Document`) and keep the
    report. `by` is the person who asked, or None for a run on its
    submission. Returns the `Reconciliation`. Raises `NotReconciled` having
    kept nothing, though the tokens of a call that failed are counted all
    the same.

    Runs as the World's Organization, as a request does: the caller checks
    that `by` may (a Plot Master, `organizations.views.is_plot_master`)."""
    llm = config.reconciliation_llm()
    if llm is None:
        raise NotReconciled(OFF)
    if mod.fields.get("state") != states().draft:
        raise NotReconciled(NOT_A_DRAFT.format(mod.name))
    world = mod.world
    refused = spending.tokens_refused(world.organization_id)
    if refused:
        raise NotReconciled(refused)
    others = list(other_drafts_of(mod))
    system = instructions(mod, others)
    text = _written(llm, system, lambda usage: spending.record(world.organization_id, usage))
    read = plotcanon.read_reconciliation(text, draft_ids=[other.slug for other in others])
    return Reconciliation.objects.create(
        organization_id=world.organization_id, world=world, mod=mod, draft=mod.text,
        ran_by=by, on_submission=by is None, model=llm.settings.model, text=text,
        verdict=read.verdict or "", problems=list(read.problems),
        other_drafts=list(read.other_drafts),
        sections=[{"heading": section.heading, "text": section.text,
                   "findings": [{"ids": list(finding.ids), "text": finding.text}
                                for finding in section.findings]}
                  for section in read.sections])


def _written(llm, system, spent):
    """The whole of what the LLM writes, its tokens given to `spent`."""
    pieces, ended = [], None
    try:
        for event in llm.provider.stream_turn(system, [Message("user", ASKED)]):
            if isinstance(event, Text):
                pieces.append(event.text)
            elif isinstance(event, Ended):
                ended = event
                spent(event.usage)
    except ProviderError as error:
        if error.usage is not None:
            spent(error.usage)
        raise NotReconciled(str(error)) from None
    text = "".join(pieces)
    if not text.strip() or ended is None:
        raise NotReconciled("The LLM gave no report.")
    return text


def of(mod):
    """The Mod's Reconciliations, latest first."""
    return Reconciliation.objects.filter(world=mod.world, mod=mod).select_related("ran_by")


def shown_on(world, mod):
    """What a Mod's page shows its Plot Masters of its Reconciliations: the
    latest, and the earlier ones."""
    latest, *earlier = list(of(mod)) or [None]
    return {"latest": latest, "earlier": earlier}


def on_submission(sender, mod, **kwargs):
    """Reconcile a draft just submitted or revised, if its World says to.
    Connected to `canon.intake.submitted`, so it runs inside the submitting
    request, as its World's Organization. A run that cannot be made keeps
    nothing; the draft's page says it is not reconciled."""
    if not reconciles_on_submission(mod.world):
        return
    try:
        reconcile(mod, by=None)
    except NotReconciled as refused:
        log.info("The draft %s was not reconciled on submission: %s", mod.pk, refused)


def not_reconciled(world, mod):
    """Whether to tell the plot team that this draft, as it now stands, has
    not been reconciled although its World reconciles drafts on submission,
    and why if that can still be told: None if there is nothing to tell, and
    otherwise a sentence, empty if the reason has passed (the LLM failed)."""
    if not reconciles_on_submission(world) or of(mod).filter(draft=mod.text).exists():
        return None
    if config.reconciliation_llm() is None:
        return OFF
    return spending.tokens_refused(world.organization_id) or ""
