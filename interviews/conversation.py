"""An Interview's conversation, and the Mod file in a reply.

The turns are kept in Postgres (`Interview`, #46), so an Interview survives a
reload or a dropped connection. Each page carries a reference to its
Interview in a hidden field, signed for the person and World it was made for,
so it cannot be edited or carried to another person's Interview; the turns
themselves never leave the server.
"""

import re
from datetime import timedelta

from django.core import signing
from django.utils import timezone

from organizations import tenancy

from .models import Interview
from .providers import Message

# An Interview with no activity for this long is deleted (ADR-0008).
IDLE_FOR = timedelta(days=30)


class Tampered(Exception):
    """The transcript sent was not one this app made for this person here,
    or its Interview is gone."""


def _salt(world, person):
    return f"interviews.transcript:{world.pk}:{person.pk}"


def _reference(interview, world, person):
    return signing.dumps(interview.pk, salt=_salt(world, person))


def _messages(interview):
    return [Message(turn["role"], turn["text"]) for turn in interview.turns]


def _interview(transcript, world, person, mod=None):
    """The Interview a page's transcript names, about `mod` if it revises
    one. Raises `Tampered`."""
    try:
        pk = signing.loads(transcript, salt=_salt(world, person))
    except signing.BadSignature:
        raise Tampered from None
    interview = Interview.objects.filter(pk=pk, world=world, person=person, mod=mod).first()
    if interview is None:
        raise Tampered
    return interview


def forget_idle():
    """Delete the Interviews with no activity for `IDLE_FOR`. Row-level
    security limits this to the current Organization's. There is no
    background worker (ADR-0003), so every Interview request does it."""
    Interview.objects.filter(active_at__lte=timezone.now() - IDLE_FOR).delete()


def in_progress(world, person, kind, mod=None):
    """The person's latest Interview of this kind in this World (about `mod`,
    for a revise Interview), as the transcript for its page and its turns, or
    `("", [])` if there is none."""
    interview = (Interview.objects.filter(world=world, person=person, kind=kind, mod=mod)
                 .order_by("-active_at", "-pk").first())
    if interview is None:
        return "", []
    return _reference(interview, world, person), _messages(interview)


def sealed(messages, world, person, kind, transcript="", mod=None):
    """Keep the turns in the Interview the transcript names, or in a new one
    if it names none, and return the transcript for the page to send back
    with the next answer. Turns that are already kept are not written again,
    and no Interview is made for no turns.

    Runs after the request's transaction has ended (from the stream), so it
    opens its own, as the person in the World's Organization."""
    with tenancy.acting_as(person, world.organization_id):
        interview = _interview(transcript, world, person, mod) if transcript else None
        if interview is None and not messages:
            return ""
        if interview is None:
            interview = Interview(organization_id=world.organization_id, world=world,
                                  person=person, kind=kind, mod=mod)
        if interview.pk is None or _messages(interview) != list(messages):
            interview.turns = [{"role": m.role, "text": m.text} for m in messages]
            interview.save()
        return transcript or _reference(interview, world, person)


def begin_from_walk(walk, world, person, kind, mod, event="", group=""):
    """Start a report Interview on `mod` from the Path the person walked
    (`walk`, the JSON `Interview.walk` holds, or None before the walk), and
    the Event and Group it is for, if they were asked, with no turns yet, in
    place of any other of theirs on it. Returns the transcript for its
    page."""
    Interview.objects.filter(world=world, person=person, kind=kind, mod=mod).delete()
    interview = Interview.objects.create(organization_id=world.organization_id, world=world,
                                         person=person, kind=kind, mod=mod, walk=walk,
                                         event=event, group=group)
    return _reference(interview, world, person)


def interview_named(transcript, world, person, mod=None):
    """The Interview a page's transcript names, for what is kept with it
    besides its turns (its walk, Event and Group), or None for no
    transcript. Raises `Tampered`."""
    return _interview(transcript, world, person, mod) if transcript else None


def opened(transcript, world, person, mod=None):
    """The turns of the Interview a page's transcript names, as `Message`s.
    An empty transcript is a new Interview. Raises `Tampered`."""
    if not transcript:
        return []
    return _messages(_interview(transcript, world, person, mod))


def forget(transcript, world, person, mod=None):
    """Delete the Interview a page's transcript names, if it is still there."""
    try:
        _interview(transcript, world, person, mod).delete()
    except Tampered:
        pass


# A fenced block: an opening fence of three or more backticks or tildes, an
# optional info string, the contents, and a closing fence of the same kind at
# least as long.
FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})[^\n`]*\n(?P<body>.*?)^(?P=fence)[`~]*[ \t]*$",
                   re.S | re.M)


def mod_file_in(reply):
    """The Mod file the LLM gave in this reply, or None. On the web surface
    plotcanon tells it to give the whole file in one code block, starting at
    the frontmatter's `---`; the last such block is the file."""
    files = [match.group("body") for match in FENCE.finditer(reply)
             if match.group("body").lstrip("﻿").startswith("---")]
    return files[-1] if files else None
