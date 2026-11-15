"""A Mod's Dry Run: one step of walking through its story, without players.

plotcanon reads the story out of the Mod's markdown (ADR-0004, ADR-0007);
nothing here parses it. Where the reader is, and how they got there, is kept
in the page's address as the passages they chose, so a Dry Run records
nothing, and going back a step is the address with the last one dropped.
"""

from urllib.parse import urlencode

import plotcanon

from .presenting import render_markdown

# The name, in a Dry Run page's address, of each passage chosen so far.
TRAIL_PARAMETER = "step"


class NoSuchStep(Exception):
    """The trail asked for is not one a reader can take through the story."""


def address(trail):
    """The address of a step, relative to the Dry Run's own page. The start
    is the page itself."""
    return f"?{urlencode([(TRAIL_PARAMETER, name) for name in trail])}" if trail else "./"


def choices_of(passage, trail):
    """What the reader may pick next, as words and the address each leads to.
    A Contest is not played out: each of its results is a choice."""
    def choice(words, way_on):
        return {"label": words, "url": address([*trail, way_on.passage])}
    return ([choice(f"If players do nothing: {way_out.label}" if way_out.players_do_nothing
                    else way_out.label, way_out)
             for way_out in passage.exits]
            + [choice(f"{contest.label}: {result.label}", result)
               for contest in passage.contests for result in contest.results])


def passage_at_end_of(story, trail):
    """The passage the trail ends at. Each step must be one of the choices of
    the step before, so an address cannot skip ahead. Raises `NoSuchStep` if
    it does, or names no passage."""
    here = story.start
    for name in trail:
        here = story.passage(name) if any(choice.passage == name for choice in here.choices) \
            else None
        if here is None:
            raise NoSuchStep(name)
    return here


def page_for(mod, trail):
    """What a Dry Run page shows at the end of `trail`, the names of the
    passages chosen so far: the step, or why the Mod has no Dry Run, in words
    its Mod Writer can paste to their LLM. Raises `NoSuchStep` for a trail
    that cannot be taken."""
    story = plotcanon.story(mod.body)
    if not story.playable:
        return {"problems": "\n".join(story.problems)}
    here = passage_at_end_of(story, trail)
    return {
        "passage": here,
        "prose": render_markdown(here.prose),
        "choices": choices_of(here, trail),
        "at_start": not trail,
        "back": address(trail[:-1]),
        "gaps": "\n".join(story.gaps) if not trail else "",
    }
