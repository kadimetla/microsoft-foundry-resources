r"""Run the Azure Functions get_weather MCP server for sample 06.

Run this project with func start, NOT python function_app.py or VS Code's
Run Python File button. The Functions host registers the decorated MCP tool.
weather_service.py is an imported helper and is not a separate service.

Prerequisites: Python 3.13, Git, Azure Functions Core Tools v4.0.7030 or
newer, and Docker Desktop running Linux containers for Azurite.
Install Core Tools separately if func is not on PATH:
    macOS with Homebrew:
        brew tap azure/functions
        brew install azure-functions-core-tools@4
    Windows with Node.js/npm already installed:
        npm install -g azure-functions-core-tools@4
The Windows 64 bit Core Tools v4 MSI is an alternative to npm.

1. Start local storage in a separate terminal

The same one line Docker command works in macOS Terminal and Windows
PowerShell. It stays in the foreground. Keep it running while the Functions
host runs. If Azurite already listens on these ports, reuse it instead.
    docker run --rm -p 10000:10000 -p 10001:10001 -p 10002:10002 mcr.microsoft.com/azure-storage/azurite

2. Prepare the Functions project

Open another terminal INSIDE this Git clone. Use this server's own .venv,
not the root agent environment. Preserve any existing local.settings.json.

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    cd 06-weather-mcp-agent/mcp-server
    test -x .venv/bin/python || python3.13 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m pip check
    test -f local.settings.json || cp local.settings.json.example local.settings.json

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    Set-Location .\06-weather-mcp-agent\mcp-server
    if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.13 -m venv .venv }
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m pip check
    if (-not (Test-Path local.settings.json)) { Copy-Item local.settings.json.example local.settings.json }

Review local.settings.json before startup. For the emulator, Values must
include AzureWebJobsStorage=UseDevelopmentStorage=true and
FUNCTIONS_WORKER_RUNTIME=python. Keep the optional App Insights string empty
unless you want local telemetry sent to that Azure resource.
No Open-Meteo API key or Azure model deployment is needed for this server.
Do not commit local.settings.json if you add credentials.

3. Start from the server directory prepared above

macOS Terminal:
    source .venv/bin/activate
    func start

Windows PowerShell:
    $env:VIRTUAL_ENV = (Resolve-Path .venv).Path
    $env:PATH = "$env:VIRTUAL_ENV\Scripts;$env:PATH"
    func start

The Windows commands select the venv without running Activate.ps1 or
changing PowerShell execution policy. Keep both terminals open.
The local MCP endpoint is http://localhost:7071/runtime/webhooks/mcp.
Core Tools skips authorization by default locally. Azure deployment uses
the authentication described below. Do not reuse an Azure key locally.
Connect a LOCAL MCP client to this endpoint. The sample 06 agent uses
hosted MCP, so Azure cannot call this localhost URL directly.
Press Ctrl+C in each terminal to stop the host and local storage.
Local startup on Mac and Windows remains unverified. For deployment, use
this directory's README.md. Do not redeploy just to run an existing agent.

Hosted on Azure Functions using the MCP extension (Python v2 model). Once
deployed, this exposes ``https://<app>.azurewebsites.net/runtime/webhooks/mcp``
which the Foundry agent in ``06-weather-mcp-agent.py`` consumes via the
standard MCP protocol.

Auth (iteration 1): callers present the ``mcp_extension`` system key because
``host.json`` sets ``webhookAuthorizationLevel: "System"``. Foundry attaches
this key as an ``x-functions-key`` header on every MCP request.

Auth (iteration 2): Easy Auth is enabled on the Function App with the Entra
app reg ``weather-mcp`` as the identity provider. ``host.json`` flips
``webhookAuthorizationLevel`` to ``"Anonymous"`` so Easy Auth is the sole gate.
Callers (the Foundry Agent Identity SP, granted the ``MCP.Invoke`` app role)
present a v2 access token for ``api://<mcp-app-id>`` as ``Authorization: Bearer``.
No code change in ``get_weather`` is required for iteration 2.

A separate ``GET /api/whoami`` HTTP route decodes the Easy-Auth-injected
``X-MS-CLIENT-PRINCIPAL`` header so KQL queries can prove **which** identity
called the MCP server. It is anonymous on the runtime side because Easy Auth
already gates it; with Easy Auth off it accepts all callers and returns
``{authenticated: false}``.
"""

from __future__ import annotations

import base64
import json
import logging
import os

