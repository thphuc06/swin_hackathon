# Jars Fintech Banking Simulator + AgentCore Advisory (MVP)

Minimal AWS-first fintech advisory demo built on Amazon Bedrock AgentCore Runtime + Gateway + KB RAG.

## 🚀 Quick Start (Test Agent in 2 Minutes)

```powershell
# 1. Generate service token
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\agent
python genToken.py 2>&1 | Select-String "^AccessToken:" | % { ($_ -replace "^AccessToken:\s*","").Trim() } | Set-Variable token

# 2. Test agent (expect 7-17s response)
agentcore invoke --bearer-token $token '{"prompt": "Tóm tắt chi tiêu 30 ngày qua của tôi", "user_id": "demo-user", "authorization": "Bearer '"$token"'"}'

> Lưu ý quan trọng: khi invoke trực tiếp bằng `agentcore invoke`, cần truyền thêm `authorization` trong payload để runtime gọi Gateway không bị `401/424`.

# 3. Run full test suite (12 cases, ~15-20 min)
cd ..
python .\run_qa_tests.py --base-url http://127.0.0.1:8010 --token $token
```

**Expected:** ✅ Sub-20s responses, no timeout errors, Gateway authentication working

## ⚡ Current Status (Feb 2026)

**Agent Performance: OPTIMIZED ✅**
- Response time: **7-17s** (was 26-32s) = **40-77% improvement**
- Connection pooling implemented (HTTPAdapter with 10 connections, 20 max pool size)
- Timeout configuration optimized (Bedrock: 120s, Tool execution: 120s)
- Gateway authentication fixed (service-to-service token)
- Agent ARN: `arn:aws:bedrock-agentcore:us-east-1:021862553142:runtime/demoAgentCore-apmuG59e4V`
- Latest image: `021862553142.dkr.ecr.us-east-1.amazonaws.com/bedrock-agentcore-demoagentcore:20260210-043325-959`
- Documentation: See [AGENT_OPTIMIZATION_CHANGES.md](AGENT_OPTIMIZATION_CHANGES.md) for detailed optimization report

**Test Results:**
- Simple queries: ~7s
- Complex queries with clarification: ~17s
- All 9 financial tools accessible via MCP Gateway
- No timeout errors with optimized configuration

## Architecture

**Production Flow (Optimized):**
```
Frontend (Next.js) 
  → Backend (FastAPI) 
    → AgentCore Runtime (LangGraph) 
      → MCP Gateway (https://jars-gw-afejhtqoqd...com/mcp)
        → MCP Financial Tools Server (App Runner)
          → Supabase (Data Store)
```

**Key Components:**
- **Frontend**: Next.js + Tailwind
- **Backend**: FastAPI BFF (REST + SSE)
- **Agent**: LangGraph orchestrator running on AgentCore Runtime (OPTIMIZED)
- **MCP Gateway**: Routes to MCP Financial Tools (9 tools available)
- **RAG**: Knowledge Bases for Bedrock via MCP tool (Gateway)
- **Safety**: Bedrock Guardrails (optional)
- **Auth**: Cognito User Pool JWT (AccessToken for service-to-service)

## Current runtime flow (implemented)

**Architecture Note:** Agent calls **MCP Gateway** (not backend API) for all tool execution. Gateway routes to MCP Financial Tools Server (App Runner) which queries Supabase.

Runtime path in `agent/graph.py` now uses semantic routing + grounded synthesis:

1. `encoding_gate`:
   - Deterministic UTF-8 gate: `detect -> repair -> fail_fast`.
   - Normalize prompt by Unicode form (`NFC` default).
   - On `fail_fast`, short-circuit before router/tools and return safe retry message.
2. `intent_router`:
   - LLM structured extraction (`intent_extraction_v1`) via Bedrock.
   - Deterministic planner policy (`router/policy.py`) decides:
     - intent/tool bundle
     - clarify or execute
     - fallback markers
3. `suitability_guard`:
   - Always runs first for compliance (via Gateway → MCP Financial Tools).
   - May short-circuit response (`deny_execution` / `education_only`).
4. `decision_engine`:
   - Executes tool bundle from route decision (via Gateway → MCP Server).
   - Uses persistent HTTP sessions with connection pooling (optimized).
