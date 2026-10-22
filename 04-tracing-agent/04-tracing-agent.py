r"""Build an agent wired up with OpenTelemetry tracing (sample 04).

Prerequisites: Python 3.13, Git, Azure CLI, a Foundry project with a
deployed model and an Application Insights resource.
Keep the complete repository together.

1. Setup

Run from any folder INSIDE this Git clone. The first command returns to
the repository root. Reuse the same .venv as samples 01 through 03.
Activation is not required.

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    test -x .venv/bin/python || python3.13 -m venv .venv
    .venv/bin/python -m pip install -r requirements-first-four.txt
    .venv/bin/python -m pip check
    az login

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
    .\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
    .\.venv\Scripts\python.exe -m pip check
    az login

2. Configure

From the repository root, create .env only if it is missing.
Do not overwrite an existing configuration.

macOS Terminal:
    test -f 04-tracing-agent/.env || cp 04-tracing-agent/.env.example 04-tracing-agent/.env

Windows PowerShell:
    if (-not (Test-Path .\04-tracing-agent\.env)) { Copy-Item .\04-tracing-agent\.env.example .\04-tracing-agent\.env }

Edit 04-tracing-agent/.env and set:
    FOUNDRY_PROJECT_ENDPOINT: your Foundry project endpoint
    FOUNDRY_MODEL: the name of your deployed model
    APPLICATIONINSIGHTS_CONNECTION_STRING: your App Insights connection string
The connection string is REQUIRED for this tracing sample.
Use an Azure identity with access to the project and model.

3. Run after saving .env

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 04-tracing-agent/04-tracing-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\04-tracing-agent\04-tracing-agent.py

4. VS Code

Open the repository root and use Python: Select Interpreter to choose
.venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Open this file and select Run Python File. Its own folder supplies .env.

Expected result: a streamed answer and a trace ID. Check Application
Insights after ingestion to confirm the trace arrived.
Live execution of this sample and Windows execution remain unverified.
See README.md for tracing queries and sensitive content settings.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from this file's folder so both `python 04-tracing-agent.py` and
# VS Code's Run button pick up the same configuration.
load_dotenv(Path(__file__).resolve().parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workshop import (
    configure_console,
    configure_tracing,
    print_stream,
    project_endpoint,
    shutdown_tracing,
)

# Microsoft Foundry Agent Configuration (read from .env, see .env.example).
ENDPOINT = project_endpoint()
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")
APPINSIGHTS_CONN = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()

if not APPINSIGHTS_CONN:
    raise RuntimeError(
        "APPLICATIONINSIGHTS_CONNECTION_STRING is not configured. "
        "This sample is specifically about tracing. Without an App Insights "
        "connection string no telemetry is exported. Get it from the Foundry "
        "portal under your project, Manage, Tracing. See README.md."
    )

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from opentelemetry import trace

AGENT_NAME = "ai-agent"
AGENT_INSTRUCTIONS = "You are a helpful AI assistant."

USER_INPUTS = [
    "Can you tell me the gravity of Earth versus the gravity of Mars?",
]


async def main() -> None:
    configure_console()
    configure_tracing(APPINSIGHTS_CONN, "tracing")
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("example-tracing") as root:
        client = FoundryChatClient(
            model=MODEL,
            project_endpoint=ENDPOINT,
            credential=AzureCliCredential(),
        )

        async with Agent(
            client=client,
            name=AGENT_NAME,
            instructions=AGENT_INSTRUCTIONS,
        ) as agent:
            for user_input in USER_INPUTS:
                print(f"\n# User: '{user_input}'")
                print(f"# {AGENT_NAME}: ", end="", flush=True)

                await print_stream(agent.run(user_input, stream=True))
                print()

    print(f"\nTrace ID: {root.get_span_context().trace_id:032x}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        raise SystemExit(130)
    finally:
        shutdown_tracing()
    print("\n--- All tasks completed successfully ---")
    print("Program finished.")
