"""A Mod's Dry Run: one step of walking through its story, without players.

plotcanon reads the story out of the Mod's markdown (ADR-0004, ADR-0007);
nothing here parses it. Where the reader is, and how they got there, is kept
in the page's address as the passages they chose, so a Dry Run records
nothing, and going back a step is the address with the last one dropped.
"""

from urllib.parse import urlencode

import plotcanon
from django.http import Http404

from .presenting import render_markdown

STEP = "step"


def address(trail):
    """The address of a step, relative to the Dry Run's own page. The start
    is the page itself."""
    return f"?{urlencode([(STEP, name) for name in trail])}" if trail else "./"


def choices_of(passage, trail):
    """What the reader may pick next, as words and the address each leads to.
    A Contest is not played out: each of its results is a choice."""
    def choice(words, exit):
        return {"label": words, "url": address([*trail, exit.passage])}
    return ([choice(f"If players do nothing: {exit.label}" if exit.players_do_nothing
                    else exit.label, exit)
             for exit in passage.exits]
            + [choice(f"{contest.label}: {result.label}", result)
               for contest in passage.contests for result in contest.results])


def walked(story, trail):
    """The passage the trail ends at. Each step must be one of the choices of
    the step before, or there is no such page: an address cannot skip ahead."""
    here = story.start
    for name in trail:
        here = story.passage(name) if any(choice.passage == name for choice in here.choices) \
            else None
        if here is None:
            raise Http404("No such step")
    return here


def step(mod, request):
    """What a Dry Run page shows for the address asked for: the step, or why
    the Mod has no Dry Run, in words its Mod Writer can paste to their LLM."""
    story = plotcanon.story(mod.body)
    if not story.playable:
        return {"problems": "\n".join(story.problems)}
    trail = request.GET.getlist(STEP)
    here = walked(story, trail)
    return {
        "passage": here,
        "prose": render_markdown(here.prose),
        "choices": choices_of(here, trail),
        "at_start": not trail,
        "back": address(trail[:-1]),
        "gaps": "\n".join(story.gaps) if not trail else "",
    }
