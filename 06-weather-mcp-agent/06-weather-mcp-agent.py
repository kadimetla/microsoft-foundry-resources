r"""Run a Foundry agent with the Azure Functions weather MCP tool (sample 06).

Prerequisites: Python 3.13, Git, Azure CLI, a Foundry project with a
deployed model and a deployed weather MCP server. Keep the full repository
together because this script imports the shared observability helpers.
The model and MCP tool execution are hosted in Azure. This Python process
orchestrates the conversation and does not publish a named Foundry agent.
Foundry must reach the MCP endpoint. A localhost URL will not work here.

1. Setup

Start from any folder INSIDE this Git clone, not the parent foundry folder.
The first command returns to the repository root. Reuse the root .venv
from samples 01 through 04. Activation is not required.

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

Keep the existing 06-weather-mcp-agent/.env with its deployed endpoint and
credentials. From the repository root, create it ONLY when it is missing.

macOS Terminal:
    test -f 06-weather-mcp-agent/.env || cp 06-weather-mcp-agent/.env.example 06-weather-mcp-agent/.env

Windows PowerShell:
    if (-not (Test-Path .\06-weather-mcp-agent\.env)) { Copy-Item .\06-weather-mcp-agent\.env.example .\06-weather-mcp-agent\.env }

Edit 06-weather-mcp-agent/.env and fill in:
    FOUNDRY_PROJECT_ENDPOINT: https://<resource>.services.ai.azure.com/api/projects/<project>
    FOUNDRY_MODEL: the name of your deployed model
    WEATHER_MCP_ENDPOINT: https://<function-app>.azurewebsites.net/runtime/webhooks/mcp
    WEATHER_MCP_AUTH: key
    WEATHER_MCP_KEY: the Function App's mcp_extension SYSTEM key
    WEATHER_MCP_AUDIENCE: leave empty for key authentication
    APPLICATIONINSIGHTS_CONNECTION_STRING: optional shared App Insights string

Get the project endpoint and deployment name from Foundry. Get the system
key from the Function App in Azure or the command below, replacing BOTH
placeholders. Do not use a function key or host key instead.
    az functionapp keys list --resource-group "<resource-group>" --name "<function-app>" --query systemKeys.mcp_extension -o tsv

Key mode requires host.json webhookAuthorizationLevel=System and Easy Auth
off. The alternative entra mode requires an already configured Entra MCP
application and Easy Auth. Set WEATHER_MCP_AUDIENCE to its full Application
ID URI, such as api://<app-client-id>, with suitable access for your Azure
CLI identity, or provide WEATHER_MCP_TOKEN. See README.md for that setup.
Do not leave WEATHER_MCP_AUTH blank. Do not change Azure authentication
settings just to run an already deployed key mode server.
If no server exists yet, follow mcp-server/README.md to deploy one first.

3. Run after saving .env

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 06-weather-mcp-agent/06-weather-mcp-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\06-weather-mcp-agent\06-weather-mcp-agent.py

4. VS Code

Select the repository root .venv interpreter and Run Python File.
This script loads .env from its own folder, regardless of terminal location.
Expected result: answers to three weather questions using get_weather.
The deployed MCP server was verified separately. This agent's complete
Foundry invocation and Windows execution remain unverified.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

# Reuse the observability bootstrap from sample 02.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02-mcp-tool-agent"))
from _observability import init_observability, project_endpoint, shutdown_tracing  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

PROJECT_ENDPOINT = project_endpoint()
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")
MCP_ENDPOINT = os.environ.get("WEATHER_MCP_ENDPOINT", "").strip()
if not MCP_ENDPOINT or "<" in MCP_ENDPOINT:
    raise RuntimeError("Set WEATHER_MCP_ENDPOINT in this folder's .env to the deployed MCP endpoint.")

# Auth selection: default to "entra" when WEATHER_MCP_AUDIENCE is provided
# (iteration 2 deployment), otherwise fall back to "key" (iteration 1).
_AUDIENCE = os.environ.get("WEATHER_MCP_AUDIENCE", "").strip()
AUTH_MODE = os.environ.get(
    "WEATHER_MCP_AUTH",
    "entra" if _AUDIENCE else "key",
).strip().lower()

AGENT_NAME = "weather-mcp-agent"
AGENT_INSTRUCTIONS = (
    "You are a concise weather assistant. When the user asks about the weather, "
    "ALWAYS call the get_weather tool and base your answer on its result. "
    "If the tool returns an 'error' field, surface that error verbatim. "
    "Report temperature in both °F and °C and include the reported_at_utc timestamp."
)

USER_INPUTS = [
    "What's the current weather in Seattle, WA?",
    "And how about Paris?",
    "Compare the wind in Mumbai and Sydney right now.",
]


def _build_mcp_headers(credential: AzureCliCredential) -> dict[str, str]:
    """Returns the per-request headers for the configured auth mode.

    Entra mode resolves the bearer token in this priority:
      1. ``WEATHER_MCP_TOKEN`` env var (a pre-acquired JWT) — handy when the
         CLI user lacks a delegated OAuth2 scope on the MCP audience. In
         production, Foundry's Agent Identity supplies this token directly.
      2. ``AzureCliCredential.get_token("<audience>/.default")`` — requires
         the user to have been pre-consented to an OAuth2 scope on the MCP
         app reg (advanced; not the default Foundry setup).

    For ``key`` mode, ``WEATHER_MCP_KEY`` is sent as ``x-functions-key``.
    """
    if AUTH_MODE not in ("key", "entra"):
        raise RuntimeError("WEATHER_MCP_AUTH must be 'key' or 'entra'.")

    if AUTH_MODE == "entra":
        pre_acquired = os.environ.get("WEATHER_MCP_TOKEN", "").strip()
        if pre_acquired:
            return {"Authorization": f"Bearer {pre_acquired}"}

        if not _AUDIENCE:
            raise RuntimeError(
                "WEATHER_MCP_AUTH=entra requires WEATHER_MCP_AUDIENCE "
                "(e.g. api://<mcp-app-id>) to mint a bearer token, or "
                "WEATHER_MCP_TOKEN to supply one directly."
            )
        scope = _AUDIENCE if _AUDIENCE.endswith("/.default") else f"{_AUDIENCE}/.default"
        token = credential.get_token(scope).token
        return {"Authorization": f"Bearer {token}"}

    # Fallback: iteration 1 function-key auth
    mcp_key = os.environ.get("WEATHER_MCP_KEY")
    if not mcp_key:
        raise RuntimeError(
            "WEATHER_MCP_AUTH=key requires WEATHER_MCP_KEY (the mcp_extension "
            "system key from the Function App)."
        )
    return {"x-functions-key": mcp_key}


async def main() -> None:
    init_observability("weather-mcp")

    credential = AzureCliCredential()

    client = FoundryChatClient(
        model=MODEL,
        project_endpoint=PROJECT_ENDPOINT,
        credential=credential,
    )

    print(f"[auth] WEATHER_MCP_AUTH={AUTH_MODE}", flush=True)
    mcp_headers = _build_mcp_headers(credential)

    # ``approval_mode="never_require"`` is safe here because get_weather is
    # read-only and idempotent. Use ``"always_require"`` (or per-tool dict)
    # for any MCP server with write/destructive tools.
    mcp_tool = client.get_mcp_tool(
        name="weather-mcp-azure-functions",
        url=MCP_ENDPOINT,
        approval_mode="never_require",
        headers=mcp_headers,
        allowed_tools=["get_weather"],
    )

    async with Agent(
        client=client,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=[mcp_tool],
    ) as agent:
        for user_input in USER_INPUTS:
            print(f"\n# User: {user_input!r}")
            result = await agent.run(user_input)
            print(f"# {AGENT_NAME}: {result}\n")

        print("\n--- All tasks completed successfully ---")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        raise SystemExit(130)
    finally:
        shutdown_tracing()
        print("Program finished.")
