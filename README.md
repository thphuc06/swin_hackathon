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

Note: When the agent is deployed to AWS Runtime, it cannot call your local backend.
This MVP returns **mock data** when `BACKEND_API_BASE` is localhost.

### 4) MCP server (optional local)

See `src/aws-kb-retrieval-server/README.md` for local run and Docker instructions.

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
