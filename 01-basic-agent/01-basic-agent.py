r"""Build a basic agent using Microsoft Agent Framework (sample 01).

Prerequisites: Python 3.13, Git, Azure CLI and access to a Foundry project
with a deployed model. Keep the complete repository together.

1. Setup

Run the block for your operating system from any folder INSIDE this Git
clone. The first command returns to the repository root. The setup reuses
an existing .venv and does not require activation.

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
    test -f 01-basic-agent/.env || cp 01-basic-agent/.env.example 01-basic-agent/.env

Windows PowerShell:
    if (-not (Test-Path .\01-basic-agent\.env)) { Copy-Item .\01-basic-agent\.env.example .\01-basic-agent\.env }

Edit 01-basic-agent/.env and set:
    FOUNDRY_PROJECT_ENDPOINT: your Foundry project endpoint
    FOUNDRY_MODEL: the name of your deployed model
The endpoint format is:
    https://<resource>.services.ai.azure.com/api/projects/<project>
Use an Azure identity with access to that project and model.

3. Run after saving .env

Pass this file to the Python interpreter as shown below. Running its path
directly in the terminal can produce "permission denied".

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 01-basic-agent/01-basic-agent.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\01-basic-agent\01-basic-agent.py

4. VS Code

Open the repository root, select Python: Select Interpreter and choose the
root .venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Open this file and select Run Python File. The script loads .env from its
own folder, independently of the terminal directory.

Expected result: a streamed answer comparing Earth and Mars gravity.
A live run passed on macOS. Windows execution remains unverified.
See README.md for project access and troubleshooting details.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent_framework import Agent
from agent_framework_foundry import FoundryChatClient
from azure.identity import AzureCliCredential

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workshop import configure_console, print_stream, project_endpoint

# Load .env from this file's folder so both `python 01-basic-agent.py` and
# VS Code's ▶ Run button pick up the same configuration.
load_dotenv(Path(__file__).resolve().parent / ".env")

# Microsoft Foundry Agent Configuration (read from .env — see .env.example).
ENDPOINT = project_endpoint()
MODEL_DEPLOYMENT_NAME = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

AGENT_NAME = "ai-agent"
AGENT_INSTRUCTIONS = "You are a helpful AI assistant."

# User inputs for the conversation
USER_INPUTS = [
    "Can you tell me the gravity of Earth versus the gravity of Mars?",
]


async def main() -> None:
    configure_console()
    # The Foundry chat client owns the HTTPS transport to your project.
    # FoundryChatClient also reads FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL
    # from the environment automatically; we pass them explicitly here so the
    # fail-fast check above runs first.
    client = FoundryChatClient(
        project_endpoint=ENDPOINT,
        model=MODEL_DEPLOYMENT_NAME,
        credential=AzureCliCredential(),
    )

    async with Agent(
        client=client,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
    ) as agent:
        session = agent.create_session()
        for user_input in USER_INPUTS:
            print(f"\n# User: '{user_input}'")
            await print_stream(agent.run(user_input, session=session, stream=True))
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
