"""The Anthropic adapter, with a stand-in for the SDK's client: the tests
never reach the real API."""

from contextlib import contextmanager
from types import SimpleNamespace

import anthropic
import httpx2
from django.test import SimpleTestCase

from interviews.config import InterviewSettings
from interviews.providers import ADAPTERS, Ended, Message, ProviderError, Text

SETTINGS = InterviewSettings(kind="new-mod", provider="anthropic", model="claude-opus-5-5",
                             effort="high", max_tokens=32000)


class FakeClient:
    """Answers `messages.stream(...)` with `pieces`, then a final message, or
    raises `error`. Keeps what it was asked."""

    def __init__(self, pieces=(), stop_reason="end_turn", error=None):
        self.asked = None
        self.pieces, self.stop_reason, self.error = pieces, stop_reason, error
        self.messages = self

    @contextmanager
    def stream(self, **arguments):
        self.asked = arguments
        if self.error:
            raise self.error
        final = SimpleNamespace(stop_reason=self.stop_reason,
                                usage=SimpleNamespace(input_tokens=120, output_tokens=7))
        yield SimpleNamespace(text_stream=iter(self.pieces), get_final_message=lambda: final)


def adapter(client, settings=SETTINGS):
    return ADAPTERS["anthropic"]("sk-test", settings, client=client)


def status_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    return cls("nope", response=response, body=None)


class AnthropicAdapter(SimpleTestCase):
    def test_a_turn_streams_its_text_then_the_tokens_it_used(self):
        events = list(adapter(FakeClient(["What is ", "it about?"]))
                      .stream_turn("SYSTEM", [Message("user", "Hello")]))

        self.assertEqual(events[:2], [Text("What is "), Text("it about?")])
        self.assertEqual(events[2].usage.total, 127)
        self.assertFalse(events[2].cut_off)

    def test_it_asks_with_the_system_prompt_adaptive_thinking_and_the_configured_effort(self):
        client = FakeClient(["Hi"])

        list(adapter(client).stream_turn("SYSTEM", [Message("user", "Hello"),
                                                    Message("assistant", "Hi"),
                                                    Message("user", "A heist")]))

        self.assertEqual(client.asked["model"], "claude-opus-5-5")
        self.assertEqual(client.asked["max_tokens"], 32000)
        self.assertEqual(client.asked["system"], "SYSTEM")
        self.assertEqual(client.asked["thinking"], {"type": "adaptive"})
        self.assertEqual(client.asked["output_config"], {"effort": "high"})
        self.assertEqual([m["role"] for m in client.asked["messages"]],
                         ["user", "assistant", "user"])
        self.assertEqual(client.asked["messages"][2]["content"], "A heist")

    def test_no_effort_configured_leaves_the_providers_default(self):
        client = FakeClient(["Hi"])
        settings = InterviewSettings(kind="new-mod", provider="anthropic", model="m")

        list(adapter(client, settings).stream_turn("S", [Message("user", "Hello")]))

        self.assertNotIn("output_config", client.asked)

    def test_a_turn_cut_off_at_max_tokens_says_so(self):
        events = list(adapter(FakeClient(["Hi"], stop_reason="max_tokens"))
                      .stream_turn("S", [Message("user", "Hello")]))

        self.assertIsInstance(events[-1], Ended)
        self.assertTrue(events[-1].cut_off)

    def test_a_refusal_is_not_a_good_turn(self):
        with self.assertRaises(ProviderError):
            list(adapter(FakeClient(["I"], stop_reason="refusal"))
                 .stream_turn("S", [Message("user", "Hello")]))

    def test_provider_failures_become_provider_errors(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        for error in (status_error(anthropic.RateLimitError, 429),
                      status_error(anthropic.InternalServerError, 500),
                      status_error(anthropic.BadRequestError, 400),
                      anthropic.APIConnectionError(request=request)):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(ProviderError):
                    list(adapter(FakeClient(error=error))
                         .stream_turn("S", [Message("user", "Hello")]))

    def test_it_takes_the_providers_own_effort_values(self):
        cls = ADAPTERS["anthropic"]
        self.assertTrue(all(cls.check_effort(e) for e in ("low", "medium", "high", "max")))
        self.assertFalse(cls.check_effort("extreme"))
