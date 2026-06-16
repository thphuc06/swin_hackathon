# Jars Specialist Advisory Stack

This repository implements a specialist-first personal finance advisory system. The live path starts at a FastAPI backend, runs orchestration inside an AgentCore runtime, delegates specialist work through an MCP-compatible specialist runtime, and returns both conversational output and structured payloads. The current codebase supports three specialist domains: grounded personal finance planning, goal and service roadmap generation, and education-only stock analysis.

Current deployed flow:

`backend -> orchestrator runtime -> gateway -> specialist MCP -> planner/service/stock -> data and external integrations`

## Core Capabilities

- Streaming advisory chat over `POST /chat/stream` with SSE metadata, trace IDs, tool summaries, disclaimers, and structured side payloads.
- Specialist-first orchestration with explicit routing, safety checks, clarification gates, and structured response metadata.
- Grounded planner output built from deterministic finance tools and a standardized financial contract.
- Goal-roadmap generation through a dedicated service specialist that turns planner state into phases, milestones, projections, and banking-service suggestions.
- Optional stock specialist integration through an external compatibility adapter, with education-only fallback when the external path is disabled or unavailable.
- Session continuity at two layers: backend-side cached specialist context by chat session, and orchestrator-side session memory.
- AWS deployment automation for orchestrator runtime, specialist runtime, gateway synchronization, and backend ECS/Fargate rollout.

For deployment, follow [`DEPLOY.md`](./DEPLOY.md). It is the single runbook for the AgentCore workflow, ECS/Fargate backend, and frontend E2E demo.

## Repository Structure

```text
.
+-- backend/                          FastAPI entry layer and SSE proxy
+-- agent/                            Orchestrator runtime, routing, policy, KB, response synthesis
+-- src/aws-specialist-agent-mcp-server/
|                                     Streamable HTTP MCP server exposing planner, service, and stock tools
+-- tests/                            Active regression suite for current architecture
+-- ops/aws/                          AWS deploy scripts, manifests, and env templates
+-- kb/                               Local knowledge base loaded directly by the orchestrator
+-- benchmark/                        Curated benchmark input for service-related evaluation
+-- diagram/                          Architecture diagrams and diagram-generation assets
+-- workers/                          Tier1 and legacy worker prototypes, not on the current main runtime path
+-- src/aws-finance-mcp-server/       Historical standalone finance MCP service
+-- src/aws-planner-agent-service/    Historical standalone planner service
`-- iac/                              Infrastructure notes and adapter-switching references
```

Important structure notes:

- `backend/app/routes/chat.py` is the operational source of truth for request ingress and SSE response shaping.
- `agent/main.py` and `agent/strands_orchestrator/` define the active orchestration path.
- `src/aws-specialist-agent-mcp-server/` is the current specialist runtime. The older `src/aws-finance-mcp-server/` and `src/aws-planner-agent-service/` directories are still present but are not the main deployed path.

## Architecture Overview

The architecture is intentionally layered. The backend is a thin entry layer, the orchestrator is responsible for routing and composition, and specialist work is pushed into a separate MCP runtime with stable tool schemas.

```text
API Client / Operator script
    -> FastAPI backend (`backend/app/main.py`)
    -> AgentCore orchestrator runtime (`agent/main.py`)
    -> Gateway tool transport (`agent/tools.py`)
    -> Specialist MCP runtime (`src/aws-specialist-agent-mcp-server/app`)
        -> planner specialist
        -> service specialist
        -> stock specialist
    -> Supabase-backed finance data, local KB files, optional external stock service
