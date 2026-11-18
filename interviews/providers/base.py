"""The provider adapter interface: the one thing an Interview talks to.

An Interview never calls an LLM provider's SDK itself (ADR-0008). It hands a
`Provider` the system prompt and the conversation so far, and reads back the
LLM's next turn as it streams: `Text` pieces, then one `Ended` with the tokens
the turn used. Each provider has its own adapter, a subclass of `Provider`
registered in `interviews.providers.ADAPTERS`, in its own file
(`anthropic.py`, `openai_compatible.py`); another goes beside them without
any change to Interview code. An adapter names its SDK's client and
exceptions, and `Provider` makes the client and turns those exceptions into
`ProviderError`s.

An adapter also says which `effort` values it accepts, so that a config
naming another stops the app at startup instead of failing at the first turn.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Iterator, Literal, Sequence


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
    """A piece of the LLM's reply, in the order it was written."""

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
    whatever was streamed before it is not a good turn. `usage` is the tokens
    the provider reported for the call before it failed, if any: they are
    spent all the same."""

    def __init__(self, message, *, usage=None):
        super().__init__(message)
        self.usage = usage


# What the person reads when a provider fails, whichever it is.
BUSY = "The LLM is busy just now. Try again in a minute."
FAULT = "The LLM's provider had a fault. Try again."
TURNED_DOWN = "The LLM's provider turned the request down: {}"
UNREACHABLE = "The LLM's provider could not be reached. Try again."
DECLINED = "The LLM declined to answer that. Try putting it another way."


class Provider(ABC):
    """An LLM provider, as an Interview sees it.

    Made with the deployment's key for the provider and the settings from
    the config (`interviews.config.InterviewSettings` or
    `ReconciliationSettings`: model, effort, max_tokens).
    """

    #: The environment variable the key is read from when the config's
    #: `[providers.<name>]` table does not say.
    default_key_env: ClassVar[str] = ""
    #: Whether its `[providers.<name>]` table must give a `base_url`, which
    #: the adapter is then made with as a keyword argument.
    takes_base_url: ClassVar[bool] = False
    #: The `effort` values this provider accepts. Empty: it takes none.
    efforts: ClassVar[tuple[str, ...]] = ()
    #: The SDK's exceptions for being rate limited, for any other answer
    #: with an HTTP status (with `status_code` and `message`), and for not
    #: reaching the provider at all, which `failures_as_provider_errors`
    #: turns into `ProviderError`s.
    sdk_errors: ClassVar[tuple[type[Exception], type[Exception], type[Exception]] | None] = None

    def __init__(self, api_key, settings, *, client=None):
        self.api_key = api_key
        self.settings = settings
        # `client` is for tests, which never reach a real provider. Otherwise
        # it is made at the first turn, so asking whether Interviews are on is
        # cheap.
        self._client = client

    @property
    def client(self) -> Any:
        """The provider SDK's client, made with the key at first use."""
        if self._client is None:
            self._client = self.make_client()
        return self._client

    def make_client(self) -> Any:
        """Make the provider SDK's client. An adapter that uses one says how."""
        raise NotImplementedError

    @contextmanager
    def failures_as_provider_errors(self, usage: Callable[[], Usage | None] = lambda: None):
        """Turn the SDK's failures in the block into `ProviderError`s, each
        carrying the tokens `usage()` says the call had reported."""
        if self.sdk_errors is None:
            yield
            return
        rate_limited, status_error, unreachable = self.sdk_errors
        try:
            yield
        except rate_limited:
            raise ProviderError(BUSY, usage=usage()) from None
        except status_error as error:
            if error.status_code >= 500:
                raise ProviderError(FAULT, usage=usage()) from None
            raise ProviderError(TURNED_DOWN.format(error.message), usage=usage()) from None
        except unreachable:
            raise ProviderError(UNREACHABLE, usage=usage()) from None

    @classmethod
    def check_effort(cls, effort):
        """Whether `effort` is one this provider accepts. None, for none
        given, always is."""
        return effort is None or effort in cls.efforts

    @abstractmethod
    def stream_turn(self, system: str, messages: Sequence[Message]) -> Iterator[Text | Ended]:
        """Stream the LLM's next turn: `Text` pieces as they arrive, then
        exactly one `Ended`. `messages` starts with the person's and ends with
        the person's. Raises `ProviderError` if no whole turn can be had."""
