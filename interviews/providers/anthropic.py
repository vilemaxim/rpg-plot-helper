"""The Anthropic adapter: an Interview's turns through the official
`anthropic` SDK, streamed, with adaptive thinking and the config's effort."""

import anthropic

from .base import Ended, Provider, ProviderError, Text, Usage


class AnthropicProvider(Provider):
    default_key_env = "ANTHROPIC_API_KEY"
    efforts = ("low", "medium", "high", "xhigh", "max")

    def __init__(self, api_key, settings, *, client=None):
        super().__init__(api_key, settings)
        # `client` is for tests, which never reach the real API.
        self.client = client or anthropic.Anthropic(api_key=api_key)

    def request(self, system, messages):
        """The arguments one turn is asked for with."""
        arguments = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": system,
            "messages": [{"role": message.role, "content": message.text}
                         for message in messages],
            "thinking": {"type": "adaptive"},
        }
        if self.settings.effort:
            arguments["output_config"] = {"effort": self.settings.effort}
        return arguments

    def stream_turn(self, system, messages):
        try:
            with self.client.messages.stream(**self.request(system, messages)) as stream:
                for text in stream.text_stream:
                    yield Text(text)
                final = stream.get_final_message()
        except anthropic.RateLimitError:
            raise ProviderError("The LLM is busy just now. Try again in a minute.") from None
        except anthropic.APIStatusError as error:
            if error.status_code >= 500:
                raise ProviderError("The LLM's provider had a fault. Try again.") from None
            raise ProviderError(f"The LLM's provider turned the request down: "
                                f"{error.message}") from None
        except anthropic.APIConnectionError:
            raise ProviderError("The LLM's provider could not be reached. "
                                "Try again.") from None
        if final.stop_reason == "refusal":
            raise ProviderError("The LLM declined to answer that. Try putting it another way.")
        usage = Usage(final.usage.input_tokens or 0, final.usage.output_tokens or 0)
        yield Ended(usage, cut_off=final.stop_reason == "max_tokens")
