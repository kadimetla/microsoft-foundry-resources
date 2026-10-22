# Microsoft Foundry + Entra Agent ID Sidecar

A visual, hands-on demonstration of how AI agents use **Microsoft Entra Agent ID** (via the official **Microsoft Entra SDK auth sidecar**) to securely call downstream APIs. This variant uses **Microsoft Foundry** as the LLM/agent runtime, proving the sidecar pattern works identically whether the model is local (Ollama), in AWS (Bedrock), or in your Foundry project.

> **Looking for other LLM variants?** The **Ollama** (offline, local) and **AWS Bedrock** (Claude) editions live in a separate, multi-cloud companion repo: [`razi-rais/3P-Agent-ID-Demo`](https://github.com/razi-rais/3P-Agent-ID-Demo).
>
> **New to Agent ID?** Start with [The Sidecar Design Pattern](../README.md) for the concepts.

---

## 1. Why the Microsoft Entra SDK sidecar?

This sample deliberately uses the **official [Microsoft Entra SDK auth sidecar](https://mcr.microsoft.com/en-us/product/entra-sdk/auth-sidecar/about)** container (`mcr.microsoft.com/entra-sdk/auth-sidecar`) rather than rolling our own token client. Here's why:

- **Interoperable across any cloud or on-prem** — the same container image runs identically on Azure, AWS, GCP, Kubernetes, or a laptop. This sample puts it next to **Microsoft Foundry** to make the "your identity, your model, no secrets in the agent" story concrete.
- **Your agent code stays decoupled from token exchanges.** The agent never handles `client_id`, `client_secret`, certificates, JWKS, token caching, or OBO exchange. It just asks the sidecar: *"Give me an authorization header for this downstream API."*
- **Swap credentials without touching agent code.** `ClientSecret` for dev, `SignedAssertionFromManagedIdentity` when deployed on Azure — change one env var, no code changes.
- **Token caching, refresh, and expiry are handled for you.** No MSAL integration to debug.
- **Security boundary is explicit.** The sidecar has no host port. Only services inside the Docker network can request tokens.

### What the agent does vs what the sidecar does

| Agent (your code) | Sidecar (Microsoft Entra SDK) |
|---|---|
| Decide *when* to call the API | Acquire and cache the right token |
| Build the HTTP request | Perform client-credentials / OBO exchange |
| Pass through user token for OBO | Validate & forward user assertion |
| Handle business logic | Talk to `login.microsoftonline.com` |

---

## 2. What this sample demonstrates

- **Two execution modes**: `Direct` (skip LLM, fast demo of token flow) vs `Foundry` (LangChain + Microsoft Foundry model makes the tool-call decision)
- **Two identity flows**: `Autonomous` (app-only token) vs `OBO` (acts on behalf of a signed-in user)
- **Full token lifecycle**: Tc (user token) → T1 (blueprint app token) → TR (agent token) → downstream API
- **JWT validation end-to-end**: The weather API verifies signature (JWKS / RS256), issuer, and expiry on every request
- **LangGraph ReAct agent**: Modern LangChain 1.x pattern with `langchain.agents.create_agent`
- **Two Foundry auth modes**: API key (quickest demo) or `DefaultAzureCredential` (no secret in `.env`)

### Modes and flows (2×2 matrix)

|  | **Autonomous** (app-only) | **OBO** (on behalf of user) |
|---|---|---|
| **Direct** (no LLM) | Fast demo path. TR token fetched, weather API called directly. | Same, but uses the authenticated sidecar endpoint with Tc. |
| **Foundry + LangChain** | LangGraph ReAct agent decides when to call `get_weather`. | Same, agent passes Tc through when the tool runs. |

---

## 3. Architecture

The sidecar sits between your agent and Microsoft Entra ID. The agent **never** talks to Entra directly, and it **never** sees an Entra credential — it just asks the sidecar for an `Authorization:` header for a named downstream API. Microsoft Foundry is just the LLM provider; identity for the downstream weather API is owned by the sidecar.

### 3.1 High-level flow (the 30-second view)

```
   ┌──────────┐  ask     ┌──────────┐  get token   ┌──────────┐
   │  Agent   │────────▶ │ Sidecar  │ ───────────▶ │  Entra   │
   │ (Flask + │          │ (Entra   │ ◀─────────── │   ID     │
   │ Foundry) │◀──────── │   SDK)   │   TR token   └──────────┘
   └────┬─────┘ header   └──────────┘
        │
        │ call API with Bearer TR
        ▼
   ┌──────────┐
   │ Weather  │   validates TR, returns data
   │   API    │
   └──────────┘

   ┌──────────────────┐   LLM inference (separate concern)
   │ Microsoft        │ ◀── agent calls this for reasoning,
   │ Foundry (model)  │    using its own Foundry credential
   └──────────────────┘    (API key or Managed Identity)
```

**Three identity moving parts, one rule:** the **Agent** focuses on reasoning, the **Sidecar** owns all downstream-API identity/credential work, and the **downstream API** just validates the token it's given. The LLM provider (Foundry) is a separate concern with its own credential path.

### 3.2 Detailed architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                     agent-network-foundry (Docker bridge)                     │
│                                                                               │
│  You (browser)                                                                │
│   http://localhost:3004 ────┐                                                 │
│                             ▼                                                 │
│   ┌──────────────────────────────────┐                                        │
│   │  llm-agent-foundry  (Flask + UI) │                                        │
│   │  :3000 → host :3004              │                                        │
│   │                                  │                                        │
│   │  ① Receive user query            │                                        │
│   │  ② LangGraph ReAct agent runs    │ ─── ① calls Foundry endpoint ──┐       │
│   │  ③ Tool needs to call weather API│                                │       │
│   │     → ask sidecar for a token    │                                ▼       │
│   └──────────────┬───────────────────┘                       ┌──────────────┐ │
│                  │ ④ GET /AuthorizationHeader...             │  Microsoft   │ │
│                  │    ?AgentIdentity={agentId}               │  Foundry     │ │
│                  │    (Bearer Tc if OBO)                     │  (model)     │ │
│                  ▼                                           └──────────────┘ │
│   ┌──────────────────────────────────┐      ⑤ OAuth2   ┌─────────────────┐   │
│   │  agent-id-sidecar-foundry        │ ──────────────▶ │  Microsoft      │   │
│   │  Microsoft Entra SDK             │                 │  Entra ID       │   │
│   │  (official MS container image)   │ ◀────────────── │  login.micro... │   │
│   │  NO host port — network only     │   ⑥ T1 or TR    └─────────────────┘   │
│   └──────────────┬───────────────────┘                                        │
│                  │ ⑦ Authorization: Bearer TR                                 │
│                  ▼                                                            │
│   ┌──────────────────────────────────┐                                        │
│   │  weather-api-foundry             │                                        │
│   │                                  │                                        │
│   │  ⑧ Validate TR (JWKS, RS256,     │                                        │
│   │    issuer, expiry, audience)     │                                        │
│   │  ⑨ Return weather JSON           │                                        │
│   └──────────────────────────────────┘                                        │
└───────────────────────────────────────────────────────────────────────────────┘
```

**The key insight:** step ⑤ and ⑥ are the *only* place an Entra credential is ever handled. It happens inside the sidecar, on a network the agent can't directly reach from outside. Your agent code at step ③ just does `requests.get(sidecar_url)` — no MSAL, no certificates, no Entra secrets in application memory. The Foundry credential at step ① is a separate, smaller surface (an API key or a Managed Identity token).

### Token flow

| Token | Issued to | When | How |
|---|---|---|---|
| **Tc** | Signed-in user | OBO flow only | MSAL.js in the browser |
| **T1** | Blueprint app | Both flows | Sidecar (client credentials) |
| **TR** | Agent (downstream API) | Both flows | Sidecar — app-only (autonomous) or OBO exchange |

---

## 4. Prerequisites

- Docker Desktop (or Docker + compose plugin)
- A Microsoft Entra tenant with the Blueprint + Agent Identity provisioned. The PowerShell bootstrap (`Start-EntraAgentIDWorkflow`) lives in the multi-cloud companion repo: [`razi-rais/3P-Agent-ID-Demo`](https://github.com/razi-rais/3P-Agent-ID-Demo).
- A Microsoft Foundry project with at least one chat model deployed (for example, `gpt-4o-mini`)
- Either a Foundry API key, or Azure CLI installed locally (`az login`) for `DefaultAzureCredential`

### 4.1 Grant Microsoft Graph permissions to the Agent Identity

The **OBO** toggle in this demo asks the Agent Identity (`AGENT_CLIENT_ID`) to exchange the signed-in user's token for a downstream Microsoft Graph token. If the Agent Identity is not pre-authorized to request Graph scopes on behalf of users, sign-in fails with:

> `AADSTS65001: The user or administrator has not consented to use the application with ID '<AGENT_CLIENT_ID>'`

> **Note:** The **Autonomous** toggle works without any Graph permission on the Agent Identity — it just mints an FMI token and inspects it; it never actually calls Graph. Only OBO strictly needs the grant below.

Grant these two permissions (same set used by the AWS Bedrock and Ollama editions in [`razi-rais/3P-Agent-ID-Demo`](https://github.com/razi-rais/3P-Agent-ID-Demo)):

| Permission | Type | Required for | Why |
|---|---|---|---|
| `User.Read`     | Delegated (`AllPrincipals` consent) | **OBO toggle** | OBO exchange returns a delegated Graph token for the signed-in user. `AllPrincipals` skips the per-user consent prompt. |
| `User.Read.All` | Application (admin-consented) | *Optional* — only if you extend the Autonomous path to actually call Graph | App-only tokens carry no user identity; need an admin-granted role to call Graph as the Agent. |

#### Option A — Azure Portal (UI)

1. **Microsoft Entra admin center → Identity → Applications → Agent identities**
2. Open the Agent identity that matches `AGENT_CLIENT_ID` from your `.env`
3. **Permissions → Add a permission → Microsoft Graph**
   - **Delegated permissions** → check `User.Read` → **Add permissions**  *(required for OBO)*
   - **Application permissions** → check `User.Read.All` → **Add permissions**  *(optional — only if you'll call Graph from the Autonomous path)*
4. Click **Grant admin consent for <tenant>** → confirm — both rows should turn green ✅

#### Option B — Microsoft Graph API (one-shot, scriptable)

Replace the four `<...>` placeholders. You need an access token with `AppRoleAssignment.ReadWrite.All` and `DelegatedPermissionGrant.ReadWrite.All` (admin).

```bash
TENANT_ID="<your-tenant-id>"
AGENT_SP_ID="<object-id-of-Agent-Identity-SP>"   # NOT the AGENT_CLIENT_ID (app id)
GRAPH_SP_ID="<object-id-of-Microsoft-Graph-SP-in-your-tenant>"
TOKEN="<bearer-token-for-graph.microsoft.com>"   # e.g. az account get-access-token --resource https://graph.microsoft.com -o tsv --query accessToken

# REQUIRED for OBO — delegated User.Read, tenant-wide consent
curl -X POST "https://graph.microsoft.com/v1.0/oauth2PermissionGrants" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{
    \"clientId\":    \"$AGENT_SP_ID\",
    \"consentType\": \"AllPrincipals\",
    \"resourceId\":  \"$GRAPH_SP_ID\",
    \"scope\":       \"User.Read\"
  }"

# OPTIONAL — application User.Read.All (only if you'll call Graph from the Autonomous path)
curl -X POST "https://graph.microsoft.com/v1.0/servicePrincipals/$AGENT_SP_ID/appRoleAssignments" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{
    \"principalId\": \"$AGENT_SP_ID\",
    \"resourceId\":  \"$GRAPH_SP_ID\",
    \"appRoleId\":   \"df021288-bdef-4463-88db-98f22de89214\"
  }"
```

Find `GRAPH_SP_ID` with:
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/servicePrincipals?\$filter=appId eq '00000003-0000-0000-c000-000000000000'" \
  | jq -r '.value[0].id'
```

#### Verify

```bash
# Should return 1 row (User.Read delegated, AllPrincipals) — required for OBO
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?\$filter=clientId eq '$AGENT_SP_ID'" \
  | jq '.value[] | {scope, consentType}'

# Should return 1 row (User.Read.All app role) — only if you granted the optional app permission
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/servicePrincipals/$AGENT_SP_ID/appRoleAssignments" | jq '.value[].appRoleId'
```

> The constant `df021288-bdef-4463-88db-98f22de89214` is the well-known Microsoft Graph `User.Read.All` **application** role id and is the same in every tenant.

---

## 5. Quickstart

Start a terminal anywhere inside this Git clone. Docker Desktop must be running
with Linux containers. The images supply Python 3.11 and install their own
requirements, so do not use the repository root `.venv` for this sample.
The Entra identities, consent and model deployment from the prerequisites must
already exist. These commands preserve an existing `.env`.

### macOS Terminal

```bash
cd "$(git rev-parse --show-toplevel)"
cd 05-end-to-end-agent/sidecar/foundry
test -f .env || cp .env.example .env
mkdir -p "$HOME/.azure"
```

### Windows PowerShell

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
Set-Location .\05-end-to-end-agent\sidecar\foundry
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$env:HOME = $HOME
New-Item -ItemType Directory -Force -Path (Join-Path $HOME ".azure") | Out-Null
```

Edit `.env` and set `TENANT_ID`, `BLUEPRINT_APP_ID`, `AGENT_CLIENT_ID`,
`BLUEPRINT_CLIENT_SECRET`, `FOUNDRY_ENDPOINT`, `FOUNDRY_MODEL` and
`FOUNDRY_API_KEY`. Also set `CLIENT_SPA_APP_ID` for OBO sign in.
Use the Blueprint secret **value**, not the secret ID.
`APPLICATIONINSIGHTS_CONNECTION_STRING` is optional.

From the service directory selected above, this command works in both shells:

```text
docker compose --env-file .env up --build
```

On Windows, keep `$env:HOME = $HOME` set in the Compose terminal. This supplies
the home directory used by the existing Azure configuration bind mount.
Keep the terminal open, visit <http://localhost:3004>, choose **Foundry** and
try `Weather in Dallas?`. Toggle between `Direct` / `Foundry` and
`Autonomous` / `OBO` to inspect the token flow.
Do not run `python app.py` as a replacement for the complete Compose stack.
The service URLs use Docker DNS rather than host localhost addresses.

Press Ctrl+C to stop. From the same directory and terminal, remove the stopped
Compose containers with:

```text
docker compose --env-file .env down
```

These Mac and Windows startup instructions have been reviewed but not executed.

### `FOUNDRY_ENDPOINT` quick reference

| Source | Format |
|---|---|
| Foundry project (AI Services-backed) | `https://<aiservices-name>.services.ai.azure.com/openai/v1` |
| Azure OpenAI resource | `https://<resource>.openai.azure.com/openai/v1` |

`FOUNDRY_MODEL` is the deployment name from your Foundry project (for example `gpt-4o-mini`, `Phi-4`, `Llama-3.3-70B-Instruct`).

---

## 6. Foundry authentication: API key vs DefaultAzureCredential

The agent talks to Foundry via the [Azure AI Inference](https://learn.microsoft.com/azure/ai-studio/reference/reference-model-inference-api) endpoint (`AzureAIChatCompletionsModel` from `langchain-azure-ai`). It supports two credential paths:

| Mode | When | How |
|---|---|---|
| **API key** | Workshops, quickest demo | Set `FOUNDRY_API_KEY` in `.env`. The agent uses `AzureKeyCredential`. |
| **DefaultAzureCredential** | An already configured identity | Leave `FOUNDRY_API_KEY` blank and set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` for an existing service principal. Compose forwards all three variables. Managed Identity is an alternative on an Azure host that provides it. Grant the identity the model access required by your endpoint. |

> [!TIP]
> The supplied Dockerfile does not install Azure CLI. Mounting `~/.azure` and
> signing in on the host is not enough for `AzureCliCredential` inside this image.
> Use the API key quickstart or the environment credential settings above.
> Host CLI authentication would also require an appropriately configured image
> containing Azure CLI.

---

## 7. Files

| File | Purpose |
|---|---|
| `app.py` | Flask app — routes, sidecar calls, token decoding, LangChain ReAct agent with `get_weather` tool |
| `templates/index.html` | Chat UI + token-trace panel + MSAL.js sign-in for OBO |
| `Dockerfile` | `python:3.11-slim`, installs `requirements.txt` and runs `app.py` |
| `docker-compose.yml` | Sidecar + weather-api + agent on a shared bridge network; no host port for the sidecar |
| `requirements.txt` | `flask`, `flask-cors`, `requests`, `langchain*`, `langchain-azure-ai`, `azure-identity` |
| `.env.example` | Template for required env vars |

The downstream `weather-api` container is the same image used by the AWS Bedrock and Ollama editions in [`razi-rais/3P-Agent-ID-Demo`](https://github.com/razi-rais/3P-Agent-ID-Demo). See [`../weather-api/README.md`](../weather-api/README.md) for its config.

---

## 8. Tracing in Microsoft Foundry / Application Insights

The agent ships with OpenTelemetry instrumentation that emits **GenAI-semconv** spans for every agent run. When you connect an Application Insights resource, the trace tree appears in the **Foundry portal → your project → Tracing** tab (and in App Insights → *Transaction search / Application map*).

A single chat turn produces a span tree like:

```
agent run (LangChain)
├── chat completion (gpt-4o)        ← prompt, tool definitions, completion, tokens
├── tool: get_weather               ← args = {city: "Seattle"}, result
│    ├── HTTP GET sidecar/AuthorizationHeaderUnauthenticated/graph-app
│    └── HTTP GET weather-api/weather?city=Seattle
└── chat completion (gpt-4o)        ← final user-facing response
```

### 8.1 Enable in three steps

1. **Create or pick an Application Insights resource.** In Azure Portal → *Application Insights* → *Create*. Use the *Workspace-based* type. Open the resource → *Overview* → copy the **Connection String** (e.g. `InstrumentationKey=…;IngestionEndpoint=https://…`).
2. **Connect it to your Foundry project** (so the Tracing tab shows the data). Foundry portal → your project → *Tracing* → *Set up tracing* → select the same App Insights resource.
3. **Set the env var** and restart the agent:
   ```bash
   echo 'APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=https://...' >> .env
   docker compose --env-file .env up -d --build llm-agent-foundry
   ```

On startup you should see `[Tracing] ✓ Application Insights / Microsoft Foundry Tracing enabled` in the agent logs, and `GET /api/status` returns `"tracing_enabled": true`.

### 8.2 How it works

| Piece | Library | What it does |
|---|---|---|
| Exporter | `azure-monitor-opentelemetry` | Configures the OTel SDK to ship spans (and logs/metrics) to App Insights. Auto-instruments `flask`, `requests`, `urllib3` — so the HTTP hops to the sidecar and weather-api appear as spans without any code changes. |
| LangChain / LangGraph spans | `opentelemetry-instrumentation-langchain` (Traceloop) | Hooks into LangChain callbacks and emits agent / tool / LLM spans with `gen_ai.provider.name`, `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.usage.*`. These render the tool-call tree in App Insights / Application Map and carry rich Traceloop metadata. |
| Foundry-compatible LLM spans | `azure-ai-inference` SDK's built-in OTel + `azure-core-tracing-opentelemetry` | Emits Microsoft-flavored spans (`name="chat"`, `gen_ai.system="az.ai.inference"`). These are what the **Foundry portal → Tracing** tab filters for. Requires `USE_FOUNDRY_INFERENCE_SDK=true` to route LangChain through the inference SDK instead of the OpenAI-API path. |
| Content capture | env: `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`, `TRACELOOP_TRACE_CONTENT=true`, `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true` (all set automatically when tracing is enabled) | Includes the prompt and completion text on each span. Disable for prod / PII-sensitive workloads. |

> **Why two LLM instrumentors?** They produce complementary data:
> - Traceloop spans live happily in App Insights but are not recognised by the Foundry portal Tracing UI (different span-name + semconv version).
> - The `azure-ai-inference` instrumentor produces the exact span shape the Foundry portal Tracing tab expects.
>
> Running both is additive: every chat call produces *one* `az.ai.inference` `chat` span (Foundry-visible) plus *one* `AzureAIChatCompletionsModel.chat` span (Traceloop-rich), nested inside the LangGraph agent span. Disable the inference path by leaving `USE_FOUNDRY_INFERENCE_SDK=false` if you don't need the Foundry portal view.

### 8.3 End-to-end trace flow (request lifecycle)

Every `POST /api/chat` produces ~10–15 spans across 4 instrumentors. Understanding which hook fires at which layer makes the resulting span tree (and any "missing span" debugging) much easier:

```
HTTP POST /api/chat               ← (A) opentelemetry-instrumentation-flask   [server span]
└── invoke_agent LangGraph        ← (B) opentelemetry-instrumentation-langchain
    └── LangGraph.workflow        ← (B) Traceloop
        ├── execute_task model    ← (B) Traceloop  (planning step)
        │   └── AzureAIChatCompletionsModel.chat            ← (B) Traceloop  [LangChain wrapper]
        │       └── chat gpt-4o   ← (C) azure-ai-inference SDK native tracing  [gen_ai.system="az.ai.inference"]
        │           └── POST /models/chat/completions       ← (D) opentelemetry-instrumentation-requests
        ├── execute_task tools    ← (B) Traceloop
        │   └── execute_tool get_weather                    ← (B) Traceloop  [tool span]
        │       ├── GET sidecar/AuthorizationHeaderUnauthenticated/graph-app  ← (D) requests
        │       └── GET weather-api/weather?city=Madrid     ← (D) requests
        └── execute_task model    ← (B) Traceloop  (final answer step)
            └── AzureAIChatCompletionsModel.chat            ← (B) Traceloop
                └── chat gpt-4o   ← (C) azure-ai-inference
                    └── POST /models/chat/completions       ← (D) requests
```

| # | Layer | Instrumentor | Span pattern | Where you see it |
|---|---|---|---|---|
| **A** | Flask request | `azure-monitor-opentelemetry` (auto) | `requests` table, name = `POST /api/chat` | App Insights / Application Map |
| **B** | LangChain / LangGraph agent + tools | `opentelemetry-instrumentation-langchain` (Traceloop) | `dependencies`, names like `invoke_agent LangGraph`, `execute_task model`, `execute_tool get_weather` | App Insights only |
| **C** | Azure AI Inference LLM call | `azure-ai-inference` SDK's built-in OTel tracing (via `AIInferenceInstrumentor` + `azure-core-tracing-opentelemetry`) | `dependencies`, name = `chat <model>`, `customDimensions.["gen_ai.system"] = "az.ai.inference"` | App Insights **and** Foundry portal Tracing tab |
| **D** | Outbound HTTP (sidecar, weather-api, Foundry models endpoint) | `azure-monitor-opentelemetry` (auto-instruments `requests` + `urllib3`) | `dependencies`, name = `POST /...` or `GET /...` | App Insights |

**The pipeline once spans are created:**

```
OpenTelemetry Tracer (per span)
        │
        ▼
BatchSpanProcessor (in-process buffer, ~5 s / 512 spans)
        │
        ▼
AzureMonitorTraceExporter   ← configured by configure_azure_monitor()
        │  HTTPS POST (gzipped batch)
        ▼
App Insights ingestion endpoint  (https://<region>-N.in.applicationinsights.azure.com/)
        │
        ├── (workspace-based AI) → stored in Log Analytics workspace
        │   tables: AppDependencies, AppRequests, AppTraces, AppExceptions
        │
        └── (legacy AI direct)   → stored in classic AI tables
            tables: dependencies, requests, traces, exceptions
```

Two consumers read this storage:
- **Azure Portal → Application Insights** — uses the *App Insights* schema (`dependencies`/`requests`/`traces`, column `timestamp`, dimensions in `customDimensions`).
- **Foundry portal → project → Tracing** — filters that same data on `gen_ai.system="az.ai.inference"` to render the agent run view.

Latency from agent process → visible in App Insights is typically **30–90 seconds** (BatchSpanProcessor flush + ingestion processing).

### 8.4 Where to view traces

Once data is flowing (see §8.1), there are four entry points. Replace `<SUB>`, `<RG>`, `<AI_NAME>`, `<FOUNDRY_ACCOUNT>`, and `<PROJECT>` with your values.

**🟢 Foundry portal — Tracing tab** (the agent-run view; shows the Microsoft-instrumented `chat` spans)

`https://ai.azure.com/tracing?wsid=/subscriptions/<SUB>/resourceGroups/<RG>/providers/Microsoft.CognitiveServices/accounts/<FOUNDRY_ACCOUNT>/projects/<PROJECT>`

**🔵 Application Insights — Logs** (paste any KQL from §8.5 here)

`https://portal.azure.com/#@/resource/subscriptions/<SUB>/resourceGroups/<RG>/providers/microsoft.insights/components/<AI_NAME>/logs`

**🟣 Application Insights — Transaction Search** (find one chat turn end-to-end, click for full span tree)

`https://portal.azure.com/#@/resource/subscriptions/<SUB>/resourceGroups/<RG>/providers/microsoft.insights/components/<AI_NAME>/searchV1`

**🟠 Application Insights — Application Map** (visual topology: agent → sidecar → weather-api → Foundry)

`https://portal.azure.com/#@/resource/subscriptions/<SUB>/resourceGroups/<RG>/providers/microsoft.insights/components/<AI_NAME>/appMap`

> **Quick discovery:** if you don't know the values yet — Foundry portal → your project → *Tracing* → *Set up* (or *Manage*) shows the linked Application Insights resource. Click into it to land directly on its Overview, where the breadcrumb gives you `<SUB>`, `<RG>`, and `<AI_NAME>`.

### 8.5 Querying traces (KQL)

**Where to run these queries** (any of):

| Tool | Path | Schema |
|---|---|---|
| Azure Portal | App Insights resource → **Logs** | `dependencies` / `requests` / `traces` (column `timestamp`, dimensions in `customDimensions`) |
| Azure Portal | Log Analytics workspace → **Logs** | `AppDependencies` / `AppRequests` / `AppTraces` (column `TimeGenerated`, dimensions in `Properties`) |
| Foundry portal | Project → **Tracing → Logs** | App Insights schema |
| VS Code | *Azure Account* + *Log Analytics* extensions | both schemas |
| Python | `azure.monitor.query.LogsQueryClient.query_resource(<resourceId>, kql)` | depends on which resource ID you pass |

> All queries below use the **App Insights schema** (`dependencies`, `timestamp`, `customDimensions`). To run them against the Log Analytics workspace instead, replace `dependencies → AppDependencies`, `timestamp → TimeGenerated`, `customDimensions → Properties`.

#### ⭐ 0. Full chat-turn timeline (one query, picks the latest turn automatically)

The single most useful query. Chronological waterfall of every span in one agent run (user prompt, then LLM thinking, then tool calls + results, then the final answer), plus a summary row with totals, wall-clock time, and gpt-4o list-price cost.

> **Why this query pins on `azure.ai.openai`, not `az.ai.inference`:** the agent has two instrumentors that both wrap each LLM call. The Microsoft `az.ai.inference` instrumentor only emits metadata (model, tokens). The Traceloop `azure.ai.openai` wrapper emits the prompts, completions, and tool definitions, and it fires on every LLM round-trip (the Microsoft instrumentor occasionally skips one). We pin and count from the Traceloop spans because they are the canonical record of an LLM call. We still show both span rows in the waterfall so you can see the full instrumentation depth.

```kusto
// To pin a specific turn, replace the target_op block with:
//   let target_op = "<operation_Id from query C>";
let target_op = toscalar(
    dependencies
    | where timestamp > ago(1h)
    | where tostring(customDimensions["gen_ai.provider.name"]) == "azure.ai.openai"
    | top 1 by timestamp desc
    | project operation_Id
);
let events = (
    union dependencies, requests
    | where operation_Id == target_op
    | extend cd = customDimensions
    | extend category = case(
        tostring(cd["gen_ai.system"])        == "az.ai.inference", "LLM-INFER",
        tostring(cd["gen_ai.provider.name"]) == "azure.ai.openai", "LLM-LC",
        name startswith "execute_tool",                            "TOOL",
        name startswith "invoke_agent",                            "AGENT",
        name startswith "LangGraph"
            or name startswith "execute_task",                     "ORCHESTR",
        itemType == "request",                                     "HTTP-IN",
        type in ("Http","HTTP"),                                   "HTTP-OUT",
                                                                   "other")
    | extend
        model      = tostring(cd["gen_ai.response.model"]),
        in_tok     = tolong(cd["gen_ai.usage.input_tokens"]),
        out_tok    = tolong(cd["gen_ai.usage.output_tokens"]),
        tool       = tostring(cd["gen_ai.tool.name"]),
        // Tool args/result are wrapped in LangChain envelopes. Reach in and pull the clean values.
        tool_arg   = tostring(parse_json(tostring(cd["gen_ai.tool.call.arguments"])).input_str),
        tool_res   = tostring(parse_json(tostring(cd["gen_ai.tool.call.result"])).output.kwargs.content),
        prompt     = tostring(cd["gen_ai.input.messages"]),
        completion = tostring(cd["gen_ai.output.messages"])
);
let waterfall = (
    events
    | project
        timestamp,
        step_ms     = tolong(duration),
        category, name, model,
        in_tok, out_tok,
        tool,
        tool_arg    = iif(strlen(tool_arg)   > 180, strcat(substring(tool_arg, 0, 180), " ..."), tool_arg),
        tool_result = iif(strlen(tool_res)   > 180, strcat(substring(tool_res, 0, 180), " ..."), tool_res),
        user_prompt = iif(strlen(prompt)     > 280, strcat(substring(prompt, 0, 280), " ..."), prompt),
        llm_answer  = iif(strlen(completion) > 280, strcat(substring(completion, 0, 280), " ..."), completion)
    | order by timestamp asc
);
let summary = (
    events
    // Sum tokens from ONLY the Traceloop span (LLM-LC) to avoid double-counting the same LLM call.
    | summarize
        wall_ms    = tolong(datetime_diff('millisecond', max(timestamp), min(timestamp))),
        llm_calls  = count_distinctif(itemId, category == "LLM-LC"),
        tool_calls = count_distinctif(itemId, category == "TOOL"),
        http_calls = count_distinctif(itemId, category in ("HTTP-OUT","HTTP-IN")),
        in_tokens  = tolong(sumif(in_tok,  category == "LLM-LC")),
        out_tokens = tolong(sumif(out_tok, category == "LLM-LC"))
    | extend cost_usd = round(in_tokens*2.50/1e6 + out_tokens*10.00/1e6, 6)
    | extend
        timestamp   = now(),
        step_ms     = wall_ms,
        category    = "SUMMARY",
        name        = strcat("llm=", llm_calls, "  tool=", tool_calls, "  http=", http_calls),
        model       = "-",
        in_tok      = in_tokens,
        out_tok     = out_tokens,
        tool        = "-",
        tool_arg    = "-",
        tool_result = "-",
        user_prompt = strcat("tokens in=", in_tokens, " out=", out_tokens),
        llm_answer  = strcat("cost $", cost_usd)
    | project timestamp, step_ms, category, name, model, in_tok, out_tok,
              tool, tool_arg, tool_result, user_prompt, llm_answer
);
union waterfall, summary
| order by category == "SUMMARY" asc, timestamp asc

```

> **Log Analytics gotchas** found while iterating on this query:
> - **Don't name a `let` `timeline`**. `timeline` is reserved (used by `render timeline` visualizations). Use `waterfall`, `events`, etc.
> - **Don't name a column `kind`**. It's a reserved parameter token (`join kind=...`). Use `category` or any other identifier.
> - **Wrap multi-line tabular `let` bodies in parentheses**, e.g. `let x = ( union ... | ... );`. Most workspaces require parens. Without them the parser may stop at the next `let`.
> - **No inline lambda functions**. `let trim = (s,n) { iif(...) };` is rejected. Inline the `iif(...)` expression directly in `project`.
> - **Stick to ASCII in string literals**. Some workspace configurations reject extended Unicode (emoji) in `case(...)` or `strcat(...)` arguments.
> - **Don't reference a column you're defining in the same `extend`**. Split into two `extend` blocks (for example, compute `cost_usd` first, then use it in `strcat`).
> - **Cast numeric types consistently before `union`**, e.g. `tolong(duration)` and `tolong(datetime_diff(...))`. Otherwise `union` will emit duplicate `_int` and `_long` columns.
> - **Don't double-count tokens from dual instrumentation**. The same LLM call is wrapped by BOTH the Microsoft `az.ai.inference` instrumentor and the Traceloop `azure.ai.openai` wrapper, and each emits its own `gen_ai.usage.input_tokens`. A plain `sum(in_tok)` doubles the number. Use `sumif(in_tok, category == "LLM-LC")` to count only the Traceloop span (which always fires).

**Returns** (one row per span, chronological, plus a final `SUMMARY` row):

| column | what it shows |
|---|---|
| `timestamp`, `step_ms` | When the step started, how long it took |
| `category` | `AGENT`, `ORCHESTR`, `LLM-INFER` (Microsoft inference SDK span), `LLM-LC` (Traceloop LangChain wrapper span), `TOOL`, `HTTP-OUT`, `HTTP-IN`, `SUMMARY` |
| `name`, `model` | Span name (for example `chat`, `AzureAIChatCompletionsModel.chat`). `model` populated on LLM rows only |
| `in_tok`, `out_tok` | Token counts on LLM rows. The same call shows in both LLM-INFER and LLM-LC rows |
| `tool`, `tool_arg`, `tool_result` | Filled on TOOL rows. `tool_arg` is the clean argument string (for example `{'city': 'Austin'}`), `tool_result` is the tool's plain-text return value |
| `user_prompt`, `llm_answer` | Actual prompt + completion content (trimmed to 180 or 280 chars). Populated on LLM-LC rows only |
| `SUMMARY` row | Wall-clock ms, call counts per layer, total in/out tokens (counted once from LLM-LC), gpt-4o list-price cost |

#### A. Confirm tracing is alive

```kql
dependencies
| where timestamp > ago(15m)
| summarize spans = count(), last_seen = max(timestamp) by cloud_RoleName
```

Should show one row with a recent `last_seen`. **In this sample, `cloud_RoleName` is `unknown_service`**, because `configure_azure_monitor(resource_attributes={'service.name': ...})` is not picked up as `cloud_RoleName` by the installed Azure Monitor exporter. To override, set `OTEL_SERVICE_NAME=llm-agent-foundry` in the `llm-agent-foundry` service's `environment:` block in `docker-compose.yml` and recreate the container. Until then, every other query in this section filters by span attributes (not by `cloud_RoleName`) so they still work.

#### B. Inventory of span sources (which instrumentors are firing)

```kql
dependencies
| where timestamp > ago(1h)
| extend gen_ai_system   = tostring(customDimensions["gen_ai.system"])
| extend gen_ai_provider = tostring(customDimensions["gen_ai.provider.name"])
| summarize spans = count(), example = any(name) by gen_ai_system, gen_ai_provider
| order by spans desc
```

You should see:
- `gen_ai.system="az.ai.inference"` → Microsoft inference SDK instrumentor (the Foundry-portal source)
- `gen_ai.provider.name="azure.ai.openai"` → Traceloop LangChain wrapper
- `gen_ai.provider.name="langgraph"` → Traceloop LangGraph spans
- Empty rows → Flask + `requests` auto-instrumentation (the HTTP-layer spans)

#### C. Foundry-portal-compatible LLM calls (the spans the Foundry Tracing tab renders)

```kql
dependencies
| where timestamp > ago(1h)
| where tostring(customDimensions["gen_ai.system"]) == "az.ai.inference"
| project timestamp,
          op = operation_Id,
          model = tostring(customDimensions["gen_ai.response.model"]),
          input_tokens  = toint(customDimensions["gen_ai.usage.input_tokens"]),
          output_tokens = toint(customDimensions["gen_ai.usage.output_tokens"]),
          duration_ms = duration
| order by timestamp desc
```

#### D. Token usage and (list-price) cost per turn

```kql
let price_in  = 2.50 / 1000000.0;   // gpt-4o input  ($/token)
let price_out = 10.00 / 1000000.0;  // gpt-4o output ($/token)
dependencies
| where timestamp > ago(24h)
| where tostring(customDimensions["gen_ai.system"]) == "az.ai.inference"
| extend input_tokens  = toint(customDimensions["gen_ai.usage.input_tokens"])
| extend output_tokens = toint(customDimensions["gen_ai.usage.output_tokens"])
| summarize
    llm_calls       = count(),
    in_tokens       = sum(input_tokens),
    out_tokens      = sum(output_tokens),
    cost_usd        = sum(input_tokens * price_in + output_tokens * price_out)
  by operation_Id, bin(timestamp, 1m)
| order by timestamp desc
```

Group by `bin(timestamp, 1d)` (and drop `operation_Id`) for a daily spend rollup.

#### E. Full prompts and completions

> **Heads-up: prompts/completions live on the Traceloop spans, not the Microsoft `az.ai.inference` ones.** The Microsoft `azure-ai-inference` instrumentor only emits metadata (model, tokens, finish reason). The Traceloop LangChain wrapper is the one that records `gen_ai.input.messages`, `gen_ai.output.messages`, and `gen_ai.tool.definitions`. Both spans cover the same LLM call, just from different layers. Filter on `gen_ai.provider.name == "azure.ai.openai"` (or span name `AzureAIChatCompletionsModel.chat`).

```kql
dependencies
| where timestamp > ago(1h)
| where tostring(customDimensions["gen_ai.provider.name"]) == "azure.ai.openai"
| project timestamp,
          op         = operation_Id,
          model      = tostring(customDimensions["traceloop.association.properties.ls_model_name"]),
          in_tokens  = toint(customDimensions["gen_ai.usage.input_tokens"]),
          out_tokens = toint(customDimensions["gen_ai.usage.output_tokens"]),
          prompt     = tostring(customDimensions["gen_ai.input.messages"]),
          completion = tostring(customDimensions["gen_ai.output.messages"]),
          tools      = tostring(customDimensions["gen_ai.tool.definitions"])
| order by timestamp desc
```

`prompt` / `completion` are JSON arrays of `{role, parts[]}` objects. `parts[]` items are typed: `{"type":"text","content":...}` for normal text, `{"type":"tool_call","id":...,"name":...,"arguments":{...}}` for assistant tool calls, and `{"type":"tool_call_response","id":...,"response":...}` for tool results. To pull just the user-visible text:

```kql
dependencies
| where timestamp > ago(1h)
| where tostring(customDimensions["gen_ai.provider.name"]) == "azure.ai.openai"
| extend prompt_json     = parse_json(tostring(customDimensions["gen_ai.input.messages"]))
| extend completion_json = parse_json(tostring(customDimensions["gen_ai.output.messages"]))
| mv-expand p = prompt_json
| extend user_text = tostring(p.parts[0].content), role = tostring(p.role)
| where role == "user"
| project timestamp, op = operation_Id, user_text,
          assistant_text = tostring(completion_json[0].parts[0].content)
| order by timestamp desc
```

> Content capture must be enabled (this sample sets `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`, `TRACELOOP_TRACE_CONTENT=true`, and `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true` automatically when tracing is on).

#### F. Tool calls (what the agent called, what it got back)

> The raw `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` are wrapped in LangChain envelopes (`{"input_str": "...", "tags": [...], "metadata": {...}}` for args, `{"output": {"lc": 1, "type": "constructor", ..., "kwargs": {"content": "..."}}}` for the result). To get readable values, parse the JSON and reach in. The query below does both.

```kql
dependencies
| where timestamp > ago(1h)
| where name startswith "execute_tool"
| extend args = parse_json(tostring(customDimensions["gen_ai.tool.call.arguments"]))
| extend res  = parse_json(tostring(customDimensions["gen_ai.tool.call.result"]))
| project timestamp,
          op = operation_Id,
          tool      = tostring(customDimensions["gen_ai.tool.name"]),
          arguments = tostring(args.input_str),
          result    = tostring(res.output.kwargs.content),
          duration_ms = duration
| order by timestamp desc
```

Example rows (last 1h):

| tool | arguments | result (truncated) | duration_ms |
|---|---|---|---|
| `get_weather` | `{'city': 'Austin'}` | `Weather for Austin: Temperature 80°F, Overcast, Humidity 91%...` | 1750 |
| `get_weather` | `{'city': 'Dallas'}` | `Weather for Dallas: Temperature 76°F, Overcast, Humidity 75%...` | 657 |

##### F.1 The two HTTP hops behind `execute_tool get_weather` (token-chain proof)

When `get_weather` runs inside the agent, two outbound HTTP calls happen inside that one tool span. Together they prove the **TR token** the sidecar minted on behalf of the Agent Identity was successfully validated by the weather API.

```kql
let target_op = toscalar(
    dependencies
    | where timestamp > ago(15m)
    | where name == "invoke_agent LangGraph"
    | top 1 by timestamp desc
    | project operation_Id);
dependencies
| where operation_Id == target_op
| where type in ("Http","HTTP")
| where target has "sidecar" or target has "weather-api"
| project timestamp, name, target, resultCode, duration_ms = duration
| order by timestamp asc
```

You should see exactly two rows per tool call, in this order. The exact sidecar endpoint name depends on which token flow the agent ran:

**Autonomous flow** (token_flow=autonomous, sidecar runs as the Agent Identity directly):

| name | target | resultCode | meaning |
|---|---|---|---|
| `GET /AuthorizationHeaderUnauthenticated/graph-app` | `sidecar:5000` | `200` | Sidecar minted the TR token from the Agent Identity (app-only, `RequestAppToken=true`) |
| `GET /weather` | `weather-api:8080` | `200` | Weather API validated the TR token (JWKS, RS256, issuer, audience) and returned Open-Meteo data |

**OBO flow** (token_flow=obo, sidecar uses the user assertion):

| name | target | resultCode | meaning |
|---|---|---|---|
| `GET /AuthorizationHeader/graph` | `sidecar:5000` | `200` | Sidecar exchanged the user's Tc for the downstream TR (on-behalf-of) |
| `GET /weather` | `weather-api:8080` | `200` | Weather API validated the TR token and returned Open-Meteo data |

A non-`200` on the second row means the weather API rejected the token. A non-`200` on the first row means the sidecar failed to mint or exchange (check the sidecar container logs for the underlying Entra error).

#### G. Full span tree for one chat turn

```kql
let op = "<paste operation_Id from query C/D/E>";
union dependencies, requests
| where operation_Id == op
| project timestamp, duration, name, type, parent = operation_ParentId, id, span = itemId
| order by timestamp asc
```

To find an `operation_Id`, run query C/D, then copy the `op` value.

#### H. Latency breakdown per layer

> Order of `case(...)` branches matters. `execute_tool` spans carry `gen_ai.provider.name=langgraph`, so a LangGraph branch placed before the Tool branch will swallow them. Also, dependency `type` is `HTTP` in uppercase (not `Http`).

```kql
dependencies
| where timestamp > ago(1h)
| extend layer = case(
    name startswith "execute_tool",                                  "Tool",
    tostring(customDimensions["gen_ai.system"]) == "az.ai.inference", "LLM (inference SDK)",
    tostring(customDimensions["gen_ai.provider.name"]) == "azure.ai.openai", "LLM (LangChain wrapper)",
    tostring(customDimensions["gen_ai.provider.name"]) == "langgraph", "LangGraph (orchestration)",
    type in ("Http","HTTP"),                                          "HTTP",
                                                                      "Other")
| summarize p50 = percentile(duration, 50),
            p95 = percentile(duration, 95),
            calls = count() by layer
| order by p95 desc
```

Expected output shape (from a recent run):

| layer | p50 (ms) | p95 (ms) | calls |
|---|---|---|---|
| LangGraph (orchestration) | ~2100 | ~4300 | many |
| LLM (LangChain wrapper) | ~900 | ~2500 | one per LLM round-trip |
| LLM (inference SDK) | ~1850 | ~2500 | usually one per LLM round-trip |
| HTTP | ~800 | ~2500 | sidecar + weather-api + Foundry POSTs |
| Tool | ~600 | ~1750 | one per `execute_tool` |

#### I. Errors and failed dependencies

> The Azure Monitor SDK probes `http://169.254.169.254/metadata/instance/compute` at startup to detect if it's running on an Azure VM. Inside Docker that probe always fails with a connect-timeout, which would otherwise dominate this query. The filter below excludes that noise so only real app errors show.

```kql
union dependencies, requests, exceptions
| where timestamp > ago(1h)
| where success == false or itemType == "exception"
// Exclude Azure Monitor SDK's IMDS probe (always fails in Docker, not a real error)
| where not(name has "metadata/instance")
| where not(target has "169.254.169.254")
| where not(tostring(customDimensions["exception.message"]) has "169.254.169.254")
| project timestamp, itemType, name, target, resultCode,
          problemId = tostring(parse_json(tostring(details))[0].typeName)
| order by timestamp desc
```

On a healthy run this returns zero rows. To see exception detail for a failure, drop the filters and join into the `exceptions` table directly:

```kql
exceptions
| where timestamp > ago(1h)
| where not(outerMessage has "169.254.169.254")
| project timestamp, type, outerMessage, method, operation_Id
| order by timestamp desc
```

### 8.6 Production note

In Azure (App Service / Container Apps) you typically:
- Provision App Insights via Bicep/Terraform alongside the Foundry project.
- Inject `APPLICATIONINSIGHTS_CONNECTION_STRING` from a secret store / Key Vault reference — same env var name, same code path.
- Turn off content capture if prompts may contain user PII (set the OTel env var to `false` before container start).

---

## 9. Notes & known limitations

- **Demo audience reuse.** Like the AWS Bedrock and Ollama editions in [`razi-rais/3P-Agent-ID-Demo`](https://github.com/razi-rais/3P-Agent-ID-Demo), the sidecar is configured to mint Graph-scoped tokens (`https://graph.microsoft.com/.default`) for the weather API. This keeps the sample runnable with a single Blueprint app registration. In production you'd register the weather API as its own resource (`api://<weather-api-app-id>/...`) and validate that audience strictly.
- **Single-user demo.** `_current_user_token` is module-level for simplicity, mirroring the AWS Bedrock and Ollama editions. Use a per-request closure or `contextvars` before exposing this to concurrent users.
- **Foundry endpoint format.** Use the full `/openai/v1` path on AI Services endpoints — `langchain-azure-ai` targets the Foundry OpenAI-compatible API. Older `/models` URLs still resolve to the same backend but emit a deprecation warning.
- **Flask debug reloader is on.** Fine for the demo; disable in any deployed environment.
- **CORS is `*`.** Demo only; lock down origins in production.

---

## 10. Further reading

- [Microsoft Entra SDK for Agent Identities](https://learn.microsoft.com/en-us/entra/agent-id/identity-platform/microsoft-entra-sdk-for-agent-identities)
- [Microsoft Foundry overview](https://learn.microsoft.com/azure/ai-studio/what-is-ai-studio)
- [Azure AI Inference API reference](https://learn.microsoft.com/azure/ai-studio/reference/reference-model-inference-api)
- [Foundry tracing & observability](https://learn.microsoft.com/azure/ai-studio/how-to/develop/trace-application)
- [Azure Monitor OpenTelemetry distro (Python)](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-enable?tabs=python)
- [`langchain-azure-ai` on PyPI](https://pypi.org/project/langchain-azure-ai/)
- Slides and full walkthrough: [`razi-rais/microsoft-foundry-resources`](https://github.com/razi-rais/microsoft-foundry-resources)
