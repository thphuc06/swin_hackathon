# TECH MILESTONES - E2E MVP (Judge-ready)

## Milestone 1 - Environment Baseline and Security
### Target
- Separate `local` and `aws-real` environments clearly with per-service `.env` files (`frontend`, `backend`, `agent`, `finance-mcp`).
- Remove all hardcoded secrets from source code and repository history.
- Ensure Cognito auth works for both backend and finance-mcp services.

### Dedicated tests
- Run secret scan on the full repo: no exposed tokens/keys.
- Backend with `DEV_BYPASS_AUTH=false`: request without token must return `401`.
- Finance MCP with `DEV_BYPASS_AUTH=false`: `POST /mcp` without token must return unauthorized.

## Milestone 2 - Data Truth and Finance MCP Tools
### Target
- Deploy `finance-mcp` and keep it stable (`/health`, `/mcp`).
- Expose all 9 core finance tools (spend, anomaly, forecast, jar, risk, suitability, recurring, goal, what-if).
- Guarantee deterministic outputs based on Supabase data.

### Dedicated tests
- `GET /health` returns `200`.
- `POST /mcp` with `tools/list` returns all 9 tools.
- Run `src/aws-finance-mcp-server/scripts/run_finance_mcp_smoke.ps1` successfully.
- Invalid tool schema input must return JSON-RPC validation error.

## Milestone 3 - Gateway Integration
### Target
- Configure AgentCore Gateway target to `finance-mcp` endpoint `/mcp`.
- Confirm Gateway `tools/list` shows prefixed tool names (for example `finance-mcp___spend_analytics_v1`).
- Execute finance tools through Gateway using valid tokens.

### Dedicated tests
- `tools/list` through Gateway with AccessToken returns prefixed tools.
- Gateway call without token returns `401/Unauthorized`.
- `tools/call` through Gateway for `spend_analytics_v1` returns valid payload.

## Milestone 4 - Agent Runtime Orchestration
### Target
- Deploy agent to AgentCore Runtime with `ROUTER_MODE=semantic_enforce`, `RESPONSE_MODE=llm_enforce`, `USE_LOCAL_MOCKS=false`.
- Enforce `suitability_guard_v1` before high-risk advisory behavior.
- Return response metadata with `Trace`, `Tools`, and `Disclaimer`.

### Dedicated tests
- `agentcore invoke` with summary prompt returns answer + tool metadata.
- Buy/sell intent prompt is blocked by education-only policy.
- Missing `AGENTCORE_GATEWAY_ENDPOINT` must fail loudly (no silent wrong-flow fallback).
- MVP SLA: p95 response time under 20 seconds on demo prompt set.

## Milestone 5 - Backend Stream Proxy (E2E Bridge)
### Target
- Keep `POST /chat/stream` stable from Backend -> Runtime.
- Propagate `Authorization` and `user_id` from backend to runtime payload correctly.
- Expose runtime source marker (`RuntimeSource: aws_runtime`).

### Dedicated tests
- `/chat/stream` with valid token returns full stream with trace metadata.
- If `AGENTCORE_RUNTIME_ARN` is set but Authorization header is missing, backend returns `401`.
- Runtime failures (timeout/5xx) must be streamed as explicit SSE error lines.

## Milestone 6 - Frontend E2E Demo
### Target
- Frontend chat successfully calls local backend via `NEXT_PUBLIC_API_BASE_URL`.
- Support 4 demo use cases: summary, planning, scenario, invest-policy.
- UI clearly handles loading, success, and error states during streaming.

### Dedicated tests
- Manual validation of all 4 demo prompts returns valid responses.
- Expired/invalid token triggers proper auth error in UI.
- Backend/network outage shows recoverable error state (no frozen UI).

## Milestone 7 - Audit and Observability
### Target
- Provide end-to-end traceability: frontend -> backend -> runtime -> gateway -> tools.
- Persist audit events by `trace_id`.
- Keep logs sufficient to explain one full session during judging.

### Dedicated tests
- Use one `trace_id` to retrieve matching logs in backend/runtime.
- `GET /audit/{trace_id}` returns record with `tool_chain`.
- At least one failure case includes reason code for root-cause explanation.

## Milestone 8 - Demo Gate (MVP Definition of Done)
### Target
- Run full AWS-real E2E demo flow reliably.
- No mock data in the primary judging path.
- Maintain pre-demo operational checklist (tokens, endpoints, service health, rollback).

### Dedicated tests
- Execute full dry-run demo 3 consecutive times with no critical failure.
- Demo prompt pass rate >= 95%.
- Pre-demo checklist pass rate = 100% before presentation.
