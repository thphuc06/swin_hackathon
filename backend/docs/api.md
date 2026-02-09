# API Contracts (MVP)

Base URL: `http://localhost:8010`

Auth:
- Most endpoints require `Authorization: Bearer <access_token>`.
- For local dev only, set `DEV_BYPASS_AUTH=true` in `backend/.env`.

## GET /health
Returns backend liveness.

## Transactions

### POST /transactions/transfer
Body:
```json
{ "jar_id": "jar_house", "category_id": "cat_rent", "amount": 5000000, "counterparty": "Landlord" }
```

### GET /transactions?range=30d|60d
Returns user-scoped transaction list.

### POST /transactions/import/statement
Import and parse VN statement (CSV/TXT/TSV parser for MVP).

```json
{
  "file_ref": "C:/data/statement.csv",
  "bank_hint": "vcb",
  "currency": "VND",
  "rules_counterparty_map": [
    { "counterparty_norm": "LANDLORD", "jar_id": "jar_house", "category_id": "cat_rent" }
  ]
}
```

## Aggregates

### GET /aggregates/summary?range=30d|60d
Returns totals and largest transaction.

## Notifications

### GET /notifications
Returns user-scoped notification list.

### POST /notifications
```json
{ "title": "Runway alert", "detail": "Runway below 6 months", "trace_id": "trc_abc123" }
```

## Goals

### POST /goals
```json
{ "name": "buy house", "target_amount": 650000000, "horizon_months": 84 }
```

## Risk Profile

### GET /risk-profile
Returns current risk profile.

### POST /risk-profile
```json
{ "profile": "balanced", "notes": "moderate volatility" }
```

## Forecast

### GET /forecast/cashflow?range=90d
Returns projected cashflow with confidence band.

### POST /forecast/cashflow/scenario
Run scenario-based forecast (1-24 months).

```json
{
  "horizon_months": 12,
  "seasonality": true,
  "scenario_overrides": { "income_delta_pct": -0.1, "spend_delta_pct": 0.08 }
}
```

### POST /forecast/runway
Compute runway and stress flags from forecast.

```json
{
  "forecast": { "monthly_forecast": [] },
  "cash_buffer": 120000000,
  "stress_config": { "income_drop_pct": 0.2, "spend_spike_pct": 0.15, "runway_threshold_months": 6 }
}
```

## Decision

### POST /decision/savings-goal
```json
{ "target_amount": 500000000, "horizon_months": 24 }
```

### POST /decision/house-affordability
```json
{
  "house_price": 3000000000,
  "down_payment": 900000000,
  "interest_rate": 10,
  "loan_years": 20,
  "fees": 60000000
}
```

### POST /decision/investment-capacity
```json
{
  "risk_profile": "balanced",
  "emergency_target": 120000000,
  "cash_buffer": 70000000
}
```

### POST /decision/what-if
```json
{
  "base_scenario": { "horizon_months": 12, "seasonality": true, "scenario_overrides": {} },
  "variants": [
    { "name": "delay_purchase_12m", "scenario_overrides": { "spend_delta_pct": -0.1 } }
  ],
  "goal": "house"
}
```

## Chat

### POST /chat/stream
SSE stream from AgentCore Runtime or local AgentCore app.
- Content-Type: `text/event-stream; charset=utf-8`
- Response headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`

## Audit

### POST /audit
```json
{
  "trace_id": "trc_abc123",
  "event_type": "agent_summary",
  "payload": { "summary": "...", "tool_calls": ["forecast_cashflow_core"] }
}
```

### GET /audit/{trace_id}
Returns audit event and tool chain for the trace ID.

## MCP (Financial Tools)

### GET /mcp
Health text endpoint for MCP target checks.

### POST /mcp
JSON-RPC endpoint used by AgentCore Gateway target.

### Example: initialize
```json
{ "jsonrpc": "2.0", "id": "init-1", "method": "initialize" }
```

### Example: tools/list
```json
{ "jsonrpc": "2.0", "id": "tools-1", "method": "tools/list" }
```

### Example: tools/call
```json
{
  "jsonrpc": "2.0",
  "id": "call-1",
  "method": "tools/call",
  "params": {
    "name": "spend_analytics_v1",
    "arguments": {
      "user_id": "64481438-5011-7008-00f8-03e42cc06593",
      "range": "30d"
    }
  }
}
```

### Financial MCP tool names
- `spend_analytics_v1`
- `anomaly_signals_v1`
- `cashflow_forecast_v1`
- `jar_allocation_suggest_v1`
- `risk_profile_non_investment_v1`
- `suitability_guard_v1`

## Single User Seeding Utility

The backend includes an internal CLI utility for deterministic single-user advisory seeding:

```bash
python scripts/seed_single_user_advisory.py \
  --sparkov-train C:/data/fraudTrain.csv \
  --sparkov-test C:/data/fraudTest.csv \
  --supabase-url https://<project-ref>.supabase.co \
  --supabase-service-key <service-role-key> \
  --seed-user-id <uuid-or-cognito-sub> \
  --months 12 \
  --target-debit-rows 5000 \
  --fx-rate 25000 \
  --currency VND \
  --seed 20260207
```

Generated artifacts:
- `backend/tmp/seed_manifest_single_user.json`
- `backend/tmp/seed_validation_single_user.json`