5. `reasoning`:
   - `build_evidence_pack` (facts from tool outputs)
   - `build_advisory_context` (deterministic insights + action candidates)
   - LLM synthesis (`answer_plan_v2`) with strict JSON schema
   - grounding/compliance validator
   - renderer (fact placeholder binding)
6. `memory_update`:
   - Writes `routing_meta`, `response_meta`, `evidence_pack`, `advisory_context`, `answer_plan_v2` to audit payload.

### Response modes

- `RESPONSE_MODE=template`: legacy template rendering (emergency path).
- `RESPONSE_MODE=llm_shadow`: run LLM pipeline in shadow, return legacy body.
- `RESPONSE_MODE=llm_enforce`: return LLM-grounded response.

In `llm_enforce`, if synthesis/grounding fails, fallback is `facts_only_compact_renderer` (not legacy intent template).

### Router + response env knobs

- `ROUTER_MODE=rule|semantic_shadow|semantic_enforce`
- `ROUTER_POLICY_VERSION=v1`
- `ROUTER_INTENT_CONF_MIN=0.70`
- `ROUTER_TOP2_GAP_MIN=0.15`
- `ROUTER_SCENARIO_CONF_MIN=0.75`
- `ROUTER_MAX_CLARIFY_QUESTIONS=2`
- `RESPONSE_PROMPT_VERSION=answer_synth_v2`
- `RESPONSE_SCHEMA_VERSION=answer_plan_v2`
- `RESPONSE_POLICY_VERSION=advice_policy_v1`
- `RESPONSE_MAX_RETRIES=1`
- `ENCODING_GATE_ENABLED=true`
- `ENCODING_REPAIR_ENABLED=true`
- `ENCODING_REPAIR_SCORE_MIN=0.12`
- `ENCODING_FAILFAST_SCORE_MIN=0.45`
- `ENCODING_REPAIR_MIN_DELTA=0.10`
- `ENCODING_NORMALIZATION_FORM=NFC`

Note: `ROUTER_MODE=rule` is kept for compatibility but runtime currently forces semantic path for safety rollout.

## Repo layout

```
/frontend
/backend
/agent
/workers
/kb
/iac
/src/aws-kb-retrieval-server
/src/aws-finance-mcp-server
```

## Local quick start

### 1) Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8010
```

Tip: set `DEV_BYPASS_AUTH=true` in `backend/.env` for local demo without Cognito.
If you're on Python 3.14 and installation fails, use Python 3.11 for the backend.

### 2) Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
```

Set API base (if not already):
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8010
```

```bash
npm run dev
```

Open: http://localhost:3000

### 3) Agent (local run, not runtime)

```bash
cd agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

The agent runs on port 8080 (AgentCoreApp default).

Local behavior is controlled by `USE_LOCAL_MOCKS` in `agent/.env`:
- `USE_LOCAL_MOCKS=true` with `BACKEND_API_BASE=http://localhost:8010` -> return mock financial data for offline demo.
- `USE_LOCAL_MOCKS=false` with `BACKEND_API_BASE=http://localhost:8010` -> call local backend APIs for real local E2E tests.

When deployed to AWS Runtime, do not use localhost for `BACKEND_API_BASE`.

### 4) MCP servers (optional local)

KB MCP:
- See `src/aws-kb-retrieval-server/README.md` for local run and Docker instructions.

Finance MCP:

```bash
cd src/aws-finance-mcp-server
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8020
```

Quick smoke check:

```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\src\aws-finance-mcp-server
$seed = (Get-Content ..\..\backend\tmp\seed_manifest_single_user.json | ConvertFrom-Json).seed_user_id
.\scripts\run_finance_mcp_smoke.ps1 -BaseUrl "http://127.0.0.1:8020" -SeedUserId $seed
```

Gateway smoke check (prefixed tool names + auth):

```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\src\aws-finance-mcp-server
$seed = (Get-Content ..\..\backend\tmp\seed_manifest_single_user.json | ConvertFrom-Json).seed_user_id
.\scripts\run_gateway_finance_smoke.ps1 `
  -GatewayEndpoint "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com" `
  -SeedUserId $seed `
  -AuthToken "<cognito-access-token>"
