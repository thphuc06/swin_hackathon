# Setup Guide (Single Source of Truth): E2E + AWS Real

Updated: 2026-03-04  
Scope: this document replaces setup scattered across multiple README files.

## 1) Quick assessment of current READMEs

Reviewed files:
- `README.md` (repo root)
- `src/aws-finance-mcp-server/README.md`
- `src/aws-kb-retrieval-server/README.md`
- `iac/README.md`
- `backend/docs/mcp_financial_tools_test_plan.md`

Current status:
- Setup docs are useful but not fully aligned with current codebase.
- Root `README.md` still references scripts that are not in the repo:
  - `run_qa_tests.py`
  - `verify_gateway_tools.py`
  - `run_gateway_finance_smoke.ps1`
  - `backend/scripts/run_chat_stream_smoke.ps1`
- Root `README.md` has text encoding corruption (mojibake) in several sections.

Conclusion:
- Use this file as the canonical setup guide for running E2E with AWS real services.

## 2) Actual runtime flow implemented now

Primary flow (hybrid local + AWS real):
- `Frontend (local Next.js)` -> `Backend (local FastAPI /chat/stream)` -> `AgentCore Runtime (AWS)` -> `AgentCore Gateway` -> `Finance MCP (App Runner)` -> `Supabase`

Notes:
- Backend decides runtime target by `AGENTCORE_RUNTIME_ARN`:
  - set -> call AWS AgentCore Runtime
  - empty -> fallback to local agent endpoint (`AGENTCORE_LOCAL_URL`)
- Agent uses local KB files (`kb/*.md`) in current implementation.
- `src/aws-kb-retrieval-server` is optional in current flow (not required for baseline AWS-real E2E).

## 3) Environment fields from current `.env*` + code usage

This section is based on:
- existing `.env` and `.env.example` files in repo
- direct env usage in code (`agent`, `backend`, `frontend`, `workers`, `src/aws-finance-mcp-server`)

## 3.1 Frontend (`frontend/.env.local`)

Required for E2E:
- `NEXT_PUBLIC_API_BASE_URL` (example: `http://localhost:8010`)

Present in env files but currently unused by frontend code:
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_COGNITO_USER_POOL_ID`
- `NEXT_PUBLIC_COGNITO_CLIENT_ID`
- `NEXT_PUBLIC_COGNITO_DOMAIN`

## 3.2 Backend (`backend/.env`)

Required for AWS-real `/chat/stream`:
- `AGENTCORE_RUNTIME_ARN`
- `AWS_REGION`
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `DEV_BYPASS_AUTH=false`

Optional:
- `AGENTCORE_LOCAL_URL` (used only when `AGENTCORE_RUNTIME_ARN` is empty)

Present in `backend/.env` but not used by active backend app routes:
- `AGENTCORE_GATEWAY_ENDPOINT`
- `AGENTCORE_MEMORY_ID`
- `AGENTCORE_ALLOWED_AUDIENCE`
- `AGENTCORE_JWT_ISSUER_DISCOVERY_URL`
- `AGENTCORE_REQUIRED_SCOPES`
- `BEDROCK_MODEL_ID`
- `BEDROCK_KB_ID`
- `BEDROCK_KB_DATASOURCE_ID`
- `BEDROCK_GUARDRAIL_ID`
- `BEDROCK_GUARDRAIL_VERSION`
- `COGNITO_DOMAIN`
- `COGNITO_CLIENT_SECRET`
- `EVENTBRIDGE_BUS_NAME`
- `SQS_QUEUE_URL`
- `SNS_TOPIC_ARN`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## 3.3 Agent runtime env (`agent/.env` and deploy env)

Minimum for AWS-real runtime behavior:
- `AWS_REGION`
- `BEDROCK_MODEL_ID`
- `AGENTCORE_GATEWAY_ENDPOINT` (must end with `/mcp` or it will be auto-normalized)
- `USE_LOCAL_MOCKS=false`
- `BACKEND_API_BASE` (reachable URL from cloud runtime)

Strongly recommended:
- `RESPONSE_MODE=llm_enforce`
- `ROUTER_MODE=semantic_enforce`
- `LOG_LEVEL=info`

For `agent/genToken.py`:
- required: `COGNITO_CLIENT_ID`, `COGNITO_USERNAME`, `COGNITO_PASSWORD`
- optional: `COGNITO_CLIENT_SECRET`
- optional with default: `AWS_REGION` (defaults to `us-east-1`)

Present in `agent/.env` but currently not used in agent runtime code path:
- `AGENTCORE_RUNTIME_ID`
- `AGENTCORE_MEMORY_ID`
- `AGENTCORE_JWT_ISSUER_DISCOVERY_URL`
- `AGENTCORE_ALLOWED_AUDIENCE`
- `AGENTCORE_REQUIRED_SCOPES`
- `BEDROCK_KB_ID` (local KB is used instead)
- `BEDROCK_KB_DATASOURCE_ID`

## 3.4 Finance MCP server (`src/aws-finance-mcp-server/.env`)

Required:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DEV_BYPASS_AUTH` (set explicitly; `false` in hardened mode, `true` in demo mode)

