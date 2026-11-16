"""The OpenAI-compatible adapter: an Interview's turns through the official
`openai` package's Chat Completions API, at any endpoint that speaks it
(OpenAI, OpenRouter, Gemini's compatibility endpoint, a local model), streamed,
with the tokens each turn used.

Its `[providers.<name>]` table says `kind = "openai-compatible"` and the
endpoint's `base_url`. `key_env` is optional, for a local endpoint that needs
no key. `effort` is sent as the endpoint's `reasoning_effort` when given, and
left out otherwise.
"""

import openai

from .base import Ended, Provider, ProviderError, Text, Usage

# Sent in place of a key to an endpoint that needs none. The `openai` package
# would otherwise read OPENAI_API_KEY from the environment and send that to
# whatever endpoint `base_url` names.
NO_KEY = "no-key"


class OpenAICompatibleProvider(Provider):
    default_key_env = ""
    takes_base_url = True
    # `reasoning_effort` as the `openai` package types it. An endpoint may take
    # fewer of these.
    efforts = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

    def __init__(self, api_key, settings, *, base_url, client=None):
        super().__init__(api_key, settings)
        self.base_url = base_url
        # Made at the first turn, so asking whether Interviews are on is cheap.
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = openai.OpenAI(api_key=self.api_key or NO_KEY,
                                         base_url=self.base_url)
        return self._client

    def request(self, system, messages):
        """The arguments one turn is asked for with."""
        arguments = {
            "model": self.settings.model,
            "max_completion_tokens": self.settings.max_tokens,
            "messages": [{"role": "system", "content": system},
                         *({"role": message.role, "content": message.text}
                           for message in messages)],
            "stream": True,
            # Without this the stream carries no token counts.
            "stream_options": {"include_usage": True},
        }
        if self.settings.effort:
            arguments["reasoning_effort"] = self.settings.effort
        return arguments

    def stream_turn(self, system, messages):
        usage, finish_reason = Usage(), None
        try:
            with self.client.chat.completions.create(**self.request(system, messages)) as stream:
                for chunk in stream:
                    if chunk.usage:
                        usage = Usage(chunk.usage.prompt_tokens or 0,
                                      chunk.usage.completion_tokens or 0)
                    for choice in chunk.choices:
                        if choice.delta and choice.delta.content:
                            yield Text(choice.delta.content)
                        finish_reason = choice.finish_reason or finish_reason
        except openai.RateLimitError:
            raise ProviderError("The LLM is busy just now. Try again in a minute.") from None
        except openai.APIStatusError as error:
            if error.status_code >= 500:
                raise ProviderError("The LLM's provider had a fault. Try again.") from None
            raise ProviderError(f"The LLM's provider turned the request down: "
                                f"{error.message}") from None
        except openai.APIConnectionError:
            raise ProviderError("The LLM's provider could not be reached. "
                                "Try again.") from None
        if finish_reason == "content_filter":
            raise ProviderError("The LLM declined to answer that. Try putting it another way.")
        yield Ended(usage, cut_off=finish_reason == "length")