```

## 🧪 Testing the Agent (RECOMMENDED METHOD)

### Prerequisites
1. Agent deployed to AWS AgentCore Runtime
2. MCP Gateway running with financial tools target
3. Cognito credentials configured in `agent/.env`

### Quick Test (5 minutes)

**Step 1: Generate Service Token**
```powershell
cd agent
python genToken.py
# Copy the AccessToken from output (starts with eyJ...)
```

**Step 2: Test Agent with Vietnamese Prompt**
```powershell
# Generate token and invoke in one command
python genToken.py 2>&1 | Select-String "^AccessToken:" | % { ($_ -replace "^AccessToken:\s*","").Trim() } | Set-Variable token

agentcore invoke --bearer-token $token '{"prompt": "Tóm tắt chi tiêu 30 ngày qua của tôi", "user_id": "demo-user", "authorization": "Bearer '"$token"'"}'
```

**Expected Results:**
- Response time: **< 20s** (7-17s typical)
- Agent returns clarifying question OR spending summary
- No `401 Unauthorized` or `424 Failed Dependency` errors
- CloudWatch logs show "Tool registry initialized" (not "DEFAULT_USER_TOKEN not set")

**Step 3: Simple Query Test**
```powershell
agentcore invoke --bearer-token $token '{"prompt": "Chi tiêu của tôi tháng này là bao nhiêu?", "user_id": "demo-user", "authorization": "Bearer '"$token"'"}'
```
Expected: **< 10s** response time

### Comprehensive Test Suite

```powershell
# Run all 12 test cases (15-20 minutes)
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
python agent/genToken.py 2>&1 | Select-String "^AccessToken:" | % { ($_ -replace "^AccessToken:\s*","").Trim() } | Set-Variable token
python .\run_qa_tests.py --base-url http://127.0.0.1:8010 --token $token
```

Test cases cover:
- Summary queries (spend analytics)
- Risk assessment
- Planning/goal feasibility
- What-if scenarios
- Out-of-scope handling

**Verification Checklist (Verified 2026-02-10):**
-   [x] **Gateway Integration**: Validated via `verify_gateway_tools.py`. The Gateway endpoint is accessible and correctly routes requests.
-   [x] **Tool Selection (Routing)**: Validated via `run_qa_tests.py`. The Agent correctly selects `spend_analytics_v1` for summary requests and `recurring_cashflow_detect_v1` for expense optimization.
-   [x] **Reasoning Logic**: Validated via `run_qa_tests.py` (CASE_01). The Agent incorporates tool outputs (e.g., specific spending amounts) into natural language responses without hardcoding.
-   [x] **Backend Connectivity**: Validated for `spend_analytics_v1`. Requires valid `user_id` to function.

**Verification Scripts:**
-   `verify_gateway_tools.py`: Tests direct connectivity to the Gateway and specific tool execution.
-   `run_qa_tests.py`: Runs a full conversational test suite against the deployed agent. Ensure `TEST_USER_ID` is set correctly in the script.ired
- Fix: Redeploy agent with fresh service token (see Deploy section below)

### Local Backend + `/chat/stream` QA (avoid common confusion)

Use this flow right after each deploy to validate runtime behavior from local backend.

1) Ensure backend Cognito settings match agent token issuer
```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
Get-Content .\agent\.env   | Select-String '^(AWS_REGION|COGNITO_USER_POOL_ID|COGNITO_CLIENT_ID)='
Get-Content .\backend\.env | Select-String '^(AWS_REGION|COGNITO_USER_POOL_ID|COGNITO_CLIENT_ID|DEV_BYPASS_AUTH)='
```

2) Free port 8010 and restart backend with explicit env
```powershell
# Kill existing listener on 8010 (if any)
Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue | % { Stop-Process -Id $_.OwningProcess -Force }

cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
$env:AWS_REGION = "us-east-1"
$env:DEV_BYPASS_AUTH = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

3) In another terminal, generate AccessToken and run full QA
```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
$token = (python .\agent\genToken.py 2>&1 | Select-String '^AccessToken:' | % { ($_ -replace '^AccessToken:\s*','').Trim() })
python .\run_qa_tests.py --base-url http://127.0.0.1:8010 --token $token
```

