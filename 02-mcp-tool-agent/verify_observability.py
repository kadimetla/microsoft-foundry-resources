#!/usr/bin/env python3
r"""Verify the latest workshop agent run using the Application Insights query API.

Prerequisites: Python 3.13, Git, Azure CLI and permission to query the
Application Insights resource used by a previous traced sample run.
Keep the complete repository together.

1. Setup

Run from any folder INSIDE this Git clone. Reuse the repository .venv.
Activation is not required.

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
    test -f 02-mcp-tool-agent/.env || cp 02-mcp-tool-agent/.env.example 02-mcp-tool-agent/.env

Windows PowerShell:
    if (-not (Test-Path .\02-mcp-tool-agent\.env)) { Copy-Item .\02-mcp-tool-agent\.env.example .\02-mcp-tool-agent\.env }

Edit 02-mcp-tool-agent/.env and set:
    APPLICATIONINSIGHTS_SUBSCRIPTION_ID
    APPLICATIONINSIGHTS_RESOURCE_GROUP
    APPLICATIONINSIGHTS_RESOURCE_NAME
Optional filters: LOOKBACK_MINUTES, OBSERVABILITY_SCENARIO and
OBSERVABILITY_TRACE_ID. See .env.example for their values.
Run a traced sample first and allow time for telemetry ingestion.

3. Run after saving .env

macOS Terminal:
    cd "$(git rev-parse --show-toplevel)"
    .venv/bin/python -X utf8 02-mcp-tool-agent/verify_observability.py

Windows PowerShell:
    Set-Location -LiteralPath (git rev-parse --show-toplevel)
    .\.venv\Scripts\python.exe -X utf8 .\02-mcp-tool-agent\verify_observability.py

4. VS Code

Open the repository root and use Python: Select Interpreter to choose
.venv/bin/python on Mac or .venv\Scripts\python.exe on Windows.
Open this file and select Run Python File. Its own folder supplies .env.

Expected result: a JSON verification report for matching telemetry.
This script does not invoke agents or create agent versions.
Live telemetry verification and Windows execution remain unverified.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _workshop import configure_console


def kql(client: httpx.Client, app_id: str, query: str, title: str) -> list[dict[str, object]] | None:
    print(f"\n{title}")
    try:
        response = client.get(
            f"https://api.applicationinsights.io/v1/apps/{quote(app_id, safe='')}/query",
            params={"query": query},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise ValueError(f"Application Insights returned an error: {data['error']}")
        table = data["tables"][0]
        columns = [column["name"] for column in table["columns"]]
        rows = table["rows"]
        if not all(isinstance(column, str) for column in columns) or not isinstance(rows, list):
            raise ValueError("Invalid columns or rows in the query response.")
        if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
            raise ValueError("A query row does not match its columns.")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        print(f"Query failed: {exc}", file=sys.stderr)
        return None

    if not rows:
        print("  No rows. Content queries may be empty when sensitive capture is disabled.")
        return []
    widths = [
        min(max(len(column), max(len(str(row[index])) for row in rows)), 90)
        for index, column in enumerate(columns)
    ]
    print("  " + " | ".join(f"{column:<{width}}" for column, width in zip(columns, widths)))
    for row in rows:
        print("  " + " | ".join(f"{str(value)[:width]:<{width}}" for value, width in zip(row, widths)))
    return [dict(zip(columns, row)) for row in rows]


def verification_queries(trace_id: str) -> list[tuple[str, str]]:
    spans = f"""
union dependencies, requests
| where operation_Id == "{trace_id}"
"""
    client_spans = spans + '| where cloud_RoleName startswith "foundry-workshop."\n'
    return [
        ("Q0: Correlated span waterfall", spans + """
| project timestamp, service=cloud_RoleName, name, success, duration,
          tool=tostring(customDimensions["gen_ai.tool.name"])
| order by timestamp asc
"""),
        ("Q1: Span counts", f"""
union dependencies, requests, traces
| where operation_Id == "{trace_id}"
| summarize spans=count() by scenario=cloud_RoleName, itemType
| order by scenario, itemType
"""),
        ("Q2: Model tokens counted once", client_spans + """
| where tostring(customDimensions["gen_ai.operation.name"]) == "chat"
| extend in_tok=tolong(customDimensions["gen_ai.usage.input_tokens"]),
         out_tok=tolong(customDimensions["gen_ai.usage.output_tokens"])
