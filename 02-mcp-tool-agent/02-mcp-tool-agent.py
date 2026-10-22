r"""Build an MCP enabled agent using Microsoft Agent Framework.

Prerequisites: Python 3.13, Git, Azure CLI, a Foundry project with a
deployed model and network access to the Microsoft Learn MCP service.
Keep the complete repository together.

1. Setup

Run from any folder INSIDE this Git clone. The first command returns to
the repository root. Reuse the same .venv as samples 01, 03 and 04.
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
APPLICATIONINSIGHTS_CONNECTION_STRING is optional for this sample.
Use an Azure identity with access to the project and model.

3. Run after saving .env

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 02-mcp-tool-agent/02-mcp-tool-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\02-mcp-tool-agent.py

4. VS Code

Open the repository root and use Python: Select Interpreter to choose
.venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Open this file and select Run Python File. Its own folder supplies .env.

Expected result: a completed answer using the Microsoft Learn MCP tool.
Live execution of this sample and Windows execution remain unverified.
See README.md for endpoint configuration and tracing details.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential

from _observability import init_observability, project_endpoint, shutdown_tracing

# Microsoft Foundry project configuration.
# Set FOUNDRY_PROJECT_ENDPOINT in .env (see .env.example).
# Format: https://<resource>.services.ai.azure.com/api/projects/<project-name>
PROJECT_ENDPOINT = project_endpoint()
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

AGENT_NAME = "mcp-learn-agent-codefirst"
AGENT_INSTRUCTIONS = "You answer questions by searching Microsoft Learn content only."

# User inputs for the conversation
USER_INPUTS = [
    "Please summarize the Azure AI Agent documentation related to MCP tool calling?",
]


async def main() -> None:
    init_observability("pure-code")

    client = FoundryChatClient(
        model=MODEL,
        project_endpoint=PROJECT_ENDPOINT,
        credential=AzureCliCredential(),
    )

    # Microsoft Learn MCP is read-only public docs search, so auto-approving
    # every tool call is safe. For any MCP server with write/destructive
    # tools, use approval_mode="always_require" (or a per-tool dict).
    mcp_tool = client.get_mcp_tool(
        name="MicrosoftLearn",
        url="https://learn.microsoft.com/api/mcp",
        approval_mode="never_require",
    )

    async with Agent(
        client=client,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=[mcp_tool],
    ) as agent:
        for user_input in USER_INPUTS:
            print(f"\n# User: '{user_input}'")
            result = await agent.run(user_input)
            print(f"# {AGENT_NAME}: {result}\n")


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
