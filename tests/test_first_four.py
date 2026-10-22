from __future__ import annotations

import asyncio
import contextlib
import io
import os
import runpy
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx
from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)
from agent_framework.observability import ChatTelemetryLayer, enable_instrumentation
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import _workshop

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ENV = {
    "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid/api/projects/test",
    "FOUNDRY_MODEL": "test-model",
    "PORTAL_AGENT_NAME": "test-agent",
    "PORTAL_AGENT_VERSION": "1",
    "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=00000000-0000-0000-0000-000000000000",
    "APPLICATIONINSIGHTS_SUBSCRIPTION_ID": "test-subscription",
    "APPLICATIONINSIGHTS_RESOURCE_GROUP": "test-group",
    "APPLICATIONINSIGHTS_RESOURCE_NAME": "test-insights",
    "LOOKBACK_MINUTES": "10",
    "OBSERVABILITY_SCENARIO": "",
    "OBSERVABILITY_TRACE_ID": "",
    "ENABLE_SENSITIVE_DATA": "false",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def load_sample(relative: str) -> dict:
    with patch.dict(os.environ, SAMPLE_ENV):
        with patch.object(sys, "path", [str(ROOT / "02-mcp-tool-agent"), *sys.path]):
            return runpy.run_path(str(ROOT / relative), run_name="test_sample")


def table(columns: list[str], rows: list[list]) -> dict:
    return {"tables": [{"columns": [{"name": name} for name in columns], "rows": rows}]}


def with_merge_mode(value, mode):
    """Model optional snapshot fields independently of the installed SDK."""
    setattr(value, "merge_mode", mode)
    return value


class ScriptedClient(FunctionInvocationLayer, ChatMiddlewareLayer, ChatTelemetryLayer, BaseChatClient):
    def __init__(self, *, tool: bool = False) -> None:
        super().__init__(middleware=[])
        self.tool = tool
        self.requests = 0
        self.tool_results: list[Content] = []

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.requests += 1
        results = [
            content for message in messages for content in message.contents
            if content.type == "function_result"
        ]
        if self.tool and not results:
            contents = [Content.from_function_call("time-call", "get_time", arguments="{}")]
            finish = "tool_calls"
        else:
            self.tool_results.extend(results)
            text = str(results[-1].result) if results else "Earth 9.81. Mars 3.71."
            contents = [Content.from_text(text)]
            finish = "stop"
        response = ChatResponse(
            messages=[Message("assistant", contents)],
            model="test-model",
            response_id=f"response-{self.requests}",
            finish_reason=finish,
            usage_details={"input_token_count": 11, "output_token_count": 7},
        )
        if not stream:
            async def complete():
                return response
            return complete()

        async def updates():
            content = contents[0]
            if content.type == "text":
                assert content.text is not None
                for text in (content.text[:5], content.text[5:]):
                    yield ChatResponseUpdate(
                        role="assistant",
                        message_id=f"message-{self.requests}",
                        contents=[Content.from_text(text)],
                    )
            else:
                yield ChatResponseUpdate(role="assistant", contents=contents, finish_reason=finish)

        return ResponseStream(updates(), finalizer=lambda updates: response)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def render(self, updates: list[AgentResponseUpdate], **kwargs) -> str:
        async def source():
            for update in updates:
                yield update
        output = io.StringIO()
        stream = ResponseStream(source(), finalizer=AgentResponse.from_updates)
        with contextlib.redirect_stdout(output):
            await _workshop.print_stream(stream, **kwargs)
        return output.getvalue()

    async def test_replacement_extends_text_without_repeating_it(self):
        updates = [
            AgentResponseUpdate(message_id="one", contents=[Content.from_text("Hello")]),
            AgentResponseUpdate(message_id="one", contents=[with_merge_mode(Content.from_text("Hello world"), "replace")]),
            AgentResponseUpdate(message_id="one", contents=[with_merge_mode(Content.from_text("Hello world"), "replace")]),
        ]
        self.assertEqual(await self.render(updates), "Hello world")

    async def test_equal_text_in_distinct_provider_parts_is_not_deduplicated(self):
        updates = []
        for item_id, part in (("one", 0), ("one", 1), ("two", 0)):
            for mode in ("append", "replace"):
                updates.append(AgentResponseUpdate(contents=[
                    with_merge_mode(
                        Content.from_text(
                            "same",
                            raw_representation=SimpleNamespace(item_id=item_id, content_index=part),
                        ),
                        mode,
                    ),
                ]))
        self.assertEqual(await self.render(updates), "samesamesame")

    async def test_final_only_and_revised_snapshots_are_displayed(self):
        output = await self.render([
            AgentResponseUpdate(message_id="one", contents=[Content.from_text("old")]),
            with_merge_mode(AgentResponseUpdate(message_id="one", contents=[Content.from_text("correct")]), "replace"),
            AgentResponseUpdate(message_id="two", contents=[with_merge_mode(Content.from_text("final"), "replace")]),
        ])
        self.assertEqual(output, "old\n[updated response]\ncorrectfinal")

    async def test_tool_snapshots_and_results_are_displayed_once(self):
        updates = [
            AgentResponseUpdate(contents=[
                Content.from_function_call("call", "get_time", arguments="{")
            ]),
            AgentResponseUpdate(contents=[
                with_merge_mode(Content.from_function_call("call", "get_time", arguments="{}"), "replace")
            ]),
            AgentResponseUpdate(contents=[Content.from_function_result("call", result="UTC result")]),
            AgentResponseUpdate(contents=[Content.from_function_result("call", result="UTC result")]),
        ]
        output = await self.render(updates, show_tools=True, agent_name="time-agent")
        self.assertEqual(output.count("[tool call] get_time({})"), 1)
        self.assertEqual(output.count("[tool result] UTC result"), 1)

    async def test_real_basic_and_function_entry_points_with_current_sdk(self):
        for relative, tool in (
            ("01-basic-agent/01-basic-agent.py", False),
            ("03-custom-function-tool-agent/03-custom-function-tool-agent.py", True),
        ):
            with self.subTest(sample=relative):
                sample = load_sample(relative)
                client = ScriptedClient(tool=tool)
                output = io.StringIO()
                with patch.dict(sample["main"].__globals__, {"FoundryChatClient": lambda **kwargs: client}):
                    with contextlib.redirect_stdout(output):
                        await sample["main"]()
                if tool:
                    self.assertEqual(len(client.tool_results), 1)
                    self.assertEqual(output.getvalue().count("[tool call] get_time"), 1)
                    self.assertEqual(output.getvalue().count("[tool result]"), 1)
                else:
                    self.assertEqual(output.getvalue().count("Earth 9.81. Mars 3.71."), 1)


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.sample = load_sample("02-mcp-tool-agent/02c-hybrid-agent.py")
        self.project = SimpleNamespace(agents=Mock())
        self.project.agents.create_version.return_value = SimpleNamespace(version="2")

    def existing(self, definition):
        self.project.agents.get.return_value = SimpleNamespace(
            versions=SimpleNamespace(latest=SimpleNamespace(version="1", definition=definition))
        )

    def ensure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.sample["ensure_agent"](self.project)

    def test_unchanged_definition_reuses_version(self):
        self.existing(deepcopy(self.sample["AGENT_DEFINITION"]))
        self.assertEqual(self.ensure(), "1")
        self.project.agents.create_version.assert_not_called()

    def test_changed_definition_publishes_version(self):
        previous = deepcopy(self.sample["AGENT_DEFINITION"])
        previous.instructions = "Previous instructions"
        self.existing(previous)
        self.assertEqual(self.ensure(), "2")
        self.project.agents.create_version.assert_called_once_with(
            agent_name=self.sample["AGENT_NAME"], definition=self.sample["AGENT_DEFINITION"]
        )

    def test_missing_agent_creates_version(self):
        self.project.agents.get.side_effect = ResourceNotFoundError("Missing")
        self.assertEqual(self.ensure(), "2")
        self.project.agents.create_version.assert_called_once()

    def test_other_http_errors_never_create_agents(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                error = HttpResponseError("Request failed")
                error.status_code = status
                self.project.agents.get.side_effect = error
                with self.assertRaises(HttpResponseError):
                    self.ensure()
                self.project.agents.create_version.assert_not_called()


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.exporter = InMemorySpanExporter()
        cls.provider = TracerProvider()
        cls.provider.add_span_processor(SimpleSpanProcessor(cls.exporter))
        trace.set_tracer_provider(cls.provider)

    async def test_sensitive_capture_respects_false_and_true(self):
        for enabled in ("false", "true"):
            with self.subTest(enabled=enabled):
                self.exporter.clear()
                with patch.dict(os.environ, {"ENABLE_SENSITIVE_DATA": enabled}):
                    with patch("azure.monitor.opentelemetry.configure_azure_monitor"):
                        with patch.object(_workshop, "_tracing_provider", None):
                            _workshop.configure_tracing("unused-in-test", "test")
                            client = ScriptedClient()
                            await client.get_response([Message("user", [Content.from_text("test prompt")])])
                captured = any(
                    span.attributes.get("gen_ai.input.messages")
                    for span in self.exporter.get_finished_spans()
                )
                self.assertEqual(captured, enabled == "true")

    async def test_tracing_sample_emits_correlated_root_agent_and_model_spans(self):
        self.exporter.clear()
        sample = load_sample("04-tracing-agent/04-tracing-agent.py")
        client = ScriptedClient()
        output = io.StringIO()
        with patch.dict(os.environ, {"ENABLE_SENSITIVE_DATA": "false"}):
            enable_instrumentation()
            with patch.dict(sample["main"].__globals__, {
                "FoundryChatClient": lambda **kwargs: client,
                "configure_tracing": Mock(),
            }):
                with contextlib.redirect_stdout(output):
                    await sample["main"]()
        spans = self.exporter.get_finished_spans()
        self.assertIn("example-tracing", {span.name for span in spans})
        self.assertTrue(any(span.name.startswith("invoke_agent") for span in spans))
        self.assertTrue(any(span.name.startswith("chat") for span in spans))
        self.assertEqual(len({span.context.trace_id for span in spans}), 1)
        self.assertEqual(output.getvalue().count("Earth 9.81. Mars 3.71."), 1)

    async def test_flush_timeout_is_reported_and_provider_is_closed(self):
        provider = Mock()
        provider.force_flush.return_value = False
        with patch.object(_workshop, "_tracing_provider", provider):
            with self.assertRaisesRegex(RuntimeError, "Timed out"):
                _workshop.shutdown_tracing()
        provider.shutdown.assert_called_once()


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = load_sample("02-mcp-tool-agent/verify_observability.py")

    def run_verifier(self, *, success=True, empty=False, missing_root=False, query_error=False):
        trace_id = "a" * 32

        def handle(request):
            if request.url.host == "management.azure.com":
                return httpx.Response(200, json={"properties": {"AppId": "test-app"}})
            query = request.url.params["query"]
            if "project operation_Id, success, scenario=" in query:
                rows = [] if empty else [[trace_id, success, "foundry-workshop.tracing"]]
                data = table(["operation_Id", "success", "scenario"], rows)
            elif "tool=tostring" in query:
                data = table(["name"], [] if missing_root else [["example-tracing"]])
            elif query_error:
                return httpx.Response(500, json={"error": {"message": "Query failed"}})
            else:
                data = table(["value"], [[1]])
            return httpx.Response(200, json=data)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        credential = MagicMock()
        credential.__enter__.return_value = credential
        credential.get_token.return_value = SimpleNamespace(token="offline-test-token")
        with patch.dict(os.environ, SAMPLE_ENV):
            with patch.dict(self.verifier["main"].__globals__, {"AzureCliCredential": lambda: credential}):
                with patch("httpx.Client", return_value=client):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        return self.verifier["main"]()

    def test_completed_trace_passes(self):
        for success in (True, "True"):
            with self.subTest(success=success):
                self.assertEqual(self.run_verifier(success=success), 0)

    def test_missing_failed_or_incomplete_traces_fail(self):
        for options in (
            {"empty": True}, {"success": False}, {"success": "False"},
            {"missing_root": True}, {"query_error": True},
        ):
            with self.subTest(options=options):
                self.assertEqual(self.run_verifier(**options), 1)

    def test_malformed_query_response_fails(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=table(["one", "two"], [["short"]]))
        ))
        with client, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(self.verifier["kql"](client, "test-app", "query", "title"))


