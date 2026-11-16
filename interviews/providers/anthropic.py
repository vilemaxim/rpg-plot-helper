"""The Anthropic adapter: an Interview's turns through the official
`anthropic` SDK, streamed, with adaptive thinking and the config's effort."""

import anthropic

from .base import DECLINED, Ended, Provider, ProviderError, Text, Usage


class AnthropicProvider(Provider):
    default_key_env = "ANTHROPIC_API_KEY"
    efforts = ("low", "medium", "high", "xhigh", "max")
    sdk_errors = (anthropic.RateLimitError, anthropic.APIStatusError,
                  anthropic.APIConnectionError)

    def make_client(self):
        return anthropic.Anthropic(api_key=self.api_key)

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
        with self.failures_as_provider_errors(lambda: _so_far(stream)):
            with self.client.messages.stream(**self.request(system, messages)) as stream:
                for text in stream.text_stream:
                    yield Text(text)
                final = stream.get_final_message()
        usage = _usage(final)
        if final.stop_reason == "refusal":
            raise ProviderError(DECLINED, usage=usage)
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
