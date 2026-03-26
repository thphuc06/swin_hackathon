# Specialist Agent MCP Server

This service exposes specialist agents as MCP tools:

- run_planner_agent_v1
- run_stock_agent_v1

It is intentionally thin and validates the canonical specialist envelope, enforces auth, runs planner in-process, and exposes stock through a local placeholder by default or an optional external stock HTTP endpoint when explicitly enabled.

## Endpoints

- GET /health
- GET /mcp (health hint)
- POST /mcp (JSON-RPC)

## Local run

```powershell
cd src/aws-specialist-agent-mcp-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DEV_BYPASS_AUTH="true"
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Docker build and run

Build from the service directory context so the image contains the specialist runtime only:

```powershell
docker build -t jars/specialist-agent-mcp src/aws-specialist-agent-mcp-server
```

The default image includes the full core runtime for the new architecture:

- `app/`
- `schemas/`
- `planner_agent/`
- `stock/`

Run locally:

```powershell
docker run --rm -p 8080:8080 `
  -e AWS_REGION=us-east-1 `
  -e DEV_BYPASS_AUTH=true `
  -e BEDROCK_MODEL_ID=<bedrock-model-id> `
  -e PLANNER_EXECUTION_MODE=auto `
  -e SUPABASE_URL=https://<project>.supabase.co `
  -e SUPABASE_SERVICE_ROLE_KEY=<service-role-key> `
  jars/specialist-agent-mcp
```

When deploying this container to AgentCore Runtime with `serverProtocol=MCP`, set
`PORT=8000`. Local Docker runs can keep `8080`.

Optional finance-scientific extras remain opt-in because the planner can degrade gracefully when they are absent:

```powershell
docker build `
  --build-arg INSTALL_OPTIONAL_FINANCE_EXTRAS=true `
  -t jars/specialist-agent-mcp:finance-extras `
  src/aws-specialist-agent-mcp-server
```

Those extras add `numpy`, `pandas`, `statsmodels`, `u8darts`, `river`, `pyod`, and `ruptures` for richer forecast/anomaly engines. They are not required for the service to boot or for the default in-process planner path to function.

## Environment variables

Use:

- `.env.example` for source-local development defaults
- `.env.aws.example` for deployed AWS runtime reference values

## Notes

- Default architecture:
  `Frontend -> Backend -> Orchestrator -> Gateway -> specialist-agent-mcp -> in-process planner / local stock adapter`
- `run_planner_agent_v1` now executes planner code in-process from `planner_agent/`.
- Planner imports finance modules directly from `planner_agent/finance/` and does not require finance MCP in the steady-state path.
- In `staging` and `prod`, planner execution defaults to the deterministic finance core unless `PLANNER_EXECUTION_MODE=model` is explicitly set.
- `run_stock_agent_v1` defaults to the runtime-local stock placeholder used by the main architecture.
- If you need the optional external stock compatibility path, enable `STOCK_AGENT_EXTERNAL_ENABLED=true` and prefer `STOCK_AGENT_EXTERNAL_URL=https://<host>/ask`.
- The `/ask` contract expects `{ question, modelProvider, model }` and returns JSON with an `answer` field.
- Deprecated compatibility flags for stub or external planner paths are intentionally omitted from the default runtime examples and should stay out of normal staging/prod deploys.
- The container image for this service must package `planner_agent/` and `stock/` alongside `app/` and `schemas/`; otherwise deployed imports from `app.mcp` will fail.

## Manual AWS Steps

- Register or update the `specialist-agent-mcp` target in AgentCore Gateway.
- Synchronize Gateway targets after schema changes so `run_planner_agent_v1` and `run_stock_agent_v1` stay current.
- Inject runtime env vars and secrets such as `AWS_REGION`, `BEDROCK_MODEL_ID` or `PLANNER_MODEL_ID`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY`.
- Attach IAM and auth settings for Bedrock access, Runtime auth, and Gateway access as needed.
- If the service is hosted on AgentCore Runtime as an MCP server, make sure the
  container listens on `0.0.0.0:8000` by setting `PORT=8000`.

## No Longer Mandatory

- A standalone planner HTTP deployment for the default planner path.
- Finance MCP as a required dependency for planner execution.
- App Runner or any other external stock deployment for the default stock path.
