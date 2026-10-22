r"""Invoke a portal defined agent from Microsoft Foundry.

Companion to ``02-mcp-tool-agent.py``.

| Script                  | Where the agent is defined | What's in the code              |
|-------------------------|----------------------------|---------------------------------|
| 02-mcp-tool-agent.py    | this Python file           | instructions + tools + name     |
| 02b-portal-agent.py     | Microsoft Foundry portal   | only the agent name + version   |

This script does NOT build an agent. It loads one you've already configured in
the Foundry portal (https://ai.azure.com) and runs the configured version.
After publishing portal changes, update PORTAL_AGENT_VERSION to the new
version before running the script again.

Prerequisites: Python 3.13, Git, Azure CLI and an existing published portal
agent. Keep the complete repository together.

1. Setup

Run from any folder INSIDE this Git clone. Reuse the repository .venv.
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
    test -f 02-mcp-tool-agent/.env || cp 02-mcp-tool-agent/.env.example 02-mcp-tool-agent/.env

Windows PowerShell:
    if (-not (Test-Path .\02-mcp-tool-agent\.env)) { Copy-Item .\02-mcp-tool-agent\.env.example .\02-mcp-tool-agent\.env }

Edit 02-mcp-tool-agent/.env and set:
    FOUNDRY_PROJECT_ENDPOINT: the project containing the portal agent
    PORTAL_AGENT_NAME: the name of your existing portal agent
    PORTAL_AGENT_VERSION: the published version to invoke
APPLICATIONINSIGHTS_CONNECTION_STRING is optional.
Use an Azure identity with access to that project and agent.

3. Run after saving .env

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 02-mcp-tool-agent/02b-portal-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\02b-portal-agent.py

4. VS Code

Open the repository root and use Python: Select Interpreter to choose
.venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Open this file and select Run Python File. Its own folder supplies .env.

Expected result: printed answers from the configured portal agent version.
Live execution of this sample and Windows execution remain unverified.
See README.md for portal agent creation and configuration details.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_framework.foundry import FoundryAgent
from azure.identity import AzureCliCredential

from _observability import init_observability, project_endpoint, shutdown_tracing

# Microsoft Foundry project configuration.
# Set FOUNDRY_PROJECT_ENDPOINT in .env (see .env.example).
PROJECT_ENDPOINT = project_endpoint()

# Pick one of the agents you can see in the Foundry portal.
# The version number is shown next to each agent in the portal listing.
AGENT_NAME = os.environ.get("PORTAL_AGENT_NAME", "<YOUR_PORTAL_AGENT_NAME>")
AGENT_VERSION = os.environ.get("PORTAL_AGENT_VERSION", "1")

USER_INPUTS = [
    "In one short sentence, tell me what kinds of questions you are designed to answer.",
]


async def main() -> None:
    if not AGENT_NAME or "<" in AGENT_NAME or not AGENT_VERSION:
        raise RuntimeError("Set PORTAL_AGENT_NAME and PORTAL_AGENT_VERSION in this folder's .env.")
    init_observability("portal-first")
    print(f"Connecting to portal agent: {AGENT_NAME} (version {AGENT_VERSION})\n")

    agent = FoundryAgent(
        project_endpoint=PROJECT_ENDPOINT,
        agent_name=AGENT_NAME,
        agent_version=AGENT_VERSION,
        credential=AzureCliCredential(),
    )

    for user_input in USER_INPUTS:
        print(f"# User: {user_input}\n")
        result = await agent.run(user_input)
        print(f"# {AGENT_NAME}:\n{result}\n")


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
