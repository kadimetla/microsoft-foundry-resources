# Weather API — Shared Downstream API

A minimal Flask app that plays the role of *"the downstream API your agent calls"* in every sample in this repo. It validates incoming Agent Identity tokens and returns real weather data from [Open-Meteo](https://open-meteo.com) (no key required).

This service demonstrates the downstream token flow for sample 05.
Its workshop validation includes a Graph token compatibility fallback.
Read `app.py` for the exact checks rather than treating it as a general
purpose token validation library.

## What it does

- Exposes `GET /weather?city=<name>`, `GET /weather/forecast?city=<name>` and `GET /health`.
- On every request to `/weather`, validates the `Authorization: Bearer <token>` header:
  - **Signature**: attempts RS256 verification against the Entra JWKS. The Graph nonce compatibility path can skip signature verification.
  - **Issuer** — must match `https://sts.windows.net/<tenant>/` or `https://login.microsoftonline.com/<tenant>/v2.0`
  - **Audience**: the workshop code does not check `aud`. There is no supported `EXPECTED_AUDIENCE` setting.
  - **Agent-identity marker** — the `xms_par_app_azp` claim (present in Agent tokens, absent in plain app-only tokens) is logged so you can see which Blueprint minted the call
- Returns real weather on success, HTTP 401 with a reason on any validation failure.

## How the samples use it

```
┌─────────────┐                  ┌──────────────────┐
│ Agent       │  Bearer <T2>     │   weather-api    │
│ (dev/aws)   ├─────────────────▶│                  │
└─────────────┘                  │  - verify token  │
                                 │  - call          │
                                 │    Open-Meteo    │
                                 └──────────────────┘
```

The [`foundry/`](../foundry/README.md) Compose stack starts this API alongside
the agent and auth sidecar. The Ollama and Bedrock variants live in the external
[`3P-Agent-ID-Demo`](https://github.com/razi-rais/3P-Agent-ID-Demo) repository,
not in sibling folders here.

## Run it standalone

Prefer the complete [Foundry Compose quickstart](../foundry/README.md#5-quickstart)
when running sample 05. The standalone commands below start only this API.
They require Git, Docker Desktop running Linux containers and a real Entra
tenant ID. Start from any folder inside this clone.
The app reads process environment variables, not `.env` automatically.

### macOS Terminal

```bash
cd "$(git rev-parse --show-toplevel)"
cd 05-end-to-end-agent/sidecar/weather-api
docker build -t weather-api:local .
printf "Entra tenant ID: "
read -r TENANT_ID
docker run --rm -p 8080:8080 -e "TENANT_ID=$TENANT_ID" -e VALIDATE_TOKEN_SIGNATURE=true weather-api:local
```

### Windows PowerShell

```powershell
Set-Location -LiteralPath (git rev-parse --show-toplevel)
Set-Location .\05-end-to-end-agent\sidecar\weather-api
docker build -t weather-api:local .
$tenantId = Read-Host "Entra tenant ID"
docker run --rm -p 8080:8080 -e "TENANT_ID=$tenantId" -e VALIDATE_TOKEN_SIGNATURE=true weather-api:local
```

Open <http://localhost:8080/health> for the unauthenticated health route.
For weather requests, use the bearer token obtained by the
[Foundry sidecar flow](../foundry/README.md). Starting this API does not mint
tokens or provision identities. Press Ctrl+C to stop the standalone service.
Do not also start it when Compose is already managing the API.
Mac and Windows startup remain unverified.

Optional weather request from macOS Terminal, using your Agent Identity token:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8080/weather?city=Dallas"
```

Expected response (real data):

```json
{
  "city": "Dallas",
  "temperature": 61,
  "temperature_unit": "F",
  "condition": "Overcast",
  "humidity": 93,
  "wind_speed": 8,
  "is_agent_identity": true,
  "agent_app_id": "<agent-app-id from xms_par_app_azp>",
  "validated_by": "Agent Identity Token",
  "data_source": "Open-Meteo API (Real-time)"
}
```

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TENANT_ID` | yes | — | Entra tenant — used to build JWKS URL and issuer check |
| `VALIDATE_TOKEN_SIGNATURE` | no | `true` | Enables the existing JWKS validation path and its Graph compatibility behavior |

The application listens on port `8080`. There is no `PORT` override in this
implementation. Docker can map a different host port if required.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app — route handlers, token validation, Open-Meteo client |
| `Dockerfile` | `python:3.11-slim` base, runs `python app.py` |
| `requirements.txt` | `flask`, `flask-cors`, `PyJWT[crypto]`, `requests` |

## Why this is in the repo

The shared service makes the sample 05 flow easier to inspect because the
agent UI, token acquisition and downstream weather request stay separate.

For the conceptual overview of how tokens flow from agent → sidecar → API, see [`../README.md`](../README.md).
