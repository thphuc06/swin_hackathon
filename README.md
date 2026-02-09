# Jars Fintech Banking Simulator + AgentCore Advisory (MVP)

Minimal AWS-first fintech advisory demo built on Amazon Bedrock AgentCore Runtime + Gateway + KB RAG.

## Architecture

- **Frontend**: Next.js + Tailwind
- **Backend**: FastAPI BFF (REST + SSE)
- **Agent**: LangGraph orchestrator running on AgentCore Runtime
- **RAG**: Knowledge Bases for Bedrock via MCP tool (Gateway)
- **Safety**: Bedrock Guardrails (optional)
- **Auth**: Cognito User Pool JWT (AccessToken)

## Current runtime flow (implemented)

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
   - Always runs first for compliance.
   - May short-circuit response (`deny_execution` / `education_only`).
4. `decision_engine`:
   - Executes tool bundle from route decision (not keyword hardcode).
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

## Deploy Agent to AgentCore Runtime (Starter Toolkit)

1) Install packages
```bash
pip install bedrock-agentcore bedrock-agentcore-starter-toolkit
```

2) Configure
```bash
cd agent
agentcore configure -e main.py
```

3) Deploy with required runtime env
```bash
agentcore deploy --auto-update-on-conflict \
  --env AWS_REGION=us-east-1 \
  --env BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
  --env BACKEND_API_BASE=https://<public-backend-url> \
  --env BEDROCK_KB_ID=G6GLWTUKEL \
  --env AGENTCORE_GATEWAY_ENDPOINT=https://<gateway-id>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp \
  --env LOG_LEVEL=info
```

Optional (guardrails):
```bash
--env BEDROCK_GUARDRAIL_ID=arn:aws:bedrock:... \
--env BEDROCK_GUARDRAIL_VERSION=DRAFT
```

If your Gateway prefixes tool names, set:
```
AGENTCORE_GATEWAY_TOOL_NAME=<prefixed_tool_name>
```
The agent also auto-resolves tool names by calling `tools/list`.

4) Invoke (JWT required)
```bash
# Use Cognito AccessToken in Authorization header
```

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

## Knowledge Base (RAG)

- Use `kb/` docs as sample corpus.
- Ingest into Knowledge Bases for Amazon Bedrock to enable citations.

## Env files

Each module has its own `.env.example` with required variables.
Token helper: `todo_cognito_token.md` and `agent/genToken.py` (uses env vars).
Runtime env is **not** baked into the container; set it via `agentcore deploy --env`.

## TODO (post-hackathon scale)

- Replace in-memory store with Supabase Postgres + migrations.
- Implement EventBridge -> SQS -> worker pipeline for Tier1.
- Add Gateway MCP tool calls + Policy enforcement.
- Enable Memory summaries (no raw ledger data stored).
- Add Observability exporters (CloudWatch + OTEL).

## AWS Reference Docs

- Amazon Bedrock AgentCore Runtime: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html
- AgentCore Gateway: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- AgentCore Policy (Cedar): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html
- AgentCore Memory: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
- Bedrock Guardrails: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
- Knowledge Bases for Bedrock: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
- Cognito User Pools: https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html
