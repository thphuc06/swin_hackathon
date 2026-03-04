# MVP Refactor Plan (End-to-End)

## 1) Goal and Constraints

This document is the implementation plan to refactor and re-structure the current codebase into a clean MVP architecture aligned with:

- Proposal source of truth: `C:\HCMUS\SWIN\SwinHack26_FinalProposal.pdf`
- Target 2-tier architecture (Tier 2 Deep Advisory + Tier 1 Proactive Notifications)
- MVP constraints:
  - Avoid expensive AWS services for MVP (especially OpenSearch).
  - Stock Agent is an externally hosted service and must be integrated via API contract.
  - Keep swap-ready interfaces so AWS components can be plugged in later (Cognito, Cedar, OpenSearch, CloudWatch).

Success criteria for MVP:

1. End-to-end advisory flow works from `POST /chat/stream` to final response.
2. Clear orchestrator state machine with deterministic tool plane and explicit policy/safety hooks.
3. External Stock Agent integration is production-safe (auth, timeout, retry, fallback).
4. Test coverage is sufficient for safe iteration (unit + integration + e2e + contract tests).


## 2) Current State Summary (Audit Snapshot)

## 2.1 What exists and is reusable

- Thin backend gateway (FastAPI) with:
  - `POST /chat/stream`
  - `goals`, `risk-profile`, `notifications`, `audit`
- LangGraph orchestrator already present in `agent/graph.py`
- MCP tool gateway integration in `agent/tools.py`:
  - tool registry
  - JSON schema validation
  - retries and pooling
- Finance MCP server with 9 deterministic tools:
  - `spend_analytics_v1`
  - `anomaly_signals_v1`
  - `cashflow_forecast_v1`
  - `jar_allocation_suggest_v1`
  - `risk_profile_non_investment_v1`
  - `suitability_guard_v1`
  - `recurring_cashflow_detect_v1`
  - `goal_feasibility_v1`
  - `what_if_scenario_v1`
- Local KB retrieval (cheap) is already used to avoid OpenSearch cost.

## 2.2 Main structural issues

- Orchestrator logic is monolithic (`agent/graph.py`) and mixes routing, business policy, rendering, memory update.
- No explicit specialized agent boundaries (Planner, Stock external, Market context).
- No external Stock Agent adapter/contract in code.
- Policy is rule-based only; no clean policy engine abstraction for Cedar swap.
- Memory is mostly audit write, not explicit session/user memory layer with TTL/privacy boundaries.
- Docs drift from code (backend docs still mention removed endpoints).
- Tier 1 workers still import removed backend financial module.
- CI is minimal and test strategy is incomplete for refactor safety.


## 3) Target Architecture (MVP-safe, upgrade-ready)

## 3.1 Tier 2 (Deep Advisory)

- Entry:
  - API Gateway equivalent: current backend FastAPI endpoint remains entry.
  - Auth provider abstraction (`JWTProvider` now, Cognito provider later).
- Input and safety:
  - input validation/sanitization
  - policy pre-check hooks
  - memory context load
- Orchestrator runtime:
  - state machine nodes:
    - intake -> safety -> plan -> select_agent -> tool_calls -> aggregate -> respond -> memory_update
  - specialized agents:
    - Planner Agent (internal)
    - Stock Agent Client (external HTTP service)
    - Market Context Agent (internal tool-based in MVP)
- Tool plane:
  - MCP Gateway remains primary tool transport
  - Policy hook before tool execution
  - Retrieval through `IndexClient` abstraction:
    - MVP: local KB / pgvector
    - later: OpenSearch adapter
- Observability:
  - structured logs
  - trace_id and call_id propagation
  - exporter interface for CloudWatch later

## 3.2 Tier 1 (Proactive Notifications)

- Keep boundary and modules in codebase:
  - Event Trigger -> Queue -> Worker/Processor -> State Store -> Alerts
- MVP implementation can stay partial, but must not depend on removed modules.