class PortabilityTests(unittest.TestCase):
    def test_legacy_console_encoding_does_not_crash_on_unicode(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252")
        with patch.object(sys, "stdout", stream):
            _workshop.configure_console()
            print("UTC \u03c0", flush=True)
        self.assertIn(b"\\u03c0", buffer.getvalue())

    def test_script_failures_return_nonzero_from_each_entry_point(self):
        bootstrap = """
import runpy, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(sys.argv[1]).parent))
def fail(coroutine):
    coroutine.close()
    raise RuntimeError("intentional validation failure")
with patch("asyncio.run", side_effect=fail):
    runpy.run_path(sys.argv[1], run_name="__main__")
"""
        paths = (
            "01-basic-agent/01-basic-agent.py",
            "02-mcp-tool-agent/02-mcp-tool-agent.py",
            "02-mcp-tool-agent/02b-portal-agent.py",
            "02-mcp-tool-agent/02c-hybrid-agent.py",
            "03-custom-function-tool-agent/03-custom-function-tool-agent.py",
            "04-tracing-agent/04-tracing-agent.py",
        )
        for relative in paths:
            with self.subTest(sample=relative):
                result = subprocess.run(
                    [sys.executable, "-c", bootstrap, str(ROOT / relative)],
                    cwd=ROOT,
                    env={**os.environ, **SAMPLE_ENV},
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=45,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("intentional validation failure", result.stderr)

    def test_mcp_scripts_do_not_report_success_when_flushing_fails(self):
        bootstrap = """
import runpy, sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
sys.path.insert(0, str(Path(sys.argv[1]).parent))
agent = MagicMock()
agent.__aenter__.return_value = agent
agent.run = AsyncMock(return_value="offline response")
with (
    patch("agent_framework.Agent", return_value=agent),
    patch("agent_framework.foundry.FoundryChatClient"),
    patch("agent_framework.foundry.FoundryAgent", return_value=agent),
    patch("azure.ai.projects.AIProjectClient"),
    patch("_workshop.configure_tracing"),
    patch("_workshop.shutdown_tracing", side_effect=RuntimeError("intentional flush failure")),
):
    runpy.run_path(sys.argv[1], run_name="__main__")
"""
        for name in ("02-mcp-tool-agent.py", "02b-portal-agent.py", "02c-hybrid-agent.py"):
            with self.subTest(sample=name):
                result = subprocess.run(
                    [sys.executable, "-c", bootstrap, str(ROOT / "02-mcp-tool-agent" / name)],
                    cwd=ROOT,
                    env={**os.environ, **SAMPLE_ENV},
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=45,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("offline response", result.stdout)
                self.assertIn("intentional flush failure", result.stderr)
                self.assertNotIn("All tasks completed successfully", result.stdout)


if __name__ == "__main__":
    unittest.main()
