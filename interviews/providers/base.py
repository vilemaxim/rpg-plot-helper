"""The provider adapter interface: the one thing an Interview talks to.

An Interview never calls an LLM provider's SDK itself (ADR-0008). It hands a
`Provider` the system prompt and the conversation so far, and reads back one
assistant turn as it streams: `Text` pieces, then one `Ended` with the tokens
the turn used. Each provider has its own adapter, a subclass of `Provider`
registered in `interviews.providers.ADAPTERS`; the Anthropic one is in
`anthropic.py`, and an OpenAI-compatible one goes beside it without any change
to Interview code.

An adapter also says which `effort` values it accepts, so that a config
naming another stops the app at startup instead of failing at the first turn.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Iterator, Literal, Sequence


@dataclass(frozen=True)
class Message:
    """One turn of the conversation: the person's (`user`) or the LLM's
    (`assistant`), as plain text."""

    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class Usage:
    """The tokens one turn used, as the provider counted them."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self):
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Text:
    """A piece of the assistant's reply, in the order it was written."""

    text: str


@dataclass(frozen=True)
class Ended:
    """The turn is over. `cut_off` says it stopped at `max_tokens` before the
    LLM had finished."""

    usage: Usage
    cut_off: bool = False


class ProviderError(Exception):
    """The provider could not give a whole turn: it refused, failed or could
    not be reached. `str()` is a sentence for the person in the Interview;
    whatever was streamed before it is not a good turn."""


class Provider(ABC):
    """An LLM provider, as an Interview sees it.

    Made with the deployment's key for the provider and the Interview's
    settings from the config (`interviews.config.InterviewSettings`: model,
    effort, max_tokens).
    """

    #: The environment variable the key is read from when the config's
    #: `[providers.<name>]` table does not say.
    default_key_env: ClassVar[str] = ""
    #: The `effort` values this provider accepts. Empty: it takes none.
    efforts: ClassVar[tuple[str, ...]] = ()

    def __init__(self, api_key, settings):
        self.api_key = api_key
        self.settings = settings

    @classmethod
    def check_effort(cls, effort):
        """Whether `effort` is one this provider accepts. None, for none
        given, always is."""
        return effort is None or effort in cls.efforts

    @abstractmethod
    def stream_turn(self, system: str, messages: Sequence[Message]) -> Iterator[Text | Ended]:
        """Stream one assistant turn: `Text` pieces as they arrive, then
        exactly one `Ended`. `messages` starts with the person's and ends with
        the person's. Raises `ProviderError` if no whole turn can be had."""
