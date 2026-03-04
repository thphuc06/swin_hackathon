# Prompt To Ask AI: Implement Forecast + Allocation Intelligence Inside Dexter (Stock Agent)

You are a senior Python backend + quant engineer. Implement this directly in the **Dexter Stock Agent** codebase.

## Goal
Move all investment forecast/allocation intelligence into Dexter so upstream orchestrator only calls Dexter external API.
Do **not** depend on `portfolio_allocation_optimize_v1` from upstream MCP anymore.

## Product Context
- Dexter can call market-data providers directly (already integrated in Dexter stack).
- Dexter should produce education-focused stock/portfolio guidance in one response.
- User risk profile may be:
  - explicitly provided by request payload, OR
  - missing/empty -> infer from user query text, OR
  - still unknown -> default `moderate`.

## Required API Contract (must remain compatible)
Implement/keep endpoint:
- `POST /v1/stock/advisory`

Expected headers:
- `X-Trace-Id`
- `X-Request-Id`
- `Idempotency-Key`
- `Authorization: Bearer ...` (if enabled)

Request body (minimum):
```json
{
  "user_id": "string",
  "query": "string",
  "risk_profile": {
    "risk_band": "conservative|moderate|aggressive|unknown",
    "horizon_months": 0,
    "liquidity_need": ""
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

Response body (required fields):
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
Optional fields allowed (for future):
- `market_snapshot`
- `portfolio_constraints` or `constraints`

## What To Build
1. Add internal module `investment_advisor/` containing:
- market data loader (with provider abstraction + retries + timeout)
- feature builder (returns, volatility, momentum, drawdown)
- risk profile resolver (payload first, then NLP heuristic, then default)
- allocation/recommendation engine (rule/quant hybrid)
- response composer (maps outputs -> API contract)

2. Risk profile resolver rules:
- If payload risk is valid -> use it.
- Else infer from query keywords:
  - conservative: `an toan`, `it rui ro`, `bao toan`, `low risk`
  - moderate: `can bang`, `vua`, `balanced`, `moderate`
  - aggressive: `rui ro cao`, `mao hiem`, `high risk`, `aggressive`
- Else default `moderate`.

3. Data freshness and TTL:
- Add per-symbol cache with TTL config.
- If stale data and refresh fails, return degraded response with warning, not 500.

4. Safety/suitability behavior:
- Keep `education_only` semantics.
- If user asks direct buy/sell execution, return `suitability_check.status = "deny"` with refusal guidance.
- For recommendation-style questions, return `warn` with explicit disclaimer.

5. Error handling:
- Validate request schema.
- Idempotency by `Idempotency-Key` for duplicate requests.
- Structured logs with `trace_id`, `request_id`, `latency_ms`, `provider`, `fallback_used`.
- Timeout budget for downstream market data calls.

6. Testing (must include):
- Unit tests for risk resolver, feature builder, and recommendation logic.
- Contract tests for request/response schema.
- Integration test with mocked market data provider.
- Idempotency replay test.
- Failure-path tests: provider timeout, stale cache fallback, missing fields.

## Acceptance Criteria
- Endpoint returns valid response contract for normal + degraded paths.
- No dependency on upstream portfolio tool.
- Risk profile fallback works when request omits/empties risk.
- Tests pass in CI.
- Documentation added: config vars, TTL, provider adapter, example requests.

## Non-goals
- No order execution.
- No broker integration.
- No expensive external search index requirement.

## Deliverables
- Code changes in Dexter repo.
- Migration note: �Dexter now owns forecast/allocation intelligence�.
- Test report summary and sample curl requests.
