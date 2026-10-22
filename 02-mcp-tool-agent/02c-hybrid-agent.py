r"""Persist a code defined agent using the Azure AI Projects SDK.

An unchanged definition reuses its existing version. A missing agent or a
changed definition creates a version using agents.create_version().
Only a missing resource is treated as a reason to create an agent.

Running this script can create an agent or publish a new version.
It does not delete agents. See README.md for setup and cleanup.

Prerequisites: Python 3.13, Git, Azure CLI, a Foundry project with a
deployed model and access to the Microsoft Learn MCP service.
Keep the complete repository together.

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
    FOUNDRY_PROJECT_ENDPOINT: your Foundry project endpoint
    FOUNDRY_MODEL: the name of your deployed model
APPLICATIONINSIGHTS_CONNECTION_STRING is optional.
Use an Azure identity with permission to create and invoke agent versions.

3. Run after saving .env

This step can publish a new agent version in Azure.

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 02-mcp-tool-agent/02c-hybrid-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\02c-hybrid-agent.py

4. VS Code

Open the repository root and use Python: Select Interpreter to choose
.venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Open this file and select Run Python File. Its own folder supplies .env.

Expected result: reuse or create an agent version, then print its answers.
Live execution of this sample and Windows execution remain unverified.
See README.md for version publishing and cleanup details.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_framework.foundry import FoundryAgent
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import AzureCliCredential

from _observability import init_observability, project_endpoint, shutdown_tracing

# Microsoft Foundry project configuration.
# Set FOUNDRY_PROJECT_ENDPOINT in .env (see .env.example).
PROJECT_ENDPOINT = project_endpoint()
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

AGENT_NAME = "mcp-learn-agent-hybrid"

AGENT_DEFINITION = PromptAgentDefinition(
    model=MODEL,
    instructions=(
        "You are a Microsoft Learn research assistant. "
        "Use the MicrosoftLearn MCP tool to answer questions about Azure and "
        "Microsoft technologies, citing the Microsoft Learn pages you used."
    ),
    tools=[
        MCPTool(
            server_label="MicrosoftLearn",
            server_url="https://learn.microsoft.com/api/mcp",
            require_approval="never",
        )
    ],
)

USER_INPUTS = [
    "Please summarize the Azure AI Agent documentation related to MCP tool calling?",
]


def _without_nulls(value: object) -> object:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def ensure_agent(project: AIProjectClient) -> str:
    """Reuse an identical definition or publish a version when it changes."""
    try:
        existing = project.agents.get(AGENT_NAME).versions.latest
    except ResourceNotFoundError:
        existing = None

    if existing is not None and (
        _without_nulls(existing.definition.as_dict()) == _without_nulls(AGENT_DEFINITION.as_dict())
    ):
        print(f"  Reusing unchanged agent '{AGENT_NAME}', version {existing.version}")
        return existing.version

    version = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=AGENT_DEFINITION,
    )
    print(f"  Published agent '{AGENT_NAME}', version {version.version}")
    return version.version


async def main() -> None:
    init_observability("hybrid")
    print(f"Hybrid pattern: code defines '{AGENT_NAME}', server hosts it.\n")

    credential = AzureCliCredential()
    with AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential) as project:
        agent_version = ensure_agent(project)
    print()

    agent = FoundryAgent(
        project_endpoint=PROJECT_ENDPOINT,
        agent_name=AGENT_NAME,
        agent_version=agent_version,
        credential=credential,
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
    print(f"View this agent in the portal at:\n  https://ai.azure.com  →  Agents  →  {AGENT_NAME}")
    print("Program finished.")
