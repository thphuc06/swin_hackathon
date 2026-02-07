# AWS Finance MCP Server

Standalone MCP server for Jars financial tools. This service is intended to be deployed separately from `backend`.

## Exposed endpoints

- `GET /health`
- `GET /mcp`
- `POST /mcp` (JSON-RPC: `initialize`, `tools/list`, `tools/call`)

## Tool names

- `spend_analytics_v1`
- `anomaly_signals_v1`
- `cashflow_forecast_v1`
- `jar_allocation_suggest_v1`
- `risk_profile_non_investment_v1`
- `suitability_guard_v1`
- `recurring_cashflow_detect_v1`
- `goal_feasibility_v1`
- `what_if_scenario_v1`

## Local run

```bash
cd src/aws-finance-mcp-server
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8020
```

Health check:

```bash
curl http://127.0.0.1:8020/mcp
```

## Required environment variables

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `AWS_REGION`

Optional:

- `SQL_TIMEOUT_SEC` (default: `20`)
- `USE_DARTS_FORECAST` (default: `true`)
- `DEV_BYPASS_AUTH` (`true` only for local development)

## App Runner (Source deploy)

Use this directory as source root:

- Root directory: `src/aws-finance-mcp-server`
- Runtime: Python 3.12
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8080`
- Port: `8080`

After deploy:

1. Verify `GET https://<service-url>/mcp`
2. Verify `POST https://<service-url>/mcp` with `tools/list`
3. Add this URL as `finance-mcp` target in AgentCore Gateway.
