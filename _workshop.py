"""Imported support code for samples 01 through 04 and 06.

This module is not a standalone application. Do not run it directly.
Each sample entry point contains complete macOS Terminal and Windows
PowerShell instructions using the repository root .venv and
requirements-first-four.txt. Start with 01-basic-agent/01-basic-agent.py.
Keep this file at the repository root so sample imports continue to work.
"""

from __future__ import annotations

import io
import os
import sys
from collections.abc import Mapping
from copy import copy
from typing import TYPE_CHECKING

from agent_framework import AgentResponse, AgentResponseUpdate, Content, ResponseStream

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

_tracing_provider: TracerProvider | None = None


def configure_console() -> None:
    """Keep redirected Windows output usable with legacy terminal encodings."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def project_endpoint() -> str:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint or "<" in endpoint:
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT is not configured. "
            "Copy .env.example to .env in this sample's folder and set the "
            "project endpoint from Foundry, ending in /api/projects/<project-name>."
        )
    return endpoint


class _StreamPrinter:
    def __init__(self, *, show_tools: bool, agent_name: str) -> None:
        self.show_tools = show_tools
        self.agent_name = agent_name
        self.text_parts: dict[tuple[str, str], str] = {}
        self.calls: dict[str, Content] = {}
        self.results: set[str] = set()

    @staticmethod
    def _text_key(update: AgentResponseUpdate, content: Content, index: int) -> tuple[str, str]:
        # Responses API events identify text parts even when message_id is absent.
        event = content.raw_representation
        if isinstance(event, Mapping):
            item_id = event.get("item_id")
            content_index = event.get("content_index")
        else:
            item_id = getattr(event, "item_id", None)
            content_index = getattr(event, "content_index", None)
        message_id = update.message_id or (item_id if isinstance(item_id, str) else "")
        part_id = content.id or str(content_index if isinstance(content_index, int) else index)
        return message_id, part_id

    def write(self, update: AgentResponseUpdate) -> None:
        for index, content in enumerate(update.contents):
            # Older SDKs emit append-only updates without merge_mode.
            replacement = (
                getattr(content, "merge_mode", None) == "replace"
                or getattr(update, "merge_mode", None) == "replace"
            )
            if content.type == "text" and content.text is not None:
                key = self._text_key(update, content, index)
                previous = self.text_parts.get(key, "")
                text = content.text if replacement else previous + content.text
                if text.startswith(previous):
                    print(text[len(previous):], end="", flush=True)
                elif text != previous:
                    print(f"\n[updated response]\n{text}", end="", flush=True)
                self.text_parts[key] = text
            elif self.show_tools and content.type == "function_call" and content.call_id:
                previous_call = self.calls.get(content.call_id)
                self.calls[content.call_id] = (
                    previous_call + content
                    if previous_call is not None and not replacement
                    else copy(content)
                )
            elif (
                self.show_tools
                and content.type == "function_result"
                and content.call_id
                and content.call_id not in self.results
            ):
                self.results.add(content.call_id)
                call = self.calls.get(content.call_id)
                if call is not None:
                    print(f"\n[tool call] {call.name}({call.arguments or '{}'})", flush=True)
                print(
                    f"[tool result] {content.result}\n# {self.agent_name}: ",
                    end="",
                    flush=True,
                )


async def print_stream(
    stream: ResponseStream[AgentResponseUpdate, AgentResponse],
    *,
    show_tools: bool = False,
    agent_name: str = "ai-agent",
) -> AgentResponse:
    """Print incremental text without repeating authoritative replacement snapshots."""
    configure_console()
    printer = _StreamPrinter(show_tools=show_tools, agent_name=agent_name)
    try:
        async for update in stream:
            printer.write(update)
        return await stream.get_final_response()
    finally:
        await stream.close()


def configure_tracing(connection_string: str, scenario: str) -> None:
    """Export complete workshop traces while respecting ENABLE_SENSITIVE_DATA."""
    global _tracing_provider

    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    if _tracing_provider is not None:
        raise RuntimeError("Tracing is already configured in this process.")

    configure_azure_monitor(
        connection_string=connection_string,
        resource=Resource.create({
            "service.name": os.environ.get("OTEL_SERVICE_NAME", f"foundry-workshop.{scenario}"),
            "workshop.scenario": scenario,
        }),
        sampling_ratio=1.0,
    )
    enable_instrumentation()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        raise RuntimeError("Azure Monitor did not configure an OpenTelemetry tracer provider.")
    _tracing_provider = provider


def shutdown_tracing() -> None:
    """Drain finished spans before shutdown and surface a flush timeout."""
    global _tracing_provider

    provider = _tracing_provider
    if provider is None:
        return
    try:
        if not provider.force_flush(timeout_millis=30000):
            raise RuntimeError("Timed out while flushing tracing spans to the exporter.")
    finally:
        provider.shutdown()
        _tracing_provider = None
