"""Whether each kind of Interview is on, for pages outside this app (canon's)
to offer it, so that canon never imports Interview code; and what a report
the LLM wrote proposes for `finished`, for the form to file it."""

from django import template

from canon.submitting import said

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
