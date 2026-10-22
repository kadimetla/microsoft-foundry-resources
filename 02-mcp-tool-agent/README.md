# Sample 02 · An agent that calls tools (Model Context Protocol)

> **What this lab teaches.** In sample 01 you built an agent that could
> only *talk*. Here you'll give an agent its first **tool** so it can
> actually *do* something — specifically, search the Microsoft Learn
> documentation library through the **Model Context Protocol (MCP)**.
> Along the way you'll learn three different patterns for *defining* an
> agent: **pure-code**, **portal-first**, and **hybrid (GitOps)** — and
> when to use each.

**Time to complete:** 25 minutes (10 min for variant A, +5 min each for B and C)
**Difficulty:** ⭐⭐ Intermediate — assumes you've completed sample 01
**Files in this folder:** 3 runnable Python files + 2 helper modules

---

## Table of contents

- [What you will learn](#what-you-will-learn)
- [Prerequisites](#prerequisites)
- [Three patterns at a glance](#three-patterns-at-a-glance)
- [What is the Model Context Protocol?](#what-is-the-model-context-protocol)
- [Variant A · `02-mcp-tool-agent.py` (pure code)](#variant-a--02-mcp-tool-agentpy-pure-code)
  - [Code walkthrough](#code-walkthrough)
  - [Running it](#running-it)
  - [Expected output](#expected-output)
- [Variant B · `02b-portal-agent.py` (portal-first)](#variant-b--02b-portal-agentpy-portal-first)
  - [How to build the portal agent](#how-to-build-the-portal-agent)
  - [Code walkthrough](#code-walkthrough-1)
  - [Running it](#running-it-1)
- [Variant C · `02c-hybrid-agent.py` (hybrid / GitOps)](#variant-c--02c-hybrid-agentpy-hybrid--gitops)
  - [Code walkthrough](#code-walkthrough-2)
  - [Running it](#running-it-2)
  - [Cleaning up the portal agent](#cleaning-up-the-portal-agent)
- [Observability — `_observability.py` explained](#observability--_observabilitypy-explained)
- [The shared `.env` file](#the-shared-env-file)
- [Verifying traces with `verify_observability.py`](#verifying-traces-with-verify_observabilitypy)
- [KQL cookbook (run these in the portal)](#kql-cookbook-run-these-in-the-portal)
- [Troubleshooting](#troubleshooting)
- [Exercises](#exercises)
- [What you've learned](#what-youve-learned)
- [Where to go next](#where-to-go-next)

---

## What you will learn

By the end of this lab you will be able to:

1. **Explain MCP**, what it is, what problem it solves, and how it differs
   from "the agent calls a Python function".
2. **Attach a remote MCP server** as a tool to a Foundry agent in three lines.
3. **Choose the right pattern** (code vs portal vs hybrid) for defining
   agents in production.
4. **Use `FoundryChatClient` and `FoundryAgent`** and know when to use each.
5. **Trace model and agent operations** in Application Insights, with
   optional prompt and answer content capture.

---

## Prerequisites

| Requirement                                                          | Why                                                                                                                                                |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **You've completed sample 01**                                       | The four building blocks (credential, client, agent, thread) are not re-explained here.                                                            |
| **Python 3.13** | Use the same Python version as the setup instructions and local verification. |
| **A Microsoft Foundry project** with a **gpt-4o** deployment         | Same as sample 01.                                                                                                                                  |
| **Azure CLI signed in** (`az login`)                                 | All three variants use `AzureCliCredential` so the CLI session is the auth source.                                                                  |
| **An Application Insights resource attached to your Foundry project** | For tracing. Find it via **Foundry portal → your project → Manage → Tracing**. Optional — the samples run without it but emit no telemetry.         |
| **VS Code with the Python and Azure Tools extensions** (recommended) | The integrated terminal hosts every command in this lab.                                                                                            |

> **Note.** All three variants in this folder share one `.env` file. Copy
> `.env.example` to `.env` only if it is missing. Preserve existing values.

From the repository root, copy the configuration using either shell:

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
Set-Location 02-mcp-tool-agent
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

```bash
cd "$(git rev-parse --show-toplevel)"
cd 02-mcp-tool-agent
test -f .env || cp .env.example .env
```

Edit `.env` before running a variant. Keep
[`_workshop.py`](../_workshop.py) at the repository root because the samples
use its shared endpoint checks, console handling and tracing lifecycle.

---

## Three patterns at a glance

Picture this folder as **three solutions to the same problem**: *"I want
an agent that can search Microsoft Learn."* All three end up calling the
same MCP server (`https://learn.microsoft.com/api/mcp`) — they just disagree
on **where the agent definition lives**.

```
                           Where does the agent definition live?

                  ┌────────────────────────────────────────────────────────────┐
                  │                                                            │
                  │   Pure code (02)         Portal (02b)        Hybrid (02c)  │
                  │   ────────────────       ─────────────       ────────────  │
                  │                                                            │
   Source of      │   the .py file ✓         the portal UI ✓      the .py file ✓
   truth          │                                                            │
                  │                                                            │
   Visible in     │   ✗ (ephemeral)          ✓ (you built it)     ✓ (auto-     │
   portal?        │                                              │     created) │
                  │                                                            │
   Persists       │   ✗ deleted on exit      ✓ stays forever     ✓ stays      │
   between runs?  │                                              │  forever     │
                  │                                                            │
   Audit trail?   │   ✗                      portal only          ✓ git diff +  │
                  │                                              │  portal      │
                  │                                              │  versioning  │
                  │                                                            │
   Best for       │   demos, scripts,        agent built by a    real teams    │
                  │   getting started        non-developer        shipping code │
                  │                                                            │
                  └────────────────────────────────────────────────────────────┘
```

**Rule of thumb for production:**
- **02 (pure code)** when the agent is short-lived (a CI job, a test, a one-off batch).
- **02b (portal-first)** when a non-developer (a domain expert) writes prompts and tools.
- **02c (hybrid)** when an engineering team owns the agent and wants the portal as a *read-only mirror* of git.

---

## What is the Model Context Protocol?

**MCP is a JSON-RPC protocol** that lets a language model discover and call
*tools* hosted on a server, without the model — or the agent code —
needing per-tool client code.

```
   ┌──────────────────┐        JSON-RPC 2.0 over HTTPS         ┌────────────────────┐
   │  Foundry agent   │                                         │   MCP server       │
   │  (gpt-4o brain)  │ ─── tools/list ───────────────────────► │   (Microsoft Learn)│
   │                  │ ◄────────── tool schemas ──────────── ──│                    │
   │                  │                                         │   exposes:         │
   │                  │ ─── tools/call ──── { name, args } ────►│   • search_docs    │
   │                  │ ◄────────── tool result ──────────── ──│   • fetch_page     │
   │                  │                                         │   • …              │
   └──────────────────┘                                         └────────────────────┘

   The model never sees JSON-RPC. It just sees "you have these tools".
   The agent never sees per-tool code. It just sees "the model wants me to call X."
```

**Why this matters for you as a Foundry user:**

1. **One protocol, every tool.** Once the agent speaks MCP, you can attach
   *any* MCP server (Microsoft Learn, GitHub, Slack, your own) with a single
   line of configuration. No client SDK per tool.
2. **Discovery at runtime.** The agent asks the server "what tools do you
   have?" and the model sees those tools' descriptions on the very next
   turn. You can ship new tools without changing client code.
3. **Standardisation.** Anthropic, OpenAI, and Microsoft all support MCP.
   The MCP server you build today is portable.

> **Curious about a deeper dive?** Sample 06 in this repo (`06-weather-mcp-agent/`)
> walks you through **building your own MCP server** on Azure Functions.
> This sample just *consumes* one.

---

## Variant A · `02-mcp-tool-agent.py` (pure code)

The agent's entire definition lives in the file. When you run the script,
the agent is constructed in memory, sent to the LLM for one or more turns,
and discarded.

### Code walkthrough

Open [`02-mcp-tool-agent.py`](02-mcp-tool-agent.py) side-by-side.

#### Imports

```python
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential

from _observability import init_observability, project_endpoint, shutdown_tracing
```

| Import | What it does |
| ------ | ------------ |
| `from agent_framework import Agent` | The current top-level agent class. Same building block you used in sample 01. |
| `from agent_framework.foundry import FoundryChatClient` | Foundry-specific chat client. It is the path that unlocks `get_mcp_tool()`. The package on PyPI is `agent-framework-foundry`. |
| `from azure.identity import AzureCliCredential` | Synchronous CLI credential. The sync version removes the need for `async with` ceremony on the credential. |
| `from _observability import init_observability` | The shared observability module. See [its dedicated section below](#observability--_observabilitypy-explained). |
| `load_dotenv(...)` | Reads `.env` from the same folder as the script. Done before importing `PROJECT_ENDPOINT` so module-level `os.environ.get` calls see the file contents. |

> **Why `agent-framework-foundry` is a separate package.** The core
> `agent-framework-core` package contains provider abstractions
> (`Agent`, sessions, harness, tools). Each backend (Foundry, OpenAI direct,
> Azure OpenAI, Bedrock, Vertex) ships as its own package so installs stay
> small. `agent-framework-foundry` adds the `agent_framework.foundry`
> namespace with `FoundryChatClient`, `FoundryAgent`, and MCP tool helpers.

#### Configuration

```python
PROJECT_ENDPOINT = project_endpoint()
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

AGENT_NAME = "mcp-learn-agent-codefirst"
AGENT_INSTRUCTIONS = "You answer questions by searching Microsoft Learn content only."

USER_INPUTS = [
    "Please summarize the Azure AI Agent documentation related to MCP tool calling?",
]
```

`project_endpoint()` reads the configured project endpoint and rejects
missing values or angle bracket placeholders before making a network call.
`FOUNDRY_MODEL` is the deployment name, not necessarily the model family.

#### Initialise observability

```python
async def main() -> None:
    init_observability("pure-code")
```

One line and every span this process emits goes to Application Insights,
tagged with `cloud_RoleName = "foundry-workshop.pure-code"`. The full
mechanics are explained [further down](#observability--_observabilitypy-explained).

#### Create the client

```python
    client = FoundryChatClient(
        model=MODEL,
        project_endpoint=PROJECT_ENDPOINT,
        credential=AzureCliCredential(),
    )
```

The `async with Agent(...)` block below owns the client lifecycle and closes
its resources when the block ends.

#### Define the MCP tool

```python
    mcp_tool = client.get_mcp_tool(
        name="MicrosoftLearn",
        url="https://learn.microsoft.com/api/mcp",
        approval_mode="never_require",
    )
```

This is the heart of the sample. Three arguments:

| Argument | What it does |
| -------- | ------------ |
| `name` | Cosmetic label that appears in traces and the portal's tool view. Avoid spaces in the label, since some server-side parsers reject them. |
| `url` | The MCP endpoint. No authentication is needed for the Microsoft Learn MCP, because it is a public read-only service. Your own MCP servers (like sample 06's `get_weather`) will require an Authorization header. That is covered in sample 06's lab. |
| `approval_mode` | The most important argument. Three values: `"never_require"` auto-approves every tool call (safe for read-only public tools like Microsoft Learn search), `"always_require"` pauses every tool call for explicit human approval (use for any tool that writes or costs money), or a `dict` mapping tool name to mode for per-tool granularity. |

> **Deep dive on tool security.** The single most important question for
> tools is: "what happens if the model calls this with bad arguments?" Use
> `approval_mode="never_require"` only when the answer is "nothing bad,
> ever". Search is fine. `delete_user(id)` is not.

#### Wire up the agent

```python
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
```

Two things to notice:

1. **`tools=[mcp_tool]`** — the *only* difference from sample 01 in
   structural terms. Adding a tool is genuinely one line.
2. **`await agent.run(user_input)`** returns the final response, unlike
   sample 01's `agent.run(..., stream=True)`. The asynchronous call completes
   after the exchanges with
   the model and the tool server has settled — you get the final answer.

### Running it

Run the complete command block after configuring `.env` above. With Git
installed, the first command returns to the repository root from any folder
inside the clone. Use the same repository `.venv` as samples 01, 03 and 04.
Install the compatible SDK set from
[`requirements-first-four.txt`](../requirements-first-four.txt).

The Foundry connector requires `azure-ai-projects>=2.2.0,<2.8.0`, so the
`azure-ai-projects==2.7.0` pin is intentional. Install the requirements as
a set rather than upgrading the Projects SDK independently.

**Windows PowerShell:**

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
.\.venv\Scripts\python.exe -m pip check
az login
.\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\02-mcp-tool-agent.py
```

**macOS or Linux with Bash:**

```bash
cd "$(git rev-parse --show-toplevel)"
test -x .venv/bin/python || python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-first-four.txt
.venv/bin/python -m pip check
az login
.venv/bin/python -X utf8 02-mcp-tool-agent/02-mcp-tool-agent.py
```

Activation is optional. These commands avoid PowerShell execution policy
changes. For a specific tenant, use `az login --tenant YOUR_TENANT_ID`.
Unexpected errors return a nonzero exit status. An interruption exits with `130`.

In VS Code, open the repository root and select `.venv/bin/python` on macOS
or `.venv\Scripts\python.exe` on Windows with **Python: Select Interpreter**.
Each variant loads `.env` from `02-mcp-tool-agent`, regardless of the terminal
directory.

Installation uses your configured package feed. Do not add a public PyPI
override when downloads from `files.pythonhosted.org` time out.

Dependency installation and offline regression checks have passed on macOS
with Python 3.13. Windows execution and live Azure runs remain unverified.

### Expected output

```
[observability] enabled: scenario='pure-code' -> Application Insights

# User: 'Please summarize the Azure AI Agent documentation related to MCP tool calling?'
# mcp-learn-agent-codefirst: The Azure AI Agent documentation describes Model
Context Protocol (MCP) tool calling as follows:

1. **MCP Overview** — MCP is an open standard that lets agents discover and
   invoke tools hosted on external servers without per-tool client code…

2. **Configuration** — You attach an MCP server to an agent by providing its
   URL and an approval policy (`require_approval`)…

3. **Authentication** — MCP servers can be public (like Microsoft Learn) or
   protected. For protected servers, configure custom headers or use
   Microsoft Entra…

(continues with cited Microsoft Learn pages…)

--- All tasks completed successfully ---
Program finished.
```

The number of model calls and tool calls depends on the response. MCP work
can execute on the Foundry service, so inspect correlated server spans as
well as client spans. A completed response alone does not prove the model
used the tool. Look for a successful `execute_tool` span for Microsoft Learn.

---

## Variant B · `02b-portal-agent.py` (portal-first)

In this variant, **the agent definition lives entirely in the Foundry
portal UI**. The Python code only knows the agent's *name* and *version*.

This is the pattern to use when a non-developer (a product manager, a
domain expert) writes the prompt and chooses the tools, and a developer
just needs to invoke it from code.

### How to build the portal agent

Before running `02b-portal-agent.py`, **create the agent in the portal**:

1. Open [https://ai.azure.com](https://ai.azure.com) and select your project.
2. Click **Agents** in the left rail → **+ Create**.
3. Fill in:
   - **Name:** `mcp-learn-agent-portal` (or whatever you prefer)
   - **Model:** `gpt-4o`
   - **Instructions:** *"You are a Microsoft Learn research assistant. Cite the pages you used."*
4. Click **+ Add tool** → **MCP server**, and configure:
   - **Server label:** `MicrosoftLearn`
   - **Server URL:** `https://learn.microsoft.com/api/mcp`
   - **Require approval:** Never
5. Click **Create**. The portal shows your agent with version **1**.

### Code walkthrough

Open [`02b-portal-agent.py`](02b-portal-agent.py).

#### Imports

```python
import asyncio
import os

from agent_framework.foundry import FoundryAgent
from azure.identity import AzureCliCredential

from _observability import init_observability
```

The headline change: **`FoundryAgent`** instead of the `Agent + Client +
get_mcp_tool` trio. `FoundryAgent` is purpose-built for "load an existing
portal agent by name and version".

#### Configuration

```python
PROJECT_ENDPOINT = project_endpoint()

AGENT_NAME = os.environ.get("PORTAL_AGENT_NAME", "<YOUR_PORTAL_AGENT_NAME>")
AGENT_VERSION = os.environ.get("PORTAL_AGENT_VERSION", "1")

USER_INPUTS = [
    "In one short sentence, tell me what kinds of questions you are designed to answer.",
]
```

Notice the **complete absence of instructions, tools, or model**. The whole
agent definition is on the server side. The script knows only the agent's
*identity*: `(name, version)`.

#### The runtime

```python
async def main() -> None:
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
```

The `FoundryAgent` constructor takes four arguments and *that's it*. The
project endpoint tells it where the agent lives; `agent_name` + `agent_version`
identify which one to load; `credential` is your CLI session.

> **Deep dive · Versions are immutable.** Each time you edit and save the
> agent in the portal, the portal creates a **new version**. You pin your
> code to `agent_version="1"` (or `"2"`, …) so a portal edit never silently
> changes your script's behaviour. To use a new portal version, update
> `PORTAL_AGENT_VERSION` to that version explicitly.

### Running it

Use the same virtual environment as variant A. Set `PORTAL_AGENT_NAME` and
`PORTAL_AGENT_VERSION` to an existing agent and its version. Run from the
repository root.

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
.\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\02b-portal-agent.py
```

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -X utf8 02-mcp-tool-agent/02b-portal-agent.py
```

**Expected output:**

```
[observability] enabled: scenario='portal-first' -> Application Insights
Connecting to portal agent: mcp-learn-agent-portal (version 1)

# User: In one short sentence, tell me what kinds of questions you are designed to answer.

# mcp-learn-agent-portal:
I'm designed to answer questions about Microsoft technologies (Azure, .NET, M365,
etc.) by searching the official Microsoft Learn documentation library.

--- All tasks completed successfully ---
Program finished.
```

Now go back to the portal, edit the agent's instructions to say *"…in
pirate slang…"*, save (creates version 2), bump
`PORTAL_AGENT_VERSION=2` in `.env`, and re-run. Same code, completely new
personality. **That's the value of portal-first.**

---

## Variant C · `02c-hybrid-agent.py` (hybrid / GitOps)

This is the **production pattern**. The agent definition is **in your
git-tracked Python file**, but it's *also* registered server-side so the
portal can show it, audit it, and let you query its versions.

The first run of the script creates the agent in the portal. Subsequent
runs reuse it. Editing the in-file `AGENT_DEFINITION` and re-running adds
a new server-side version — the portal becomes a *mirror* of git, not the
source of truth.

### Code walkthrough

Open [`02c-hybrid-agent.py`](02c-hybrid-agent.py).

#### The typed agent definition

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition

MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")
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
```

The Azure AI Projects SDK provides typed definitions and agent version
operations. The model, instructions, MCP endpoint and approval policy are
declared in code. `FOUNDRY_MODEL` applies to both variants A and C.

#### Reuse or publish a version

```python
def ensure_agent(project: AIProjectClient) -> str:
    try:
        existing = project.agents.get(AGENT_NAME).versions.latest
    except ResourceNotFoundError:
        existing = None

    if existing is not None and (
        _without_nulls(existing.definition.as_dict())
        == _without_nulls(AGENT_DEFINITION.as_dict())
    ):
        return existing.version

    version = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=AGENT_DEFINITION,
    )
    return version.version
```

The script imports `ResourceNotFoundError` from `azure.core.exceptions`.
Its `_without_nulls` helper recursively omits null dictionary fields before
comparison, so optional fields omitted by the service do not create differences.
List order and nonnull fields are preserved.

1. Read the latest agent version through `project.agents.get(...)`.
2. Reuse that exact version when the definitions match.
3. Call `project.agents.create_version(...)` when the agent is missing or
   the definition changed.

Authentication failures, forbidden access, throttling and server errors
propagate. They are not treated as evidence that the agent is missing.
Running this script can publish an agent version. It never deletes one.

#### The main flow

```python
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
```

Sequence:

1. Let `AIProjectClient` authenticate through `AzureCliCredential`.
2. Call the synchronous `ensure_agent(project)` helper and close the SDK client.
3. Invoke the selected version with `FoundryAgent`, as in variant B.

### Running it

The pinned requirements already include the Projects SDK. Use the same
virtual environment as variants A and B and run from the repository root.
This command can create an Azure agent version. Run it only when you intend
to test that behavior.

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
.\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\02c-hybrid-agent.py
```

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -X utf8 02-mcp-tool-agent/02c-hybrid-agent.py
```

**First run output:**

```
[observability] enabled: scenario='hybrid' -> Application Insights
Hybrid pattern: code defines 'mcp-learn-agent-hybrid', server hosts it.

  Published agent 'mcp-learn-agent-hybrid', version 1

# User: Please summarize the Azure AI Agent documentation related to MCP tool calling?

# mcp-learn-agent-hybrid:
The Azure AI Agent documentation describes MCP (Model Context Protocol)
tool calling as follows…
```

**Second run** (no code change):

```
  Reusing unchanged agent 'mcp-learn-agent-hybrid', version 1
```

**Third run**, after editing `AGENT_DEFINITION.instructions`:

```
  Published agent 'mcp-learn-agent-hybrid', version 2
```

Version numbers shown here are illustrative. The SDK returns the created
version, which the script uses for the subsequent invocation.

### Cleaning up the portal agent

The agent created by 02c **persists in your portal** until you delete it.
That's intentional. To remove a workshop agent, select it in the portal's
Agents panel and delete it only after confirming you no longer need its versions.

Same goes for the agent you built by hand in variant B — delete it from
the portal's Agents panel when you're done with the workshop.

---

## Observability — `_observability.py` explained

All three variants begin with `init_observability("<scenario>")`.
The wrapper delegates configuration to [`_workshop.py`](../_workshop.py).
It enables export of agent, model and supported HTTP instrumentation to
Application Insights. Foundry service spans can appear in the same trace.

Open [`_observability.py`](_observability.py) and walk through it:

### Step 1: Read `.env`

```python
load_dotenv(Path(__file__).resolve().parent / ".env")
```

`load_dotenv` reads `.env` from the *same folder as this file* (not the
current working directory). The installed `python-dotenv` dependency is
required. Import or configuration errors are not silently swallowed.

### Step 2: Report optional tracing configuration

```python
conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
if not conn:
    print("[observability] skipped: APPLICATIONINSIGHTS_CONNECTION_STRING is not set.")
    return
```

If the connection string is missing, the variants still run and explicitly
report that tracing was skipped. Once tracing is configured, an exporter
configuration failure is an error rather than a silent fallback.

### Step 3: Configure scenario labels and sampling

```python
configure_tracing(conn, scenario)
```

The helper sets the default service name to `foundry-workshop.<scenario>`
and requests full trace sampling for these small workshop runs.
The service name maps to `cloud_RoleName`. Leave `OTEL_SERVICE_NAME` unset
for the verifier's default workshop filters.
The three scenario names are `pure-code`, `portal-first` and `hybrid`.

### Step 4: Respect content capture settings and flush on exit

```python
from agent_framework.observability import enable_instrumentation
from azure.monitor.opentelemetry import configure_azure_monitor

configure_azure_monitor(connection_string=conn, resource=resource, sampling_ratio=1.0)
enable_instrumentation()
```

Here `resource` is the OpenTelemetry `Resource` constructed by the helper.
`configure_azure_monitor` configures the exporter and supported instrumentation.
`enable_instrumentation()` refreshes the framework's instrumentation settings
without replacing the provider or forcing sensitive capture on.

`ENABLE_SENSITIVE_DATA=false` is the example configuration. Timing, model
metadata and reported token usage remain available. Set it to `true` only
when you intend to export prompts, answers and tool content. The old
`AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED` and
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` flags are not the
framework's content capture control in this SDK set.

Each entry point calls `shutdown_tracing()` in `finally`. The helper checks
`force_flush()` and then shuts down the tracing provider. A flush timeout
returns an error. Successful flushing is not proof of ingestion, so verify
the correlated trace after Azure has processed it.

### The KQL view

Once traces are flowing, this is the canonical *"show me every workshop
run, by scenario"* query. Run it in the **Foundry portal → Tracing →
KQL** tab, or in your Application Insights resource directly:

```kql
union dependencies, requests
| where timestamp > ago(15m)
| where cloud_RoleName startswith "foundry-workshop."
| project timestamp, scenario=tostring(customDimensions["workshop.scenario"]),
          name, duration, customDimensions
| order by timestamp desc
```

The query includes agent and model spans as well as supported HTTP spans.
Use `operation_Id` to follow a particular run across client and service roles.

---

## The shared `.env` file

[`.env.example`](.env.example) lists every variable used by the variants
and the helpers in this folder. Copy it to `.env` and fill in your values.

| Variable                                       | Used by             | What to put                                                                                                  |
| ---------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------ |
| `FOUNDRY_PROJECT_ENDPOINT`                     | A, B, C             | Your Foundry project endpoint URL.                                                                            |
| `FOUNDRY_MODEL` | A, C | The model deployment name. B uses the model from its pinned portal version. |
| `AZURE_TENANT_ID`                              | (your shell)        | For `az login --tenant <id>` to avoid signing into the wrong directory.                                       |
| `PORTAL_AGENT_NAME`                            | B                   | Name of the agent you built in the portal.                                                                    |
| `PORTAL_AGENT_VERSION`                         | B                   | Usually `1` on first creation.                                                                                |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | A, B, C | Optional. Without it, these scripts skip client trace export. |
| `ENABLE_SENSITIVE_DATA` | A, B, C | Optional conversation content capture. Defaults to `false` in the example. |
| `APPLICATIONINSIGHTS_SUBSCRIPTION_ID` | Verifier | Subscription containing the Application Insights component. |
| `APPLICATIONINSIGHTS_RESOURCE_GROUP` | Verifier | Resource group containing that component. |
| `APPLICATIONINSIGHTS_RESOURCE_NAME` | Verifier | Application Insights component name, not the workspace name. |
| `LOOKBACK_MINUTES` | Verifier | Positive integer. Defaults to `1440`. |
| `OBSERVABILITY_SCENARIO` | Verifier | Optional `pure-code`, `portal-first`, `hybrid` or `tracing` filter. |
| `OBSERVABILITY_TRACE_ID` | Verifier | Optional exact trace ID containing 32 hexadecimal characters. |

`.env` is **gitignored** (the repo's `.gitignore` covers it). Treat it like
a secret file.

---

## Verifying traces with `verify_observability.py`

The verifier selects one agent operation, then runs all five reports against
that same `operation_Id`. It uses `AzureCliCredential` and the Application
Insights query API directly. No Azure CLI monitoring extension or shell
specific query syntax is required.

Run it from the repository root with the virtual environment created above.

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
.\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\verify_observability.py
```

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -X utf8 02-mcp-tool-agent/verify_observability.py
```

Set the three `APPLICATIONINSIGHTS_*` resource settings listed in the table
above. The signed in identity needs access to read that component and query
its telemetry. Allow time for ingestion before running the verifier.

By default, it selects the latest workshop agent operation in the lookback
window. To verify sample 04, set `OBSERVABILITY_SCENARIO=tracing` and set
`OBSERVABILITY_TRACE_ID` to the trace ID printed by that sample.
The Application Insights settings must identify the same component used by
sample 04's connection string.

| Report | What it checks or displays |
| ------ | -------------------------- |
| Q0 | The actual correlated spans across client and service roles, including tool names when recorded. |
| Q1 | Span and log counts for the selected operation. |
| Q2 | Model usage from client `chat` spans only. Parent agent totals and separately collected server totals are excluded. |
| Q3 | Optional captured user text. Empty results are expected when sensitive capture is disabled. |
| Q4 | Optional recorded output content types. These vary by provider and are not a substitute for tool execution spans. |

| Exit status | Meaning |
| ----------- | ------- |
| `0` | A successful agent operation was found and every report query succeeded. A selected sample 04 operation also contains `example-tracing`. |
| `1` | Authentication or query failure, no matching agent data, a failed agent operation, or a missing sample 04 root span. |
| `2` | Missing resource settings, invalid lookback or an invalid trace ID. |

The verifier does not estimate monetary cost or claim that a successful
agent necessarily used MCP. For MCP proof, inspect successful `execute_tool`
spans in Q0 for the selected operation.

---

## KQL cookbook (run these in the portal)

These focused examples use the same correlation approach as the verifier.
Run them in **Application Insights, Logs**. Replace `<TRACE_ID>` in each
query with the selected operation ID. For sample 04, the script prints it.
Using an explicit ID prevents unrelated recent runs from being mixed together.

### Q0: Correlated span waterfall

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| project timestamp, service=cloud_RoleName, name, success, duration,
          tool=tostring(customDimensions["gen_ai.tool.name"])
| order by timestamp asc
```

Successful Microsoft Learn `execute_tool` spans can be on a Foundry service
role rather than the workshop client role. Do not filter those out of Q0.

### Q1: Span counts

```kql
union dependencies, requests, traces
| where operation_Id == "<TRACE_ID>"
| summarize spans=count() by scenario=cloud_RoleName, itemType
| order by scenario, itemType
```

### Q2: Model tokens counted once

An agent span can contain aggregate usage also present on its child model
span. Count only client `chat` spans for this report.

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| where cloud_RoleName startswith "foundry-workshop."
| where tostring(customDimensions["gen_ai.operation.name"]) == "chat"
| extend in_tok=tolong(customDimensions["gen_ai.usage.input_tokens"]),
         out_tok=tolong(customDimensions["gen_ai.usage.output_tokens"])
| where isnotnull(in_tok)
| summarize input_tok=sum(in_tok), output_tok=sum(out_tok), model_calls=count()
```

Pricing depends on the deployment and billing terms. Token counts here
are not a price estimate.

### Q3: Optional user prompt content

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| where cloud_RoleName startswith "foundry-workshop."
| where name startswith "invoke_agent"
| extend msgs=parse_json(tostring(customDimensions["gen_ai.input.messages"]))
| mv-expand m=msgs
| where tostring(m.role) == "user"
| mv-expand p=m.parts
| where tostring(p.type) == "text"
| project timestamp, scenario=cloud_RoleName, prompt=substring(tostring(p.content), 0, 90)
| order by timestamp asc
```

Empty results are expected when `ENABLE_SENSITIVE_DATA=false`.

### Q4: Optional output content types

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| where cloud_RoleName startswith "foundry-workshop."
| where name startswith "invoke_agent"
| extend msgs=parse_json(tostring(customDimensions["gen_ai.output.messages"]))
| mv-expand m=msgs
| mv-expand p=m.parts
| where isnotempty(tostring(p.type))
| summarize parts=count() by content_type=tostring(p.type)
```

Content types depend on the provider and API. They are not guaranteed to
include a fixed pair of MCP part names. Use Q0 to confirm actual tool execution.

---

## Troubleshooting

| Symptom                                                                                                | Cause                                                                                          | Fix                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `AADSTS65001: The user or administrator has not consented to use the application` from `AzureCliCredential` | The Foundry-bound app needs consent in your tenant.                                              | Run `az login --tenant <YOUR_TENANT_ID>` once. If problems persist, ask a tenant admin to grant consent (rare for first-party apps).                                                              |
| `[observability] skipped …`                                                                            | `APPLICATIONINSIGHTS_CONNECTION_STRING` is empty in `.env`.                                    | Get it from the Foundry portal → Project → Manage → Tracing → "Connect a new Application Insights resource".                                                                                      |
| MCP connection or `tools/list` fails | The URL, protocol negotiation, proxy or service may be unavailable. | Check the exact MCP URL and the actual MCP error. A plain GET or `curl` response does not test MCP initialization or tool discovery. |
| Portal agent (02b) returns generic answers, doesn't search Learn                                       | You forgot to attach the MCP tool when creating the portal agent.                              | Re-edit the agent in the portal and add the tool (see [How to build the portal agent](#how-to-build-the-portal-agent)). The portal's "Test" pane is a fast way to verify.                          |
| 02c returns `403 Forbidden` | The signed in identity may lack agent data permissions at the project scope. | Check the current [Foundry roles](https://learn.microsoft.com/azure/ai-foundry/concepts/rbac-ai-foundry). Creating agent versions does not inherently require an Owner role. |
| Spans do not appear after several minutes | Wrong destination, query filters, ingestion delay or exporter connectivity. | Check exporter errors and the destination. Use `verify_observability.py` with the matching scenario and trace ID. The scripts explicitly flush tracing before reporting success. |
| `429` or rate limit error | The deployment has insufficient available capacity for the request. | Follow the service retry window or use an appropriately provisioned deployment. A large MCP tool prompt can exceed a small deployment's capacity even when tool discovery works. |

---

## Exercises

1. **Narrow the Learn question.** Request one short answer and one source
   link. Compare actual `execute_tool` spans, reported token usage and
   latency with the original question.
2. **Inspect approval requests.** Change `approval_mode` in 02 to
   `"always_require"`. The sample does not provide an interactive approval
   UI. Inspect the returned requests and add an explicit approval
   interaction before expecting tool execution to continue.
3. **Test version reuse.** With permission to publish agent changes, run
   02c twice with an unchanged definition and confirm version reuse. Then
   change the instructions and verify `agents.create_version()` publishes
   a new version. The script already implements this comparison.
4. **Compare correlated traces.** Query one operation ID per scenario
   and distinguish `pure-code`, `portal-first` and `hybrid` by service role.

---

## What you've learned

You can now:

- **Attach an MCP server as a tool to a Foundry agent** with three lines of
  configuration.
- **Pick the right deployment pattern** for your team's workflow: pure code,
  portal-first, or hybrid.
- **Read traces** from Application Insights, tagged per scenario, with
  optional prompt and completion content capture.
- **Use `FoundryChatClient` and `FoundryAgent`** appropriately. The chat
  client is for code-defined agents (variant A). The agent class is for
  invoking a server-side agent record (variants B and C).

These three patterns plus tracing are the foundation of every production
Foundry agent. Sample 03 narrows scope back to a single concept (custom
*local* functions as tools) and is shorter; sample 05 widens it to full
production identity and audit.

---

## Where to go next

| If you want to…                                                                | Go to                                                                |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| Use a **local Python function** as a tool (no MCP needed)                      | [Sample 03 · Custom function tool](../03-custom-function-tool-agent/README.md) |
| Add a custom parent span and checked tracing shutdown | [Sample 04 tracing guide](../04-tracing-agent/README.md) |
| **Build your own MCP server** on Azure Functions and consume it from Foundry  | [Sample 06 · Weather MCP agent](../06-weather-mcp-agent/README.md)    |
| Add **per-agent Entra identity** to authenticate the agent against an API     | [Sample 05 · End-to-end with Entra Agent ID](../05-end-to-end-agent/) |
