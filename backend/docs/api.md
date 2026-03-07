# API Contracts (Current Runtime)

Base URL: `http://localhost:8010`

## Auth

- Protected endpoints use `Authorization: Bearer <access_token>`.
- Local MVP bypass: set `DEV_BYPASS_AUTH=true` in `backend/.env`.

## Health

### `GET /health`

Returns API liveness:

```json
{ "status": "ok" }
```

## Chat

### `POST /chat/stream`

Streams advisory response as SSE.

Request:

```json
{ "prompt": "Tôi muốn xem tổng quan dòng tiền tháng này" }
```

Response:

- `Content-Type: text/event-stream; charset=utf-8`
- Emits `data:` events for advisory text, trace id, tool list, response mode, disclaimer.

## Goals

### `POST /goals`

```json
{
  "name": "buy house",
  "target_amount": 650000000,
  "horizon_months": 84
}
```

Response:

```json
{ "status": "ok", "goal": { "name": "buy house", "target_amount": 650000000, "horizon_months": 84 } }
```

## Risk Profile

### `GET /risk-profile`

Returns latest user profile:

```json
{ "current": { "profile": "balanced", "notes": "moderate volatility", "user_id": "demo-user", "version": 1 } }
```

### `POST /risk-profile`

```json
{ "profile": "balanced", "notes": "moderate volatility" }
```

## Notifications

### `GET /notifications`

Returns user-scoped notifications:

```json
{ "items": [] }
```

### `POST /notifications`

```json
{ "title": "Runway alert", "detail": "Runway below 6 months", "trace_id": "trc_abc123" }
```

## Audit

### `POST /audit`

```json
{
  "trace_id": "trc_abc123",
  "event_type": "agent_summary",
  "payload": { "summary": "...", "tool_calls": ["spend_analytics_v1"] }
}
```

### `GET /audit/{trace_id}`

Returns audit payload plus `tool_chain` for matching trace id.

## Notes

- Financial tool execution is handled by Agent Runtime through MCP gateway (`agent/tools.py`).
- Backend remains a thin entry layer and does not expose legacy `/transactions`, `/forecast`, or `/decision/*` endpoints.
