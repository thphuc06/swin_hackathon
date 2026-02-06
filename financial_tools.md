# Financial Tools Plan (Jars)

This note answers:
- Which repos/libraries we will use
- Which ones we defer or use as references only
- How to integrate with current code (`backend/app/services/financial_tools.py`, `backend/app/routes/*`, `agent/tools.py`)

## Current integration anchors
- Backend calculators: `backend/app/services/financial_tools.py`
- Forecast APIs: `backend/app/routes/forecast.py`
- Decision APIs: `backend/app/routes/decision.py`
- Spend summary API (currently mocked): `backend/app/routes/aggregates.py`
- Agent tool caller: `agent/tools.py`

## Repo decision matrix

| Repo / Service | Decision | Why | Integration |
|---|---|---|---|
| River | Use (Phase 1) | Best fit for streaming anomaly + drift in deterministic pipeline | Worker service (`workers/`) + backend read API for latest anomaly flags |
| PyOD | Use later | Good anomaly baseline pack, but mostly batch/offline | Offline evaluation job only; do not put deep models on request path |
| Kats | Skip for now | Useful, but release cadence is old for core dependency | Keep only as benchmark notebook/reference |
| Darts | Use later | Strong forecasting toolkit, heavier dependencies | ECS forecast worker after MVP |
| Actual Budget | Reference only (now) | Great envelope budgeting/jar logic patterns | Implement own deterministic jar allocator in Python (no runtime dependency) |
| Firefly III | Reference only (now) | Good budget/category/rules schema ideas | Borrow schema/rule ideas only; avoid AGPL coupling in core services |
| OpenFisca | Optional later | Rules-as-code engine, explainable but heavy for MVP | Consider as separate MCP/policy service if rule complexity grows |
| statsmodels | Use (Phase 0) | Deterministic, auditable forecasting (ETS/ARIMA) | Import directly in backend service layer |
| skforecast | Use later | Better ML forecasting wrappers and backtesting | Optional enhancement for worker-tier forecast experiments |
| ruptures | Use (Phase 1) | Deterministic change-point detection for income/spend shifts | Backend/worker utility for sudden-change flags |
| Cedar + Amazon Verified Permissions | Use (Phase 0) | Explicit policy decisions for suitability/education-only guard | Suitability guard endpoint + policy decision log in audit trail |
| Bedrock Guardrails | Use (Phase 0) | Required safety layer for unsafe/financially sensitive responses | Apply before final agent response; log guardrail result with `trace_id` |

## What we will implement now (MVP)

1. Spend analytics (tool family 1)
- Source of truth: SQL only (Supabase/Aurora).
- Add deterministic summary function in backend service layer:
  - 30/60/90-day totals
  - jar splits
  - top merchants
  - budget drift
- Wire endpoint:
  - Extend `backend/app/routes/aggregates.py` or add `backend/app/routes/spend.py`.
- Agent call path:
  - Add function in `agent/tools.py` (`spend_analytics(...)`) to call backend endpoint.

2. Cashflow forecasting (tool family 3)
- Replace heuristic-only forecast path with `statsmodels` baseline (ETS first, ARIMA optional).
- Keep deterministic config:
  - fixed model type
  - fixed history window
  - no random seeds required for ETS/ARIMA path
- Integration file split:
  - Add `backend/app/services/forecast_statsmodels.py`
  - Keep orchestration in `backend/app/routes/forecast.py`.

3. Realtime anomaly + shift detection (tool family 2)
- River in worker path for streaming anomaly/drift state.
- `ruptures` for periodic change-point detection (income drop/category spike).
- Deployment:
  - Worker consumes transaction events and stores latest user-level anomaly signals.
  - Backend reads latest signal snapshot for chat/tool response.

4. Jar allocation + risk profile (tool families 4,5)
- Keep rule-based allocator in Python service (deterministic, explainable).
- Use Actual Budget as logic reference only:
  - envelope-first priority
  - fixed-cost coverage -> emergency buffer -> goal buckets.
- Implement in `backend/app/services/financial_tools.py` or split `allocation_rules.py`.

5. Suitability/regulatory guard (tool family 6)
- Add pre-response guard endpoint (backend or MCP tool):
  - classify intent (buy/sell/execute vs education)
  - call Verified Permissions (Cedar policy)
  - enforce disclaimer/refusal template
- Agent orchestration:
  - call guard first
  - if denied, return refusal + disclaimer + `trace_id`
  - if allowed, continue with finance tools.

## How to integrate in current codebase

1. Backend (`backend/app/services`)
- Keep pure deterministic computation functions.
- Add audit payload in all outputs:
  - `trace_id`
  - `params_hash` (sha256 canonical json)
  - `version`
  - `sql_snapshot_ts`

2. Backend routes (`backend/app/routes`)
- `aggregates.py`: replace hardcoded summary with SQL-backed analytics.
- `forecast.py`: route stays, implementation calls statsmodels service + optional worker results.
- `decision.py`: keep education-only semantics for `investment-capacity`; add suitability guard check before returning.

3. Agent runtime (`agent/tools.py`)
- Add calls for:
  - `spend_analytics`
  - `cashflow_anomaly`
  - `suitability_guard`
- Maintain fallback mocks only for local dev; production path must use public backend/Gateway endpoints (no localhost from runtime).

4. Policy + safety
- MCP/Gateway tool for KB retrieval remains wording-only.
- Numeric truth remains SQL-derived only.
- Every chat response should include:
  - citations (KB for wording)
  - disclaimer
  - `trace_id`

## Suggested order

1. Implement SQL spend analytics endpoint + agent wrapper.
2. Swap forecast core to `statsmodels` deterministic baseline.
3. Add suitability guard (Cedar/Verified Permissions + disclaimers).
4. Add River + `ruptures` worker pipeline for anomaly signals.
5. Add Darts/PyOD/skforecast only when baseline metrics require improvement.
