"""The OpenAI-compatible adapter, against a fake OpenAI-compatible HTTP server
run in the test: the tests never reach a real LLM."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.test import SimpleTestCase

from interviews.config import InterviewSettings
from interviews.providers import ADAPTERS, Ended, Message, ProviderError, Text

SETTINGS = InterviewSettings(kind="new-mod", provider="openrouter", model="some/model",
                             effort="high", max_tokens=32000)


class FakeEndpoint:
    """An OpenAI-compatible chat completions endpoint on localhost. Each POST
    streams `pieces` as server-sent events, then a chunk with `finish_reason`
    and one with the usage; or answers with `status` and an error body. Keeps
    each request's JSON body and headers."""

    def __init__(self, pieces=("Hello",), finish_reason="stop", usage=(120, 7), status=200):
        self.pieces, self.finish_reason, self.usage, self.status = (
            pieces, finish_reason, usage, status)
        self.asked, self.headers = [], []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                endpoint.asked.append((self.path, json.loads(body)))
                endpoint.headers.append({k.lower(): v for k, v in self.headers.items()})
                if endpoint.status != 200:
                    self.send_response(endpoint.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(
                        {"error": {"message": "No such model", "type": "invalid"}}).encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in endpoint.chunks():
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def chunks(self):
        def chunk(choices, usage=None):
            return {"id": "c1", "object": "chat.completion.chunk", "created": 0,
                    "model": "some/model", "choices": choices, "usage": usage}

        for piece in self.pieces:
            yield chunk([{"index": 0, "delta": {"content": piece}, "finish_reason": None}])
        yield chunk([{"index": 0, "delta": {}, "finish_reason": self.finish_reason}])
        if self.usage:
            prompt, completion = self.usage
            yield chunk([], {"prompt_tokens": prompt, "completion_tokens": completion,
                             "total_tokens": prompt + completion})

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01},
                         daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def adapter(endpoint, settings=SETTINGS, key="sk-test"):
    made = ADAPTERS["openai-compatible"](key, settings, base_url=endpoint.base_url)
    made.client.max_retries = 0  # a failure fails at once, not after a backoff
    return made


def turn(endpoint, settings=SETTINGS, key="sk-test"):
    return list(adapter(endpoint, settings, key).stream_turn("SYSTEM",
                                                             [Message("user", "Hello")]))


class OpenAICompatibleAdapter(SimpleTestCase):
    def test_a_turn_streams_its_text_then_the_tokens_it_used(self):
        with FakeEndpoint(pieces=["What is ", "it about?"], usage=(120, 7)) as endpoint:
            events = turn(endpoint)

        self.assertEqual(events[:2], [Text("What is "), Text("it about?")])
        self.assertEqual(len(events), 3)
        self.assertEqual((events[2].usage.input_tokens, events[2].usage.output_tokens),
                         (120, 7))
        self.assertFalse(events[2].cut_off)

    def test_it_asks_the_endpoint_with_the_system_prompt_model_effort_and_usage(self):
        with FakeEndpoint() as endpoint:
            list(adapter(endpoint).stream_turn("SYSTEM", [Message("user", "Hello"),
                                                          Message("assistant", "Hi"),
                                                          Message("user", "A heist")]))

        path, asked = endpoint.asked[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(asked["model"], "some/model")
        self.assertEqual(asked["max_completion_tokens"], 32000)
        self.assertEqual(asked["reasoning_effort"], "high")
        self.assertTrue(asked["stream"])
        self.assertEqual(asked["stream_options"], {"include_usage": True})
        self.assertEqual([(m["role"], m["content"]) for m in asked["messages"]],
                         [("system", "SYSTEM"), ("user", "Hello"), ("assistant", "Hi"),
                          ("user", "A heist")])
        self.assertEqual(endpoint.headers[0]["authorization"], "Bearer sk-test")

    def test_no_effort_configured_sends_no_reasoning_effort(self):
        settings = InterviewSettings(kind="new-mod", provider="openrouter", model="m")
        with FakeEndpoint() as endpoint:
            turn(endpoint, settings)

        self.assertNotIn("reasoning_effort", endpoint.asked[0][1])

    def test_an_endpoint_that_needs_no_key_is_not_sent_the_openai_key(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-openai"}), \
                FakeEndpoint() as endpoint:
            turn(endpoint, key=None)

        self.assertNotIn("sk-real-openai", endpoint.headers[0].get("authorization", ""))

    def test_an_endpoint_that_sends_no_usage_counts_none(self):
        with FakeEndpoint(usage=None) as endpoint:
            events = turn(endpoint)

        self.assertEqual(events[-1].usage.total, 0)

    def test_a_turn_cut_off_at_max_tokens_says_so(self):
        with FakeEndpoint(finish_reason="length") as endpoint:
            events = turn(endpoint)

        self.assertIsInstance(events[-1], Ended)
        self.assertTrue(events[-1].cut_off)

    def test_a_filtered_answer_is_not_a_good_turn(self):
        with FakeEndpoint(finish_reason="content_filter") as endpoint, \
                self.assertRaises(ProviderError):
            turn(endpoint)

    def test_endpoint_failures_become_provider_errors(self):
        for status in (400, 404, 429, 500):
            with self.subTest(status=status), FakeEndpoint(status=status) as endpoint, \
                    self.assertRaises(ProviderError):
                turn(endpoint)

    def test_an_endpoint_that_cannot_be_reached_is_a_provider_error(self):
        with FakeEndpoint() as endpoint:
            pass  # shut down: nothing listens at its address now
        unreachable = adapter(endpoint)
        with self.assertRaises(ProviderError):
            list(unreachable.stream_turn("S", [Message("user", "Hello")]))
