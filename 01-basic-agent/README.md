# Sample 01: Your first Microsoft Foundry agent

This sample sends a prompt to a model deployed in a Microsoft Foundry project
and prints the response as it streams. The agent is defined in Python. Running
the sample does not create a saved agent in the Foundry portal.

**Estimated time:** 10 minutes after setup.
**Difficulty:** Beginner.

## Table of contents

* [What you will learn](#what-you-will-learn)
* [Prerequisites](#prerequisites)
* [The mental model](#the-mental-model)
* [Step by step code walkthrough](#step-by-step-code-walkthrough)
* [Running the sample](#running-the-sample)
* [Expected output](#expected-output)
* [Troubleshooting](#troubleshooting)
* [Exercises, try these next](#exercises-try-these-next)
* [What you've learned](#what-youve-learned)
* [Where to go next](#where-to-go-next)
* [Microsoft references](#microsoft-references)

## What you will learn

1. Use a credential, a model client, an agent and a session together.
2. Authenticate with `AzureCliCredential` using your Azure CLI login.
3. Send prompts to a deployed model and print streamed responses.

## Prerequisites

| Requirement | Details |
| --- | --- |
| **Python 3.13** | The setup commands below use this version. |
| **Git and the complete repository clone** | The commands use Git to find the repository root. The script also imports the shared helper from that root. |
| **A Microsoft Foundry project with a deployed model** | Use a model that supports the Foundry Responses API. The default deployment name is `gpt-4o`. |
| **Azure CLI** | Sign in with `az login` using an identity that can access the project and model. |
| **Project access** | Your identity needs project and model inference permissions, such as **Foundry User** at project scope or equivalent permissions. This role was previously named **Azure AI User**. |
| **Project endpoint and deployment name** | Configure them as described [below](#step-1-configure-your-env-file). |
| **VS Code with the Python extension** | Optional. Select the repository virtual environment before running the script. |

Signing in with `az login` does not grant project access. Ask a project
administrator to check your role assignment if access has not been granted.
Microsoft's [resource setup guide](https://learn.microsoft.com/en-us/azure/foundry/tutorials/quickstart-create-foundry-resources?tabs=portal)
covers project creation, model deployment and access assignments.

### Step 1: Configure your `.env` file

The script loads `.env` from the same folder as `01-basic-agent.py`, regardless
of the terminal directory. The terminal commands and VS Code's **Run Python
File** command therefore use the same file.

1. **Create `.env` only if it is missing. Preserve existing values:**
   ```bash
   cd "$(git rev-parse --show-toplevel)"
   cd 01-basic-agent
   test -f .env || cp .env.example .env
   ```

   In Windows PowerShell, use:
   ```powershell
   Set-Location -LiteralPath (git rev-parse --show-toplevel)
   Set-Location 01-basic-agent
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   ```

2. **Open `.env` in VS Code** and fill in two values:

   | Variable | Where to find it |
   | --- | --- |
   | `FOUNDRY_PROJECT_ENDPOINT` | In the new Foundry portal, select your project and copy the project endpoint from its welcome screen. Its format is `https://<resource>.services.ai.azure.com/api/projects/<project-name>`. |
   | `FOUNDRY_MODEL` | Select **Build > Models** in the new Foundry portal and copy the deployment name. Use that name, not just the model family. If the variable is unset, the script uses `gpt-4o`. |

These directions refer to the new Foundry portal. Older portal instructions
may refer to **Models + Endpoints** instead.

The repository ignores `.env` files. Keep credentials, function keys and
connection strings out of tracked files.

Existing process environment variables take precedence over values in `.env`.
The file is not required if the needed values are already set in the environment.
If editing `.env` appears to have no effect, check for existing variables in
your terminal.

Before making a request, the shared helper rejects an empty project endpoint
or one that still contains `<`. It does not validate the full URL or check
whether the project and model deployment exist.

## The mental model

```text
Your Python process                         Azure

AzureCliCredential -----------------------> Microsoft Entra ID
Agent -> FoundryChatClient ----------------> Foundry project
  instructions                                deployed model
  shared session
  print_stream <--------------------------- response updates
```

| Part | Class or function | Responsibility |
| --- | --- | --- |
| **Credential** | `AzureCliCredential()` | Obtains access tokens using your Azure CLI login. |
| **Client** | `FoundryChatClient(...)` | Sends model requests to the Foundry project Responses endpoint. |
| **Agent** | `Agent(...)` | Combines the client, instructions, tools and request options. |
| **Session** | `agent.create_session()` | Tracks conversation state so later prompts can use earlier turns. |

The session can hold local history or a service conversation identifier,
depending on how the client and history provider manage the conversation.

## Step by step code walkthrough

Open [`01-basic-agent.py`](01-basic-agent.py) alongside this guide.

### Section 1, Imports and `.env` loader

```python
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from agent_framework import Agent
from agent_framework_foundry import FoundryChatClient
from azure.identity import AzureCliCredential

load_dotenv(Path(__file__).resolve().parent / ".env")
```

The script also resolves the repository root and imports `configure_console`,
`print_stream` and `project_endpoint` from [`_workshop.py`](../_workshop.py).
Keep the cloned repository together rather than copying only the entry script.

**What each import is for:**

| Import or call | Purpose |
| --- | --- |
| `asyncio` | Runs the `main()` coroutine through `asyncio.run(main())`. |
| `os` | Reads environment variables. |
| `Path` | Locates `.env` relative to the script rather than the terminal directory. |
| `load_dotenv(...)` | Loads the sample configuration without replacing existing process environment variables. |
| `Agent` | Combines model access, instructions and optional tools. |
| `FoundryChatClient` | Connects to the model through the Foundry project endpoint. |
| `AzureCliCredential` | Authenticates using your Azure CLI login. |

`agent_framework` contains the shared agent interfaces.
`agent_framework_foundry` supplies the Foundry integration. Other providers
have their own client packages and configuration requirements.

### Section 2, Configuration constants and endpoint check

```python
ENDPOINT = project_endpoint()
MODEL_DEPLOYMENT_NAME = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

AGENT_NAME = "ai-agent"
AGENT_INSTRUCTIONS = "You are a helpful AI assistant."

USER_INPUTS = [
    "Can you tell me the gravity of Earth versus the gravity of Mars?",
]
```

| Constant | Value |
| --- | --- |
| `ENDPOINT` | The project endpoint from `FOUNDRY_PROJECT_ENDPOINT`, with surrounding whitespace removed. |
| `MODEL_DEPLOYMENT_NAME` | The deployment name from `FOUNDRY_MODEL`. Defaults to `gpt-4o` when the variable is unset. |
| `AGENT_NAME` | A local label for the framework and telemetry. It does not register a portal agent. |
| `AGENT_INSTRUCTIONS` | Instructions included with model requests. |
| `USER_INPUTS` | Prompts sent in order using the same session. |

`project_endpoint()` raises `RuntimeError` if the resolved endpoint is empty,
contains only whitespace or contains `<`. This happens before any HTTP
request. A nonempty but incorrect URL can still fail later, as can an
incorrect deployment name.

### Section 3, The `main()` coroutine

The coroutine creates the client and agent, sends the prompts and closes
the client resources.

#### Part 3a, Build the client and agent

```python
async def main() -> None:
    configure_console()
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
        ...
```

`AzureCliCredential()` obtains a token when the client needs to authenticate.
The client receives the endpoint, deployment name and credential explicitly.
It can also read `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` from the
environment when those arguments are omitted.

`Agent(...)` uses the client to generate responses. No tools are configured
in this sample. Samples 02 and 03 add tools.

#### Part 3b, Create a session and send each prompt

```python
        session = agent.create_session()

        for user_input in USER_INPUTS:
            print(f"\n# User: '{user_input}'")
            await print_stream(agent.run(user_input, session=session, stream=True))
            print()
```

**Sessions retain conversation context.**
`agent.create_session()` creates a session before the loop so all prompts
share conversation state. Depending on the client and history configuration,
the session can contain history in its state or track a service conversation
identifier. It does not necessarily store every message locally.
Creating a fresh session for each prompt starts a separate conversation.

**Streaming updates can append or replace text.**
`agent.run(..., stream=True)` returns a `ResponseStream` of
`AgentResponseUpdate` objects. A final update can repeat the complete answer.
Printing every `chunk.text` verbatim would duplicate that answer.
`print_stream` respects append and replacement semantics, tracks distinct
message parts, obtains the final response and closes the stream.

**You can also print a completed response.**
Omit `stream=True` and call
`result = await agent.run(user_input, session=session)`, then print
`result.text`. This still uses asynchronous code, but returns the complete
response instead of a stream of updates.

#### Part 3c, Print a completion banner

```python
    print("\n--- All tasks completed successfully ---")
```

The `async with Agent(...)` block closes the owned client resources.
Closing a client is not the same as deleting a registered agent or its versions.

### Section 4, The entry point

```python
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        raise SystemExit(130)
    finally:
        print("Program finished.")
```

`asyncio.run(main())` creates an event loop, runs the coroutine and closes
the loop. Unexpected errors propagate with a traceback and a nonzero exit
status. An interruption exits with status `130`.

`Program finished.` is printed when this `finally` block runs, including
when `main()` fails. It is not a success indicator. The success banner is
printed only after all prompts complete and the agent context closes.

## Running the sample

Run the complete command block after configuring `.env` above. With Git
installed, the first command returns to the repository root from any folder
inside the clone, including `01-basic-agent`. Keep the complete repository
together because these samples import the shared `_workshop.py`.

Use one repository `.venv` for samples 01 through 04.
Install the compatible SDK set from
[`requirements-first-four.txt`](../requirements-first-four.txt), not an
unbounded upgrade of individual SDK packages.

### Windows PowerShell

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
.\.venv\Scripts\python.exe -m pip check
az login
.\.venv\Scripts\python.exe -X utf8 .\01-basic-agent\01-basic-agent.py
```

### macOS or Linux with Bash

```bash
cd "$(git rev-parse --show-toplevel)"
test -x .venv/bin/python || python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-first-four.txt
.venv/bin/python -m pip check
az login
.venv/bin/python -X utf8 01-basic-agent/01-basic-agent.py
```

These commands do not require virtual environment activation or a PowerShell
execution policy change. `-X utf8` also makes redirected output predictable.

Installation uses your configured package feed. If downloads from
`files.pythonhosted.org` time out, check that feed and your network rather
than adding a public PyPI override.

The sample has previously run on macOS with Python 3.13. Actual Windows
execution remains unverified.

### VS Code

Open the repository root in VS Code. Use **Python: Select Interpreter** to
select `.venv/bin/python` on macOS or `.venv\Scripts\python.exe` on Windows.
Open `01-basic-agent.py` and use **Run Python File**. The script loads `.env`
from its own sample folder.

## Expected output

The response wording and the size of each streamed update can vary.
A run might look like this:

```text
# User: 'Can you tell me the gravity of Earth versus the gravity of Mars?'
Earth's surface gravity is about 9.81 m/s^2. Mars's is about 3.71 m/s^2.
Mars has about 38% of Earth's surface gravity.

--- All tasks completed successfully ---
Program finished.
```

The answer is printed as updates arrive. There is no fixed number of words
per update. The shared renderer flushes each text update it prints.

## Troubleshooting

| Symptom | Possible cause | What to do |
| --- | --- | --- |
| `RuntimeError: FOUNDRY_PROJECT_ENDPOINT is not configured` | The resolved endpoint is empty or still contains `<`. | Follow the guarded copy commands in [Step 1](#step-1-configure-your-env-file), then edit the endpoint without overwriting an existing `.env`. |
| `azure.identity.exceptions.CredentialUnavailableError` or `AzureCliCredential failed to retrieve a token` | Azure CLI is not signed in or is using the wrong tenant. | Run `az login`, or `az login --tenant <YOUR_TENANT_ID>`. Check the active account with `az account show`. |
| `403 Forbidden` or a permission error | The identity lacks project or model access. Network restrictions can also deny access. | Confirm the account and tenant with `az account show`. Ask an administrator to check project permissions, such as Foundry User or equivalent access, and any network restrictions. |
| `ResourceNotFound` or `404` for the project | The endpoint points to the wrong resource or project. | In the new Foundry portal, select your project and copy its endpoint from the welcome screen. Set `FOUNDRY_PROJECT_ENDPOINT` to that value. |
| `DeploymentNotFound` or `404` for the model | The deployment name does not match an available deployment. | In the new Foundry portal, select **Build > Models** and copy the exact deployment name into `FOUNDRY_MODEL`. |
| Duplicated or unexpected streamed text | A printing loop may be printing both updates and the complete response. | Keep the shared `print_stream` renderer. It handles replacement snapshots, preserves provider whitespace and flushes each printed text update. |
| `ModuleNotFoundError` for a dependency | Dependencies are missing or a different Python interpreter is being used. | Repeat the appropriate [setup block](#running-the-sample) from inside the clone. It installs the root `requirements-first-four.txt` using the same `.venv` interpreter that runs the sample. |
| `.env` changes have no effect | Existing environment variables override values in the file. | Check whether `FOUNDRY_PROJECT_ENDPOINT` or `FOUNDRY_MODEL` is already set in your terminal environment. Update or remove that value before rerunning. |
| `429` or `Too Many Requests` | The deployment has insufficient request or token quota for the call. | Allow the quota window to reset. If the request still exceeds the allowance, use a deployment with enough capacity. Waiting alone will not fix a request that is too large for the allowance. |

## Exercises, try these next

1. **Change the personality.** Edit `AGENT_INSTRUCTIONS` to say *"You are a
   pirate who answers in nautical slang."* Run the sample again and compare
   the wording with the original response.
2. **Add a second prompt to `USER_INPUTS`** that depends on the first
   answer, such as *"Which of those two planets has stronger gravity?"*.
   Keep the shared session so the second request can use the earlier turn.
3. **Recreate the session inside the `for` loop** by moving `session =
   agent.create_session()` into the loop. Run both prompts again. The
   second request now starts without the earlier turn, so the model may
   ask for clarification or make a guess.
4. **Print a completed response.** Replace `await print_stream(...)` with
   `result = await agent.run(user_input, session=session)`, followed by
   `print(result.text)`. The complete answer is printed after the call
   finishes rather than as streamed updates.

## What you've learned

The sample combines a credential, a model client, an agent and a session.
It loads configuration from the environment, sends prompts to a deployed
model and uses the shared renderer to print streamed responses.

Samples 02 and 03 add tools. Sample 04 adds tracing. Sample 05 covers agent
identity and downstream API authentication. Sample 06 uses a custom MCP server.

## Where to go next

| If you want to…                                                                                       | Go to                                                                                  |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Give the agent its first **tool** so it can do more than talk                                         | [Sample 02 · MCP tool agent](../02-mcp-tool-agent/README.md)                            |
| Define the same agent in the **Foundry portal** instead of in code                                    | [Sample 02b · Portal agent](../02-mcp-tool-agent/README.md#variant-b--02b-portal-agentpy-portal-first) |
| Use a **local Python function** as a tool (no MCP server needed)                                      | [Sample 03 · Custom function tool](../03-custom-function-tool-agent/README.md)          |
| Send all of this to **Application Insights** for queryable traces | [Sample 04, tracing](../04-tracing-agent/README.md) |
| See the **full workshop arc**                                                                         | [Root README](../README.md#-hands-on-samples--the-learning-arc)                         |

## Microsoft references

* [Foundry model provider and client configuration](https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/model-providers/microsoft-foundry)
* [Create Foundry resources, deploy a model and grant project access](https://learn.microsoft.com/en-us/azure/foundry/tutorials/quickstart-create-foundry-resources?tabs=portal)
* [Agent sessions and conversation state](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/session)