4) Check outputs
```powershell
Get-Content .\results.txt
Get-Content .\test_results_runtime_stream.txt -TotalCount 120
```

Expected:
- `runtime=aws_runtime` when backend is configured with `AGENTCORE_RUNTIME_ARN`
- `CASE_05` has `recurring_cashflow_detect_v1`
- `CASE_06` has `anomaly_signals_v1` and no suitability refusal
- `CASE_08` is `suitability_refusal`
- `CASE_09` is planning and has citations

If you get `401 {"detail":"Unknown key"}`:
- Restart backend after env changes (JWKS is cached in-process).
- Ensure backend is started with `AWS_REGION=us-east-1` (wrong region causes wrong JWKS URL).

**Issue: 424 Failed Dependency**  
- Cause: Gateway authentication failed or MCP server down
- Fix: Verify Gateway endpoint includes `/mcp` path, check MCP server status

**Issue: Timeout after 60s**
- Cause: Old deployment without optimizations
- Fix: Redeploy with optimized timeouts (see Deploy section)

**Check CloudWatch Logs:**
```powershell
aws logs tail /aws/bedrock-agentcore/runtimes/demoAgentCore-apmuG59e4V --follow
```

## 🚀 Deploy Agent to AgentCore Runtime (Starter Toolkit)

### Prerequisites
```bash
pip install bedrock-agentcore bedrock-agentcore-starter-toolkit
```

### Standard Deployment (with optimizations)

**Step 1: Generate Service Token**
```powershell
cd agent
python genToken.py 2>&1 | Select-String "^AccessToken:" | % { ($_ -replace "^AccessToken:\s*","").Trim() } | Set-Variable serviceToken
```

**Step 2: Deploy with Environment Variables**
```bash
cd agent
agentcore deploy --auto-update-on-conflict \
  --env AGENTCORE_GATEWAY_ENDPOINT=https://jars-gw-afejhtqoqd.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp \
  --env DEFAULT_USER_TOKEN=$serviceToken \
  --env AWS_REGION=us-east-1 \
  --env BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
  --env BEDROCK_GUARDRAIL_ID=arn:aws:bedrock:us-east-1:021862553142:guardrail-profile/us.guardrail.v1:0 \
  --env BEDROCK_GUARDRAIL_VERSION=DRAFT \
  --env BEDROCK_KB_ID=G6GLWTUKEL \
  --env BEDROCK_KB_DATASOURCE_ID=WTYVWINQP9 \
  --env BEDROCK_READ_TIMEOUT=120 \
  --env TOOL_EXECUTION_TIMEOUT=120 \
  --env GATEWAY_TIMEOUT_SECONDS=25 \
  --env ROUTER_MODE=semantic_enforce \
  --env RESPONSE_MODE=llm_enforce \
  --env LOG_LEVEL=info
```

**PowerShell (Windows):**
```powershell
cd agent
python genToken.py 2>&1 | Select-String "^AccessToken:" | % { ($_ -replace "^AccessToken:\s*","").Trim() } | Set-Variable serviceToken

agentcore deploy --auto-update-on-conflict `
  --env AGENTCORE_GATEWAY_ENDPOINT=https://jars-gw-afejhtqoqd.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp `
  --env DEFAULT_USER_TOKEN=$serviceToken `
  --env BEDROCK_READ_TIMEOUT=120 `
  --env TOOL_EXECUTION_TIMEOUT=120 `
  --env GATEWAY_TIMEOUT_SECONDS=25 `
  --env LOG_LEVEL=info
```

**Critical Environment Variables:**
- `AGENTCORE_GATEWAY_ENDPOINT`: **MUST include `/mcp` path** (base URL returns 404)
- `DEFAULT_USER_TOKEN`: Service-to-service authentication token from `genToken.py`
- `BEDROCK_READ_TIMEOUT=120`: Increased from 60s for Vietnamese 900-token responses
- `TOOL_EXECUTION_TIMEOUT=120`: Increased from 90s to prevent premature failures
- `GATEWAY_TIMEOUT_SECONDS=25`: Per-request timeout for Gateway calls

**Optional Configuration:**
```bash
# HTTP Connection Pooling (already configured in code)
--env HTTP_POOL_CONNECTIONS=10 \
--env HTTP_POOL_MAXSIZE=20 \

