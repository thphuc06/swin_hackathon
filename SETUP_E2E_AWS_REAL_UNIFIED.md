# Setup Guide (Single Source of Truth): E2E + AWS Real

Updated: 2026-03-04  
Purpose: one setup document with explicit field mapping, so you can configure quickly without re-discovery.

## 1) Current flow in this codebase

Primary E2E path:
- `Frontend (local Next.js)` -> `Backend (local FastAPI /chat/stream)` -> `AgentCore Runtime (AWS)` -> `AgentCore Gateway` -> `Finance MCP (App Runner)` -> `Supabase`

Important behavior:
- Backend uses `AGENTCORE_RUNTIME_ARN`:
  - set -> call AWS runtime
  - empty -> fallback to local agent URL (`AGENTCORE_LOCAL_URL`)
- Agent KB in current runtime is local files under `kb/` (not mandatory to use `aws-kb-retrieval-server` for baseline E2E).

## 2) Docs mismatch note (so you do not follow stale instructions)

Root `README.md` still references removed scripts:
- `run_qa_tests.py`
- `verify_gateway_tools.py`
- `src/aws-finance-mcp-server/scripts/run_gateway_finance_smoke.ps1`
- `backend/scripts/run_chat_stream_smoke.ps1`

Current existing smoke script:
- `src/aws-finance-mcp-server/scripts/run_finance_mcp_smoke.ps1`

## 3) Field Source Catalog (where to get/create each value)

Use this catalog ID when filling env files below.

## 3.1 AWS / AgentCore fields

| ID | Field | Get/Create at | How to get |
|---|---|---|---|
| `A1` | `AWS_REGION` | Choose target AWS region first | Example: `us-east-1` |
| `A2` | `BEDROCK_MODEL_ID` | Amazon Bedrock model access | Pick enabled model ID (example: `amazon.nova-pro-v1:0`) |
| `A3` | `AGENTCORE_GATEWAY_ENDPOINT` | AgentCore Gateway console | Copy Gateway endpoint and ensure `/mcp` suffix |
| `A4` | `AGENTCORE_RUNTIME_ARN` | Agent runtime deployment | Get from deploy output or `agentcore status` |
| `A5` | `DEPLOY_BACKEND_API_BASE` / `BACKEND_API_BASE` | Your reachable backend URL for runtime | Must be cloud-reachable from runtime (not localhost unless bypass check) |

## 3.2 Cognito fields

| ID | Field | Get/Create at | How to get |
|---|---|---|---|
| `C1` | `COGNITO_USER_POOL_ID` | Cognito User Pool | Copy User Pool ID |
| `C2` | `COGNITO_CLIENT_ID` | Cognito App Client | Copy App Client ID |
| `C3` | `COGNITO_CLIENT_SECRET` | Cognito App Client (if secret enabled) | Copy client secret; optional in some flows |
| `C4` | `COGNITO_USERNAME` | User Pool user | Create service user (or test user) |
| `C5` | `COGNITO_PASSWORD` | User Pool user credential | Set service user password |
| `C6` | `ACCESS_TOKEN` (for test calls) | Generated from `agent/genToken.py` | Run script and use `AccessToken` output |

## 3.3 Supabase / Finance MCP fields

| ID | Field | Get/Create at | How to get |
|---|---|---|---|
| `S1` | `SUPABASE_URL` | Supabase project settings | Project URL |
| `S2` | `SUPABASE_SERVICE_ROLE_KEY` | Supabase API keys | Service role key (secret) |
| `S3` | `FINANCE_MCP_URL` | App Runner service URL | `https://<service-url>/mcp` |

## 3.4 Local/manual config fields

| ID | Field | Set at | Value guidance |
|---|---|---|---|
| `L1` | `NEXT_PUBLIC_API_BASE_URL` | `frontend/.env.local` | `http://localhost:8010` for local frontend |
| `M1` | `DEV_BYPASS_AUTH` (backend) | `backend/.env` | `false` for real auth test |
| `M2` | `DEV_BYPASS_AUTH` (finance-mcp) | finance-mcp env | `true` for demo bypass, `false` for hardened mode |
| `M3` | `USE_LOCAL_MOCKS` | agent runtime env | `false` for AWS-real E2E |
| `M4` | `WORKER_HTTP_TIMEOUT_SECONDS` | workers env | start with `15` |
| `M5` | `FINANCE_MCP_AUTH_TOKEN` | workers env | usually `Bearer <C6>` |
| `M6` | `FINANCE_MCP_FIXED_USER_ID` | finance-mcp env | demo-only: fixed Supabase `user_id` when Cognito `sub` does not match seeded data |

## 4) File Mapping Matrix (exactly what to put where)

This is the matching section for quick config.

## 4.1 `backend/.env` (AWS runtime path)

| Field in file | Fill from ID |
|---|---|
| `AGENTCORE_RUNTIME_ARN` | `A4` |
| `AWS_REGION` | `A1` |
| `COGNITO_USER_POOL_ID` | `C1` |
| `COGNITO_CLIENT_ID` | `C2` |
| `DEV_BYPASS_AUTH` | `M1` |

Optional:
- `AGENTCORE_LOCAL_URL` only when runtime ARN is empty.

## 4.2 `agent/.env` (token generation and local defaults)