import azure.functions as func

# Wire OpenTelemetry → Application Insights so the Function App's incoming
# request span and outbound Open-Meteo dependency spans land in the same App
# Insights workspace as the Foundry agent. Required for the KQL cookbook.
_AI_CONN = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
if _AI_CONN:
    # NOTE: We rely on the Functions runtime's built-in App Insights
    # auto-instrumentation (enabled by `APPLICATIONINSIGHTS_ENABLE_AGENT=true`
    # in Bicep) rather than calling `azure.monitor.opentelemetry.configure_azure_monitor`.
    # On Flex Consumption / Linux Python, calling configure_azure_monitor in
    # user code attaches a LoggingHandler that competes with the runtime's
    # handler — the net effect is user-code `logging.*` records get filtered
    # OR silently dropped, while runtime-emitted spans/requests still land.
    # The auto-instrumentation handles incoming HTTP, outbound HTTP (when
    # opentelemetry-instrumentation-* packages are installed), and stdlib
    # `logging` records at INFO+ (controlled by host.json `logLevel`).
    try:
        from opentelemetry.instrumentation.urllib import URLLibInstrumentor
        URLLibInstrumentor().instrument()
        logging.warning("[obs] urllib outbound instrumentation enabled (App Insights auto-wired by runtime)")
    except Exception as exc:  # noqa: BLE001 — never fail boot due to telemetry
        logging.warning("[obs] urllib instrumentation init failed: %s", exc)

from weather_service import get_current_weather  # noqa: E402

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.mcp_tool()
@app.mcp_tool_property(
    arg_name="location",
    description="City name, region, or ZIP/postal code (e.g. 'Seattle, WA', 'Paris', '10001').",
    is_required=True,
)
def get_weather(location: str) -> str:
    """Returns current weather (temperature, condition, humidity, wind) for a city.

    Uses the free Open-Meteo API. Read-only and idempotent; safe to auto-approve.
    """
    if not isinstance(location, str) or not location.strip():
        return json.dumps({
            "error": "Argument 'location' is required (e.g. 'Seattle, WA').",
            "source": "open-meteo",
        })

    result = get_current_weather(location)
    logging.info(
        "get_weather → %s (%s)",
        result.get("location"),
        result.get("condition") or result.get("error"),
    )
    return json.dumps(result)


@app.function_name(name="whoami")
@app.route(route="whoami", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def whoami(req: func.HttpRequest) -> func.HttpResponse:
    """Echoes the Easy Auth-injected client principal as JSON.

    Easy Auth populates these headers on every authenticated request:
      * ``X-MS-CLIENT-PRINCIPAL-ID``    — the caller's OID
      * ``X-MS-CLIENT-PRINCIPAL-NAME``  — UPN / SPN display name (if any)
      * ``X-MS-CLIENT-PRINCIPAL-IDP``   — identity provider (``aad``)
      * ``X-MS-CLIENT-PRINCIPAL``       — base64-encoded JSON with full claims

    Useful for proving in KQL which Foundry Agent Identity made a call:
        traces | where message contains "[whoami]"

    Returns ``{authenticated: false}`` when no principal is present (Easy Auth
    off, or the route bypasses it).
    """
    raw = req.headers.get("x-ms-client-principal")
    oid = req.headers.get("x-ms-client-principal-id")
    name = req.headers.get("x-ms-client-principal-name")
    idp = req.headers.get("x-ms-client-principal-idp")

    payload: dict = {
        "authenticated": bool(raw or oid),
        "oid": oid,
        "name": name,
        "idp": idp,
    }
    if raw:
        try:
            claims = json.loads(base64.b64decode(raw))
            payload["claims"] = claims
            # Convenience: pull the role assertions to the top.
            role_claims = [
                c.get("val") for c in claims.get("claims", [])
                if c.get("typ") == "roles"
            ]
            payload["roles"] = role_claims
        except Exception as exc:  # noqa: BLE001
            payload["decode_error"] = str(exc)

    # Use WARNING so the line is never filtered out by the
    # azure-monitor-opentelemetry default level (WARNING). The string is
    # discoverable by KQL via `traces | where message startswith "[whoami]"`.
    logging.warning(
        "[whoami] oid=%s name=%s idp=%s roles=%s",
        oid, name, idp, payload.get("roles"),
    )
    return func.HttpResponse(
        json.dumps(payload, default=str),
        mimetype="application/json",
        status_code=200,
    )
