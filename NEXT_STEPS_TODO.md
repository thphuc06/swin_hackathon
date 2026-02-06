# Next Steps TODO (Forecast + Cashflow Agent)

## 0) Current status
- [x] 9 financial tools implemented (ingest/normalize/recurring/forecast/runway/decision/what-if)
- [x] New backend APIs exposed under `/transactions`, `/forecast`, `/decision`, `/audit`
- [x] Agent routing updated for intents: `house`, `saving`, `invest`
- [x] Unit tests passing:
  - Backend: 6 tests
  - Agent: 3 tests
- [x] Smoke test HTTP run successfully on local backend

## 1) What to do next (priority)

### P0 - Verify end-to-end locally (do now)
- [ ] Start backend and run endpoint checks manually
- [ ] Start frontend and verify user flows in UI
- [ ] Start local agent and verify `/chat/stream` path calls tool chain correctly

### P1 - Harden MVP quality
- [ ] Add more statement parser coverage (bank-specific CSV formats)
- [ ] Add explicit error codes for parser quality warnings
- [ ] Add regression tests for edge prompts (mixed Vietnamese + English)
- [ ] Add audit replay test (`GET /audit/{trace_id}` returns full tool chain)

### P2 - Deployable integration
- [ ] MCP/Gateway schema mapping for 9 tool names
- [ ] Cedar policy rules for tool scope and PII boundaries
- [ ] Deploy backend public URL and set `BACKEND_API_BASE` in runtime
- [ ] Re-deploy agent runtime with updated env vars

### P3 - Phase B connector
- [ ] Replace `MockExternalCashflowProvider` with first real provider adapter
- [ ] Keep response contract unchanged
- [ ] Add provider failover and timeout handling

## 2) How to test locally

## 2.1 Run backend
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
$env:DEV_BYPASS_AUTH="true"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

## 2.2 Run tests
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
python -m unittest discover -s backend/tests -p "test_*.py"
.\agent\.venv\Scripts\python.exe -m unittest discover -s agent/tests -p "test_*.py"
python -m compileall backend/app agent workers backend/tests agent/tests
```

## 2.3 API smoke checks
Use any API client (Postman/Insomnia/PowerShell). Minimum cases:
- [ ] `GET /health` -> `status=ok`
- [ ] `GET /forecast/cashflow?range=90d` -> each point has `p10/p50/p90`
- [ ] `POST /forecast/runway` -> returns `runway_months` + `risk_flags`
- [ ] `POST /decision/savings-goal` -> returns `grade`, `metrics`, `trace_id`
- [ ] `POST /decision/house-affordability` -> returns `DTI`, `monthly_payment`
- [ ] `POST /decision/investment-capacity` -> includes guardrail `education_only=true`
- [ ] `POST /decision/what-if` -> returns `scenario_comparison`, `best_variant_by_goal`
- [ ] `POST /transactions/import/statement` -> returns `quality_score`, `parse_warnings`, `imported_count`

## 3) Prompt acceptance test (chat)

- [ ] House case:
  - Prompt: `Toi muon mua nha 3 ty, co 900 trieu`
  - Expect: uses `evaluate_house_affordability`, `forecast_cashflow_core`, `simulate_what_if`

- [ ] Savings case:
  - Prompt: `Moi thang toi tiet kiem duoc bao nhieu de dat 500 trieu trong 24 thang?`
  - Expect: uses `evaluate_savings_goal`

- [ ] Investment case:
  - Prompt: `Toi co nen dau tu them khong?`
  - Expect: uses `evaluate_investment_capacity`
  - Must include education-only limitation (no buy/sell/ticker timing advice)

## 4) Deployment checklist

- [ ] Backend:
  - [ ] Deploy FastAPI service (ECS/Lambda/API Gateway)
  - [ ] Set production env vars
- [ ] Agent:
  - [ ] Set `BACKEND_API_BASE` to public backend
  - [ ] Set `AGENTCORE_GATEWAY_ENDPOINT`, `BEDROCK_KB_ID`
  - [ ] Deploy runtime and validate `/chat/stream`
- [ ] Security:
  - [ ] Disable `DEV_BYPASS_AUTH`
  - [ ] Rotate and secure secrets
  - [ ] Verify policy enforcement logs

## 4.1 AgentCore deploy reminder (important)

- [ ] Do not rely on local `agent/.env` when deploying runtime.
- [ ] `agent/.dockerignore` excludes `.env`, so runtime needs explicit `--env` params.
- [ ] Always pass these envs during deploy:
  - `AWS_REGION`
  - `BEDROCK_MODEL_ID`
  - `BACKEND_API_BASE` (must be public URL, not localhost)
  - `BEDROCK_KB_ID`
  - `AGENTCORE_GATEWAY_ENDPOINT`
  - `LOG_LEVEL`

Use this command template:
```bash
cd c:/HCMUS/PYTHON/jars-fintech-agentcore-mvp/agent
agentcore deploy --auto-update-on-conflict \
  --env AWS_REGION=us-east-1 \
  --env BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
  --env BACKEND_API_BASE=https://<public-backend-url> \
  --env BEDROCK_KB_ID=<your_kb_id> \
  --env AGENTCORE_GATEWAY_ENDPOINT=https://<gateway-id>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp \
  --env LOG_LEVEL=info
```

Quick post-deploy checks:
- [ ] `agentcore status`
- [ ] `agentcore invoke '{"prompt":"Hello"}'`
- [ ] Verify response is not fallback template and not localhost mock numbers.

## 5) Nice-to-have improvements
- [ ] Add robust Excel/PDF parser pipeline (Textract/Document AI adapter)
- [ ] Add structured metrics dashboard for forecast error and decision usage
- [ ] Add rate-limit + retry policy for all tool calls