```

### Layer boundaries

- **Backend layer**: Cognito AccessToken validation in deployed mode, runtime invocation, SSE streaming, and lightweight support endpoints.
- **Orchestrator layer**: request normalization, safety, routing, specialist selection, response synthesis, and session memory.
- **Specialist layer**: planner, service, and stock tools exposed over streamable HTTP MCP with JSON schema validation.
- **Data and policy layer**: Supabase-backed finance modules, local KB loading from `kb/`, and policy enforcement through auth, routing, and allow lists.

## End-to-End Runtime Flow

### Deployed API flow

1. An API client or operator script sends `POST /chat/stream` to the backend.
2. The backend validates the bearer token as a Cognito **AccessToken**. ID tokens are explicitly rejected.
3. The backend creates or reuses trace and session identifiers, and attaches any cached planner or stock context for the same chat session.
4. The backend invokes the deployed AgentCore runtime ARN and forwards the normalized request envelope.
5. The orchestrator intake node normalizes the prompt, loads session memory, and prepares routing state.
6. The safety node applies suitability policy. Non-investment requests are allowed, educational stock questions are allowed with constraints, and recommendation-style investment requests are refused.
7. The routing node performs semantic extraction and policy-aware intent resolution.
8. The delegation node selects a specialist from `agent/subagents/agent_catalog.v1.json`.
9. The tool invocation node calls the selected specialist through the MCP gateway path.
10. The aggregation and response nodes turn specialist output into user-facing markdown while preserving structured specialist payloads in response metadata.
11. The backend streams SSE back to the caller and emits side-channel payloads such as `ServiceEnvelopePayload` and `RoadmapPayload`.

### Local harness flow

The local stack mirrors the deployed shape, but the runtime boundary is local rather than AWS-hosted:

1. API Client calls the backend at `http://127.0.0.1:8010`.
2. Backend forwards to `AGENTCORE_LOCAL_URL`, which points to the local orchestrator harness.
3. The local orchestrator uses `AGENTCORE_GATEWAY_ENDPOINT=http://127.0.0.1:8080/mcp`, so the specialist runtime is called directly over MCP without a managed AWS gateway.
4. Auth bypass is supported only when `APP_ENV` is `local` or `demo` and the relevant bypass flags are enabled.

### Streaming contract and side payloads

The backend SSE stream is more than plain assistant text. An API client can parse metadata lines such as:

- `Trace:`
- `Tools:`
- `RuntimeSource:`
- `ResponseMode:`
- `ResponseFallback:`
- `ResponseReasonCodes:`
- `Citations:`
- `Disclaimer:`
- `ServiceEnvelopePayload:`
- `RoadmapPayload:`

This is designed so external UIs can render both a conversation and structured financial or roadmap widgets from a single stream.

## Internal Components Deep Dive

### Backend API (`backend/`)

**Role**

- Thin entry layer and SSE proxy.

**When it is called**

- For every chat prompt and for supporting goal, risk-profile, notifications, and audit operations.

**Inputs**

- Chat prompt, session ID, and optional bearer token.

**Outputs**

- SSE stream for chat.
- Simple JSON payloads for support endpoints.

**Key runtime behavior**

- `backend/app/main.py` wires the FastAPI app and routes.
- `backend/app/routes/chat.py` is the operational heart of the system.
- The chat route validates runtime target configuration:
  - deployed mode requires `AGENTCORE_RUNTIME_ARN`
  - local mode requires `AGENTCORE_LOCAL_URL`
- Per-session planner and stock context are cached in memory, with TTL controlled by `CHAT_SESSION_CONTEXT_TTL_SECONDS` and a default of 7200 seconds.

**Support endpoints**

- `GET /health`
- `POST /goals`
- `GET /risk-profile`
- `POST /risk-profile`
- `GET /notifications`
- `POST /notifications`
- `POST /audit`
- `GET /audit/{trace_id}`

**Caveats**

- These support endpoints use `backend/app/services/store.py`, which is an in-memory store. They are useful for local or demo flows, but they are not a durable production data plane.

### Orchestrator Runtime (`agent/`)

**Role**

- Owns routing, safety, delegation, response shaping, session memory, local KB retrieval, and gateway calls.

**When it is called**

- On every backend chat invocation.

**Inputs**

- Canonical advisory request envelope with actor, correlation, request, and routing metadata.

