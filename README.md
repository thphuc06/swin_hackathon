# Jars Fintech Banking Simulator + AgentCore Advisory (MVP)

Minimal AWS-first fintech advisory demo built on Amazon Bedrock AgentCore Runtime + Gateway + KB RAG.

## Architecture

- **Frontend**: Next.js + Tailwind
- **Backend**: FastAPI BFF (REST + SSE)
- **Agent**: LangGraph orchestrator running on AgentCore Runtime
- **RAG**: Knowledge Bases for Bedrock via MCP tool (Gateway)
- **Safety**: Bedrock Guardrails (optional)
- **Auth**: Cognito User Pool JWT (AccessToken)

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