## 4) Refactor Principles (Non-negotiable)

1. Interface-first:
   - Core logic depends on ports, not concrete infra clients.
2. Dependency direction:
   - `core` cannot import `infra`.
3. Deterministic finance computations:
   - numbers from SQL/tool outputs only.
4. Policy and safety before action:
   - no write/execution path without policy check.
5. Resilience defaults:
   - timeout, retry, fallback, and typed errors.
6. Traceability:
   - every request and tool call has correlation metadata.
7. Incremental migration:
   - do not rewrite from scratch; move behavior behind new module boundaries progressively.


## 5) Proposed Folder Structure

Use this structure under `agent/` while preserving compatibility for current runtime:

```text
agent/
  api/
    runtime_entry.py
    schemas.py
  core/
    models.py
    errors.py
    ports.py
    settings.py
  orchestrator/
    state.py
    graph_builder.py
    router.py
    planner.py
    nodes/
      intake.py
      safety.py
      plan.py
      select_agent.py
      tool_calls.py
      aggregate.py
      respond.py
      memory_update.py
  agents/
    planner_agent.py
    stock_agent_client.py
    market_context_agent.py
  tools/
    gateway_client.py
    registry.py
    protocol.py
    wrappers.py
  policy/
    engine.py
    simple_policy.py
    cedar_adapter.py
  memory/
    store.py
    session_memory.py
  retrieval/
    index_client.py
    local_index.py
    pgvector_index.py
    opensearch_index.py
  infra/
    auth/
      provider.py
      jwt_provider.py
      cognito_provider.py
    storage/
      repository.py
      supabase_repo.py
      aurora_repo.py
    llm/
      provider.py
      bedrock_provider.py
  observability/
    tracing.py
    audit_logger.py
    exporters/
      cloudwatch_exporter.py
  tests/
    unit/
    integration/
    e2e/
    contract/
```

For backend and workers:

```text
backend/
  app/
    main.py
    routes/
    services/
    dependencies/
workers/
  tier1/
    trigger_worker.py
    aggregate_worker.py
    processors/
    adapters/
```


## 6) Tool Coverage Mapping (Proposal vs Current vs Planned)

| Capability | Current | Planned action |
|---|---|---|
| Spend analytics | yes | keep |
| Anomaly signals | yes | keep |
| Cashflow forecast | yes | keep |
| Jar allocation | yes | keep |
| Non-investment risk profile | yes | extend with profile completeness linkage |
| Suitability guard | yes | keep + policy abstraction |
| Recurring detection | yes | keep |
| Goal feasibility | yes | keep |
| What-if scenario | yes | keep |
| Conservative/Balanced/Growth plan output | partial | add `tradeoff_plan_builder_v1` |
| Best-interest check | missing | add `best_interest_guard_v1` |
| Data sufficiency/reliability gate | missing | add `data_sufficiency_score_v1` |
| Stock Agent external capability | missing | add `stock_agent_client` + contract tests |
| Market macro context | missing | add market context tool/agent module |


## 7) External Stock Agent Integration Spec (MVP)

## 7.1 Contract (proposed)

- Endpoint: `POST /v1/stock/advisory`
- Auth:
  - `Authorization: Bearer <service-token>` or signed JWT
- Required headers:
  - `X-Trace-Id`
  - `X-Request-Id`
  - `Idempotency-Key`

Request body:

```json
{
  "user_id": "string",
  "query": "string",
  "risk_profile": {
    "risk_band": "conservative|moderate|aggressive|unknown",
    "horizon_months": 0,
    "liquidity_need": "string"
  },
  "constraints": {
    "education_only": true,
    "suitability_required": true
  },
  "context_snapshot": {
    "net_cashflow": 0,
    "runway_months": 0,
    "anomaly_flags": []
  }
}
```

Response body:

```json
{
  "summary": "string",
  "alternatives": ["string"],
  "suitability_check": {
    "status": "pass|warn|deny",
    "reasons": ["string"]
  },
  "citations": ["string"],
  "confidence": 0.0,
  "warnings": ["string"],
  "trace_ref": "string"
}
```