**Outputs**

- Final assistant response.
- Specialist outputs, tool call summaries, routing metadata, planner context, roadmap payload, disclaimer, and response metadata.

**Implementation details**

- `agent/main.py` is the runtime entrypoint.
- The default path is the Strands orchestrator graph in `agent/strands_orchestrator/`.
- `agent/strands_orchestrator/graph.py` defines these major stages:
  - intake
  - safety
  - routing
  - delegation
  - tool invocation
  - aggregation
  - response
  - memory update
- Several Strands nodes reuse legacy helpers from `agent/graph.py` and `agent/orchestrator/nodes/`, so the current system is best described as a specialist-first graph that still reuses older response and routing utilities where practical.

**Dependencies**

- Bedrock model access for semantic extraction and optional response synthesis.
- Gateway transport and local KB access.
- Cognito-aware auth settings in deployed mode.

**Failure modes and caveats**

- `USE_STRANDS_ORCHESTRATOR=false` and `ENABLE_SPECIALIST_DELEGATION=false` are blocked in deployed environments.
- The routing and response layers still contain historical compatibility code, so maintainers should treat `agent/main.py`, `agent/config.py`, `agent/core/settings.py`, and `agent/strands_orchestrator/` as the active boundaries.

### Gateway Tool Transport (`agent/tools.py`)

**Role**

- Encapsulates gateway and backend HTTP transport, connection pooling, idempotency keys, circuit breaking, MCP session initialization, and KB loading.

**When it is called**

- Whenever the orchestrator needs a specialist tool or local KB retrieval.

**Outputs**

- Normalized tool result or transport-layer errors.

**Important behaviors**

- Maintains persistent HTTP sessions for both gateway and backend calls.
- Initializes MCP sessions and reuses `mcp-session-id` when supported.
- Falls back to sessionless MCP transport when the gateway does not support sessions.
- Loads KB files from `kb/` at startup instead of relying on a managed Bedrock KB ID.

### Specialist MCP Runtime (`src/aws-specialist-agent-mcp-server/`)

**Role**

- Exposes planner, service, and stock specialist tools over streamable HTTP MCP.

**When it is called**

- Via the orchestrator gateway tool path.

**Outputs**

- Tool-specific envelopes validated against JSON schemas.

**Implementation details**

- `app/main.py` creates the FastAPI host and MCP session manager.
- `app/mcp.py` defines the tool registry and validation behavior.
- Supported tools are:
  - `run_planner_agent_v1`
  - `run_service_agent_v1`
  - `run_stock_agent_v1`
- Tool input schemas are stripped of gateway-hostile schema keys before they are exposed publicly.

**Caveats**

- The repository includes `app/auth.py` and deploy-time auth examples, but the active MCP transport in `app/mcp.py` does not currently enforce FastAPI auth dependencies to tool calls.

### Planner Specialist

**Role**: Analytics engine. Produces grounded personal-finance analysis from live Supabase data. LLM involvement is intentionally minimal — it is only used at the final step to narrate computed numbers. All arithmetic is executed by Python functions, never by the model, eliminating hallucination risk on financial figures.

**Called when**: `summary`, `risk`, `planning`, and `scenario` intents. Also invoked implicitly by the Service Specialist when finance context is missing.

**Intent-based tool policy**: The planner does not run all tools on every request. It activates only the modules relevant to the incoming intent:

| Intent | Tools activated |
| --- | --- |
| `summary` | `spend_analytics`, `cashflow_forecast`, `jar_allocation` |
| `planning` | All summary tools + `goal_feasibility`, `recurring_detect` |
| `risk` | `spend_analytics`, `anomaly_signals`, `risk_profile` |
| `scenario` | `cashflow_forecast`, `what_if_scenario` |

**Output**: `PlannerResult` containing the standardized financial contract, computed health metrics (runway months, gap amount, net cashflow), tool trace, warnings, and errors.

