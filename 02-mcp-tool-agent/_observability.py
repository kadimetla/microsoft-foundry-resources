"""Imported tracing helpers for samples 02, 02b, 02c and 06.

This module is not a standalone application. Do not run it directly.
Use the macOS Terminal or Windows PowerShell setup and run commands in
02-mcp-tool-agent.py, 02b-portal-agent.py, 02c-hybrid-agent.py or
../06-weather-mcp-agent/06-weather-mcp-agent.py instead.
Keep the repository together so the shared _workshop.py can be imported.

Set APPLICATIONINSIGHTS_CONNECTION_STRING to export spans.
Set ENABLE_SENSITIVE_DATA=true only when prompt and tool content should
also be recorded. Metadata is recorded without that opt in.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workshop import configure_console, configure_tracing, project_endpoint, shutdown_tracing

TRACING_ENABLED: bool = False
SCENARIO: str | None = None


def init_observability(scenario: str) -> None:
    """Tag workshop traces with their scenario and configure the exporter once."""
    global TRACING_ENABLED, SCENARIO

    configure_console()
    load_dotenv(Path(__file__).resolve().parent / ".env")
    if TRACING_ENABLED:
        if SCENARIO != scenario:
            raise RuntimeError("A different tracing scenario is already configured.")
        return

    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not conn:
        print(
            "[observability] skipped: APPLICATIONINSIGHTS_CONNECTION_STRING is not set. "
            "Copy .env.example to .env and paste the project's Application Insights connection string."
        )
        return

    configure_tracing(conn, scenario)

    TRACING_ENABLED = True
    SCENARIO = scenario
    print(f"[observability] enabled: scenario='{scenario}' -> Application Insights")