| where isnotnull(in_tok)
| summarize input_tok=sum(in_tok), output_tok=sum(out_tok), model_calls=count()
"""),
        ("Q3: Optional user prompt content", client_spans + """
| where name startswith "invoke_agent"
| extend msgs=parse_json(tostring(customDimensions["gen_ai.input.messages"]))
| mv-expand m=msgs
| where tostring(m.role) == "user"
| mv-expand p=m.parts
| where tostring(p.type) == "text"
| project timestamp, scenario=cloud_RoleName, prompt=substring(tostring(p.content), 0, 90)
| order by timestamp asc
"""),
        ("Q4: Optional output content types", client_spans + """
| where name startswith "invoke_agent"
| extend msgs=parse_json(tostring(customDimensions["gen_ai.output.messages"]))
| mv-expand m=msgs
| mv-expand p=m.parts
| where isnotempty(tostring(p.type))
| summarize parts=count() by content_type=tostring(p.type)
"""),
    ]


def main() -> int:
    configure_console()
    load_dotenv(Path(__file__).resolve().parent / ".env")
    names = (
        "APPLICATIONINSIGHTS_SUBSCRIPTION_ID",
        "APPLICATIONINSIGHTS_RESOURCE_GROUP",
        "APPLICATIONINSIGHTS_RESOURCE_NAME",
    )
    settings = [os.environ.get(name, "").strip() for name in names]
    if any(not value or "<" in value for value in settings):
        print(f"Set {', '.join(names)} in .env. See .env.example.", file=sys.stderr)
        return 2
    try:
        lookback = int(os.environ.get("LOOKBACK_MINUTES", "1440"))
        if lookback <= 0:
            raise ValueError
    except ValueError:
        print("LOOKBACK_MINUTES must be a positive integer.", file=sys.stderr)
        return 2
    trace_id = os.environ.get("OBSERVABILITY_TRACE_ID", "").strip().lower()
    if trace_id and not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        print("OBSERVABILITY_TRACE_ID must contain 32 hexadecimal characters.", file=sys.stderr)
        return 2
    scenario = os.environ.get("OBSERVABILITY_SCENARIO", "").strip()
    role_filter = (
        f"cloud_RoleName == {json.dumps('foundry-workshop.' + scenario)}"
        if scenario else 'cloud_RoleName startswith "foundry-workshop."'
    )
    trace_filter = f'| where operation_Id == "{trace_id}"' if trace_id else ""
    sub, group, app = (quote(value, safe="") for value in settings)
    resource_url = (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{group}"
        f"/providers/Microsoft.Insights/components/{app}"
    )

    try:
        with AzureCliCredential() as credential, httpx.Client(timeout=60) as client:
            token = credential.get_token("https://management.azure.com/.default")
            resource = client.get(
                resource_url,
                params={"api-version": "2015-05-01"},
                headers={"Authorization": f"Bearer {token.token}"},
            )
            resource.raise_for_status()
            app_id = resource.json()["properties"]["AppId"]
            token = credential.get_token("https://api.applicationinsights.io/.default")
            client.headers["Authorization"] = f"Bearer {token.token}"
            latest = kql(client, app_id, f"""
union dependencies, requests
| where timestamp > ago({lookback}m)
| where {role_filter}
{trace_filter}
| where name startswith "invoke_agent"
| top 1 by timestamp desc
| project operation_Id, success, scenario=cloud_RoleName
""", "Latest matching agent run")
            if not latest:
                print("No agent run found. Check the settings and allow time for ingestion.", file=sys.stderr)
                return 1
            trace_id = str(latest[0]["operation_Id"])
            if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
                raise ValueError("Application Insights returned an invalid operation ID.")
            success = latest[0]["success"]
            passed = success is True or (isinstance(success, str) and success.lower() == "true")
            for title, query in verification_queries(trace_id):
                rows = kql(client, app_id, query, title)
                if rows is None:
                    passed = False
                if title.startswith("Q0") and latest[0]["scenario"] == "foundry-workshop.tracing":
                    if not rows or not any(row.get("name") == "example-tracing" for row in rows):
                        print("The tracing sample's root span is missing.", file=sys.stderr)
                        passed = False
    except (AzureError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1

    if not passed:
        print("Verification failed: a query failed or the selected agent run was incomplete.", file=sys.stderr)
        return 1
    print(f"\nVerified a completed agent run. Trace ID: {trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