Required when `DEV_BYPASS_AUTH=false`:
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `AWS_REGION`

Optional:
- `SQL_TIMEOUT_SEC`
- `USE_DARTS_FORECAST`
- `LOG_LEVEL`

## 3.5 Workers (`workers/.env` if workers are used)

Actually used by worker code:
- `FINANCE_MCP_URL`
- `FINANCE_MCP_AUTH_TOKEN`
- `WORKER_HTTP_TIMEOUT_SECONDS`

Current gap:
- these 3 fields are missing from `workers/.env.example`.

## 4) End-to-end setup (AWS real)

This is the recommended path:
- frontend local
- backend local
- runtime/gateway/finance-mcp in AWS

## 4.1 Prerequisites

- Python 3.11
- Node.js 18+
- AWS CLI configured
- `agentcore` CLI installed and authenticated
- Cognito app client and user credentials ready

## 4.2 Finance MCP on AWS

1. Set env in `src/aws-finance-mcp-server/.env` (or App Runner env) with required fields.
2. Deploy service to App Runner.
3. Verify health:

```powershell
Invoke-RestMethod -Method GET -Uri "https://<finance-mcp-url>/health"
```

4. Verify MCP tools list directly:

```powershell
$body = @{ jsonrpc = "2.0"; id = "1"; method = "tools/list" } | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method POST -Uri "https://<finance-mcp-url>/mcp" -ContentType "application/json" -Body $body
```

If `DEV_BYPASS_AUTH=false`, include auth header:

```powershell
Invoke-RestMethod -Method POST -Uri "https://<finance-mcp-url>/mcp" `
  -Headers @{ Authorization = "Bearer <ACCESS_TOKEN>" } `
  -ContentType "application/json" -Body $body
```

## 4.3 AgentCore Gateway

Configure target URL:
- `https://<finance-mcp-url>/mcp`

Then verify through gateway:

```powershell
$token = "<ACCESS_TOKEN>"
$gw = "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
$body = @{ jsonrpc = "2.0"; id = "tools-1"; method = "tools/list" } | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method POST -Uri $gw -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $body
```

Expect to see finance tools (possibly prefixed like `finance-mcp___spend_analytics_v1`).

## 4.4 Deploy/update Agent runtime

Use repo deploy helper (recommended):

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
$env:DEPLOY_BACKEND_API_BASE = "https://<reachable-backend-url>"
$env:DEPLOY_AGENTCORE_GATEWAY_ENDPOINT = "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
$env:DEPLOY_AWS_REGION = "us-east-1"
$env:DEPLOY_BEDROCK_MODEL_ID = "amazon.nova-pro-v1:0"
$env:DEPLOY_RESPONSE_MODE = "llm_enforce"
python .\deploy_agent.py
```

Important:
- `DEPLOY_BACKEND_API_BASE` is mandatory in deploy helper and cannot be localhost unless bypass flag is explicitly used.
- endpoint must be `/mcp`.

## 4.5 Run backend locally

Set minimum `backend/.env` for AWS runtime path:
- `AGENTCORE_RUNTIME_ARN=<runtime-arn>`
- `AWS_REGION=us-east-1`
- `COGNITO_USER_POOL_ID=<pool-id>`
- `COGNITO_CLIENT_ID=<client-id>`
- `DEV_BYPASS_AUTH=false`

Run:

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

## 4.6 Run frontend locally

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\frontend
npm install
npm run dev
```

Set in `frontend/.env.local`:
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8010`

## 4.7 Generate Cognito token for testing

Prepare in `agent/.env`:
- `COGNITO_CLIENT_ID`
- `COGNITO_USERNAME`
- `COGNITO_PASSWORD`
- optional `COGNITO_CLIENT_SECRET`
- optional `AWS_REGION`

Generate token:

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\agent
python genToken.py
```

## 4.8 E2E smoke test from backend stream endpoint

```powershell
curl.exe -N -X POST "http://127.0.0.1:8010/chat/stream" `
  -H "Authorization: Bearer <ACCESS_TOKEN>" `
  -H "Content-Type: application/json" `
  -d "{\"prompt\":\"Tom tat chi tieu 30 ngay qua cua toi\"}"
```

Expected stream lines include:
- advisory answer text
- `RuntimeSource: aws_runtime`
- `Trace: ...`
- `Tools: ...`
- `Disclaimer: ...`

## 5) What is not available anymore (to avoid confusion)

These are referenced in docs but missing in repo:
- `run_qa_tests.py`
- `verify_gateway_tools.py`
- `src/aws-finance-mcp-server/scripts/run_gateway_finance_smoke.ps1`
- `backend/scripts/run_chat_stream_smoke.ps1`

Existing smoke script in repo:
- `src/aws-finance-mcp-server/scripts/run_finance_mcp_smoke.ps1`

## 6) Recommended cleanup next

1. Keep this file as the only setup source.
2. Replace setup sections in root `README.md` with a short link to this file.
3. Add missing worker env keys to `workers/.env.example`:
   - `FINANCE_MCP_URL`
   - `FINANCE_MCP_AUTH_TOKEN`
   - `WORKER_HTTP_TIMEOUT_SECONDS`
