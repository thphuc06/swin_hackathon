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

## Agent routing bundles (current policy v1)

These tools are selected by the agent planner (semantic routing + deterministic bundle policy):

- `summary` -> `spend_analytics_v1`, `cashflow_forecast_v1`, `jar_allocation_suggest_v1`
- `risk` -> `spend_analytics_v1`, `anomaly_signals_v1`, `risk_profile_non_investment_v1`
- `planning` -> `spend_analytics_v1`, `cashflow_forecast_v1`, `recurring_cashflow_detect_v1`, `goal_feasibility_v1`, `jar_allocation_suggest_v1`
- `scenario` -> `what_if_scenario_v1`
- `invest` -> `suitability_guard_v1`, `risk_profile_non_investment_v1`
- `out_of_scope` -> `suitability_guard_v1`

Notes:
- `suitability_guard_v1` is always called early in the graph for compliance.
- Tool arguments are sanitized with omit-none behavior (`exclude_none`/drop `None`) before MCP calls to avoid schema violations.

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

- `COGNITO_ALLOWED_CLIENT_IDS` (comma-separated allow-list; if omitted, falls back to `COGNITO_CLIENT_ID`)
- `COGNITO_SERVICE_CLIENT_IDS` (comma-separated client IDs treated as trusted service callers)
- `SQL_TIMEOUT_SEC` (default: `20`)
- `USE_DARTS_FORECAST` (default: `true`)
- `DEV_BYPASS_AUTH` (`true` for demo-first gateway integration)
- `FINANCE_MCP_FIXED_USER_ID` (demo-only override: force all authenticated calls to use one Supabase `user_id`)

Demo note:

- If `DEV_BYPASS_AUTH=false` but your Supabase seed data belongs to a single fixed UUID, set `FINANCE_MCP_FIXED_USER_ID=<seed_user_id>`.
- When this override is set, the server rewrites both the authenticated subject and the request `user_id` to that fixed UUID for all tools.
- Remove `FINANCE_MCP_FIXED_USER_ID` after you align Cognito `sub` values with real application user IDs.

Gateway hardened auth note:

- For `Gateway -> finance-mcp` via outbound OAuth, create a second Cognito app client for machine-to-machine access.
- Keep the existing user app client for inbound Gateway JWT auth.
- Configure:
  - `COGNITO_ALLOWED_CLIENT_IDS=<user_client_id>,<m2m_client_id>`
  - `COGNITO_SERVICE_CLIENT_IDS=<m2m_client_id>`
- User tokens still enforce `sub == user_id`.
- Service tokens are treated as trusted service callers and do not use token `sub` as the business `user_id`.
- During demo, keep `FINANCE_MCP_FIXED_USER_ID=<seed_user_id>` until you implement real user mapping.

## App Runner (Source deploy)

Use this directory as source root:

- Root directory: `src/aws-finance-mcp-server`
- Runtime: Python 3.11
- Build command: `python3 -m venv .venv && . .venv/bin/activate && python -m pip install --upgrade pip setuptools wheel && python -m pip install -r requirements.txt`
- Start command: `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080`
- Port: `8080`

After deploy:

1. Verify `GET https://<service-url>/mcp`
2. Verify `POST https://<service-url>/mcp` with `tools/list`
3. Add this URL as `finance-mcp` target in AgentCore Gateway.

Demo auth with seeded Supabase data:

- Keep `DEV_BYPASS_AUTH=false` if you want to validate real JWT auth.
- Set `FINANCE_MCP_FIXED_USER_ID=<seed_user_id>` in App Runner if your test token subject does not match the seeded Supabase `user_id`.
- Remove the override later and migrate data/user mapping before switching to production auth.

## Smoke checks

Direct MCP:

```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\src\aws-finance-mcp-server
$seed = (Get-Content ..\..\backend\tmp\seed_manifest_single_user.json | ConvertFrom-Json).seed_user_id
.\scripts\run_finance_mcp_smoke.ps1 -BaseUrl "https://<finance-mcp-app-runner>" -SeedUserId $seed
```

Via Gateway (prefixed tools):

```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\src\aws-finance-mcp-server
$seed = (Get-Content ..\..\backend\tmp\seed_manifest_single_user.json | ConvertFrom-Json).seed_user_id
.\scripts\run_gateway_finance_smoke.ps1 `
  -GatewayEndpoint "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com" `
  -SeedUserId $seed `
  -AuthToken "<cognito-access-token>"
```
