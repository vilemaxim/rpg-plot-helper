"""An Interview's conversation, and the Mod file in a reply.

For now a conversation lives only as long as the page (#44): each page carries
the turns so far in a hidden field, signed for the person and World it was
made for, so it cannot be edited or carried to another person's Interview.
Keeping it in Postgres instead (the transcripts slice) replaces `sealed` and
`opened`; nothing else needs to know where the turns are kept.
"""

import re

from django.core import signing

from .providers import Message


class Tampered(Exception):
    """The transcript sent was not one this app made for this person here."""


def _salt(world, person):
    return f"interviews.transcript:{world.pk}:{person.pk}"


def sealed(messages, world, person):
    """The turns as text for the page to send back with the next answer."""
    return signing.dumps([[m.role, m.text] for m in messages], salt=_salt(world, person),
                         compress=True)


def opened(transcript, world, person):
    """The turns a page sent back, as `Message`s. An empty transcript is a
    new Interview. Raises `Tampered`."""
    if not transcript:
        return []
    try:
        turns = signing.loads(transcript, salt=_salt(world, person))
    except signing.BadSignature:
        raise Tampered from None
    return [Message(role, text) for role, text in turns]


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
