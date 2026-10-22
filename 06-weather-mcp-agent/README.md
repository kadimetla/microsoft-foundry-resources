# 06 · Weather MCP — A Foundry Agent calls an Azure Functions MCP Server

> **What you'll build.** A complete, end-to-end Microsoft Foundry sample that
> demonstrates the **Model Context Protocol (MCP)** pattern:
>
> 1. A custom **MCP server** hosted on **Azure Functions** that exposes a
>    `get_weather` tool backed by the free Open-Meteo public API.
> 2. A **Foundry agent** (gpt-4o) that *discovers* and *calls* that tool over
>    MCP — without any per-tool client code.
> 3. A **bring-your-own-Entra** security model (Easy Auth on the Function App,
>    app-role gated) so only authorized identities can call the tool.
> 4. A complete **observability** pipeline through Application Insights, with a
>    KQL cookbook ([`kql/observability-cookbook.md`](kql/observability-cookbook.md))
>    that stitches the agent and server sides of every call together.
>
> **Total run time after prereqs:** ~15 minutes for Iteration 1 (function-key
> auth), ~30 more minutes for Iteration 2 (Entra hardening).

---

## Table of contents

- [Part 0 · Set up VS Code (recommended)](#part-0--set-up-vs-code-recommended)
- [Part 1 · Why this sample exists](#part-1--why-this-sample-exists)
- [Part 2 · REST API vs MCP — the mental model](#part-2--rest-api-vs-mcp--the-mental-model)
- [Part 3 · Architecture](#part-3--architecture)
- [Part 4 · Lab — Iteration 1: deploy and call with a function key](#part-4--lab--iteration-1-deploy-and-call-with-a-function-key)
- [Part 5 · Lab — Iteration 2: harden with Microsoft Entra](#part-5--lab--iteration-2-harden-with-microsoft-entra)
- [Part 6 · Observability — KQL queries that prove it all worked](#part-6--observability--kql-queries-that-prove-it-all-worked)
- [Part 7 · Reference](#part-7--reference)
- [Part 8 · Troubleshooting](#part-8--troubleshooting)
- [Part 9 · Cleanup & rollback](#part-9--cleanup--rollback)

---

## Part 0 · Set up VS Code (recommended)

> **Everything in this lab runs perfectly inside VS Code.** Every shell
> command goes in the **integrated terminal** (`` Ctrl+` `` on Windows/Linux,
> `` Cmd+` `` on macOS). You do not need to leave the editor at any point.

### 0.1 Recommended extensions

Install these from the VS Code Extensions panel (`Ctrl+Shift+X` / `Cmd+Shift+X`).
All are first-party Microsoft and free.

| Extension                              | Publisher           | Why you want it for this lab                                                                                  |
| -------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Python**                             | Microsoft           | Picks up `.env` automatically, runs/debugs `06-weather-mcp-agent.py`, manages the virtualenv.                  |
| **Azure Functions**                    | Microsoft           | One-click deploy, local `func start`, browse function logs, retrieve keys from the Azure panel.                |
| **Azure Tools** (extension pack)       | Microsoft           | Bundles Azure Account + Azure Resources + Functions + Storage + App Service. The single most useful install.   |
| **Azure Developer CLI (`azd`)**        | Microsoft           | "Run azd up", "Run azd provision" right from the Command Palette. Status bar shows current `azd` env.          |
| **Bicep**                              | Microsoft           | Syntax, IntelliSense, validation, and inline preview for `infra/main.bicep`.                                   |
| **Kusto (KQL)**                        | Microsoft           | Run the queries from `kql/observability-cookbook.md` against App Insights without leaving the editor.          |
| **REST Client** *(optional)*           | Huachao Mao         | Lets you save the curl examples in §5.7 as `.http` files and click "Send Request" instead of pasting curl.    |
| **GitHub Pull Requests and Issues**    | GitHub              | If you're forking and PR'ing back, this gives you the full GitHub UI in the sidebar.                          |

Or install them all at once from the terminal:

```bash
code --install-extension ms-python.python \
     --install-extension ms-azuretools.vscode-azurefunctions \
     --install-extension ms-azuretools.vscode-azuretools \
     --install-extension ms-azuretools.azure-dev \
     --install-extension ms-azuretools.vscode-bicep \
     --install-extension ms-azuretools.vscode-azurekusto \
     --install-extension humao.rest-client
```

### 0.2 Open the workshop folder in VS Code

```bash
git clone https://github.com/razi-rais/microsoft-foundry-resources.git
code microsoft-foundry-resources/06-weather-mcp-agent
```

You'll see the file tree on the left:

```
06-weather-mcp-agent/        ← root of the lab in VS Code
├── .env.example
├── 06-weather-mcp-agent.py
├── README.md                ← you are here (open with Ctrl+Shift+V for preview)
├── kql/
└── mcp-server/              ← the Azure Functions project (Iter 1+2 deploy target)
```

### 0.3 Open the integrated terminal

- **Menu:** Terminal → New Terminal
- **Shortcut:** `` Ctrl+` `` (Windows/Linux) or `` Cmd+` `` (macOS)

The terminal opens **already cd'ed to `06-weather-mcp-agent/`**. Every
shell command in this README runs there (or one level deeper in
`mcp-server/`). When you need to switch directories the commands say so
explicitly.

### 0.4 Two .env tips for VS Code

1. **`.env` is auto-loaded by the Python extension.** When you click ▶ *Run*
   in the editor's top-right corner on `06-weather-mcp-agent.py`, the
   variables from `06-weather-mcp-agent/.env` are injected into the run
   automatically. No extra config needed.
2. **`.env` files are pre-`.gitignored`** in this repo. You can safely paste
   your function key, App Insights connection string, and (Iter 2) the
   pre-acquired bearer into `.env` without risking a `git commit`.

### 0.5 VS Code-native shortcuts for common lab tasks

| Task                                                 | Terminal command (shown in lab)                                        | VS Code-native alternative                                                                                                  |
| ---------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Sign in to Azure                                     | `az login` / `azd auth login`                                          | Command Palette → **Azure: Sign In** (handles both `az` and `azd`).                                                          |
| Deploy the Function App                              | `azd up`                                                               | Command Palette → **Azure Developer: Up**. Status bar shows progress.                                                       |
| Re-provision just the infra (after Bicep change)     | `azd provision`                                                        | Command Palette → **Azure Developer: Provision**.                                                                            |
| View live function logs                              | `az webapp log tail ...`                                               | Azure panel → expand your function app → right-click → **Start Streaming Logs**. Live stream appears in the Output pane.    |
| Fetch the `mcp_extension` system key                 | `az functionapp keys list ...`                                          | Azure panel → expand the function app → **Functions** → right-click → **Copy Key**.                                          |
| Run the agent                                        | `python 06-weather-mcp-agent.py`                                       | Click ▶ in the editor's top-right corner of `06-weather-mcp-agent.py`. `.env` is injected automatically.                    |
| Inspect Bicep before deploy                          | `cat infra/main.bicep`                                                 | Open `infra/main.bicep` → the Bicep extension shows inline validation; Command Palette → **Bicep: Show Visualizer**.        |
| Run a KQL query against App Insights                 | `curl ...api.applicationinsights.io...`                                | Open any `.kql` file (or paste a query into a new one) → click **Run Query**. Results render in a table inside VS Code.     |

### 0.6 If you prefer Dev Containers / Codespaces

Both work — the Functions, Bicep, Azure Tools, Python, and Kusto extensions
are available pre-installed in the Microsoft `python:3.13` dev container
image. Open the repo in a GitHub Codespace and skip Step 0.1 entirely.

---

## Part 1 · Why this sample exists

### 1.1 What you'll demonstrate

```
┌─────────────────────────────────────────────────────────────────────┐
│  YOUR LAPTOP                                                        │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  06-weather-mcp-agent.py     (python; agent-framework SDK) │     │
│  │                                                            │     │
│  │   "What's the weather in Seattle?"                         │     │
│  │             │                                              │     │
│  │             ▼                                              │     │
│  │   gpt-4o decides: "I need to call get_weather"             │     │
│  │             │                                              │     │
│  │             ▼  (HTTPS, bearer or function-key, JSON-RPC)   │     │
│  └─────────────┼──────────────────────────────────────────────┘     │
└────────────────┼────────────────────────────────────────────────────┘
                 │
   ┌─────────────▼──────────────────────────────────────────────┐
   │  AZURE — Foundry project (gpt-4o)        Azure Functions   │
   │  ┌────────────────────────┐         ┌─────────────────────┐│
   │  │ chat/completions       │         │ /runtime/webhooks/  ││
   │  │ same App Insights ─────┼────┐    │   mcp               ││
   │  └────────────────────────┘    │    │                     ││
   │                                │    │ get_weather tool ──┐││
   │  ┌────────────────────────┐    │    └────────────────────┼┘│
   │  │  Application Insights  │◄───┴────── traces (both)─────┘ │
   │  │  ↳ KQL cookbook        │                                │
   │  └────────────────────────┘                                │
   └─────────────────────────────────────────────────────────┬──┘
                                                             │
                                                             ▼
                                                   ┌─────────────────┐
                                                   │  Open-Meteo     │
                                                   │  (public, free) │
                                                   └─────────────────┘
```

By the end of the lab you will have:

| ✔ | Capability                                                                                                                                    |
| - | --------------------------------------------------------------------------------------------------------------------------------------------- |
| ✓ | An **Azure Functions** app speaking the MCP protocol over Streamable HTTP                                                                     |
| ✓ | A **Foundry agent** that discovered the tool via `tools/list` and invoked it via `tools/call` — *without any per-tool code on the agent side* |
| ✓ | A **JWT-based** auth posture using **Easy Auth + an Entra app role** (optional Iteration 2)                                                   |
| ✓ | KQL queries that show **one waterfall** crossing both the agent process and the Function App                                                  |

### 1.2 Who this lab is for

- Application developers building **agentic systems** on Microsoft Foundry who
  need to **add their own tools** (not just the Microsoft-hosted ones).
- Platform engineers who want to understand the **security and observability**
  boundary between the agent runtime and a custom MCP server.
- Anyone who has read about MCP but wants a **concrete, deployable** example
  smaller than the official `remote-mcp-functions-python` template.

### 1.3 Prerequisites

| Tool / resource                                                                                                                          | Why                                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Visual Studio Code**                                                                                                                   | Recommended IDE — full lab runs inside it. See [Part 0](#part-0--set-up-vs-code-recommended) for extensions.                  |
| **Azure subscription** with rights to create a resource group, a Function App, and a Storage account                                     | Hosts the MCP server                                                                                                          |
| **Microsoft Foundry project** with a gpt-4o (or compatible) model deployed                                                               | The agent's brain. See [Foundry quickstart](https://learn.microsoft.com/azure/ai-foundry/quickstarts/get-started-code) if you don't have one. |
| **Python 3.13+**                                                                                                                         | The MCP Functions extension requires it on the server side. The agent works on 3.10+.                                         |
| **[Azure Developer CLI (`azd`)](https://aka.ms/azd)** ≥ 1.10                                                                             | One-command deploy of the MCP server                                                                                          |
| **[Azure CLI (`az`)](https://learn.microsoft.com/cli/azure/install-azure-cli)** ≥ 2.60                                                   | Retrieve keys, configure Entra (Iteration 2)                                                                                  |
| **[Azure Functions Core Tools v4.0.7030+](https://learn.microsoft.com/azure/azure-functions/functions-run-local)**                       | Optional, for local `func start` (the Azure Functions VS Code extension installs this for you on first use)                   |

> 📘 **Naming convention used in this guide.** When you see angle brackets
> (`<your-func-app>`, `<MCP_APP_ID>`, `<tenant>`) replace them with your
> actual values. No real tenant IDs, app IDs, or subscription IDs appear in
> this repository — they are all in your local `.env` (which is `.gitignored`).

---

## Part 2 · REST API vs MCP — the mental model

> **TL;DR.** The wire format is still HTTP. But MCP turns *one* HTTP endpoint
> into a *self-describing, multi-tool* service that the model can **discover
> and call on its own** — no hard-coded URLs, no hand-written tool schemas, no
> per-tool client code. Add a tool to the server, the agent picks it up on the
> next run.

### 2.1 The REST mental model (e.g. sample `05-end-to-end-agent`)

```
┌────────────────┐   GET /weather?location=Seattle    ┌──────────────────┐
│  Agent client  │───────────────────────────────────►│   Flask weather  │
│                │                                    │   API            │
│  Must hard-    │   GET /forecast?location=Seattle   │                  │
│  code each     │───────────────────────────────────►│   • one URL per  │
│  URL + schema  │                                    │     operation    │
│                │   GET /alerts?region=WA            │   • schema lives │
│                │───────────────────────────────────►│     on client    │
└────────────────┘                                    └──────────────────┘
```

- **One URL per operation.** Each tool needs its own endpoint.
- **Schema lives on the client.** You either write a Python function tool with
  type hints (sample 03) or paste an OpenAPI doc into the agent definition.
  Either way, the model is **told** at startup *"here are these N tools"*.
- **No conversation contract.** Each call is independent; no session, no
  streaming, no server-push.
- **Adding a fourth tool** = update the server **and** the agent **and**
  redeploy both.

### 2.2 The MCP mental model (this sample)

```
┌────────────────┐   POST /runtime/webhooks/mcp       ┌──────────────────┐
│  Agent client  │   ┌─────────────────────────────┐  │   Azure Functions│
│                │   │ 1. initialize               │  │   MCP server     │
│  Knows ONLY    │──▶│ 2. tools/list ──────────────┼─▶│                  │
│  the server    │   │ 3. tools/call (get_weather) │  │  • ONE URL       │
│  URL.          │   │ 4. tools/call (get_forecast)│  │  • Many tools    │
│                │   │ ...                         │  │  • Schemas live  │
│  Schema is     │   └─────────────────────────────┘  │    on the server │
│  discovered.   │                                    │                  │
└────────────────┘                                    └──────────────────┘
```

The agent and the server have a short, standardized **conversation** over a
single endpoint:

| Turn | JSON-RPC method                                                | Purpose                                                            |
| ---- | -------------------------------------------------------------- | ------------------------------------------------------------------ |
| 1    | `initialize`                                                   | Handshake — protocol version, capabilities, session id             |
| 2    | `tools/list`                                                   | Server replies with **every tool's name, description, JSON schema**  |
| 3    | `tools/call`                                                   | Model picks a tool by name, supplies arguments matching the schema |
| 4+   | `tools/call`, `resources/read`, `prompts/get`, notifications…  | Repeat / stream / push                                              |

The critical bit: **step 2 is what makes it MCP.** gpt-4o never gets told
"there is a tool called `get_weather` that takes `location: str`" — it learns
that by **asking the server**. The agent code in this sample just says
"here's an MCP server URL"; the model figures the rest out at runtime.

### 2.3 Side-by-side comparison

|                                       | REST tool (sample 05)                                | MCP server (this sample)                                                                      |
| ------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| URLs the agent must know              | one per tool                                         | **one, total**                                                                                |
| Tool schema lives in                  | agent code / OpenAPI doc                             | **the server itself** (via decorators)                                                        |
| Adding a new tool                     | edit server + edit agent + redeploy both             | **edit server only**, agent picks it up next run                                              |
| Discovery                             | none — static                                        | `tools/list` at runtime                                                                       |
| Streaming partial results             | needs custom SSE/websocket plumbing                  | built in (Streamable HTTP `text/event-stream`)                                                |
| Server → client push                  | not in REST                                          | first-class (`notifications/*`)                                                                |
| Reusable across LLM clients           | no — schema is client-shaped                         | **yes** — any MCP-capable client (Foundry, Claude, Copilot, LangGraph…) speaks the same wire  |
| Versioning                            | URL path versioning                                  | protocol version negotiated in `initialize`                                                   |

### 2.4 An actual MCP exchange on the wire

The HTTP envelope is boring (`POST`, JSON body, optional bearer header). What
is *inside* the body is the interesting part. Here are the three calls that
power one Seattle weather lookup:

**Turn 1 — Handshake (`initialize`)**
```json
→ {"jsonrpc":"2.0","id":1,"method":"initialize",
   "params":{"protocolVersion":"2024-11-05","capabilities":{},
             "clientInfo":{"name":"foundry","version":"1"}}}
← {"jsonrpc":"2.0","id":1,
   "result":{"protocolVersion":"2024-11-05",
             "capabilities":{"tools":{}},
             "serverInfo":{"name":"weather-mcp","version":"1.0.0"}}}
```
The server also returns an `Mcp-Session-Id` HTTP response header that the
client must echo on every subsequent request.

**Turn 2 — Discovery (`tools/list`) — this is the MCP magic**
```json
→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
← {"jsonrpc":"2.0","id":2,"result":{"tools":[
     {"name":"get_weather",
      "description":"Returns current weather for a city by name.",
      "inputSchema":{"type":"object",
                     "properties":{"location":{"type":"string"}},
                     "required":["location"]}}
   ]}}
```
Foundry feeds that schema into gpt-4o's tool-calling context. The model now
knows the tool exists and how to call it — **without you writing any of it on
the agent side**.

**Turn 3 — Invocation (`tools/call`)**
```json
→ {"jsonrpc":"2.0","id":3,"method":"tools/call",
   "params":{"name":"get_weather","arguments":{"location":"Seattle"}}}
← {"jsonrpc":"2.0","id":3,"result":{
     "content":[{"type":"text",
                 "text":"{\"tempF\":66,\"wind\":\"8 km/h WNW\"}"}]}}
```

### 2.5 The exact HTTP request the agent sends

```http
POST /runtime/webhooks/mcp HTTP/1.1
Host: <your-func-app>.azurewebsites.net
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...    ← Iteration 2 (Entra)
Content-Type: application/json
Accept: application/json, text/event-stream
Mcp-Session-Id: <bound after initialize>

{ "jsonrpc": "2.0", "id": 3, "method": "tools/call",
  "params": { "name": "get_weather", "arguments": { "location": "Seattle" } } }
```

- **Transport** = HTTP — the gateway, Easy Auth, App Insights all "just work".
- **Protocol** = MCP — the body, the session, the discovery handshake.

### 2.6 What endpoints does this server actually expose?

The whole point of MCP is **one URL serves the whole protocol** — but Azure
Functions hosts a handful of utility endpoints alongside it.

| URL path                    | Method | Who calls it       | Auth (Iter 1)              | Auth (Iter 2)                       | Purpose                                                                                                   |
| --------------------------- | ------ | ------------------ | -------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `/runtime/webhooks/mcp`     | `POST` | Agent (Foundry)    | `?code=<system-key>`       | `Authorization: Bearer <jwt>`       | **The MCP endpoint.** Speaks JSON-RPC: `initialize`, `tools/list`, `tools/call`, `notifications/*`, `ping`. Every MCP method goes here. |
| `/runtime/webhooks/mcp/sse` | `GET`  | Agent (Foundry)    | same as above              | same as above                       | Optional SSE transport for streaming partial tool results.                                                |
| `/api/whoami`               | `GET`  | You (debugging)    | anonymous                  | `Authorization: Bearer <jwt>`       | Iteration 2 claim probe — decodes Easy Auth's `X-MS-CLIENT-PRINCIPAL` header and returns `{oid, idp, roles, claims}`. |
| `/`                         | `GET`  | n/a                | none / Easy Auth           | Easy Auth (401 unauth)              | Default Function App landing page. Not part of MCP.                                                       |
| `/admin/host/status`        | `GET`  | n/a                | master key only            | master key only                     | Built-in Functions runtime admin. Never exposed to the agent.                                             |

**What lives behind the single `/runtime/webhooks/mcp` URL?** In
`function_app.py`, the decorator pair

```python
@app.mcp_tool()
@app.mcp_tool_property(arg_name="location",
                       description="City name, region, or ZIP/postal code.",
                       is_required=True)
def get_weather(location: str) -> str: ...
```

is enough to make the Functions MCP extension:

1. **Register `get_weather`** so it shows up in `tools/list` with its
   description and JSON schema (derived from type hints + decorator args).
2. **Route `tools/call`** invocations for that name into the Python function.
3. **Handle JSON-RPC envelope, session id, SSE framing, and protocol version
   negotiation** — none of that boilerplate is in your code.

To add `get_forecast`, write another `@app.mcp_tool()` function in the same
file. It appears in `tools/list` immediately; Foundry picks it up the next
time the agent runs — **with zero code changes on the agent side**.

---

## Part 3 · Architecture

### 3.1 The four moving parts

```
┌───────────────────────────┐                ┌────────────────────────────┐
│                           │                │                            │
│   YOUR PROCESS            │   1. mint      │   ENTRA ID                 │
│   06-weather-mcp-agent.py │      bearer    │   • App reg "weather-mcp"  │
│                           │◄──────────────►│   • MCP.Invoke app role    │
│   (client-side agent)     │   client_creds │   • appRoleAssignment      │
│                           │                │     Required = true        │
└─────┬──────────────────┬──┘                └──────────┬─────────────────┘
      │                  │                              │ validates JWT
      │ 2. chat          │ 3. MCP call (JSON-RPC)      │ on every call
      │    completions   │    + Authorization header   │
      ▼                  ▼                              ▼
┌──────────────┐   ┌──────────────────────────────────────────┐
│  FOUNDRY     │   │  AZURE FUNCTIONS                         │
│  PROJECT     │   │  ┌────────────────────────────────────┐  │
│              │   │  │  Easy Auth v2 (gatekeeper)         │  │
│  gpt-4o      │   │  │  • validates iss / aud / sig       │  │
│              │   │  │  • injects X-MS-CLIENT-PRINCIPAL   │  │
│              │   │  └────────────────────────────────────┘  │
│              │   │              │                           │
│              │   │              ▼                           │
│              │   │  ┌────────────────────────────────────┐  │
│              │   │  │  function_app.py                   │  │
│              │   │  │   @app.mcp_tool                    │  │
│              │   │  │   def get_weather(location): ...   │  │
│              │   │  └─────────────────┬──────────────────┘  │
│              │   │                    │  4. Open-Meteo      │
│              │   │                    ▼                     │
└──────┬───────┘   └──────────────────┬─────────────────────┘ │
       │                              │                       │
       └───────────┬──────────────────┘                       │
                   │                                          │
                   ▼  spans, traces, dependencies             │
       ┌──────────────────────────────────────────────────────┘
       │  APPLICATION INSIGHTS (same workspace, both sides)
       │  • cloud_RoleName = "foundry-workshop.weather-mcp" (agent)
       │  • cloud_RoleName = "<func-app-name>"              (server)
       │  → KQL cookbook stitches via operation_Id correlation
       └──────────────────────────────────────────────────────
```

### 3.2 The end-to-end call flow (sequence)

```
You          Agent process     Foundry         Azure Functions      Open-Meteo
  │               │              │                    │                  │
  │ run script    │              │                    │                  │
  ├──────────────►│              │                    │                  │
  │               │ 1. mint bearer (client_credentials, Entra)           │
  │               │◄═══════════════════════════════════════════════ Entra│
  │               │ 2. create_agent(tools=[McpTool(server_url=...,       │
  │               │                            headers={Authorization})])│
  │               │ 3. chat completion                                   │
  │               ├─────────────►│                    │                  │
  │               │              │ 4. gpt-4o:         │                  │
  │               │              │    "call get_weather(location=Seattle)│
  │               │◄─────────────┤                    │                  │
  │               │ 5. POST /runtime/webhooks/mcp                        │
  │               │     {tools/call,name:get_weather,args:{location:...}}│
  │               │     Authorization: Bearer <jwt>                      │
  │               ├──────────────────────────────────►│                  │
  │               │              │  6. Easy Auth validates the JWT       │
  │               │              │     - iss = v2 issuer for our tenant  │
  │               │              │     - aud = api://<MCP_APP_ID>        │
  │               │              │     - signature OK                    │
  │               │              │     - role MCP.Invoke is present      │
  │               │              │  7. injects X-MS-CLIENT-PRINCIPAL     │
  │               │              │  8. routes to function_app.get_weather│
  │               │              │                    │ 9. GET geocode + │
  │               │              │                    │    GET current   │
  │               │              │                    ├─────────────────►│
  │               │              │                    │◄──────────── JSON│
  │               │              │ 10. MCP tool result (text content)    │
  │               │◄──────────────────────────────────┤                  │
  │               │ 11. send tool result back to model                   │
  │               ├─────────────►│                    │                  │
  │               │              │ 12. gpt-4o formats final answer       │
  │               │◄─────────────┤                    │                  │
  │ prints answer │              │                    │                  │
  │◄──────────────┤              │                    │                  │
```

### 3.3 The two auth modes

```
ITERATION 1 (function-key auth)        ITERATION 2 (Entra / Easy Auth)
═══════════════════════════════        ═══════════════════════════════

Agent                                   Agent
  │                                      │
  │  x-functions-key: <system-key>       │  Authorization: Bearer <jwt>
  ▼                                      ▼
┌─────────────────────┐                ┌─────────────────────────────┐
│ Azure Functions     │                │ Easy Auth v2                │
│ webhook handler:    │                │   - validates iss/aud/sig   │
│   checks system key │                │   - 401 if missing/bad      │
│   401 if missing    │                │   - injects claims          │
└─────────┬───────────┘                └─────────┬───────────────────┘
          │                                      │
          ▼                                      ▼
   get_weather()                         Functions webhook handler:
                                           webhookAuthorizationLevel
                                              = "Anonymous"
                                              (Easy Auth is the gate)
                                          │
                                          ▼
                                    get_weather()
```

| Aspect                       | Iteration 1                                                                                          | Iteration 2                                                                                                  |
| ---------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Secret type                  | Long-lived **function key** (system key `mcp_extension`)                                              | Short-lived **JWT** minted per call by Entra                                                                  |
| Who can call                 | Anyone holding the key                                                                                | Only SPs that have been **explicitly granted the `MCP.Invoke` app role**                                      |
| Revoking one caller          | Rotate the key — affects **all** callers                                                              | Remove the app-role assignment for that SP only                                                                |
| Token expiry                 | None — key never expires                                                                              | ~1 h, re-minted automatically each run                                                                         |
| Tamper / leak blast radius   | Full access until rotated                                                                             | Restricted by `roles` claim + RBAC; signature pinning                                                          |
| Audit trail                  | "Some caller with the key" — opaque                                                                   | `X-MS-CLIENT-PRINCIPAL` gives you `oid`, `appid`, `idp`, `roles` — proven by `/api/whoami`                    |
| `host.json` setting          | `"webhookAuthorizationLevel": "System"`                                                               | `"webhookAuthorizationLevel": "Anonymous"` (Easy Auth is the sole gate)                                       |
| Setup complexity             | One key in `.env`                                                                                     | App registration + role + Easy Auth + role assignment                                                          |

### 3.4 Observability pipeline

```
Agent process                                     Function App
─────────────                                     ────────────
 init_observability("weather-mcp")                 OpenTelemetry runtime
       │                                           agent enabled by
       ▼                                           APPLICATIONINSIGHTS_*
 configure_azure_monitor(...)                      env vars from Bicep
       │                                                 │
       │ emits gen_ai.* spans for                        │ emits standard HTTP
       │ model calls and tool decisions                  │ request + dependency
       ▼                                                 ▼ spans
 ┌─────────────────────────────────────────────────────────────────┐
 │   Application Insights workspace (one for both)                 │
 │                                                                 │
 │   requests / dependencies / traces / customEvents / customMet…  │
 │                                                                 │
 │   stitched by operation_Id (W3C traceparent propagated through  │
 │   the HTTP call from agent → MCP server)                        │
 └─────────────────────────────────────────────────────────────────┘
            ▲
            │   KQL queries in kql/observability-cookbook.md
            │   answer:  what tool ran? for which user prompt?
            │            how long? how many tokens? what was the
            │            tool's inbound + outbound HTTP cost?
            │
       ┌─────────────────┐
       │   You (KQL)     │
       └─────────────────┘
```

---

## Part 4 · Lab — Iteration 1: deploy and call with a function key

> **Goal of this part.** Get the simplest, end-to-end working pipeline up:
> agent → MCP server → Open-Meteo → answer. Auth is just the Functions system
> key (`mcp_extension`). Total time: ~15 minutes.

### Step 1 — Clone the repo and enter the sample

```bash
git clone https://github.com/razi-rais/microsoft-foundry-resources.git
cd microsoft-foundry-resources/06-weather-mcp-agent
```

> 💡 **VS Code shortcut.** Skip the `cd` and open the lab folder directly:
> `code microsoft-foundry-resources/06-weather-mcp-agent`. The integrated
> terminal will open at that path.

You should see:

```
06-weather-mcp-agent/
├── README.md                       ← this file
├── 06-weather-mcp-agent.py         ← the agent
├── .env.example
├── kql/observability-cookbook.md
└── mcp-server/                     ← Azure Functions MCP server (azd-ready)
    ├── function_app.py
    ├── weather_service.py
    ├── host.json
    ├── requirements.txt
    ├── azure.yaml
    └── infra/
        ├── main.bicep
        └── main.parameters.json
```

### Step 2 — Sign in to Azure

```bash
az login --tenant <your-tenant-id>
az account set --subscription <your-subscription-id>
azd auth login
```

> 📘 **Why both `az` and `azd`?** `az` is used for ad-hoc reads (keys, role
> assignments). `azd` owns deployment. They have separate sign-in caches.

### Step 3 — Wire your Foundry App Insights into the deployment

To get cross-boundary KQL queries to work, the Function App must report to
the **same** Application Insights workspace as your Foundry project.

1. In the Foundry portal, open your project → **Manage → Tracing**. Copy the
   **Connection string** (starts with `InstrumentationKey=...;IngestionEndpoint=...`).
2. Tell `azd` to use it:

   ```bash
   cd mcp-server
   azd env new weather-mcp-demo                                      # name your env
   azd env set APPLICATIONINSIGHTS_CONNECTION_STRING "<paste here>"
   ```

> 📘 **If you skip this step**, the Bicep will provision a fresh App Insights
> automatically, but the agent's spans and the server's spans will live in
> *different* workspaces and KQL cross-correlation won't work.

### Step 4 — Deploy the MCP server with `azd up`

```bash
# Still in mcp-server/
azd up
```

> 💡 **VS Code shortcut.** Open the Command Palette (`Ctrl+Shift+P` /
> `Cmd+Shift+P`) and run **Azure Developer: Up**. You'll get the same
> prompts, with output streamed to the integrated terminal.

`azd` will:

1. Ask you for an Azure region (East US 2 is a good default).
2. Create a resource group `rg-<env-name>`.
3. Provision: Storage account → Flex Consumption plan → Function App
   (Python 3.13) → (optional) App Insights.
4. Deploy the function code.
5. Run a post-provision hook that prints the **MCP endpoint URL** and the
   exact `az` command to fetch the system key.

Expected last 10 lines:

```
SUCCESS: Your application was provisioned and deployed in 2 minutes 14 seconds.

------------------------------------------------------------
 MCP_ENDPOINT     https://<your-func-app>.azurewebsites.net/runtime/webhooks/mcp
 KEY_RETRIEVAL    az functionapp keys list --resource-group rg-weather-mcp-demo \
                       --name <your-func-app> --query systemKeys.mcp_extension -o tsv
------------------------------------------------------------
```

### Step 5 — Retrieve the function system key

```bash
az functionapp keys list \
  --resource-group rg-weather-mcp-demo \
  --name <your-func-app> \
  --query systemKeys.mcp_extension -o tsv
```

> 💡 **VS Code shortcut.** Open the **Azure** panel (the A icon in the
> activity bar) → expand your subscription → expand the function app →
> **Functions** node → right-click → **Copy Function URL** or **Copy Key**.
> No CLI required.

You'll get back a ~52-character base64-ish string. **This is a secret — treat
it like a password.** It goes in `.env` next.

### Step 6 — Configure the agent

Start inside this Git clone. Preserve an existing `.env`, especially one that
already contains a deployed MCP endpoint and key.

macOS Terminal:

```bash
cd "$(git rev-parse --show-toplevel)"
cd 06-weather-mcp-agent
test -f .env || cp .env.example .env
```

Windows PowerShell:

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
Set-Location .\06-weather-mcp-agent
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env` and fill in:

```bash
# Foundry project (from portal → your project → Overview)
FOUNDRY_PROJECT_ENDPOINT=https://<your-foundry>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL=gpt-4o

# MCP endpoint (from azd up output)
WEATHER_MCP_ENDPOINT=https://<your-func-app>.azurewebsites.net/runtime/webhooks/mcp

# Iteration 1: function-key auth
WEATHER_MCP_AUTH=key
WEATHER_MCP_KEY=<paste the mcp_extension key from step 5>

# Same App Insights connection string you set in step 3
APPLICATIONINSIGHTS_CONNECTION_STRING=<paste here too>
```

### Step 7 — Install agent dependencies

Use the repository root environment shared with samples 01 through 04.
The existing pinned requirements also supply this agent's dependencies.
Do not install an unpinned `agent-framework` metapackage into another environment.
Python 3.13, Git and Azure CLI must be installed.

macOS Terminal:

```bash
cd "$(git rev-parse --show-toplevel)"
test -x .venv/bin/python || python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-first-four.txt
.venv/bin/python -m pip check
az login
```

Windows PowerShell:

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-first-four.txt
.\.venv\Scripts\python.exe -m pip check
az login
```

### Step 8 — Run the agent

Save `06-weather-mcp-agent/.env` first. Foundry calls the deployed MCP server,
so do not replace its endpoint with localhost. This process does not publish a
named Foundry agent.

macOS Terminal:

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -X utf8 06-weather-mcp-agent/06-weather-mcp-agent.py
```

Windows PowerShell:

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
.\.venv\Scripts\python.exe -X utf8 .\06-weather-mcp-agent\06-weather-mcp-agent.py
```

> **VS Code.** Select the repository root `.venv` interpreter, open
> `06-weather-mcp-agent.py` and select **Run Python File**.
> The script itself loads `06-weather-mcp-agent/.env`.

The MCP server was verified separately after deployment. A complete invocation
of this agent through Foundry and Windows execution remain unverified.

Expected output:

```
[observability] ✓ enabled  scenario='weather-mcp'  → Application Insights
[auth] WEATHER_MCP_AUTH=key

# User: "What's the current weather in Seattle, WA?"
# weather-mcp-agent: The current weather in Seattle, WA is partly cloudy with
  a temperature of 18°C (64°F). Humidity is at 55%, with a light wind blowing
  at 8 km/h from the WNW. Reported at 2026-05-24T22:15:00Z.

# User: 'And how about Paris?'
# weather-mcp-agent: ...

# User: 'Compare the wind in Mumbai and Sydney right now.'
# weather-mcp-agent: ...

--- All tasks completed successfully ---
Program finished.
```

✓ **Iteration 1 complete.** You now have an end-to-end MCP pipeline.

### Step 9 — Verify with KQL (optional but recommended)

Open [`kql/observability-cookbook.md`](kql/observability-cookbook.md) and run
**Strategy 2: The cross-boundary waterfall**. You should see one
`operation_Id` that contains both:
- agent-side spans (gpt-4o chat completion, tool decision, token counts)
- server-side spans (HTTP request to `/runtime/webhooks/mcp`, outbound
  dependency to Open-Meteo)

That single waterfall is the proof your observability wiring is correct.

> 💡 **VS Code shortcut.** Create a new file `query.kql` and paste any
> cookbook query into it. With the **Kusto** extension installed, the editor
> title bar gets a green ▶ **Run Query** button. Connect once to your
> Application Insights workspace, and every subsequent query runs in-place
> with results rendered as a table directly in the editor.

---

## Part 5 · Lab — Iteration 2: harden with Microsoft Entra

> **Goal of this part.** Replace the long-lived function key with a JWT-based
> auth model:
> - Function App is gated by **Easy Auth v2**.
> - Only callers explicitly granted the `MCP.Invoke` app role can mint a token.
> - Each call is auditable via the injected `X-MS-CLIENT-PRINCIPAL` header.
>
> Total time: ~30 minutes. Iteration 1 is a complete sample on its own — do
> Iteration 2 only if you care about JWT-based auth or want to mirror what a
> production Foundry deployment would look like.

### 5.1 What changes

| Layer                                  | Iteration 1                            | Iteration 2                                                                          |
| -------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------ |
| Entra app registration                 | none                                   | **new** — exposes `MCP.Invoke` app role, v2 tokens                                  |
| Function App auth                      | function key only                      | **Easy Auth v2 (AAD)** validating JWT issuer + audience + signature                  |
| Caller authorization                   | "holds the key"                        | **app-role assignment** on the MCP server SP                                          |
| `host.json` `webhookAuthorizationLevel`| `System`                               | `Anonymous` (Easy Auth becomes the sole gate)                                         |
| Function App code change               | none                                   | adds `/api/whoami` claim probe — `get_weather` unchanged                              |
| Caller HTTP header                     | `x-functions-key: <key>`               | `Authorization: Bearer <jwt>`                                                         |
| Stored secret                          | `WEATHER_MCP_KEY` in `.env`            | None at rest in the agent — token minted per run via client credentials               |

### 5.2 The Entra security model

```
┌──────────────────────────────────────────────────────────────────────┐
│  Entra ID (your tenant)                                              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  App registration: "weather-mcp"                                │ │
│  │   - appId                <MCP_APP_ID>                           │ │
│  │   - identifierUris       api://<MCP_APP_ID>                     │ │
│  │   - accessTokenAccepted  v2                                     │ │
│  │   - appRoles                                                    │ │
│  │       - id     <MCP_INVOKE_ROLE_ID>                             │ │
│  │       - value  MCP.Invoke                                       │ │
│  │       - allowedMemberTypes ["Application"]                      │ │
│  └─────────────────────────────┬───────────────────────────────────┘ │
│                                │ creates                             │
│                                ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Service principal "weather-mcp" (server-side identity)         │ │
│  │   - appRoleAssignmentRequired = true   ◄── KEY                  │ │
│  │     (Entra refuses to mint a token for unassigned callers)      │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                │                                     │
│                                │ grant MCP.Invoke to ...             │
│                                ▼                                     │
│  ┌──────────────────────────────────────────┐                        │
│  │  Caller SP (e.g. workshop-runner)         │                        │
│  │   - any service principal in same tenant │                        │
│  │   - can now mint tokens with             │                        │
│  │     roles=["MCP.Invoke"] in JWT          │                        │
│  └──────────────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTPS bearer
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Function App: <your-func-app>                                       │
│                                                                      │
│   Easy Auth v2 config (in Bicep):                                    │
│    - issuer:     https://login.microsoftonline.com/<tenant>/v2.0     │
│    - audiences:  api://<MCP_APP_ID>,  <MCP_APP_ID>                   │
│    - unauthenticatedClientAction: Return401  ◄── critical            │
│    - tokenStore: disabled (pure API)                                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

> 📘 **Defense in depth.** Three independent layers protect the server:
> 1. **Entra** won't issue a token without the role assignment.
> 2. **Easy Auth** won't pass the request without a valid JWT for our audience.
> 3. **`/api/whoami`** proves which identity actually called.

### Step 1 — Create the Entra app registration

Run these from a shell that is `az login`-ed to the same tenant where the
**caller** will sign in (your user, or a deployment SP).

```bash
# 1. The app registration that represents your MCP server in Entra
MCP_APP_ID=$(az ad app create --display-name weather-mcp \
              --sign-in-audience AzureADMyOrg \
              --query appId -o tsv)
echo "MCP_APP_ID=$MCP_APP_ID"          # ← save; you'll need this everywhere

# Use the immutable GUID-based App ID URI — never collides with a sibling app.
az ad app update --id $MCP_APP_ID --identifier-uris "api://$MCP_APP_ID"
```

### Step 2 — Force v2 access tokens & add the `MCP.Invoke` app role

```bash
ROLE_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
echo "ROLE_ID=$ROLE_ID"

cat > /tmp/patch.json <<JSON
{
  "api": { "requestedAccessTokenVersion": 2 },
  "appRoles": [{
    "id": "$ROLE_ID",
    "displayName": "MCP.Invoke",
    "description": "Invoke MCP tools on the weather server",
    "value": "MCP.Invoke",
    "allowedMemberTypes": ["Application"],
    "isEnabled": true
  }]
}
JSON

az rest --method PATCH \
  --url "https://graph.microsoft.com/v1.0/applications(appId='$MCP_APP_ID')" \
  --headers "Content-Type=application/json" \
  --body @/tmp/patch.json
```

> 📘 **Why force v2?** It locks the `iss` claim to
> `https://login.microsoftonline.com/<tenant>/v2.0`, which is exactly what
> Easy Auth will accept. Without it, callers can request v1 tokens
> (`iss=https://sts.windows.net/<tenant>/`) and your validation breaks.

### Step 3 — Create the server SP & require role assignments

```bash
MCP_SP_OID=$(az ad sp create --id $MCP_APP_ID --query id -o tsv)
echo "MCP_SP_OID=$MCP_SP_OID"

# THIS is the critical flag: Entra now refuses to mint tokens for callers
# that don't have an assignment on this app.
az ad sp update --id $MCP_SP_OID --set appRoleAssignmentRequired=true
```

### Step 4 — Create a caller SP and grant the role

For a workshop you usually want a dedicated caller SP (so it can use client
credentials cleanly).

```bash
CALLER_APP_ID=$(az ad app create --display-name weather-mcp-caller \
                  --sign-in-audience AzureADMyOrg \
                  --query appId -o tsv)
CALLER_SP_OID=$(az ad sp create --id $CALLER_APP_ID --query id -o tsv)

# Grant a 1-year client secret (capture the value — it's only shown once)
CALLER_SECRET=$(az ad app credential reset --id $CALLER_APP_ID \
                  --display-name workshop \
                  --years 1 --query password -o tsv)

# Grant MCP.Invoke to the caller
cat > /tmp/grant.json <<JSON
{
  "principalId": "$CALLER_SP_OID",
  "resourceId":  "$MCP_SP_OID",
  "appRoleId":   "$ROLE_ID"
}
JSON

az rest --method POST \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_SP_OID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body @/tmp/grant.json
```

> 📘 **Revoking access later.** `DELETE /v1.0/servicePrincipals/<CALLER_SP_OID>/appRoleAssignments/<assignment-id>` removes one caller's access without touching anyone else.

### Step 5 — Enable Easy Auth on the Function App (via Bicep)

The Bicep already supports this — it's gated on a non-empty `entraAppId`
parameter. Tell `azd` about the app you just created:

```bash
cd mcp-server
azd env set WEATHER_MCP_ENTRA_APP_ID $MCP_APP_ID
azd provision        # only re-runs the auth config; no app code redeploy
```

What this provisions (excerpt from `infra/main.bicep`):

```bicep
resource authSettings 'Microsoft.Web/sites/config@2024-04-01' = if (enableEasyAuth) {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'    // NEVER RedirectToLoginPage
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://login.microsoftonline.com/${entraTenantId}/v2.0'
          clientId: entraAppId
        }
        validation: {
          allowedAudiences: [ 'api://${entraAppId}', entraAppId ]
        }
      }
    }
    login: { tokenStore: { enabled: false } }     // pure API, no cookies
  }
}
```

### Step 6 — Flip `host.json` to anonymous webhooks

The Functions runtime's webhook handler has its own auth check that *also*
needs the function key — but Easy Auth strips the key, producing a baffling
403. The fix is to let Easy Auth be the only gate:

```jsonc
// mcp-server/host.json
{
  "version": "2.0",
  "extensions": {
    "mcp": {
      "instructions": "...",
      "webhookAuthorizationLevel": "Anonymous"    // ← changed from "System"
    }
  }
}
```

Redeploy: `azd deploy api`.

### Step 7 — Verify with curl

```bash
# Fresh bearer from the caller SP
TOKEN=$(curl -sS -X POST \
  "https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CALLER_APP_ID" \
  -d "client_secret=$CALLER_SECRET" \
  -d "scope=api://$MCP_APP_ID/.default" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# (a) Unauthenticated POST → 401
curl -sS -o /dev/null -w "no-auth: %{http_code}\n" -X POST \
  https://<your-func-app>.azurewebsites.net/runtime/webhooks/mcp -d '{}'
# → no-auth: 401

# (b) Bearer succeeds with full MCP initialize handshake → 200
curl -sS -o /dev/null -w "bearer: %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST https://<your-func-app>.azurewebsites.net/runtime/webhooks/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"curl","version":"1"}}}'
# → bearer: 200

# (c) The whoami probe — proves Easy Auth injected our claims
curl -sS https://<your-func-app>.azurewebsites.net/api/whoami \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# → { "authenticated": true,
#     "oid":   "<caller-sp-objectId>",
#     "idp":   "aad",
#     "roles": ["MCP.Invoke"],
#     ... }
```

✓ **Easy Auth is working.** Three independent proofs:
1. 401 on no auth
2. 200 on valid bearer
3. `roles: ["MCP.Invoke"]` in the decoded claims

### Step 8 — Switch the agent to Entra mode

Update `.env`:

```bash
WEATHER_MCP_AUTH=entra
WEATHER_MCP_AUDIENCE=api://<MCP_APP_ID>
# WEATHER_MCP_KEY is no longer used; you can leave it set for rollback.
```

The agent code in `06-weather-mcp-agent.py` supports three sub-paths inside
`entra` mode (see `_build_mcp_headers()`):

1. **`WEATHER_MCP_TOKEN`** env var — a pre-acquired JWT. Used by CI / scripts
   that mint the token themselves (the curl in step 7).
2. **`AzureCliCredential.get_token(<audience>/.default)`** — works only if
   the Azure CLI public app has been pre-consented to your audience.
   *Most users hit consent errors here* (`AADSTS65001`).
3. **Fallback** — error message telling you to provide one of the above.

For workshop runs the easiest path is option 1: mint a bearer once per run
and inject it as `WEATHER_MCP_TOKEN`. Wrap the run in a one-liner:

```bash
TOKEN=$(curl -sS -X POST \
  "https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CALLER_APP_ID" \
  -d "client_secret=$CALLER_SECRET" \
  -d "scope=api://$MCP_APP_ID/.default" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

WEATHER_MCP_TOKEN="$TOKEN" python 06-weather-mcp-agent.py
```

Expected output is identical to Iteration 1, plus `[auth] WEATHER_MCP_AUTH=entra`
at startup.

### 5.3 Known limitation: the Foundry portal "Add MCP tool" UX

The Foundry portal lets you register an MCP server against a hosted agent
("Add Tools → Model Context Protocol"). Two save modes exist:

| Mode in portal                | Backed by                                                       | Works for you?                                                                                |
| ----------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Key-based**                 | Foundry-managed Key Vault project connection                    | Only if your Foundry resource's managed identity is in the **same tenant** as your Key Vault. |
| **Microsoft Entra → Agent Identity** | Foundry's ARA service mints a JWT per call for your audience      | Only if your Foundry resource's MI is in the **same tenant** as your Entra app reg.            |

If your Foundry resource was provisioned in a **different tenant** than the
one where you'd register the MCP server's app reg, **both portal modes will
fail**:
- Key-based save → `CrossTenantCredentialRequestForbidden`
- Agent Identity invocation → `ARA request failed: BadRequest`

This is a Foundry preview limitation, not anything you can fix server-side.
The **SDK / client-side** path documented above is the workaround that always
works regardless of tenant topology.

---

## Part 6 · Observability — KQL queries that prove it all worked

The full cookbook lives in [`kql/observability-cookbook.md`](kql/observability-cookbook.md).
The two most useful queries:

### 6.1 "What did the last 5 agent runs look like?"

```kusto
dependencies
| where cloud_RoleName == "foundry-workshop.weather-mcp"
| where name == "chat gpt-4o" or name has "tools/call"
| project timestamp, name, duration, operation_Id,
          tool   = tostring(customDimensions['gen_ai.tool.name']),
          in_tok = toint(customDimensions['gen_ai.usage.input_tokens']),
          out_tok= toint(customDimensions['gen_ai.usage.output_tokens'])
| order by timestamp desc
| take 20
```

### 6.2 "Cross-boundary waterfall: one prompt across both sides"

```kusto
// Replace <OP> with an operation_Id from query 6.1
union requests, dependencies, traces
| where timestamp > ago(30m)
| where operation_Id == "<OP>"
| project timestamp,
          kind             = itemType,         // 'request' | 'dependency' | 'trace'
          cloud_RoleName,
          name,
          target,
          duration,
          tool   = tostring(customDimensions['gen_ai.tool.name']),
          args   = tostring(customDimensions['gen_ai.tool.call.arguments']),
          model  = tostring(customDimensions['gen_ai.request.model']),
          in_tok = tostring(customDimensions['gen_ai.usage.input_tokens']),
          out_tok= tostring(customDimensions['gen_ai.usage.output_tokens']),
          msg    = message
| order by timestamp asc
```

> 📘 **Why `kind = itemType`?** Don't use `kind = $table` — that's invalid in
> the Application Insights schema and causes a `Query could not be parsed`
> error. Use `itemType` instead (it's the column the union row tracks).

### 6.3 "Who actually called my MCP server today?" (Iteration 2 only)

```kusto
traces
| where timestamp > ago(1d)
| where message contains "[whoami]"
| extend oid   = extract(@"oid=([^ ]+)",   1, message)
| extend idp   = extract(@"idp=([^ ]+)",   1, message)
| extend roles = extract(@"roles=([^ ]+)", 1, message)
| summarize calls = count() by oid, idp, roles
| order by calls desc
```

---

## Part 7 · Reference

### 7.1 Environment variables

| Var                                         | Required        | Example                                                              | Notes                                                                 |
| ------------------------------------------- | --------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `FOUNDRY_PROJECT_ENDPOINT`                  | always          | `https://<foundry>.services.ai.azure.com/api/projects/<project>`     | From Foundry portal → Overview.                                       |
| `FOUNDRY_MODEL`                             | optional        | `gpt-4o`                                                             | Defaults to `gpt-4o`. Any chat-completion deployment in your project. |
| `WEATHER_MCP_ENDPOINT`                      | always          | `https://<func>.azurewebsites.net/runtime/webhooks/mcp`              | The MCP endpoint from `azd up`.                                       |
| `WEATHER_MCP_AUTH`                          | optional        | `key` or `entra`                                                     | Auto-detects: `entra` if `WEATHER_MCP_AUDIENCE` set, else `key`.       |
| `WEATHER_MCP_KEY`                           | iter 1          | `<52-char base64>`                                                   | The `mcp_extension` system key.                                       |
| `WEATHER_MCP_AUDIENCE`                      | iter 2          | `api://<MCP_APP_ID>`                                                 | Audience of the Entra app reg protecting the function.                |
| `WEATHER_MCP_TOKEN`                         | iter 2 (CI)     | `eyJ0eXAiOiJKV1Qi...`                                                | Pre-acquired bearer. Bypasses `AzureCliCredential` consent issues.    |
| `APPLICATIONINSIGHTS_CONNECTION_STRING`     | recommended     | `InstrumentationKey=...;IngestionEndpoint=...`                       | Same workspace used by Foundry — required for cross-boundary KQL.     |

### 7.2 Files in this sample

| File                                          | Purpose                                                                                    |
| --------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `06-weather-mcp-agent.py`                     | The agent. Builds MCP headers, registers `McpTool`, runs three prompts, cleans up.         |
| `.env.example`                                | Template `.env` — copy to `.env`, fill in your values. `.env` is `.gitignored`.              |
| `kql/observability-cookbook.md`               | KQL queries with sample output: per-run summary, cross-boundary waterfall, identity probe. |
| `mcp-server/function_app.py`                  | `@app.mcp_tool def get_weather(location)` + `@app.route("/api/whoami")` claim probe.       |
| `mcp-server/weather_service.py`               | Pure-Python Open-Meteo client (geocode + current observation). No SDK.                     |
| `mcp-server/host.json`                        | Enables the MCP extension. Iter 1: webhook level `System`; Iter 2: `Anonymous`.            |
| `mcp-server/requirements.txt`                 | `azure-functions>=2.0.0b1`, `azure-monitor-opentelemetry`, urllib instrumentor.            |
| `mcp-server/azure.yaml`                       | `azd` service definition + post-provision hook that prints the endpoint and key command.   |
| `mcp-server/infra/main.bicep`                 | Storage + Flex plan + Function App + (optional) App Insights + (optional) Easy Auth.       |
| `mcp-server/infra/main.parameters.json`       | Bicep parameter bindings to `azd env` vars.                                                |
| `mcp-server/local.settings.json.example`      | Template for `func start` local dev.                                                       |

### 7.3 The `McpTool` API used in the agent

```python
from agent_framework.foundry import FoundryChatClient

client = FoundryChatClient(model="gpt-4o",
                           project_endpoint=PROJECT_ENDPOINT,
                           credential=AzureCliCredential())

mcp_tool = client.get_mcp_tool(
    name="weather-mcp-azure-functions",     # any human name
    url=MCP_ENDPOINT,                        # the /runtime/webhooks/mcp URL
    approval_mode="never_require",           # safe for read-only tools
    headers=mcp_headers,                     # auth headers — see below
    allowed_tools=["get_weather"],           # opt-in whitelist
)
```

The `headers` dict is **passed verbatim on every MCP call** by Foundry. This
is the seam where the two auth modes diverge:

```python
# Iteration 1
mcp_headers = {"x-functions-key": os.environ["WEATHER_MCP_KEY"]}

# Iteration 2
mcp_headers = {"Authorization": f"Bearer {acquired_jwt}"}
```

---

## Part 8 · Troubleshooting

| Symptom                                                                                    | Likely cause                                                                                                   | Fix                                                                                                                                                |
| ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `401` on every MCP call (Iter 1)                                                           | Wrong function key, or key from the wrong app                                                                 | `az functionapp keys list ... --query systemKeys.mcp_extension -o tsv` — make sure it matches.                                                      |
| `401` on every MCP call (Iter 2)                                                           | Easy Auth not yet provisioned, or audience mismatch                                                            | Run the curl in §5.7. If even unauth gets 200, Easy Auth never enabled — re-run `azd provision` with `WEATHER_MCP_ENTRA_APP_ID` set.               |
| `403` with valid bearer + valid function key (Iter 2)                                      | `host.json` still has `webhookAuthorizationLevel: "System"`                                                    | Change to `"Anonymous"` and `azd deploy api`. With Easy Auth on, the webhook level **must** be `Anonymous`.                                        |
| `AADSTS65001: The user or administrator has not consented`                                 | `AzureCliCredential` can't mint a custom-audience token without scope consent                                  | Use the `WEATHER_MCP_TOKEN` path: mint via `client_credentials` and inject the bearer directly.                                                    |
| `AADSTS500011: The resource principal was not found in the tenant`                         | App registration is in a different tenant than `az login`                                                      | `az login --tenant <correct-tenant>` and retry.                                                                                                    |
| Tool returns "Argument 'location' is required"                                             | Model called the tool with an empty/missing arg                                                                | Check the system prompt — confirm it tells the model to always pass `location`.                                                                    |
| KQL query "Query could not be parsed at 'kind' on line [4,22]"                             | Used `kind = $table` — invalid syntax                                                                          | Use `kind = itemType` instead. Updated in §6.2 of this doc.                                                                                        |
| Foundry portal "Add MCP tool" save fails with `CrossTenantCredentialRequestForbidden`      | Foundry resource MI is in a different tenant than your Key Vault                                               | See §5.3 — use the SDK path. Recreating the Foundry resource in the right tenant is the only "real" fix.                                          |
| Foundry portal Agent Identity tool call fails with `ARA request failed: BadRequest`        | Same cross-tenant constraint as above, but surfaced at runtime                                                 | Same answer.                                                                                                                                       |
| App Insights shows the function calls but no `gen_ai.*` spans from the agent              | `init_observability` not called, or the wrong connection string used                                            | Check the agent's first log line: `[observability] ✓ enabled scenario='weather-mcp' → Application Insights`. If absent, your env var is wrong.    |

---

## Part 9 · Cleanup & rollback

### 9.1 Tear down everything

```bash
# Removes the resource group, Function App, storage, App Insights (if Bicep created it)
cd mcp-server
azd down --purge --force
```

### 9.2 Roll back Iteration 2 → Iteration 1

```bash
# 1. Disable Easy Auth instantly
az webapp auth update --resource-group <rg> --name <func-name> --enabled false

# 2. Revert host.json (webhook level back to System) and redeploy
git checkout HEAD -- mcp-server/host.json
azd deploy api

# 3. In .env, switch back:
#    WEATHER_MCP_AUTH=key
#    (WEATHER_MCP_KEY is already populated)
```

### 9.3 Revoke one specific caller (Iteration 2)

Find the assignment id:

```bash
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_SP_OID/appRoleAssignments" \
  --query "value[?appRoleId=='$ROLE_ID'].id" -o tsv
```

Delete it:

```bash
az rest --method DELETE \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_SP_OID/appRoleAssignments/<id>"
```

Effect is immediate — Entra refuses to mint tokens for that SP on the next
request, no Function App restart needed.

### 9.4 Delete the Entra app registrations

```bash
az ad app delete --id $MCP_APP_ID
az ad app delete --id $CALLER_APP_ID
```

---

## Attribution

The `get_weather` implementation and the Functions MCP extension pattern are
adapted from the official
[`Azure-Samples/remote-mcp-functions-python`](https://github.com/Azure-Samples/remote-mcp-functions-python)
template (MIT-licensed).

The Open-Meteo data is provided free of charge by
[open-meteo.com](https://open-meteo.com) under
[CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/).
