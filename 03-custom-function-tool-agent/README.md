# Sample 03 · An agent that calls your own Python functions

> **What this lab teaches.** Sample 02 showed an agent calling a
> *remote* tool over MCP. Here you'll do the opposite extreme: give the
> agent a **plain Python function** living inside the same script. No
> additional server or MCP connection. The model still runs in Foundry.
> The model decides when to call the function, the
> framework wires up the arguments, and you write business logic the way
> you always have. By the end you'll understand exactly when to reach for
> a local function tool vs an MCP server.

**Time to complete:** 15 minutes
**Difficulty:** ⭐⭐ Intermediate. Assumes you've completed sample 01

---

## Table of contents

- [What you will learn](#what-you-will-learn)
- [Prerequisites](#prerequisites)
- [Local function tools vs MCP: the trade-off](#local-function-tools-vs-mcp-the-trade-off)
- [How the framework discovers your function](#how-the-framework-discovers-your-function)
- [Step-by-step code walkthrough](#step-by-step-code-walkthrough)
  - [Section 1 · Imports and `.env` loader](#section-1--imports-and-env-loader)
  - [Section 2 · Configuration and fail-fast check](#section-2--configuration-and-fail-fast-check)
  - [Section 3 · The function tool](#section-3--the-function-tool)
  - [Section 4 · `main()`: wiring the function as a tool](#section-4--main-wiring-the-function-as-a-tool)
  - [Section 5 · The streaming loop with tool-call visibility](#section-5--the-streaming-loop-with-tool-call-visibility)
- [Running the sample](#running-the-sample)
- [Expected output](#expected-output)
- [Troubleshooting](#troubleshooting)
- [Exercises](#exercises)
- [What you've learned](#what-youve-learned)
- [Where to go next](#where-to-go-next)

---

## What you will learn

By the end of this lab you will be able to:

1. **Define a Python function as an agent tool**, and explain exactly how
   the model knows what arguments it takes.
2. **Choose between a local function and an MCP server** for a given task.
3. **See the tool-call event in the streaming response** and understand
   what's happening on the wire.
4. **Apply the docstring-as-schema convention** so the model's tool-call
   arguments are correctly typed.

---

## Prerequisites

| Requirement                                                       | Why                                                                                                           |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **You've completed sample 01**                                    | The four building blocks (credential, client, agent, thread) are not re-explained here.                       |
| **Python 3.13** | Use the same Python version as the setup instructions and local verification. |
| **A Microsoft Foundry project** with a **gpt-4o** deployment      | Same as samples 01 and 02.                                                                                     |
| **Azure CLI signed in** (`az login`)                              | `AzureCliCredential` reads your CLI login.                                                                     |
| **A configured `.env` file in this folder**                       | Holds your project endpoint and model name. See [Step 1 below](#step-1-configure-your-env-file).              |
| **VS Code with the Python extension** (optional) | Select the sample's virtual environment. The script loads `.env`. Debug breakpoints work inside `get_time()`. |

### Step 1: Configure your `.env` file

This sample reads configuration from a `.env` file **in this folder**.

1. **Create `.env` only if it is missing. Preserve existing values:**
   ```bash
   cd "$(git rev-parse --show-toplevel)"
   cd 03-custom-function-tool-agent
   test -f .env || cp .env.example .env
   ```

   In Windows PowerShell, use:
   ```powershell
   Set-Location -LiteralPath (git rev-parse --show-toplevel)
   Set-Location 03-custom-function-tool-agent
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   ```

2. **Open `.env` in VS Code** and fill in:

   | Variable                    | Where to find it                                                                                                                       |
   | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
   | `FOUNDRY_PROJECT_ENDPOINT`  | Foundry portal → **your project → Overview**. Copy the **project endpoint URL** (ends in `/api/projects/<project-name>`).               |
   | `FOUNDRY_MODEL`             | The **deployment name** of a chat model in your project. Defaults to `gpt-4o`.                                                          |

If you already configured `.env` in sample 01, you can copy the same values
over. Both samples need the same two variables.

> **Security.** `.env` is **gitignored** at the repo root.
> **Fail-fast behaviour.** Run the script without a configured `.env` and
> you'll get a clear error pointing back here, not a confusing 404.

---

## Local function tools vs MCP: the trade-off

You now know two ways to give an agent capabilities. When do you reach for
each?

| Dimension                          | Local Python function (this sample)                                       | Remote MCP server (sample 02)                                                |
| ---------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **Where the code runs**            | In your Python process                                                    | In an HTTP service somewhere                                                  |
| **Latency**                        | Microseconds                                                              | Tens to hundreds of milliseconds                                              |
| **Deployment**                     | Ship with your agent                                                      | Independent service, independent versioning                                   |
| **Sharing across teams / agents**  | Hard. Copy the function or extract a library                              | Trivial. Point another agent at the same URL                                  |
| **Auth / authorisation**           | Inherits the agent's process identity                                     | Each call can flow a separate token                                            |
| **Sandboxing**                     | Same process, bad function = bad agent                                     | Process isolated, can be hardened independently                                |
| **Discovery by other agents**      | None                                                                      | `tools/list` JSON-RPC, language-agnostic                                       |
| **Best for…**                      | Quick utilities, in-process calculations, talking to local files          | Anything shared across multiple agents, written by a different team, or that needs its own scaling story |

**Rule of thumb:** Start local. The moment a second agent in a different
codebase needs the same capability, **promote it to an MCP server**.

---

## How the framework discovers your function

The single most important thing to internalise about local function tools
is this:

> **The model sees your function's name, signature, type hints, and
> docstring, and that's it.** Everything else (your variable names,
> comments, internal logic) is invisible.

So when you write a function like:

```python
def get_time() -> str:
    """Get the current UTC time."""
    current_time = datetime.now(timezone.utc)
    return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
```

…the model receives a tool spec roughly equivalent to:

```json
{
  "name": "get_time",
  "description": "Get the current UTC time.",
  "parameters": { "type": "object", "properties": {}, "required": [] },
  "returns": "string"
}
```

That JSON spec is the **only** thing the model uses to decide:
1. Whether to call `get_time` for a given user prompt.
2. What arguments to pass (none in this case).
3. How to interpret the returned string.

**Three concrete consequences:**

- A **bad docstring** = the model never calls your tool. Treat the
  docstring as critically as you treat the system prompt.
- **Type hints matter.** `def f(x)` gives the model nothing. `def f(x: int)`
  gives it a clear schema.
- **Argument names matter.** `def find_user(q: str)` vs
  `def find_user(email: str)` produces different tool-call behaviour. The
  model literally reads the names.

---

## Step-by-step code walkthrough

Open [`03-custom-function-tool-agent.py`](03-custom-function-tool-agent.py)
side-by-side with this guide.

### Section 1 · Imports and `.env` loader

```python
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
```

| Import                                              | Purpose                                                                                                                                                                                |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `asyncio`, `os`, `Path`, `load_dotenv`              | Read the `.env` file in this folder into `os.environ` so the rest of the script can `os.environ.get(...)`. Same pattern as sample 01.                                                  |
| `Agent`                                             | Same class as samples 01 and 02.                                                                                                                                                       |
| `FoundryChatClient`                                 | The Foundry transport, lives in the separate `agent-framework-foundry` package.                                                                                                        |
| `AzureCliCredential`                                | Sync credential that reads your `az login` token. Matches the sync `Agent` constructor in this script.                                                                                 |
| `from datetime import datetime, timezone`           | Used by our tool function. This is the entire reason `get_time()` works, and a reminder that local function tools can use any Python library you can `pip install`.                    |

> **Note.** Load `.env` before reading configuration values. Resolving its
> path from `__file__` keeps terminal runs and VS Code on the same settings.

The script imports `configure_console`, `print_stream` and `project_endpoint`
from [`_workshop.py`](../_workshop.py) using the resolved repository root.
Keep that helper with the cloned sample folders.

> **Mixing tools.** Want to add an MCP server alongside `get_time`? Call
> `client.get_mcp_tool(...)` (see sample 02) and pass it in the same `tools=[...]`
> list. The framework treats each entry by type.

### Section 2 · Configuration and fail-fast check

```python
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
```

Three things worth pointing out:

1. **`load_dotenv` populated `os.environ`.** When `python-dotenv` runs at
   import time (in Section 1), the values in `.env` are merged into the
   process environment. So `os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")`
   here returns whatever you wrote in `.env`. **Real environment variables
   set in the shell take precedence over `.env`**. Useful for CI / Docker.
2. **The fail-fast check** catches the most common workshop mistake (forgot
   to fill in `.env`) before any HTTP call. The error message tells you
   exactly what to do.
3. **`AGENT_INSTRUCTIONS` mentions UTC time explicitly.** This *nudges* the
   model to use the tool. Without that hint, gpt-4o might confidently
   make up a time. The system prompt and the available tools work together,
   change one, expect the other to behave differently.

### Section 3 · The function tool

```python
def get_time() -> str:
    """Get the current UTC time."""
    current_time = datetime.now(timezone.utc)
    return f"The current UTC time is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
```

Four lines that do **three jobs**:

1. **`def get_time() -> str:`** is the tool's *contract*: it takes no
   arguments and returns a string. The model sees this exact shape.
2. **`"""Get the current UTC time."""`** is the tool's *description* to the
   model. Be specific. "Get the time" vs "Get the current UTC time" are
   very different signals.
3. **Body** is the actual logic. The model never sees this. You can change the
   implementation freely without re-introducing the tool.

> **Deep dive · Async vs sync tool functions.** This one is sync. The Agent
> Framework accepts both. Use an asynchronous client for I/O, or move
> blocking work to a thread with `asyncio.to_thread()`. Adding `async def`
> alone does not make blocking code asynchronous. A short call such as
> `datetime.now()` is fine in this synchronous tool.

### Section 4 · `main()`: wiring the function as a tool

```python
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
```

Same pattern as sample 01, but **`tools=[get_time]`**. That's the entire
mechanic for adding a Python function as a tool. Put a reference to it in
the `tools` list.

You can mix and match:

```python
tools=[get_time, mcp_search_tool, get_user_profile]
```

The framework introspects each entry. Plain function becomes a local
function tool. An MCP-tool object (from `client.get_mcp_tool(...)`) is
registered as an MCP tool. Same list, multiple kinds. The model sees a flat
menu.

### Section 5 · The streaming loop with tool-call visibility

```python
        for user_input in USER_INPUTS:
            print(f"\n# User: '{user_input}'")
            print(f"# {AGENT_NAME}: ", end="", flush=True)

            await print_stream(
                agent.run(user_input, stream=True),
                show_tools=True,
                agent_name=AGENT_NAME,
            )
            print()
```

Each streaming update contains typed `Content` objects. The shared renderer
handles three relevant content types. It merges function call fragments by
`call_id` and displays each completed call and its result once. Text updates
can append text or replace an earlier snapshot, so printing every update
verbatim would duplicate the answer.

| Content `type`      | When it appears                                                | What we print                              |
| ------------------- | -------------------------------------------------------------- | ------------------------------------------ |
| `text` | Text deltas or complete replacement snapshots arrive. | Only new text, or an explicit correction label. |
| `function_call` | The model supplies a tool name and arguments. | Stored until the corresponding result arrives. |
| `function_result`   | The framework has run the function and is returning its value. | `[tool result] The current UTC time is ...` |

Walk through what happens on a single user prompt:

```
   ┌──────────────────────────────────────────────────────────────────────┐
   │  agent.run("What is the current time in UTC?", stream=True)          │
   │                                                                      │
   │   Chunk #1   contents=[function_call(name=get_time, args={})]        │
   │              records the call and merges its argument fragments     │
   │                                                                      │
   │   (framework invokes get_time(), captures the return value)          │
   │                                                                      │
   │   Chunk #2   contents=[function_result(result="The current UTC...")] │
   │              prints the completed call, then its result              │
   │                                                                      │
   │   Chunk #3   contents=[text("The")]                                  │
   │   Chunk #4   contents=[text(" current")]                             │
   │   Chunk #5   contents=[text(" UTC")]                                 │
   │   ...        contents=[text(" time is 2026-06-15 04:59:20.")]        │
   └──────────────────────────────────────────────────────────────────────┘
```

The helper uses public `Content` attributes such as `call_id`, `name`,
`arguments` and `merge_mode`. It also obtains the final response and closes
the stream. Both direct iteration of `agent.run(..., stream=True)` and the
awaited streaming form are supported by the pinned SDK.

---

## Running the sample

Run the complete command block after configuring `.env` above. With Git
installed, the first command returns to the repository root from any folder
inside the clone. Use the same repository `.venv` as samples 01, 02, 04 and 06.
Install the compatible SDK set from
[`requirements-first-four.txt`](../requirements-first-four.txt).

### Windows PowerShell

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
.\.venv\Scripts\python.exe -m pip check
az login
.\.venv\Scripts\python.exe -X utf8 .\03-custom-function-tool-agent\03-custom-function-tool-agent.py
```

### macOS or Linux with Bash

```bash
cd "$(git rev-parse --show-toplevel)"
test -x .venv/bin/python || python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-first-four.txt
.venv/bin/python -m pip check
az login
.venv/bin/python -X utf8 03-custom-function-tool-agent/03-custom-function-tool-agent.py
```

Activation is optional. Calling the virtual environment Python directly
avoids PowerShell execution policy issues. In VS Code, open the repository
root and use **Python: Select Interpreter** to select `.venv/bin/python` on
macOS or `.venv\Scripts\python.exe` on Windows. Use **Run Python File**.
The script loads `.env` from its own sample folder.

Unexpected errors exit with a nonzero status. An interruption exits with `130`.

Installation uses your configured package feed. Do not add a public PyPI
override when downloads from `files.pythonhosted.org` time out.

Dependency installation and offline regression checks have passed on macOS
with Python 3.13. Windows execution and live Azure runs remain unverified.

---

## Expected output

```
# User: 'What is the current time in UTC?'
# time-agent: 
[tool call] get_time({})
[tool result] The current UTC time is 2026-06-15 04:59:20.
# time-agent: The current time in UTC is June 15, 2026, at 04:59:20.

--- All tasks completed successfully ---
Program finished.
```

You should see **three distinct things** in the output:

1. A `[tool call]` line showing the completed call when its result arrives.
   The arguments are `{}` because the function takes none. This is not an
   execution start timestamp.
2. A `[tool result]` line, emitted when the framework has executed the
   function and is feeding the return value back to the model.
3. The **final answer** that incorporates the tool's return value. The
   model doesn't just echo the tool result, it weaves it into a natural
   sentence. After the tool returns, the model gets another turn to compose
   the final user-facing reply.

If you see only the final answer with no `[tool call]` line, the model
chose not to call your tool. Tighten the system prompt, for example
*"Always use the get_time tool when asked about time"*, and try again.

---

## Troubleshooting

| Symptom                                                    | Cause                                                                                                | Fix                                                                                                                                                                |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `RuntimeError: FOUNDRY_PROJECT_ENDPOINT is not configured` | You haven't created `.env`, or `.env` still has the `<YOUR_…>` placeholder.                          | `cp .env.example .env` and fill in the two values. See [Prerequisites → Step 1](#step-1-configure-your-env-file).                                                  |
| `[tool call]` line never appears | The model did not call the tool, or execution failed before a result arrived. | Check the error output and keep the instruction to use `get_time` for current time questions. |
| `TypeError: get_time() takes 0 positional arguments but 1 was given` | You added an argument to `get_time` but didn't update the type hint, and the model passed an unexpected payload. | Add a typed argument: `def get_time(timezone: str = "UTC") -> str`, and update the docstring. The model's tool-call args will line up.                              |
| `CredentialUnavailableError`                                | Not signed in to Azure CLI.                                                                          | `az login` (optionally `az login --tenant <YOUR_TENANT_ID>`).                                                                                                       |
| `'Agent' object has no attribute 'run_stream'` | Old API usage. | Use `await print_stream(agent.run(user_input, stream=True), show_tools=True, agent_name=AGENT_NAME)`. |
| `DeploymentNotFound` / `404`                                | `MODEL_DEPLOYMENT_NAME` is wrong.                                                                    | Check the Foundry portal → **Models + Endpoints** for the exact name.                                                                                                |
| Tool runs but the model ignores the result                  | The function returns something the model can't usefully interpret (e.g., a complex object).           | Return a **clear, human-readable string**. The model "sees" the return value as text. Avoid returning huge JSON blobs unless you also instruct the model how to parse them. |
| `429` or `Too Many Requests` | The deployment quota is too small for the request or the full tool exchange. | Allow the quota window to reset or use an appropriately sized deployment. A tool round trip requires more than one model call. |

---

## Exercises

1. **Add a `city` parameter** to `get_time(city: str = "UTC") -> str` and
   teach it to return the local time for that city (use `zoneinfo` from the
   standard library). Re-run with the prompt *"What time is it in Tokyo?"*
   and watch the model fill in the `city` argument from the prompt. No
   extra parsing on your side.
2. **Add a second tool** `get_date()` that returns today's date as a string.
   Put both in `tools=[get_time, get_date]`. Ask *"What's the date and time
   in UTC?"* and observe the model call **both** tools before composing the
   final answer.
3. **Mix local and MCP.** Add an MCP tool for `https://learn.microsoft.com/api/mcp`
   alongside `get_time` (use `client.get_mcp_tool(name="MicrosoftLearn", url=..., approval_mode="never_require")` from sample 02). Ask the model *"Look up the Foundry MCP docs and tell me what time it is in UTC."* The model picks one tool per claim, one for the lookup and one for the time.
4. **Return JSON instead of a sentence.** Change `get_time` to return
   `{"utc": "2025-05-24T22:50:08Z"}` (as a JSON string). The model usually
   still incorporates it correctly, *because* the JSON keys are
   self-describing. Confirm by inspecting the streamed response.
5. **Break the docstring on purpose.** Change `"""Get the current UTC time."""`
   to `"""Function."""`. Re-run. Most of the time, the model will refuse to
   call the tool. That's the practical importance of docstrings.

---

## What you've learned

You can now:

- **Wire a Python function as an agent tool** with one item in a `tools=[…]`
  list.
- **Predict whether the model will call your tool** by inspecting just the
  signature, type hints, and docstring.
- **Read tool-call events** in the streaming response so you can log them,
  meter them, or block them.
- **Decide on the right boundary** for a tool: local function for in-process
  utilities, MCP server for anything shared.

You've now seen the **two fundamental tool flavours** in the Agent
Framework. Everything else is variations on these themes. Built-in tools
(Bing search, code interpreter) are pre-defined hosted-tool classes.
OpenAPI tools auto-generate function tools from an OpenAPI spec. Custom
authentication on MCP is a wrapper around the MCP tool object returned by
`client.get_mcp_tool(...)`.

---

## Where to go next

| If you want to…                                                                          | Go to                                                                  |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Add **OpenTelemetry tracing** so you can query tool latency and optional captured arguments | [Sample 04, tracing](../04-tracing-agent/README.md) |
| **Build your own MCP server** and have a Foundry agent call its tools                    | [Sample 06 · Weather MCP agent](../06-weather-mcp-agent/README.md)      |
| Give the agent **its own Entra identity** and call an authenticated downstream API       | [Sample 05 · End-to-end with Entra Agent ID](../05-end-to-end-agent/)   |
| See the **full workshop arc**                                                            | [Root README](../README.md#-hands-on-samples--the-learning-arc)          |