## 7.2 Runtime behavior

- Timeout:
  - connect 2s, read 8s (tunable)
- Retry:
  - max 2 retries for timeout/429/5xx
- Circuit breaker:
  - open after consecutive failures threshold
- Fallback:
  - return education-only advisory from internal planner path with explicit reason code:
    - `stock_agent_unavailable_fallback`


## 8) Orchestrator State Machine Design

## 8.1 State model

Core state keys:

- `trace_id`, `request_id`, `session_id`, `user_id`
- `prompt`, `normalized_prompt`, `language`
- `route_decision`, `policy_decision`
- `tool_plan`, `tool_outputs`, `tool_errors`
- `agent_outputs` (planner/stock/market)
- `evidence_pack`, `advisory_context`, `response_payload`
- `memory_read`, `memory_write`

## 8.2 Node flow

1. `intake`
   - validate request shape
   - create trace metadata
2. `safety`
   - sanitize prompt
   - PII and policy pre-check hooks
3. `plan`
   - classify intent
   - build execution plan (agents/tools)
4. `select_agent`
   - choose internal planner vs external stock path
5. `tool_calls`
   - execute internal tools via gateway with policy checks
6. `aggregate`
   - build evidence pack, merge agent outputs
7. `respond`
   - enforce response schema and mandatory output fields
8. `memory_update`
   - persist summary and audit package

## 8.3 Mandatory output contract

All final responses must include:

- `rationale`
- `alternatives`
- `suitability_check`
- `trace_id`


## 9) Phase Plan (P0 / P1 / P2)

## P0 - MVP foundation and end-to-end flow

Objective:

- Make architecture clean enough to build fast without regressions.
- Deliver production-safe external Stock Agent integration.
- Keep current behavior while moving to modular structure.

### P0 Checklist

- [ ] Introduce new module boundaries (`core`, `orchestrator`, `agents`, `tools`, `policy`, `memory`, `retrieval`, `observability`).
- [ ] Extract graph nodes from monolith into module files.
- [ ] Add `StockAgentClient` with full resilience behavior.
- [ ] Implement `IndexClient` interface with `LocalIndexClient` default.
- [ ] Add typed error taxonomy and fallback mapping.
- [ ] Fix Tier1 workers to remove broken imports.
- [ ] Align docs with actual API surface.
- [ ] Add minimum integration and e2e tests for new flow.

### P0 PR Breakdown

1. `P0-PR1` Architecture scaffold and ports
   - Create interfaces and base models
   - Keep compatibility wrappers for old imports
2. `P0-PR2` Orchestrator modularization
   - Split `graph.py` into node modules + graph builder
3. `P0-PR3` External Stock Agent integration
   - Add client, config, route conditions, fallback
4. `P0-PR4` Tool protocol hardening
   - idempotency key, unified timeout and error mapping
5. `P0-PR5` Tier1 worker boundary fix + docs cleanup
6. `P0-PR6` Test harness (integration + e2e baseline)

### P0 Files to Create/Modify (primary)

Create:

- `agent/core/ports.py`
- `agent/core/models.py`
- `agent/orchestrator/graph_builder.py`
- `agent/orchestrator/nodes/*.py`
- `agent/agents/stock_agent_client.py`
- `agent/retrieval/index_client.py`
- `agent/retrieval/local_index.py`
- `agent/policy/engine.py`
- `agent/observability/tracing.py`
- `agent/tests/integration/test_orchestrator_flow.py`
- `agent/tests/contract/test_stock_agent_contract.py`
- `agent/tests/e2e/test_chat_stream_e2e.py`

Modify:

- `agent/main.py`
- `agent/graph.py` (compat wrapper or reduced facade)
- `agent/tools.py`
- `backend/docs/api.md`
- `workers/aggregate_worker.py`
- `workers/trigger_worker.py`

### P0 Effort / Risk

