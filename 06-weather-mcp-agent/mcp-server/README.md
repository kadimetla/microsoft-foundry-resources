# MCP server (Azure Functions) — sample 06

A minimal **Model Context Protocol** server exposing a `get_weather` tool,
hosted on **Azure Functions** with the MCP extension. The Foundry agent in
[`../06-weather-mcp-agent.py`](../06-weather-mcp-agent.py) consumes it.

## What it does

```text
                                 +---------------------+
 user prompt --→  Foundry agent  |   Azure Functions   |
                  (your model)   |   /runtime/webhooks |  ──► Open-Meteo
                       │         |        /mcp         |     (geocode + obs)
                       └────────►|  get_weather tool   |
                                 +---------------------+
                                  • mcp_tool decorator
                                  • Flex Consumption, Python 3.13
                                  • App Insights = same workspace as Foundry
```

## Files

| File | Purpose |
|---|---|
| `function_app.py` | The `get_weather` MCP tool (decorated with `@app.mcp_tool` + `@app.mcp_tool_property` — the canonical Python v2 MCP API). |
| `weather_service.py` | Pure Python Open-Meteo client (geocode + current observation). No SDK. |
| `host.json` | Enables the MCP extension; sets `webhookAuthorizationLevel: "System"` so callers must present the `mcp_extension` system key. |
| `requirements.txt` | `azure-functions>=2.0.0b1`, `azure-monitor-opentelemetry`, urllib instrumentor. |
| `azure.yaml` | `azd` service definition + post-provision hook that prints the endpoint and the key-retrieval command. |
| `infra/main.bicep` | Storage + Flex Consumption plan + Function App (Python 3.13) + (optional) App Insights. Wires the same App Insights connection string the Foundry project uses, so KQL queries correlate. |

## Prerequisites

| Tool | Why |
|---|---|
| Python **3.13** | Matches this workshop's Function App runtime. |
| [Azure Functions Core Tools v4.0.7030+](https://learn.microsoft.com/azure/azure-functions/functions-run-local) | `func start` for local testing. |
| [Azure Developer CLI (`azd`)](https://aka.ms/azd) | One-command deploy. |
| [Azure CLI (`az`)](https://learn.microsoft.com/cli/azure/install-azure-cli) | Retrieve the `mcp_extension` system key. |
| Docker (or the Azurite VS Code extension) | Local storage emulator for `func start`. |

## Local dev (optional)

Run the Functions host, not `python function_app.py`. The complete Mac and
Windows instructions also appear at the top of `function_app.py`.
Keep the server environment separate from the repository root agent `.venv`.

### Start local storage

Run this command in its own terminal. It works in macOS Terminal and Windows
PowerShell. Keep it running while the Functions host runs. If Azurite already
uses these ports, reuse that instance instead.

```text
docker run --rm -p 10000:10000 -p 10001:10001 -p 10002:10002 mcr.microsoft.com/azure-storage/azurite
```

### macOS Terminal

Open another terminal anywhere inside this Git clone:

```bash
cd "$(git rev-parse --show-toplevel)"
cd 06-weather-mcp-agent/mcp-server
test -x .venv/bin/python || python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
test -f local.settings.json || cp local.settings.json.example local.settings.json
```

### Windows PowerShell

Open another terminal anywhere inside this Git clone:

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
Set-Location .\06-weather-mcp-agent\mcp-server
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
if (-not (Test-Path local.settings.json)) { Copy-Item local.settings.json.example local.settings.json }
```

Review `local.settings.json`. The template uses
`AzureWebJobsStorage=UseDevelopmentStorage=true` and
`FUNCTIONS_WORKER_RUNTIME=python`. The optional App Insights connection string
can remain empty. If you add it, local telemetry is sent to that Azure resource.
Preserve existing settings and do not commit credentials.

### Start the Functions host

From the server directory prepared above, select the server environment.

macOS Terminal:

```bash
source .venv/bin/activate
func start
```

Windows PowerShell:

```powershell
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
$env:PATH = "$env:VIRTUAL_ENV\Scripts;$env:PATH"
func start
```

The Windows commands avoid `Activate.ps1` and do not change execution policy.
Connect a local MCP client or [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
to `http://localhost:7071/runtime/webhooks/mcp`.
Core Tools skips authorization by default locally, so no Azure system key is
needed for this local setup. See the official
[local runtime guidance](https://learn.microsoft.com/azure/azure-functions/functions-run-local#start-the-functions-runtime)
and [local MCP client example](https://learn.microsoft.com/azure/azure-functions/functions-bindings-mcp#connect-to-your-mcp-server).
The deployed Azure endpoint still requires its `mcp_extension` system key.
The sample 06 agent uses hosted MCP, so Foundry cannot reach this localhost
address directly. Local server startup on Mac and Windows remains unverified.
Press Ctrl+C in both terminals to stop the host and emulator.

## Deploy to Azure

For a new deployment, start in this server directory, sign in and create an
azd environment before setting environment values. These commands work in
macOS Terminal and Windows PowerShell:

```text
azd auth login
azd env new
```

Choose a unique environment name when prompted. For an existing deployment,
select its environment with `azd env select` instead of creating a new one.
Skip deployment entirely if you only need to run the agent against an existing
server.

Optional shared tracing configuration, using your real connection string:

```text
# Optional but recommended: paste your Foundry project's App Insights connection
# string before `azd up` so the Function App reports to the same workspace as
# the agent. (See the parent .env file.)
azd env set APPLICATIONINSIGHTS_CONNECTION_STRING "<connection-string>"
```

Then provision and deploy:

```text
azd up
```

After it finishes, the post-provision hook prints both the MCP endpoint and the
exact `az` command to fetch the `mcp_extension` system key. Paste both into
`../.env`.

## Smoke-test the deployed server

The MCP Streamable HTTP transport requires an `initialize` handshake before
any other request, so the easiest sanity check is the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector
# In the UI:
#   Transport: Streamable HTTP
#   URL:       https://<func>.azurewebsites.net/runtime/webhooks/mcp
#   Headers:   x-functions-key: <mcp_extension system key>
```

You should see the `get_weather` tool and be able to invoke it with
`{"location": "Seattle, WA"}` and get a JSON weather payload back.

If you prefer raw HTTP, use the [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk):

```bash
pip install "mcp[cli]"
python - <<'PY'
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://<func>.azurewebsites.net/runtime/webhooks/mcp"
KEY = "<mcp_extension system key>"

async def main():
    async with streamablehttp_client(URL, headers={"x-functions-key": KEY}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            result = await session.call_tool("get_weather", {"location": "Seattle, WA"})
            print("Result:", result.content[0].text)

asyncio.run(main())
PY
```

A 200 with `Tools: ['get_weather']` and a populated weather JSON proves the
server, the system key, and the MCP extension are all healthy and ready for
the Foundry agent.

## Attribution

The weather lookup logic is adapted from the official
[`Azure-Samples/remote-mcp-functions-python`](https://github.com/Azure-Samples/remote-mcp-functions-python)
`McpWeatherApp` sample (MIT-licensed).