| Field in file | Fill from ID |
|---|---|
| `AWS_REGION` | `A1` |
| `COGNITO_CLIENT_ID` | `C2` |
| `COGNITO_CLIENT_SECRET` (optional) | `C3` |
| `COGNITO_USERNAME` | `C4` |
| `COGNITO_PASSWORD` | `C5` |

For AWS-real runtime behavior:

| Field in deploy/runtime | Fill from ID |
|---|---|
| `AGENTCORE_GATEWAY_ENDPOINT` | `A3` |
| `BEDROCK_MODEL_ID` | `A2` |
| `BACKEND_API_BASE` | `A5` |
| `USE_LOCAL_MOCKS` | `M3` |

## 4.3 Deploy script env (`deploy_agent.py`)

| Field to export before deploy | Fill from ID |
|---|---|
| `DEPLOY_BACKEND_API_BASE` | `A5` |
| `DEPLOY_AGENTCORE_GATEWAY_ENDPOINT` | `A3` |
| `DEPLOY_AWS_REGION` | `A1` |
| `DEPLOY_BEDROCK_MODEL_ID` | `A2` |

## 4.4 `src/aws-finance-mcp-server/.env` (or App Runner env)

| Field in file | Fill from ID |
|---|---|
| `SUPABASE_URL` | `S1` |
| `SUPABASE_SERVICE_ROLE_KEY` | `S2` |
| `DEV_BYPASS_AUTH` | `M2` |
| `COGNITO_USER_POOL_ID` (required when bypass=false) | `C1` |
| `COGNITO_CLIENT_ID` (required when bypass=false) | `C2` |
| `AWS_REGION` (required when bypass=false) | `A1` |
| `FINANCE_MCP_FIXED_USER_ID` (optional demo override) | `M6` |

Notes:
- Set `FINANCE_MCP_FIXED_USER_ID=<seed_user_id>` only for demo auth when your JWT `sub` does not match the seeded Supabase `user_id`.
- Remove `FINANCE_MCP_FIXED_USER_ID` after you provision real user mapping and before hardened production rollout.

## 4.5 `frontend/.env.local`

| Field in file | Fill from ID |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `L1` |

## 4.6 `workers/.env` (if workers enabled)

| Field in file | Fill from ID |
|---|---|
| `FINANCE_MCP_URL` | `S3` |
| `FINANCE_MCP_AUTH_TOKEN` | `M5` |
| `WORKER_HTTP_TIMEOUT_SECONDS` | `M4` |

Note:
- These worker fields are used in code but currently missing in `workers/.env.example`.

## 5) Minimal setup runbook (AWS real)

## 5.1 Prerequisites
- Python 3.11
- Node.js 18+
- AWS CLI configured
- `agentcore` CLI installed

## 5.2 Deploy Finance MCP
1. Fill finance-mcp env using section `4.4`.
2. Deploy to App Runner.
3. Verify:

```powershell
Invoke-RestMethod -Method GET -Uri "https://<finance-mcp-url>/health"
$body = @{ jsonrpc = "2.0"; id = "1"; method = "tools/list" } | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method POST -Uri "https://<finance-mcp-url>/mcp" -ContentType "application/json" -Body $body
```

## 5.3 Configure and verify Gateway
- Target URL must be `https://<finance-mcp-url>/mcp`.

```powershell
$token = "<ACCESS_TOKEN>"
$gw = "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
$body = @{ jsonrpc = "2.0"; id = "tools-1"; method = "tools/list" } | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method POST -Uri $gw -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $body
```

## 5.4 Deploy/update agent runtime

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
$env:DEPLOY_BACKEND_API_BASE = "https://<reachable-backend-url>"
$env:DEPLOY_AGENTCORE_GATEWAY_ENDPOINT = "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
$env:DEPLOY_AWS_REGION = "us-east-1"
$env:DEPLOY_BEDROCK_MODEL_ID = "amazon.nova-pro-v1:0"
python .\deploy_agent.py
```

## 5.5 Run backend local

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

## 5.6 Run frontend local

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\frontend
npm install
npm run dev
```

## 5.7 Generate token for testing

```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\agent
python genToken.py
```

Use `AccessToken` output as `C6`.

## 5.8 E2E smoke via backend stream

```powershell
curl.exe -N -X POST "http://127.0.0.1:8010/chat/stream" `
  -H "Authorization: Bearer <ACCESS_TOKEN>" `
  -H "Content-Type: application/json" `
  -d "{\"prompt\":\"Tom tat chi tieu 30 ngay qua cua toi\"}"
```

Expected SSE lines:
- advisory answer text
- `RuntimeSource: aws_runtime`
- `Trace: ...`
- `Tools: ...`
- `Disclaimer: ...`

## 6) Active fields vs legacy fields (to avoid confusion)

Clarification:
- AgentCore Gateway is actively used by the agent runtime (`agent/tools.py` via `AGENTCORE_GATEWAY_ENDPOINT`).
- The list below only means "not used by active backend routes" (`backend/app/routes/*`), not "unused by the whole system".

Fields present in env files but currently not used by active backend routes:
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

Fields present in agent env but not used in current runtime path:
- `AGENTCORE_RUNTIME_ID`
- `AGENTCORE_MEMORY_ID`
- `AGENTCORE_JWT_ISSUER_DISCOVERY_URL`
- `AGENTCORE_ALLOWED_AUDIENCE`
- `AGENTCORE_REQUIRED_SCOPES`
- `BEDROCK_KB_ID`
- `BEDROCK_KB_DATASOURCE_ID`
