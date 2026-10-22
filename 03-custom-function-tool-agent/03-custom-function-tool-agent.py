r"""Build an agent with a custom Python function tool (sample 03).

Prerequisites: Python 3.13, Git, Azure CLI and access to a Foundry project
with a deployed model. Keep the complete repository together.

1. Setup

Run from any folder INSIDE this Git clone. The first command returns to
the repository root. Reuse the same .venv as samples 01, 02, 04 and 06.
Activation is not required.

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    test -x .venv/bin/python || python3.13 -m venv .venv
    .venv/bin/python -m pip install -r requirements-first-four.txt
    .venv/bin/python -m pip check

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
    .\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
    .\.venv\Scripts\python.exe -m pip check

Sign in only if Azure CLI is not already signed in:
    az login

2. Configure

From the repository root, create this sample's .env only if it is missing.
Do not overwrite an existing configuration.

macOS Terminal:
    test -f 03-custom-function-tool-agent/.env || cp 03-custom-function-tool-agent/.env.example 03-custom-function-tool-agent/.env

Windows PowerShell:
    if (-not (Test-Path .\03-custom-function-tool-agent\.env)) { Copy-Item .\03-custom-function-tool-agent\.env.example .\03-custom-function-tool-agent\.env }

Edit 03-custom-function-tool-agent/.env and use the values that worked in 01:
    FOUNDRY_PROJECT_ENDPOINT: your Foundry project endpoint
    FOUNDRY_MODEL: the name of your deployed model
Use an Azure identity with access to that project and model.

3. Run after saving .env

Pass the script to Python. Do not run the .py file path directly, which
can produce "permission denied". These commands use the repository .venv
created above and work from any folder inside the clone.

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 03-custom-function-tool-agent/03-custom-function-tool-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\03-custom-function-tool-agent\03-custom-function-tool-agent.py

4. VS Code

Open the repository root and use Python: Select Interpreter to choose
.venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Alternatively, select the configured interpreter that worked for 01.
Open this file and select Run Python File in Terminal. Its own folder
supplies .env, regardless of the terminal's current directory.

Expected result:
    [tool call] get_time({})
    [tool result] The current UTC time is ...
    # time-agent: The current time in UTC is ...

For a 429 error, follow the service's retry interval. An oversized request
may require a deployment with more capacity rather than repeated retries.
Actual Windows execution remains unverified.
See README.md for project access and tool behavior details.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from this file's folder so both `python 03-...py` and VS Code's
# Run button pick up the same configuration.
load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workshop import configure_console, print_stream, project_endpoint

# Microsoft Foundry Agent Configuration (read from .env, see .env.example).
ENDPOINT = project_endpoint()
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

AGENT_NAME = "time-agent"
AGENT_INSTRUCTIONS = (
    "You are a helpful assistant that can provide time information in UTC "
    "format. Always call the get_time tool when asked about the current time."
)

USER_INPUTS = [
    "What is the current time in UTC?",
]


def get_time() -> str:
    """Get the current UTC time."""
    current_time = datetime.now(timezone.utc)
    return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."


async def main() -> None:
    configure_console()
    client = FoundryChatClient(
        model=MODEL,
        project_endpoint=ENDPOINT,
        credential=AzureCliCredential(),
    )

    async with Agent(
        client=client,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=[get_time],
    ) as agent:
        for user_input in USER_INPUTS:
            print(f"\n# User: '{user_input}'")
            print(f"# {AGENT_NAME}: ", end="", flush=True)

            await print_stream(
                agent.run(user_input, stream=True),
                show_tools=True,
                agent_name=AGENT_NAME,
            )
            print()

        print("\n--- All tasks completed successfully ---")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        raise SystemExit(130)
    finally:
        print("Program finished.")
