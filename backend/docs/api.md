# API Contracts (MVP)

Base URL: `http://localhost:8000`

## POST /transactions/transfer
Body:
```json
{ "jar_id": "jar_house", "category_id": "cat_rent", "amount": 5000000, "counterparty": "Landlord" }
```

## GET /transactions?range=30d|60d
Returns user-scoped list.

## GET /aggregates/summary?range=30d|60d
Returns totals and largest transaction.

## GET /notifications
Returns Tier1 insights.

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
