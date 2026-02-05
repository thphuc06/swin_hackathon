# API Contracts (MVP)

Base URL: `http://localhost:8010`

## POST /transactions/transfer
Body:
```json
{ "jar_id": "jar_house", "category_id": "cat_rent", "amount": 5000000, "counterparty": "Landlord" }
```

## POST /transactions/suggest
Suggest `jar_id` + `category_id` (Top-K + confidence) from messy transaction text.

Body:
```json
{
  "counterparty": "Landlord",
  "amount": 5000000,
  "currency": "VND",
  "raw_narrative": "MBVCB... CHUYEN TIEN THUE NHA T2",
  "user_note": "",
  "channel": "transfer",
  "direction": "debit"
}
```

## GET /transactions?range=30d|60d
Returns user-scoped list.

## GET /aggregates/summary?range=30d|60d
Returns totals and largest transaction.

## GET /notifications
Returns Tier1 insights.

## GET /jars
List user-defined jars.

## POST /jars
Create a jar (improves personalization + categorization).

```json
{
  "name": "Ví đi chơi với người yêu",
  "description": "Date nights, travel, movies, cafes",
  "keywords": ["cgv", "highlands", "grab", "pizza"]
}
```

## GET /jars/templates
List default jar templates for first-time users.

## POST /jars/seed-defaults
Create default jars for a user (one-time init).

## GET /signals/summary
Returns data quality + behavior signals for UI and Tier2 (example: % categorized, discipline score).

## GET /forecast/cashflow?range=90d
Returns 90-day cashflow/runway projection (truth from views; can start heuristic).

## POST /rules/counterparty
Persist a mapping rule for messy data (counterparty -> jar/category).

```json
{
  "counterparty_norm": "LANDLORD",
  "jar_id": "jar_bills",
  "category_id": "cat_rent"
}
```

## GET /budgets
List budgets/thresholds for proactive alerts.

## POST /budgets
Create/update a budget threshold (jar/category scope).

```json
{
  "scope_type": "jar",
  "scope_id": "jar_fun",
  "period": "weekly",
  "limit_amount": 1500000,
  "currency": "VND",
  "active": true
}
```

## POST /goals
```json
{ "name": "buy house", "target_amount": 650000000, "horizon_months": 84 }
```

## GET /risk-profile
Returns latest risk profile.

## POST /risk-profile
```json
{ "profile": "balanced", "notes": "moderate volatility" }
```

## POST /chat/stream
SSE stream from AgentCore Runtime.

## GET /audit/{trace_id}
Returns audit record for demo transparency.
