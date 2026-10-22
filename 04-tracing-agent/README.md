# Sample 04: Observing an Agent with OpenTelemetry and Application Insights

> **You have just finished sample 03**: an agent with one local function tool
> that fires on demand. The agent works, and you have *no idea* what's
> happening inside it. Was the tool actually called? How many tokens did the
> model consume? Which prompt produced which completion? When something
> regresses next week, how will you debug it?
>
> Welcome to the lab that grows your eyes.

This lab takes the basic agent from sample 01 and adds export configuration,
a custom parent span and checked tracing shutdown. It connects
**OpenTelemetry (OTel)** to **Azure Monitor Application Insights**.
Agent and model operations, timing and reported token usage are recorded.
Prompt and answer content capture is optional.

By the time you finish this lab you'll know:

- What OpenTelemetry is, why every cloud SDK now ships with it, and how the
  abstraction stack of **OTel API, OTel SDK, Azure Monitor exporter,
  Application Insights** works end to end.
- How `configure_azure_monitor()` is the *one line* that wires everything up.
- How the Agent Framework's GenAI-aware instrumentation populates
  semantic span attributes (`gen_ai.operation.name`,
  `gen_ai.usage.input_tokens`, `gen_ai.input.messages`,
  `gen_ai.output.messages`).
- How to write **Kusto Query Language (KQL)** queries against the
  `dependencies`, `requests` and `traces` tables to inspect an agent run.
- The privacy switch that controls whether prompts and completions are recorded
  in your telemetry, and when to flip it on or off.

---

## Table of contents