**Dependencies**: Supabase-backed finance functions through `planner_agent/tool_router.py`, plus optional model-backed execution controlled by `PLANNER_EXECUTION_MODE`.

---

### Service Specialist

**Role**: Autonomous master planner and Generative UI engine. Converts grounded planner state, goals, and user context into a structured roadmap contract. Unlike other specialists, the Service Specialist operates as a self-contained orchestrator: it does not wait passively for context — it actively fetches what it needs.

**Called when**: Roadmap-style planning prompts involving goal paths, purchase journeys, milestone-oriented plans, and banking service recommendations.

**Cross-agent auto-invocation**: If the incoming request lacks finance context or market sentiment, the Service Specialist automatically triggers internal calls before generating the roadmap:

- `run_planner()` — invoked **only when `user_context` is absent or insufficient**. If planner state is already present in the request (e.g. carried over from a prior orchestrator turn), this call is skipped entirely and the existing state is reused directly.
- `run_stock()` — invoked to retrieve current market sentiment (e.g. interest rate environment, macro tone). This signal influences whether the roadmap recommends aggressive goal pursuit or a defensive, debt-reduction-first strategy.

**4-Layer hallucination-proof roadmap engine**:

1. **Readiness check**: Evaluates planner signals. If runway is critically low or net debt is high, the agent redirects the user toward financial stabilization rather than drafting an aspirational roadmap.
2. **Roadmap builder**: LLM drafts structured phases and milestones grounded in the planner's computed gap amount and cashflow figures.
3. **Dynamic banking service binding**: Python queries Supabase directly to retrieve currently active banking products (cards, loans, savings accounts). The LLM is constrained to recommend only services present in this live catalog. Fabricated product names are structurally impossible.
4. **Explanation layer**: A dedicated LLM pass writes concise advisory explanations (word-budgeted, 30–50 words per item) in professional Business English, suitable for UI tooltips and recommendation cards.

**Output**: Service agent envelope with roadmap contract, explanation layer, UI-ready visualization metadata, `recommended_now` banking services (Supabase-sourced), and diagnostics.

**Dependencies**: Planner and Stock specialists (auto-invoked), Supabase banking service catalog, Bedrock model for roadmap generation and explanation.

---

### Stock Specialist

**Role**: Market radar and external API gateway. Connects to an optional external stock service and normalizes results into the repository's standard specialist envelope. Serves two distinct analysis modes:

- **Micro analysis**: Evaluates specific securities by ticker. Pulls P/E and P/B ratios and recent price action to emit a deterministic action flag: `BUY`, `HOLD`, or `AVOID`.
- **Macro analysis**: Reads broader economic signals (interest rates, currency movements, sector sentiment) to produce a market tone label (`constructive` or `cautious`). This macro tone is consumed by the Service Specialist to calibrate roadmap risk posture.

**Called when**: `invest` intent after suitability checks. Also invoked implicitly by the Service Specialist when macro context is needed for roadmap generation.

**Fallback behavior**: If the external stock path is disabled, slow, or unhealthy, the adapter returns an education-only envelope instead of failing hard. The rest of the system continues to function normally.

**Output**: Stock specialist envelope with summary, recommendations, alternatives, suitability status, market notes, citations, warnings, and errors.

**Dependencies**: External HTTP service configured through `STOCK_AGENT_EXTERNAL_*`.

## Configuration

### Environment files

| Area | Local reference | Deployed reference | Notes |
| --- | --- | --- | --- |
| Backend | `backend/.env.example` | `backend/.env.aws.example` | Entry-layer auth and runtime target |
| Orchestrator | `agent/.env.example` | `agent/.env.aws.example` | Runtime, model, gateway, and routing policy |
| Specialist | `src/aws-specialist-agent-mcp-server/.env.example` | `src/aws-specialist-agent-mcp-server/.env.aws.example` | Planner, service, stock adapter, Supabase |
| Deploy scripts | `ops/aws/deploy.env.example` | operator shell env | Used by PowerShell deploy scripts |