- Effort: 10-14 dev days
- Risk: medium-high (runtime path changes)

### P0 Done Criteria

- End-to-end advisory works for:
  - summary
  - planning
  - stock query with external success
  - stock query with external fallback
- Trace IDs and reason codes are present in every response.
- No broken worker imports.
- Core tests pass in CI baseline.


## P1 - Hardening and policy/safety depth

Objective:

- Strengthen policy compliance, resilience, observability, and deterministic quality gates.

### P1 Checklist

- [ ] Add `best_interest_guard_v1`.
- [ ] Add `data_sufficiency_score_v1`.
- [ ] Add `tradeoff_plan_builder_v1` for 3-option outputs.
- [ ] Add PII/safety sanitizer module with policy hooks.
- [ ] Add circuit breaker for Stock Agent and selected tool paths.
- [ ] Add structured audit envelope standards across layers.
- [ ] Add cache (TTL) for stable context slices and market snapshots.

### P1 PR Breakdown

1. `P1-PR1` Policy engine expansion + new policy tools
2. `P1-PR2` Response gating and mandatory output enforcement
3. `P1-PR3` Resilience features (breaker/cache/retry tuning)
4. `P1-PR4` Observability and trace propagation improvements

### P1 Files to Create/Modify (primary)

Create:

- `src/aws-finance-mcp-server/app/finance/best_interest.py`
- `src/aws-finance-mcp-server/app/finance/data_sufficiency.py`
- `src/aws-finance-mcp-server/app/finance/tradeoff_plan.py`
- `agent/tests/unit/test_policy_engine.py`
- `agent/tests/integration/test_stock_agent_resilience.py`

Modify:

- `src/aws-finance-mcp-server/app/mcp.py` (register new tools and schemas)
- `agent/orchestrator/nodes/plan.py`
- `agent/orchestrator/nodes/respond.py`
- `agent/policy/simple_policy.py`
- `agent/observability/audit_logger.py`

### P1 Effort / Risk

- Effort: 7-10 dev days
- Risk: medium

### P1 Done Criteria

- All advisory responses include mandatory structure and policy evidence.
- New policy tools are callable and covered by tests.
- External dependency failures degrade gracefully without crashing flow.


## P2 - Scale prep and AWS swap readiness

Objective:

- Make infra adapters swappable with minimal core changes.

### P2 Checklist

- [ ] Add `OpenSearchIndexClient` adapter (optional activation).
- [ ] Add `CedarPolicyAdapter` integration layer.
- [ ] Add `CognitoAuthProvider` formal adapter.
- [ ] Add `CloudWatchExporter` adapter for traces/audit logs.
- [ ] Add Tier1 event pipeline skeleton aligned with queue-worker-store pattern.
- [ ] Add CI pipelines for unit/integration/e2e/contract suites.

### P2 PR Breakdown

1. `P2-PR1` AWS adapter implementation package
2. `P2-PR2` Tier1 module boundary and processor skeleton
3. `P2-PR3` CI/CD and deployment quality gates

### P2 Files to Create/Modify (primary)

Create:

- `agent/retrieval/opensearch_index.py`
- `agent/policy/cedar_adapter.py`
- `agent/infra/auth/cognito_provider.py`
- `agent/observability/exporters/cloudwatch_exporter.py`
- `.github/workflows/ci.yml` (or equivalent pipeline config)

Modify:

- `agent/core/settings.py` (feature flags and adapter switches)
- `iac/*` scaffolding docs and templates
- `workers/tier1/*` modules

### P2 Effort / Risk

- Effort: 8-12 dev days
- Risk: medium-high (infra integration)

### P2 Done Criteria

- Switching from local adapters to AWS adapters is config-driven.
- Test suites run automatically in CI for all core layers.
- Tier1 boundaries are present and consistent with proposal direction.


## 10) Testing Strategy and Coverage Targets

## 10.1 Unit tests

Focus:

- router/planner decisions
- policy guards
- tool protocol validation
- error mapping and fallback logic