- [What you will build](#what-you-will-build)
- [Prerequisites](#prerequisites)
  - [Step 1 · Configure your `.env` file](#step-1--configure-your-env-file)
  - [Step 2 · Get an Application Insights connection string](#step-2--get-an-application-insights-connection-string)
- [Mental model: the telemetry pipeline](#mental-model-the-telemetry-pipeline)
- [Mental model: spans, traces, and the GenAI semantic conventions](#mental-model-spans-traces-and-the-genai-semantic-conventions)
- [Step-by-step code walkthrough](#step-by-step-code-walkthrough)
  - [Section 1: Imports and `.env` loader](#section-1-imports-and-env-loader)
  - [Section 2: Configuration and fail-fast checks](#section-2-configuration-and-fail-fast-checks)
  - [Section 3: Content capture control](#section-3-content-capture-control)
  - [Section 4: Wiring Azure Monitor and getting a tracer](#section-4-wiring-azure-monitor-and-getting-a-tracer)
  - [Section 5: The custom span around `main()`](#section-5-the-custom-span-around-main)
  - [Section 6: Checked tracing shutdown](#section-6-checked-tracing-shutdown)
- [Running the sample](#running-the-sample)
- [Expected output (console)](#expected-output-console)
- [Querying Application Insights with KQL](#querying-application-insights-with-kql)
- [Troubleshooting](#troubleshooting)
- [Exercises, try these next](#exercises-try-these-next)
- [What you've learned](#what-youve-learned)
- [Where to go next](#where-to-go-next)

---

## What you will build

A Python script that:

1. Loads Foundry endpoint, model name, and an **Application Insights
   connection string** from a `.env` file in this folder.
2. Configures Azure Monitor once at the start of `main()`, before creating
   the tracer, client or agent.
3. Opens a custom `example-tracing` span as the root.
4. Inside that span, runs a one-prompt conversation against a Foundry agent.
5. Behind the scenes, the Agent Framework's built-in OTel instrumentation
   emits **GenAI semantic-convention spans** for every model call.
6. Flushes completed spans and shuts down the tracing provider before the
   success banner. After ingestion, queries can inspect the exact trace ID.

The code change relative to sample 01 is *tiny*. The capability you unlock
is enormous: you now have a queryable record of every model interaction,
which is the foundation of every production AI system.

---

## Prerequisites

| Requirement                                                                  | Why                                                                                                       |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **You've completed sample 01**                                               | We re-use the agent skeleton verbatim. The four building blocks are not re-explained.                      |
| **Python 3.13** | Use the same Python version as the setup instructions and local verification. |
| **A Microsoft Foundry project** with a **gpt-4o** deployment                 | Same as previous labs.                                                                                     |
| **An Application Insights resource** attached to your Foundry project        | The destination for our telemetry. See [Step 2 below](#step-2--get-an-application-insights-connection-string). |
| **Azure CLI signed in** (`az login`)                                         | `AzureCliCredential` picks up your CLI login.                                                              |
| **A configured `.env` file in this folder**                                  | Holds three values: project endpoint, model name, App Insights connection string.                         |
| **VS Code with the Python and Azure Tools extensions** (recommended)         | One click to run. You can also open the App Insights blade from inside VS Code's Azure side panel.         |

### Step 1 · Configure your `.env` file

1. **Create `.env` only if it is missing. Preserve existing values:**
   ```bash
   cd "$(git rev-parse --show-toplevel)"
   cd 04-tracing-agent
   test -f .env || cp .env.example .env
   ```

   In Windows PowerShell, use:
   ```powershell
   Set-Location -LiteralPath (git rev-parse --show-toplevel)
   Set-Location 04-tracing-agent
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   ```

2. **Open `.env`** and fill in three variables:

   | Variable                                  | Where to find it                                                                                                                                |
   | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
   | `FOUNDRY_PROJECT_ENDPOINT`                | Foundry portal → **your project → Overview**. Ends in `/api/projects/<project-name>`.                                                            |
   | `FOUNDRY_MODEL`                           | The **deployment name** of your chat model. Defaults to `gpt-4o`.                                                                                |
   | `APPLICATIONINSIGHTS_CONNECTION_STRING`   | Foundry portal → **your project → Manage → Tracing**. Click **View Application Insights**, then **Properties**, then copy **Connection String**. |
   | `ENABLE_SENSITIVE_DATA` | Optional content capture. Keep `false` for metadata only. |

> **Fail-fast behaviour.** This sample is specifically about tracing. When
> `APPLICATIONINSIGHTS_CONNECTION_STRING` is empty, the script raises a
> `RuntimeError` *before* opening any HTTP connection. Running a
> "tracing" sample with no destination would be silently useless.

### Step 2 · Get an Application Insights connection string

You need an Application Insights component, usually backed by a Log Analytics
workspace. A Foundry project may already have one connected. Check the
project's tracing settings rather than assuming a component exists.

To grab the connection string from the portal:

1. Open the **Foundry portal** at [ai.azure.com](https://ai.azure.com).
2. Select your project, then **Manage → Tracing**.
3. Click **View Application Insights**. This opens the Azure portal blade
   for the resource.
4. In the App Insights blade's left rail, click **Configure → Properties**.
5. Copy the complete **Connection String**, not only the instrumentation key.
6. Paste it into `.env` as `APPLICATIONINSIGHTS_CONNECTION_STRING=...`.

> **No Application Insights resource attached?** Create one from
> *Azure portal, Create a resource, Application Insights*, choose
> **Workspace-based**, attach it to any Log Analytics workspace in your
> subscription, and then optionally wire it back to the Foundry project
> under **Manage, Tracing, Enable tracing**. For this lab you only need
> the connection string. The resource can be standalone.

---

## Mental model: the telemetry pipeline

When you call `configure_azure_monitor(...)`, you assemble this pipeline in
memory inside your Python process:

```
┌──────────────────────────────────────────────────────────────────────┐
│  YOUR CODE                                                          │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │ tracer.start_as_current_span("example-tracing")            │     │
│  │   └─ Agent.run(input, stream=True)                          │     │
│  │      └─ FoundryChatClient HTTPS POST to Foundry              │     │
│  │         (Agent Framework auto-instruments this call)       │     │
│  └────────────────────────────────────────────────────────────┘     │
│                            │                                        │
│                            ▼                                        │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  OpenTelemetry API   (vendor-neutral, opentelemetry-api)   │     │
│  │  • Span objects, Context propagation                        │    │
│  └────────────────────────────────────────────────────────────┘     │
│                            │                                        │
│                            ▼                                        │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  OpenTelemetry SDK   (opentelemetry-sdk)                   │     │
│  │  • TracerProvider, BatchSpanProcessor                       │    │
│  └────────────────────────────────────────────────────────────┘     │
│                            │                                        │
│                            ▼                                        │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  Azure Monitor exporter   (azure-monitor-opentelemetry)    │     │
│  │  • Converts OTel spans → App Insights envelopes             │    │
│  └────────────────────────────────────────────────────────────┘     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ HTTPS (≈ every 5 s)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AZURE                                                              │
│  Application Insights ingestion endpoint                            │
│      └─ Log Analytics workspace tables:                             │
│         • dependencies  ← outgoing HTTP, model calls, tool calls    │
│         • traces        ← log lines, custom messages                │
│         • requests      ← server spans when present                  │
│         • exceptions    ← Python tracebacks                         │
└─────────────────────────────────────────────────────────────────────┘
```

Two ideas that this picture makes concrete:

1. **You write to a vendor-neutral API.** Your code only ever touches
   `opentelemetry.trace`. If a future you wants to switch from Application
   Insights to Jaeger, Honeycomb, or a self-hosted Tempo, you swap *only*
   the exporter. Your spans and your queries-against-spans rationale
   carry over.
2. **The Agent Framework is already instrumented.** You don't have to call
   `tracer.start_span("model_call")` around every model call. The
   framework's HTTP client emits a span automatically for every outbound
   request to Foundry, *and* enriches it with GenAI semantic conventions.
   You only need a custom span if you want to **group related work**
   (which is exactly what our `example-tracing` span does).

> **Deep dive · Why batching matters.** The exporter doesn't ship every
> span over the wire immediately. It buffers them in a `BatchSpanProcessor`
> and exports periodically or when the buffer fills. OpenTelemetry normally
> registers shutdown handling for a clean exit. This sample also explicitly
> checks flushing and shuts down tracing, rather than relying on a fixed
> sleep. See [Section 6](#section-6-checked-tracing-shutdown).

---

## Mental model: spans, traces, and the GenAI semantic conventions

Three OTel concepts are enough to read every dashboard you'll ever see:

| Concept     | One-line definition                                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Span**    | A timed operation. It has a name, a start time, an end time, attributes (key-value pairs), and optional events.               |
| **Trace**   | A tree of spans tied together by a shared `trace_id`. A parent span's `span_id` becomes a child span's `parent_span_id`.      |
| **Context** | Thread-local (or async-task-local) state that carries the *current* span so child operations attach themselves automatically. |

When you write:

```python
with tracer.start_as_current_span("example-tracing"):
    ...  # any spans created here will be children of "example-tracing"
```

the `with` block sets the context. Anything that creates a span inside,
the Agent Framework's HTTP client included, produces a child. After the
block exits, the context is restored.

For agent workloads, the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
define *which attributes a model-call span should carry*. The Agent
Framework follows them. Concretely, when you run this sample you will see
spans in App Insights with attributes like:

| Attribute name                       | Example value                                              | What it means                                   |
| ------------------------------------ | ---------------------------------------------------------- | ----------------------------------------------- |
| `gen_ai.provider.name`               | `azure.ai.foundry`                                         | Which provider was called.                      |
| `gen_ai.operation.name`              | `chat`                                                     | The kind of model interaction.                  |
| `gen_ai.request.model`               | `gpt-4o`                                                   | The deployment that handled this request.       |
| `gen_ai.usage.input_tokens`          | `87`                                                       | Prompt tokens billed.                           |
| `gen_ai.usage.output_tokens`         | `124`                                                      | Completion tokens billed.                       |
| `gen_ai.input.messages`              | `[{"role":"user","parts":[{"type":"text","content":"Can you tell me the gravity of Earth versus Mars?"}]}]` | JSON array of conversation messages sent to the model. Recorded **only** when content recording is on. |
| `gen_ai.output.messages`             | `[{"role":"assistant","parts":[{"type":"text","content":"Sure! On Earth gravity is approximately 9.81 m/s² ..."}]}]` | JSON array of messages produced by the model. Recorded **only** when content recording is on. |

These attributes are *exactly* what the KQL queries at the end of this
lab rely on.

---

## Step-by-step code walkthrough

Open `04-tracing-agent.py` in VS Code and read along.

### Section 1: Imports and `.env` loader

```python
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workshop import (
    configure_console,
    configure_tracing,
    print_stream,
    project_endpoint,
    shutdown_tracing,
)
```

Identical to samples 01 and 03. We load `.env` from this folder so the
script behaves the same whether you launch it from VS Code's Run button or
from a terminal in any directory. The resolved parent path makes
[`_workshop.py`](../_workshop.py) importable on Windows, macOS and Linux.
Keep the repository together. Content capture is configured explicitly when
`configure_tracing()` runs, not by forcing old flags before imports.

### Section 2: Configuration and fail-fast checks

```python
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
```

`project_endpoint()` rejects empty values and angle bracket placeholders.
The connection string check is additional to sample 01 because tracing is
required for this lab. A missing destination is reported before a network call.

### Section 3: Content capture control

In `.env`, start with:

```dotenv
ENABLE_SENSITIVE_DATA=false
```

The framework records timing, model metadata and reported token usage
without exporting the conversation text. Set the value to `true` only when
you intend to export prompts, answers and tool content. This enables
`gen_ai.input.messages` and `gen_ai.output.messages` where the framework
records those attributes.

The shared helper calls `enable_instrumentation()` without a forced
`enable_sensitive_data=True` argument, so an explicit `false` remains
effective. The old `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED` and
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` flags are not the content
capture control for this SDK set.

### Section 4: Wiring Azure Monitor and getting a tracer

```python
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from opentelemetry import trace

async def main() -> None:
    configure_console()
    configure_tracing(APPINSIGHTS_CONN, "tracing")
    tracer = trace.get_tracer(__name__)
    ...
```

The helper calls `configure_azure_monitor` with the connection string,
an OpenTelemetry resource and `sampling_ratio=1.0` for these workshop runs.
Its default service name is `foundry-workshop.tracing`. Leave
`OTEL_SERVICE_NAME` unset when using the workshop verifier's default filters.

It then calls `enable_instrumentation()` to refresh the framework settings.
That function does not create or replace the tracer provider. Configuration
happens once before the tracer and agent are created.

The installed Azure Monitor distribution supplies the exporter, batching
and supported HTTP instrumentation. `trace.get_tracer(__name__)` uses the
configured provider to create the custom span.

### Section 5: The custom span around `main()`

```python
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
```

The custom grouping operation is `tracer.start_as_current_span("example-tracing")`.
The shared streaming helper avoids repeating final replacement snapshots.

This creates one **custom parent span** for the entire run. Why bother?

- **Grouping.** Every model-call and `invoke_agent` span emitted by the
  framework underneath gets `example-tracing` as its parent. In KQL, you
  can find this trace by name (`name == "example-tracing"`) and then
  enumerate all children via `operation_Id`.
- **Custom attributes.** You can attach business-meaningful attributes
  (user ID, request ID, A/B-test bucket) to this parent span, and they
  will be present in queries for the whole run.
- **Latency budget.** The span's start-to-end duration tells you the
  end-to-end time for the request as the user experienced it. The
  framework's child spans tell you *where* inside that budget the time
  went (Foundry HTTPS latency, model inference, local processing).

You'll see this `example-tracing` span at the **top** of the trace tree in
the App Insights Transaction Search blade.

### Section 6: Checked tracing shutdown

```python
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
```

The helper checks `force_flush(timeout_millis=30000)` and then shuts down
the tracing provider. A flush timeout raises an error and prevents the
success banner. Unexpected model or configuration errors also return a
nonzero status. An interruption exits with `130`.

A fixed sleep does not prove a batch was exported. Normal OpenTelemetry
shutdown handling is useful, but an explicit checked flush makes this short
sample easier to diagnose. Neither flushing nor a successful model answer
proves ingestion. Query the printed trace ID to confirm Azure received it.

---

## Running the sample

Run the complete command block after configuring `.env` above. With Git
installed, the first command returns to the repository root from any folder
inside the clone. Use the same repository `.venv` as samples 01 through 03. Install
[`requirements-first-four.txt`](../requirements-first-four.txt), which pins
the compatible framework, Projects SDK and tracing dependencies.

### Windows PowerShell

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
.\.venv\Scripts\python.exe -m pip check
az login
.\.venv\Scripts\python.exe -X utf8 .\04-tracing-agent\04-tracing-agent.py
```

### macOS or Linux with Bash

```bash
cd "$(git rev-parse --show-toplevel)"
test -x .venv/bin/python || python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-first-four.txt
.venv/bin/python -m pip check
az login
.venv/bin/python -X utf8 04-tracing-agent/04-tracing-agent.py
```

Activation is optional. In VS Code, open the repository root and use
**Python: Select Interpreter** to select `.venv/bin/python` on macOS or
`.venv\Scripts\python.exe` on Windows. Use **Run Python File**.

Installation uses your configured package feed. Do not add a public PyPI
override when downloads from `files.pythonhosted.org` time out.

Dependency installation and offline regression checks have passed on macOS
with Python 3.13. Windows execution and live Azure runs remain unverified.

Use **Application Insights, Logs** or **Transaction Search** to inspect
ingested spans. Live Metrics alone does not confirm that a complete trace
has been stored.

---

## Expected output (console)

```
# User: 'Can you tell me the gravity of Earth versus the gravity of Mars?'
# ai-agent: Here's a comparison of the gravitational acceleration on Earth and Mars:

- **Earth**: The standard gravitational acceleration is approximately **9.81 m/s²**.
- **Mars**: The gravitational acceleration is about **3.71 m/s²**.

In simpler terms, the gravity on Mars is about **38%** of that on Earth.

Trace ID: 0123456789abcdef0123456789abcdef

--- All tasks completed successfully ---
Program finished.
```

The answer varies. The trace ID identifies this execution for the queries below.

---

## Querying Application Insights with KQL

Application Insights stores telemetry across several tables.

| Table          | What it contains                                                          |
| -------------- | ------------------------------------------------------------------------- |
| `dependencies` | Outgoing and internal operations, including the model calls in this sample. |
| `requests` | Server operations when present. Include this table when looking for correlated spans. |
| `traces` | Python logging and OpenTelemetry log records. These are not the span tree. |

Open the App Insights blade → **Logs**. Paste each query and click **Run**.
For a terminal check with a meaningful exit status, follow the
[sample 02 verifier instructions](../02-mcp-tool-agent/README.md).
Use `OBSERVABILITY_SCENARIO=tracing` and set `OBSERVABILITY_TRACE_ID` to the
ID printed by this script. No additional inference call is needed.

### Query 1: Find the run

```kql
union dependencies, requests
| where timestamp > ago(1h)
| where cloud_RoleName == "foundry-workshop.tracing"
| where name == "example-tracing"
| project timestamp, name, success, duration, operation_Id
| top 5 by timestamp desc
```

After ingestion, a completed run should have a root row. Use the printed
trace ID, or copy its `operation_Id` from this query. Replace `<TRACE_ID>`
below with that value to avoid mixing different executions.

### Query 2: The whole trace, in order

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| order by timestamp asc
| project timestamp, service=cloud_RoleName, name, success, duration,
          id, operation_ParentId
```

This lists the spans in timestamp order. The parent IDs describe the actual
hierarchy rather than reconstructing one from conversation messages.
Expect `example-tracing`, `invoke_agent ai-agent`, a model `chat` operation
and the related SDK or HTTP spans.

### Query 3: Token usage

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| where cloud_RoleName startswith "foundry-workshop."
| where tostring(customDimensions["gen_ai.operation.name"]) == "chat"
| extend
    input_tokens = tolong(customDimensions["gen_ai.usage.input_tokens"]),
    output_tokens = tolong(customDimensions["gen_ai.usage.output_tokens"]),
    model = tostring(customDimensions["gen_ai.request.model"])
| where isnotnull(input_tokens)
| summarize input_tokens=sum(input_tokens), output_tokens=sum(output_tokens),
            model_calls=count() by model
```

Only client model spans are counted. Agent spans can repeat aggregate
usage from their children, so adding both would double count tokens.
These counts are not a billing or price estimate.

### Query 4: Prompt and completion text

With `ENABLE_SENSITIVE_DATA=true`, the framework can record structured
`gen_ai.input.messages` and `gen_ai.output.messages` attributes.
Inspect the arrays rather than assuming the last input message is always
a user prompt or every part is plain text.

```kql
union dependencies, requests
| where operation_Id == "<TRACE_ID>"
| where cloud_RoleName startswith "foundry-workshop."
| where name startswith "invoke_agent"
| extend
    input_messages  = todynamic(tostring(customDimensions["gen_ai.input.messages"])),
    output_messages = todynamic(tostring(customDimensions["gen_ai.output.messages"]))
| where isnotempty(tostring(input_messages)) or isnotempty(tostring(output_messages))
| project timestamp, input_messages, output_messages
| order by timestamp asc
```

Empty results are expected with the default `ENABLE_SENSITIVE_DATA=false`.
Successful metadata queries are still useful when conversation content is
not exported.

> **Deep dive on `customDimensions` vs flat columns.** App Insights stores
> OTel span attributes in a dynamic JSON column called `customDimensions`.
> Use `customDimensions["key"]` to read them, and `tostring(...)`,
> `toint(...)`, or `todynamic(...)` to convert them out of the dynamic
> type. Save your favourite queries. KQL syntax is dense at first but
> pays off enormously.

---

## Troubleshooting

| Symptom                                                                                  | Cause                                                                                                                | Fix                                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RuntimeError: APPLICATIONINSIGHTS_CONNECTION_STRING is not configured`                  | `.env` is missing the connection string.                                                                             | Follow [Prerequisites → Step 2](#step-2--get-an-application-insights-connection-string) and paste the full connection string into `.env`.                                                  |
| `RuntimeError: FOUNDRY_PROJECT_ENDPOINT is not configured`                               | `.env` is missing or still has the `<YOUR_…>` placeholder.                                                            | `cp .env.example .env` and fill in all three values. See [Prerequisites → Step 1](#step-1--configure-your-env-file).                                                                       |
| Script runs but no spans appear after several minutes | The destination, query filters, ingestion delay or exporter connectivity may be wrong. | Check exporter errors, the full connection string and the exact printed trace ID. Run the native verifier after allowing for ingestion. A success banner alone is not ingestion proof. |
| `ModuleNotFoundError: azure.monitor.opentelemetry` | The selected interpreter is missing the pinned dependencies. | Install `requirements-first-four.txt` using that interpreter and select the same environment in VS Code. |
| Conversation content is empty | `ENABLE_SENSITIVE_DATA=false`, or the provider did not record that content. | Empty content is expected by default. Opt in only intentionally, start a new process and inspect that new trace ID. |
| Spans land in App Insights but `operation_Id` differs per child span (no shared trace)   | The `with tracer.start_as_current_span(...)` block isn't covering the model call.                                    | Make sure the framework calls happen *inside* the `with` block. Check that no exception bypassed the block before `await agent.run(..., stream=True)` ran.                                                  |
| Token query returns no rows | The destination or trace ID is wrong, ingestion is pending, or the model did not report usage. | Check Query 2 first, then inspect its client model spans. Do not replace missing usage with a made up count. |
| `429` or rate limit error | The deployment does not have enough current capacity for the request. | Wait for the service retry window or use an appropriately provisioned deployment. This script reports failure and does not change quota. |
| Tracing flush timeout | The exporter did not drain within the configured timeout. | Check connectivity and exporter errors. The script returns a nonzero status rather than printing success. |

---

## Exercises, try these next

1. **Compare content settings.** Run with `ENABLE_SENSITIVE_DATA=false`,
   then opt in with `true` using a harmless prompt. Query each printed
   trace ID separately. Content should be absent in the first run while
   reported token usage remains available.
2. **Attach a custom attribute** to the parent span. Replace the `with`
   line with:
   ```python
   with tracer.start_as_current_span("example-tracing") as span:
       span.set_attribute("workshop.session", "demo")
       span.set_attribute("workshop.iteration", 4)
   ```
   Then query: `where customDimensions has "workshop.session"`. You've just
   added a queryable tag to every run.
3. **Inspect a failure.** Temporarily set `FOUNDRY_MODEL` to an unavailable
   deployment name in `.env`. Check the nonzero exit status and failed
   spans, then restore the original value. Error telemetry depends on how
   far execution reached, so do not assume an `exceptions` row is required.
4. **Run the local regressions.** From the repository root, use
   `.venv/bin/python -X utf8 -m unittest discover -s tests -v` on macOS.
   The Windows PowerShell command awaiting Windows verification is
   `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v`.
   These checks cover streaming, sensitive capture, root correlation and
   flush failures without Azure credentials. The prepared CI workflow is
   configured for Windows and macOS, but its presence is not proof of a
   successful run on either platform.

---

## What you've learned

- Export configuration, instrumentation and custom spans are separate
  responsibilities. This sample joins them with checked shutdown.
- The conceptual stack from OTel API to the Azure Monitor exporter to
  the Log Analytics tables in your subscription.
- The GenAI semantic conventions and why following them means your
  dashboards work against any framework that emits them, not just the
  Microsoft Agent Framework.
- How to drive App Insights with KQL: four queries that you'll re-use
  on every agent project you build from now on.
- The one privacy-policy switch that controls whether prompts and
  completions are persisted with your telemetry.

---

## Where to go next

You now have **eyes on every agent run**. The remaining labs take that
visibility into more sophisticated territory:

| Next lab                                                                                                                              | Why                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`05-end-to-end-agent/`](../05-end-to-end-agent/)                                                                                     | An agent that calls a JWT-protected weather API as a Python function tool. The same observability lessons apply to outgoing HTTP from your tool functions.          |
| [`06-weather-mcp-agent/`](../06-weather-mcp-agent/)                                                                                   | A weather agent backed by a **custom MCP server on Azure Functions**, with an entire KQL cookbook (`06-weather-mcp-agent/kql/observability-cookbook.md`) showing how to correlate spans across the network boundary. |
| [Sample 02 observability guide](../02-mcp-tool-agent/README.md) | Native telemetry verification and queries for the first four samples. |

Onward.