# Router fine-tuning
--env ROUTER_INTENT_CONF_MIN=0.70 \
--env ROUTER_MAX_CLARIFY_QUESTIONS=2 \

# Response customization
--env RESPONSE_PROMPT_VERSION=answer_synth_v2 \
--env RESPONSE_MAX_RETRIES=1
```

### Verify Deployment

```powershell
# Check agent status
agentcore status

# Test immediately after deploy
python genToken.py 2>&1 | Select-String "^AccessToken:" | % { ($_ -replace "^AccessToken:\s*","").Trim() } | Set-Variable token
agentcore invoke --bearer-token $token '{"prompt": "Hello test", "user_id": "demo-user", "authorization": "Bearer '"$token"'"}'
```

**Expected Build Time:** 30-40 seconds  
**Expected Response Time:** 7-17s (depending on query complexity)

If `AGENTCORE_RUNTIME_ARN` is set in `backend/.env`, the backend calls AWS Runtime.
Use **AccessToken** (token_use=access) when AgentCore is configured with `allowedClients`.

## Demo-first E2E (Frontend local -> Backend local -> Runtime -> Gateway -> MCP)

1) Keep finance MCP in demo mode (temporary):
- App Runner env: `DEV_BYPASS_AUTH=true`
- Gateway target `finance-mcp`: outbound auth `No authorization`

2) Backend local env:
- `AGENTCORE_RUNTIME_ARN=<runtime-arn>`
- `COGNITO_USER_POOL_ID=<pool-id>`
- `COGNITO_CLIENT_ID=<client-id>`
- `AWS_REGION=us-east-1`
- `DEV_BYPASS_AUTH=false`

3) Run backend local:
```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

4) Smoke `/chat/stream`:
```powershell
cd backend
.\scripts\run_chat_stream_smoke.ps1 -BackendBaseUrl "http://127.0.0.1:8010" -AuthToken "<cognito-access-token>" -Prompt "Tom tat chi tieu 30 ngay"
```

