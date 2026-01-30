# Jars Fintech Banking Simulator + AgentCore Advisory (MVP)

Minimal AWS-first MVP for a fintech advisory demo: Tier1 insights + Tier2 advisory on top of Amazon Bedrock AgentCore Runtime + Gateway + Policy + Memory + Observability.

## Architecture (MVP)

- **Frontend**: Next.js + Tailwind (minimal UI)
- **Backend**: FastAPI BFF (REST)
- **Agent**: LangGraph orchestrator running on AgentCore Runtime
- **Tier1 pipeline**: EventBridge -> (optional SQS) -> workers (Lambda/ECS)
- **RAG**: Knowledge Bases for Amazon Bedrock (citations)
- **Safety**: Bedrock Guardrails (input/output + PII masking + prompt attack)
- **Auth**: Cognito User Pool JWT (AgentCore Identity recommended for inbound JWT)

## Repo layout

```
/frontend
/backend
/agent
/workers
/kb
/iac
```

## Quick Start (Local)

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

Note: When the agent is deployed to AWS Runtime, it cannot call your local backend.
This MVP returns **mock data** when `BACKEND_API_BASE` is localhost.

## Deploy Agent to AgentCore Runtime (Starter Toolkit pattern)

1) Install packages
```bash
pip install bedrock-agentcore bedrock-agentcore-starter-toolkit
```

2) Configure
```bash
cd agent
agentcore configure -e main.py
```

3) Deploy
```bash
agentcore deploy
```

4) Invoke (JWT required)
```bash
# Use Cognito access token in Authorization header
```

If `AGENTCORE_RUNTIME_ARN` is set in `backend/.env`, the backend calls AWS Runtime.
Use **AccessToken** (token_use=access) when AgentCore is configured with `allowedClients`.

## Gateway + Policy (MVP skeleton)

- Use AgentCore Gateway to expose MCP tools (SQL views, KB retrieve, audit write, code interpreter).
- Attach Policy Engine with Cedar to enforce intent + scope constraints.

## Knowledge Base (RAG)

- Use `kb/` docs as sample corpus.
- Ingest into Knowledge Bases for Amazon Bedrock to enable citations.

## Env files

Each module has its own `.env.example` with required variables.
Token helper: `todo_cognito_token.md` and `agent/genToken.py` (uses env vars).

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
