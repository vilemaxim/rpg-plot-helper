"""Fixing the LLM's file before the person sees it (#45, ADR-0008): a Mod
file, or a report's.

As soon as the LLM gives a file, the app checks it the way the intake
would, saving nothing (`problems`). A file with errors goes back to the LLM
with them, in plotcanon's words (`plotcanon.interview_fix_request`), up to
the Interview's `max_fix_attempts`, without asking the person; they see a note that it is being fixed, and then the file
once it is good, or once the attempts are used up, with its errors. The
errors either of them sees are only what the person may read in the World
(`canon.access.readable_findings`).

So that the person never reads a file that is about to be fixed, the files in
a reply are held back from the page as it streams (`FilesHeldBack`): the file
is shown under the reply, in the form to submit it, once it has been checked.
"""

import re

from canon import access
from canon.submitting import Refused
from organizations import tenancy

FILE_SHOWN_BELOW = "[The file is shown below, once it has been checked.]"


def problems(world, person, check):
    """What is wrong with a file, as the person may read it, or None if the
    intake would take it in as it stands. `check`, called with nothing, checks
    it the way its intake would, saving nothing, and raises
    `canon.submitting.Refused` if it would be refused: a new Mod, a revision
    of a draft or a report. Runs in a transaction of its own, as the person,
    so it can be called while a reply streams."""
    with tenancy.acting_as(person, world.organization):
        try:
            check()
        except Refused as refused:
            said = "\n".join(part for part in (str(refused), refused.errors) if part)
            return access.readable_findings(world, person, said)
    return None


# A line that opens or closes a fenced block, as `conversation.FENCE` reads
# one: three or more backticks or tildes at the start of the line.
FENCE_LINE = re.compile(r"(`{3,}|~{3,})")


class FilesHeldBack:
    """A reply as the person may read it while it streams: everything but
    the Mod files in it, which `conversation.mod_file_in` finds the same way.
    Each file is replaced by a note that it is shown below.

    Text is passed on as it comes, except a line that may open or close a
    fence, which waits until it is whole.
    """

    def __init__(self):
        self.held = ""          # the start of a line not yet passed on
        self.passing = False    # the current line is being passed on as it comes
        self.fence = None       # the fence of the block we are in, if any
        self.hiding = False     # that block is a Mod file
        self.opening = None     # a fence line waiting to see if a file follows

    def feed(self, text):
        """The part of `text` the person may read now."""
        out = []
        for piece in re.split(r"(?<=\n)", text):
            if not piece:
                continue
            if self.passing:
                out.append(self._shown(piece))
                self.passing = not piece.endswith("\n")
                continue
            self.held += piece
            if self.held.endswith("\n"):
                line, self.held = self.held, ""
                out.append(self._line(line))
            elif not self.held.startswith(("`", "~")) and self.opening is None:
                out.append(self._shown(self.held))
                self.held, self.passing = "", True
        return "".join(out)

    def end(self):
        """What is left to show once the reply is over."""
        rest, self.held = self.held, ""
        shown = self._line(rest) if rest else ""
        if self.opening is not None:
            shown, self.opening = self.opening + shown, None
        return shown

    def _shown(self, text):
        return "" if self.hiding else text

    def _line(self, line):
        if self.opening is not None:
            opening, self.opening = self.opening, None
            if line.lstrip("﻿").startswith("---"):
                self.hiding = True
                return FILE_SHOWN_BELOW + "\n"
            return opening + self._line(line)
        fence = FENCE_LINE.match(line)
        if self.fence is not None:
            if fence and fence.group(1).startswith(self.fence) and \
                    not line[len(fence.group(1)):].strip(" \t\n`~"):
                closing = self._shown(line)
                self.fence, self.hiding = None, False
                return closing
            return self._shown(line)
        if fence:
            self.fence = fence.group(1)
            self.opening = line
            return ""
        return line
