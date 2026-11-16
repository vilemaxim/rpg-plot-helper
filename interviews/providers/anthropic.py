"""The Anthropic adapter: an Interview's turns through the official
`anthropic` SDK, streamed, with adaptive thinking and the config's effort."""

import anthropic

from .base import Ended, Provider, ProviderError, Text, Usage


class AnthropicProvider(Provider):
    default_key_env = "ANTHROPIC_API_KEY"
    efforts = ("low", "medium", "high", "xhigh", "max")

    def __init__(self, api_key, settings, *, client=None):
        super().__init__(api_key, settings)
        # `client` is for tests, which never reach the real API. Otherwise it
        # is made at the first turn, so asking whether Interviews are on is
        # cheap.
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def request(self, system, messages):
        """The arguments one turn is asked for with."""
        arguments = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": system,
            "messages": [{"role": message.role, "content": message.text}
                         for message in messages],
            "thinking": {"type": "adaptive"},
            # The instructions and the World are sent again with every turn;
            # caching the conversation so far makes each later turn cheaper.
            "cache_control": {"type": "ephemeral"},
        }
        if self.settings.effort:
            arguments["output_config"] = {"effort": self.settings.effort}
        return arguments

    def stream_turn(self, system, messages):
        stream = None
        try:
            with self.client.messages.stream(**self.request(system, messages)) as stream:
                for text in stream.text_stream:
                    yield Text(text)
                final = stream.get_final_message()
        except anthropic.RateLimitError:
            raise ProviderError("The LLM is busy just now. Try again in a minute.",
                                usage=_so_far(stream)) from None
        except anthropic.APIStatusError as error:
            if error.status_code >= 500:
                raise ProviderError("The LLM's provider had a fault. Try again.",
                                    usage=_so_far(stream)) from None
            raise ProviderError(f"The LLM's provider turned the request down: "
                                f"{error.message}", usage=_so_far(stream)) from None
        except anthropic.APIConnectionError:
            raise ProviderError("The LLM's provider could not be reached. "
                                "Try again.", usage=_so_far(stream)) from None
        usage = _usage(final)
        if final.stop_reason == "refusal":
            raise ProviderError("The LLM declined to answer that. Try putting it another way.",
                                usage=usage)
        yield Ended(usage, cut_off=final.stop_reason == "max_tokens")


def _usage(message):
    return Usage(message.usage.input_tokens or 0, message.usage.output_tokens or 0)


def _so_far(stream):
    """The tokens a stream that failed had reported, or None if it had not
    started."""
    if stream is None:
        return None
    try:
        return _usage(stream.current_message_snapshot)
    except AssertionError:  # no message started yet
        return None
