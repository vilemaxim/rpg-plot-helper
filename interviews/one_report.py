"""One LLM call that writes one report for the plot team: a Reconciliation
(`reconciling`) or a World review (`world_reviewing`). Not a conversation:
the LLM is sent its instructions and one message, and what it writes is the
report, read by plotcanon into its sections."""

from .providers import Ended, Message, ProviderError, Text


class NotWritten(Exception):
    """No report was kept. `str()` is a sentence for the plot team saying
    why."""


def written(llm, system, asked, spent, failed=NotWritten):
    """The whole of what the LLM writes, told `system` and sent `asked`, its
    tokens given to `spent` whether or not it finishes. Raises `failed`, a
    `NotWritten`, if the provider fails or the LLM writes nothing."""
    pieces, ended = [], None
    try:
        for event in llm.provider.stream_turn(system, [Message("user", asked)]):
            if isinstance(event, Text):
                pieces.append(event.text)
            elif isinstance(event, Ended):
                ended = event
                spent(event.usage)
    except ProviderError as error:
        if error.usage is not None:
            spent(error.usage)
        raise failed(str(error)) from error
    text = "".join(pieces)
    if not text.strip() or ended is None:
        raise failed("The LLM gave no report.")
    return text


def sections_of(read):
    """plotcanon's reading of a report (`read_reconciliation`,
    `read_world_review`) as its sections, to keep: each `{"heading", "text",
    "findings": [{"ids", "text"}]}`."""
    return [{"heading": section.heading, "text": section.text,
             "findings": [{"ids": list(finding.ids), "text": finding.text}
                          for finding in section.findings]}
            for section in read.sections]