### Backend variables

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Explicit runtime mode: `local`, `demo`, `staging`, or `prod`. |
| `AWS_REGION` | Region used for deployed runtime invocation. |
| `DEV_BYPASS_AUTH` | Local/demo-only auth bypass for the backend. |
| `AGENTCORE_LOCAL_URL` | Local agent invocation URL, typically `http://127.0.0.1:8081/invocations`. |
| `AGENTCORE_RUNTIME_ARN` | Deployed AgentCore runtime ARN. Required in staging/prod. |
| `COGNITO_USER_POOL_ID` | Cognito access-token issuer. |
| `COGNITO_CLIENT_ID` | Primary allowed client ID. |
| `COGNITO_ALLOWED_CLIENT_IDS` | Optional allow list for multiple clients. |
| `CHAT_SESSION_CONTEXT_TTL_SECONDS` | Backend-side planner/stock session-context cache TTL. |

### Orchestrator variables

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Runtime mode and contract enforcement. |
| `BEDROCK_MODEL_ID` | Main orchestration model. |
| `AGENTCORE_GATEWAY_ENDPOINT` | MCP gateway endpoint in deployed mode, or direct local specialist MCP URL in local mode. |
| `BACKEND_API_BASE` | Backend base URL used by runtime helpers. |
| `AUTH_PROVIDER` | `jwt` for local/demo, `cognito` for staging/prod. |
| `AUTH_DEV_BYPASS` | Local/demo-only auth bypass. |
| `POLICY_ADAPTER` | `simple` or `cedar`. |
| `POLICY_ALLOWED_TOOLS` | Required allow list when `POLICY_ADAPTER=simple` in staging/prod. |
| `USE_STRANDS_ORCHESTRATOR` | Must remain enabled in deployed mode. |
| `ENABLE_SPECIALIST_DELEGATION` | Must remain enabled in deployed mode. |
| `ROUTER_MODE` | Routing mode, currently defaulting to `semantic_enforce`. |
| `RESPONSE_MODE` | Response synthesis mode, typically `llm_enforce` or `llm_shadow`. |
| `SESSION_MEMORY_ENABLED` | Enables orchestrator-side session memory. |
| `GATEWAY_TIMEOUT_SECONDS` | Runtime budget for gateway and specialist calls. |
| `STOCK_AGENT_EXTERNAL_*` | Optional compatibility settings for external stock advisory hosting. |

### Specialist variables

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Specialist runtime mode. |
| `DEV_BYPASS_AUTH` | Local/demo bypass in the specialist env templates. |
| `BEDROCK_MODEL_ID` | Model used by planner in model-backed mode. |
| `PLANNER_MODEL_ID` | Optional planner-specific override. |
| `PLANNER_EXECUTION_MODE` | `deterministic`, `model`, or `auto` locally; `auto` is blocked in staging/prod. |
| `PLANNER_TEMPERATURE` | Planner model temperature when model-backed mode is active. |
| `SUPABASE_URL` | Data endpoint for planner-owned finance modules. |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role used by planner finance functions. |
| `SQL_TIMEOUT_SEC` | Finance data timeout. |
| `USE_DARTS_FORECAST` | Enables optional forecasting extras. |
| `ENABLE_TRACING` | Specialist-side tracing switch. |
| `PORT` | Local or deployed specialist container port. |
| `STOCK_AGENT_EXTERNAL_*` | Optional external stock compatibility path. |

### Deploy configuration

`ops/aws/deploy.settings.json` is the checked-in deploy default set for profile, region, gateway ID, orchestrator allow list, and build flags. Use it together with:

- `ops/aws/deploy_full_aws.ps1`
- `iac/terraform/ecs-services`

## Installation and Setup

### Prerequisites

- Python environments compatible with the checked-in container images:
  - backend and specialist Dockerfiles use Python 3.12
  - orchestrator Dockerfile uses Python 3.10