5) Frontend local:
```powershell
cd frontend
npm run dev
```
Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8010`, paste AccessToken in chat page, then run prompts for summary/planning/scenario/invest.

6) After demo hardening:
- rotate exposed secrets
- set `DEV_BYPASS_AUTH=false` on finance MCP
- configure outbound auth from Gateway to finance-mcp

## Gateway + Policy notes

- Configure the Gateway target URL to the MCP server `/mcp` endpoint.
- Gateway tool names can be prefixed (for example: `target-xyz___retrieve_from_aws_kb`).
- The agent can auto-discover the tool name, or you can set `AGENTCORE_GATEWAY_TOOL_NAME`.
- Financial tools are exposed by the standalone service in `src/aws-finance-mcp-server` and should be added as a second Gateway target (for example `finance-mcp`).
- Current finance MCP tool set:
  - `spend_analytics_v1`
  - `anomaly_signals_v1`
  - `cashflow_forecast_v1`
  - `jar_allocation_suggest_v1`
  - `risk_profile_non_investment_v1`
  - `suitability_guard_v1`
  - `recurring_cashflow_detect_v1`
  - `goal_feasibility_v1`
  - `what_if_scenario_v1`

### Intent -> tool bundle policy (v1)

- `summary` -> `spend_analytics_v1`, `cashflow_forecast_v1`, `jar_allocation_suggest_v1`
- `risk` -> `spend_analytics_v1`, `anomaly_signals_v1`, `risk_profile_non_investment_v1`
- `planning` -> `spend_analytics_v1`, `cashflow_forecast_v1`, `recurring_cashflow_detect_v1`, `goal_feasibility_v1`, `jar_allocation_suggest_v1`
- `scenario` -> `what_if_scenario_v1`
- `invest` -> `suitability_guard_v1`, `risk_profile_non_investment_v1` (education-only)
- `out_of_scope` -> `suitability_guard_v1`

## 🔐 Authentication Architecture

### Service-to-Service (Agent ↔ Gateway)

**Problem:** Agent needs to authenticate to MCP Gateway, but end-user OAuth tokens don't work for service calls.

**Solution:** Use dedicated service account token via `genToken.py`

**Flow:**
1. `agent/genToken.py` generates Cognito AccessToken using `USER_PASSWORD_AUTH`
2. Token deployed as `DEFAULT_USER_TOKEN` environment variable
3. Agent uses token in `Authorization: Bearer <token>` header for Gateway calls
4. Gateway validates token against Cognito User Pool

**Token Configuration (`agent/.env`):**
```bash
COGNITO_USER_POOL_ID=us-east-1_7v1arA5wU
COGNITO_CLIENT_ID=kn881gncgsv7ku4bc5bm73uue
COGNITO_CLIENT_SECRET=<your-secret>
COGNITO_USERNAME=<service-account-username>
COGNITO_PASSWORD=<service-account-password>
```

**Generate Token:**
```powershell
cd agent
python genToken.py
# Output: AccessToken: eyJraWQiOiJr... (1071 chars)
```

**Token Lifetime:** ~1 hour (3600s)  
**Rotation:** Redeploy agent with fresh token when expired

### End-User Authentication (Frontend → Backend)

- Frontend obtains Cognito AccessToken via Amplify/Auth
- Backend validates token against User Pool
- Backend includes token in `payload["authorization"]` when calling agent
- Agent still uses `DEFAULT_USER_TOKEN` for Gateway (service-to-service)

## Knowledge Base (RAG)

- Use `kb/` docs as sample corpus.
- Ingest into Knowledge Bases for Amazon Bedrock to enable citations.

## Env files

Each module has its own `.env.example` with required variables.
Token helper: `todo_cognito_token.md` and `agent/genToken.py` (uses env vars).
Runtime env is **not** baked into the container; set it via `agentcore deploy --env`.

## 📊 Performance & Optimization

### Optimization History

**Before (Jan 2026):**
- Response time: 26-32s (frequent timeouts)
- No connection pooling (300ms+ SSL handshake per request)
- Timeout mismatches (60s Bedrock, 90s tool execution + 5s per-task conflict)
- Synchronous blocking I/O

**After (Feb 2026):**
- Response time: **7-17s** (40-77% improvement) ✅
- HTTPAdapter connection pooling (10 connections, 20 max)
- Unified timeouts (120s Bedrock, 120s tool execution)
- Retry logic with exponential backoff
- Persistent sessions per endpoint

**Optimizations Implemented:**
1. **Connection Pooling** ([agent/tools.py](agent/tools.py))
   - `_get_gateway_session()` with HTTPAdapter
   - Saves ~2.5-3.0s per request

2. **Timeout Configuration** ([agent/config.py](agent/config.py))
   - Bedrock read timeout: 60s → 120s
   - Tool execution: 90s → 120s (removed 5s per-task conflict)
   - Gateway: 25s per-request

3. **Retry Logic** ([agent/tools.py](agent/tools.py))
   - @retry decorator with exponential backoff (1s, 2s, 4s)
   - Does NOT retry 4xx errors (401/403/404)

4. **Authentication** ([agent/main.py](agent/main.py))
   - Service token via `DEFAULT_USER_TOKEN` env var
   - Fallback from `payload.get("authorization")`

**See [AGENT_OPTIMIZATION_CHANGES.md](AGENT_OPTIMIZATION_CHANGES.md) for complete details.**

## TODO (post-MVP scale)

- ✅ ~~Optimize agent performance~~ (DONE: 40-77% improvement)
- ✅ ~~Fix Gateway authentication~~ (DONE: service token approach)
- ✅ ~~Implement connection pooling~~ (DONE: HTTPAdapter with retry)
- Replace in-memory store with Supabase Postgres + migrations
- Implement EventBridge → SQS → worker pipeline for Tier1
- Enable Memory summaries (no raw ledger data stored)
- Add Observability exporters (CloudWatch + OTEL)
- Token rotation strategy for `DEFAULT_USER_TOKEN`

## AWS Reference Docs

- Amazon Bedrock AgentCore Runtime: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html
- AgentCore Gateway: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- AgentCore Policy (Cedar): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html
- AgentCore Memory: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
- Bedrock Guardrails: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
- Knowledge Bases for Bedrock: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
- Cognito User Pools: https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html
