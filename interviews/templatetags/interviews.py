"""Whether each kind of Interview is on, for pages outside this app (canon's)
to offer it, so that canon never imports Interview code; a Mod's
Reconciliations and the Reconcile button, for the plot team on its page; and
what a report the LLM wrote proposes for `finished`, for the form to file
it."""

from django import template

from canon.submitting import said

from .. import config, reconciling
from ..config import Kind, is_on

register = template.Library()


@register.simple_tag
def new_mod_interviews_on():
    """Whether a new Mod can be written in an Interview."""
    return is_on(Kind.NEW_MOD)


@register.simple_tag
def revise_interviews_on():
    """Whether a draft can be revised in an Interview."""
    return is_on(Kind.REVISE_MOD)


@register.simple_tag
def report_interviews_on():
    """Whether an After-Action Report can be written in an Interview."""
    return is_on(Kind.REPORT)


@register.filter
def finished_in(report):
    """What a report file gives for `finished`, as written ("true",
    "false"), or None."""
    return said(report, "finished")


@register.inclusion_tag("interviews/reconciliations_on_mod.html", takes_context=True)
def reconciliations(context, mod, is_draft):
    """A Mod's Reconciliations, the latest in full and the earlier ones
    listed, a note when another draft's latest Reconciliation says it may
    conflict with this one, the Reconcile button on a draft when
    Reconciliation is on, and whether a draft its World reconciles on
    submission is not reconciled.
    The page shows it to its World's Plot Masters only."""
    return {"csrf_token": context.get("csrf_token"), "world": mod.world, "mod": mod,
            "may_reconcile": is_draft and config.reconciliation_llm() is not None,
            "not_reconciled": reconciling.not_reconciled(mod) if is_draft else None,
            **reconciling.shown_on(mod)}