- `pip`.
- AWS, Cognito, and Supabase credentials only if you intend to run live or deployed paths.

### Backend setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### Orchestrator setup

```powershell
cd agent
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

### Specialist runtime setup

```powershell
cd src/aws-specialist-agent-mcp-server
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements.optional-finance.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

## Running the Project

### Full local stack

Recommended startup order:

1. Start the specialist runtime on `127.0.0.1:8080`.
2. Start the orchestrator runtime on `127.0.0.1:8081`.
3. Start the backend on `127.0.0.1:8010`.

The local `.env.example` files are already aligned to that order:

- backend calls `AGENTCORE_LOCAL_URL=http://127.0.0.1:8081/invocations`
- orchestrator calls `AGENTCORE_GATEWAY_ENDPOINT=http://127.0.0.1:8080/mcp`

### Backend health check

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/health
```

### AWS deployment

Follow [`DEPLOY.md`](./DEPLOY.md) for the full command sequence.

## Testing

### Quick regression suite

```powershell
python -m unittest `
  tests.test_service_agent_mvp `
  tests.test_specialist_architecture `
  tests.test_stock_agent_client `
  tests.test_backend_chat_session_context
```

### Broader root test inventory

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

### Live testing

Live testing is supported via operators and scripts using the deployed backend and real credentials.

#### Preconditions

- A reachable deployed backend, typically the ALB URL from `iac/terraform/ecs-services`.
- Cognito credentials for a user that actually owns advisory data.
- Environment that allows `agent/genToken.py` to mint an access token.
- If needed, provision an aligned advisory principal with `backend/scripts/provision_advisory_principal.py`.

#### Recommended live flow

Generate or resolve an AccessToken:

```powershell
python agent/genToken.py
```

Export a user-facing TXT artifact from the live backend:

```powershell
python backend/scripts/export_chat_stream_txt.py `
  --prompt "Analyze my finances over the last 6 months." `
  --endpoint "http://<your-backend-alb-dns>/chat/stream" `
  --output "backend/tmp/financial_analysis_6_months_live.txt"
```

## Debugging and Observability

### Useful signals

- `GET /health` on the backend
- `trace_id` propagated through backend, orchestrator, and specialist outputs
- SSE metadata lines streamed from the backend
- user-facing TXT exports under `backend/tmp/`

## Development Workflow

### If you are changing request ingress

- Work in `backend/app/routes/chat.py`.
- Validate whether the change affects auth, session context caching, or SSE metadata.
- Update `backend/docs/api.md` if the observable API contract changes.

### If you are changing routing or response behavior

- Start in `agent/main.py`, `agent/strands_orchestrator/`, and `agent/config.py`.
- Keep `agent/core/settings.py` aligned with any auth or policy changes.
- Add or update tests under the root `tests/` directory.

### If you are adding a new specialist

- Extend `agent/subagents/agent_catalog.v1.json`.
- Add input and output schemas under `src/aws-specialist-agent-mcp-server/schemas/`.
- Register the tool in `src/aws-specialist-agent-mcp-server/app/mcp.py`.
- Extend specialist selection and payload building in `agent/strands_orchestrator/specialist.py`.

## Known Caveats and Design Notes

- The backend support endpoints use an in-memory store today. They are useful for demo scaffolding, not durable operational state.
- The orchestrator currently loads KB content locally from `kb/` rather than using a managed Bedrock knowledge base.
- The stock specialist is optional and may legitimately return an education-only fallback even when the rest of the system is healthy.
- The service specialist may perform hidden planner prefetch when roadmap generation lacks finance context. This is intentional and active in the current implementation.

## Extension Points

- Add a new specialist by extending the catalog, MCP schema set, selector, and response adapter.
- Add new deterministic finance capabilities in the planner finance core and expose them through planner or service flows.
- Replace mock simulator API calls with real API-backed data once the non-chat backend endpoints move beyond the in-memory store.
