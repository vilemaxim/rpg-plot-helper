"""Walking the Path a Stretch took through a Mod's Dry Run, for a report
Interview (#43), with no LLM.

The Mod Runner starts at a Hook, or where the last report's Path stopped, and
picks a way on at each passage: an exit, or a Contest's result. Where they
are is kept in the page's address, as where they started and the choices
taken, each by its place among the passage's choices, so going back a step is
the address with the last one dropped and nothing is kept until they say
where play stopped. plotcanon turns the choices into the report's `path`
steps (`plotcanon.path_steps`), by the same rules it checks a report's `path`
by, so the walk and the checks agree.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import plotcanon

from canon.dry_runs import labelled

# The names, in a walk's address, of where it starts and of each choice.
FROM, CHOICE = "from", "choice"
# `from` this, the walk starts at the Premise, to take a Hook.
HOOK = "hook"


class NoSuchWalk(Exception):
    """The address names a walk that cannot be taken through the story."""


@dataclass(frozen=True)
class Walked:
    """A Path walked, as a report Interview keeps it (`Interview.walk`): its
    `path`, the steps plotcanon wrote for the report's `path`, and where play
    had stopped on the Mod before it (`last_stop`): `among` several stops
    when Groups come back together (#67)."""

    path: tuple
    last_stop: plotcanon.LastStop

    def to_json(self):
        return {"path": list(self.path),
                "last_stop": {"passage": self.last_stop.passage,
                              "known": self.last_stop.known,
                              "among": list(self.last_stop.among)}}

    @classmethod
    def from_json(cls, kept):
        """The Path kept as `to_json` wrote it, or None for none."""
        if kept is None:
            return None
        return cls(tuple(kept["path"]), plotcanon.LastStop(**kept["last_stop"]))


@dataclass(frozen=True)
class Walk:
    """A walk so far: where it `starts` (a scene's name, or None for the
    Premise), `start_given` as the address gives it ("" for the default),
    the `choices` taken, each by its place among its passage's, the passage
    it has reached (`here`), and the `steps` of the Path it makes."""

    stop: plotcanon.LastStop
    starts: str | None
    start_given: str
    choices: tuple[int, ...]
    here: plotcanon.Passage
    steps: tuple

    def address(self, choices=None, start=None):
        """The address of a walk, relative to the walk's page: this one, or
        one with other `choices` or another `start` ("hook", a scene, or ""
        for the default)."""
        start = self.start_given if start is None else start
        choices = self.choices if choices is None else choices
        pairs = ([(FROM, start)] if start else []) + [(CHOICE, str(c)) for c in choices]
        return f"?{urlencode(pairs)}" if pairs else "./"

    @property
    def at_start(self):
        return not self.choices

    @property
    def stoppable(self):
        """Whether play can be said to have stopped here: at a scene or an
        ending, not the Premise."""
        return not self.at_premise

    def ways_on(self):
        """What may be picked next, as words and the address each leads to."""
        return [{"label": words, "url": self.address([*self.choices, i])}
                for i, (words, _) in enumerate(labelled(self.here))]

    def back(self):
        return self.address(self.choices[:-1])

    @property
    def at_premise(self):
        return self.here.kind == "start"

    def from_a_hook(self):
        """The address to start from a Hook instead, when the walk has just
        picked up at a scene; otherwise None."""
        if not self.stop.takes_a_hook:
            return None  # Groups coming back together go on from where one stopped
        return self.address((), HOOK) if self.starts is not None and self.at_start else None

    def from_the_stop(self):
        """The address to pick up where the last report's Path stopped
        instead, when the walk is at the Hooks and there is such a place;
        otherwise None."""
        if self.starts is None and self.at_start and default_start(self.stop):
            return self.address((), "")
        return None

    def other_stops(self):
        """Where else the walk may pick up, as names and addresses, when it
        has just picked up where one of several Groups stopped: where each
        other Group that had not finished stopped."""
        if not self.at_start or self.starts is None:
            return []
        return [{"label": passage, "url": self.address((), passage)}
                for passage in self.stop.among if passage != self.here.name]

    def walked(self):
        """The Path, for a report Interview to start from."""
        return Walked(self.steps, self.stop)


def default_start(stop):
    """Where a walk starts unless the Mod Runner says otherwise: where the
    last report's Path stopped, the first of the stops of the Groups coming
    back together, or a Hook."""
    return stop.passages[0] if stop.known and stop.passages else None


def walk_from(story, stop, query):
    """The walk an address names, from its `from` and `choice` values in
    `query` (a `QueryDict`). Raises `NoSuchWalk` for one that cannot be
    taken."""
    given = query.get(FROM, "")
    if given == HOOK:
        starts = None
    elif given:
        starts = given
    else:
        starts = default_start(stop)
    try:
        picked = tuple(int(c) for c in query.getlist(CHOICE))
    except ValueError:
        raise NoSuchWalk from None
    here = story.start if starts is None else story.passage(starts)
    if here is None or (starts is not None and here.kind == "start"):
        raise NoSuchWalk
    taken = []
    for i in picked:
        ways = labelled(here)
        if not 0 <= i < len(ways):
            raise NoSuchWalk
        taken.append(ways[i][1])
        here = story.passage(ways[i][1].passage) if ways[i][1].passage else None
        if here is None:
            raise NoSuchWalk
    try:
        steps = plotcanon.path_steps(story, taken, continues_from=stop, start=starts)
    except ValueError:
        raise NoSuchWalk from None
    return Walk(stop, starts, given, picked, here, tuple(steps))


def scenes_to_pick_up_at(story, stop):
    """The scenes a walk may start at instead of a Hook, when where the last
    report's Path stopped is not known, as names and addresses."""
    if stop.known:
        return []
    return [{"label": p.name, "url": f"?{urlencode([(FROM, p.name)])}"}
            for p in story.passages if p.kind == "scene"]