Target:

- >= 85% for `agent/core`, `agent/orchestrator`, `agent/policy`, `agent/tools` core modules.

## 10.2 Integration tests

Focus:

- orchestrator <-> MCP tool plane
- orchestrator <-> external Stock Agent mock service
- backend `chat/stream` <-> runtime behavior

Target:

- >= 70% critical integration paths.

## 10.3 E2E tests

Golden flows:

1. summary advisory
2. risk anomaly advisory
3. planning feasibility
4. scenario what-if
5. stock route with external service
6. stock route fallback on external failure

## 10.4 Contract tests

- Define JSON schema for Stock Agent request/response.
- Validate backward compatibility on every change.

## 10.5 Test data

- Reuse seeded single-user fixtures under `backend/tmp` and `backend/seed`.
- Add deterministic fixture snapshots for each intent class.


## 11) Observability and Error Model

## 11.1 Correlation keys

- `trace_id` per user request
- `call_id` per tool invocation
- `request_id` per external service call

## 11.2 Structured error codes

Standardize:

- `POLICY_DENY`
- `DATA_INSUFFICIENT`
- `TOOL_TIMEOUT`
- `TOOL_UNAVAILABLE`
- `EXTERNAL_AGENT_UNAVAILABLE`
- `VALIDATION_FAILED`
- `GROUNDING_FAILED`

## 11.3 Logging minimum payload

Each stage logs:

- stage name
- trace_id
- call_id (if applicable)
- latency_ms
- outcome (`ok`, `fallback`, `error`)
- reason_codes


## 12) Migration and Rollout Strategy

## 12.1 Branch and release model

- Keep refactor incremental behind feature flags:
  - `ORCHESTRATOR_V2_ENABLED`
  - `STOCK_AGENT_EXTERNAL_ENABLED`
  - `POLICY_ENGINE_V2_ENABLED`

## 12.2 Rollout steps

1. Deploy P0 with feature flags off.
2. Enable on staging and run full test suite.
3. Enable for small internal user slice.
4. Observe traces/errors and tune.
5. Roll out globally.

## 12.3 Rollback

- If severe errors spike:
  - disable `ORCHESTRATOR_V2_ENABLED`
  - route all traffic to current stable orchestration path
  - keep audit trails intact


## 13) Non-goals for MVP (but keep hooks)

- No full OpenSearch managed RAG deployment for MVP.
- No full Cedar managed policy execution in MVP runtime.
- No full production Tier1 async pipeline implementation.
- No trade execution features; advisory only.
- No long-horizon model experimentation outside deterministic baseline.


## 14) Immediate Next Actions (Implementation Order)

Week 1:

1. P0-PR1 architecture scaffold
2. P0-PR2 orchestrator modularization

Week 2:

3. P0-PR3 Stock Agent integration
4. P0-PR4 tool protocol hardening

Week 3:

5. P0-PR5 worker/docs cleanup
6. P0-PR6 integration/e2e tests and stabilization

Then start P1 hardening.


## 15) Acceptance Checklist (Final MVP Gate)

- [ ] End-to-end flow works with deterministic advisory and traceability.
- [ ] External Stock Agent path has tested contract and fallback.
- [ ] Policy and safety hooks are explicit and test-covered.
- [ ] Tool plane protocol is standardized with retry/timeout/idempotency.
- [ ] Codebase boundaries are clean and ready for scale adapters.
- [ ] Docs and tests are aligned with actual runtime behavior.

## 16) P0 Outstanding Notes

Detailed unfinished/deployment items for P0 are tracked in:

- `P0_OUTSTANDING_NOTES.md`
- `P0_NOTES.md` (shortcut pointer)

## 17) Phase 2 Kickoff Notes

Current incomplete items requiring product/infra decisions are tracked in:

- `P1_NOTES.md`

## 18) Phase 3 Notes

Current scale-prep pipeline notes are tracked in:

- `P2_NOTES.md`
