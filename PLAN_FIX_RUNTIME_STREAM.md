# PLAN_FIX_RUNTIME_STREAM (v2 - Dynamic Timeframe + UI Stream Integrity)

## 1) Goal
- Keep existing routing/policy behavior stable.
- Add dynamic timeframe support for all tools that depend on time windows.
- Ensure answer wording and grounding reflect the exact window user asked.
- Fix UI short/truncated answer issue caused by SSE multiline handling.
- Keep backward compatibility and avoid business-data hardcoding.

## 2) Current findings (evidence from code)
- `agent/graph.py:352-376` still buckets summary to `30/60/90d` via `_bucket_days` and `_resolve_summary_range`.
- `agent/graph.py:1516-1546` uses fixed defaults for:
  - anomaly `lookback_days` default 90
  - risk `lookback_days` default 180
  - recurring `lookback_months` default 6
- `src/aws-finance-mcp-server/app/mcp.py:104-112` limits spend schema to enum `30d/60d/90d`.
- `agent/response/facts.py:157` hardcodes risk facts timeframe to `180d`.
- `agent/response/facts.py:212-264` hardcodes anomaly facts to `.90d`.
- `agent/response/insights.py:61` and `agent/response/renderer.py:174` read exact fact id `anomaly.latest_change_point.90d`.
- `agent/response/synthesizer_bedrock.py:140,592+` also assumes anomaly fact id `.90d`.
- `backend/app/routes/chat.py:136` sends full multiline result in one SSE `data:` event.
- `frontend/app/chat/page.tsx:91-95` expects each event part to start with `data:` and splits by `\n\n`; multiline event payload can be partially dropped in UI.

## 3) Phase checklist (status + reason)

### Phase 0 - Baseline mapping
- [x] DONE - Survey router/policy/graph/tools/response/tests/deploy/env done.
- [x] DONE - Confirmed all timeframe-sensitive paths and SSE weak points with file/line evidence.

### Phase 1 - Dynamic timeframe parser in agent
- [x] DONE - Added shared parser in `agent/graph.py` for Vietnamese/English timeframe hints:
  - explicit days: `14 ngay`, `45 days`, `90d`
  - months: `2 thang`, `2 months`
  - relative phrases: `thang nay`, `thang truoc`, `gan day`, `recent`, `this month`
- [x] DONE - Removed summary bucketing (`30/60/90`) for tool input; exact window is preserved and clamped by bounds.
- [x] DONE - Mapped parsed timeframe to tool args:
  - `spend_analytics_v1.range`
  - `anomaly_signals_v1.lookback_days`
  - `risk_profile_non_investment_v1.lookback_days`
  - `recurring_cashflow_detect_v1.lookback_months`
- [x] DONE - Backward compatibility kept:
  - If parsing fails, keep current defaults (summary 30, risk 90/180, recurring 6).

### Phase 2 - MCP contract/schema alignment
- [x] DONE - Updated `src/aws-finance-mcp-server/app/mcp.py`:
  - SpendInput/schema should accept dynamic `Xd` instead of enum-only `30/60/90`.
  - Keep existing values valid to avoid breaking callers.
- [x] DONE - Server-side bounds still enforced by finance functions:
  - spend range 1..365 days (already in `parse_range_days`)
  - anomaly 30..365
  - risk 60..720
  - recurring 3..24 months

### Phase 3 - Grounding + response timeframe consistency
- [x] DONE - Removed hardcoded `.90d` / `.180d` in response facts:
  - In `agent/response/facts.py`, derive risk/anomaly timeframe from actual tool output params.
  - Fact IDs should become dynamic, e.g. `anomaly.latest_change_point.<lookback>d`.
- [x] DONE - Updated consumers to use prefix/dynamic lookup:
  - `agent/response/insights.py`
  - `agent/response/renderer.py`
  - `agent/response/synthesizer_bedrock.py`
- [ ] PENDING - Keep Vietnamese wording clean and consistent:
  - enforce `dong tien rong` wording (no malformed variants)
  - avoid duplicated phrase/value in same sentence.

### Phase 4 - SSE stream integrity (UI truncation fix)
- [x] DONE - Backend framing fix (`backend/app/routes/chat.py`):
  - split multiline result into SSE-compliant `data:` lines per line, then end event by blank line.
- [x] DONE - Frontend parser fix (`frontend/app/chat/page.tsx`):
  - parse SSE events by lines, concatenate all `data:` lines in one event.
  - do not drop event fragments just because event chunk does not start with `data:`.

### Phase 5 - Tests (unit + integration)
- [x] DONE - Agent unit tests:
  - timeframe parsing cases (`thang nay`, `2 thang gan day`, `45 ngay`)
  - tool arg mapping per intent
  - fallback-to-default when no timeframe detected
- [x] DONE - Response tests:
  - dynamic anomaly/risk fact IDs work end-to-end (no hardcoded `.90d` dependency)
  - wording cleanup still passes
- [x] DONE - MCP tests:
  - spend schema accepts dynamic `Xd` values
  - invalid ranges rejected
- [x] DONE - Stream tests:
  - multiline output not truncated in frontend rendering

### Phase 6 - Local validation and evidence logs
- [x] DONE - Ran all relevant unit/integration tests.
- [x] DONE - Ran runtime E2E `/chat/stream` on local backend `http://127.0.0.1:8010` with Vietnamese prompts (with accents).
- [ ] PENDING - Include new dynamic-window prompts on deployed runtime:
  - "2 thang gan day toi co giao dich nao la khong?"
  - "45 ngay qua dong tien cua toi the nao?"
  - "Thang nay co bat thuong nao can luu y?"
- [x] DONE - Exported evidence:
  - `test_results_runtime_stream.txt` (detailed)
  - `results.txt` (summary pass/fail per case)

### Phase 7 - Redeploy MCP + Agent
- [ ] PENDING - Redeploy MCP first (schema/contract changed), then verify gateway `tools/list` and `tools/call`.
- [ ] PENDING - Redeploy Agent runtime with updated env/config.
- [ ] PENDING - Restart local backend with correct auth env and rerun runtime QA for dynamic-window assertions.

## 4) Local test plan (commands)

### 4.1 Unit + integration tests
```powershell
# Repo root
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp

# Agent tests
python -m pytest agent\tests -q

# MCP tests
python -m pytest src\aws-finance-mcp-server\tests -q
```

### 4.2 Start backend local for /chat/stream
```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
$env:AWS_REGION = "us-east-1"
$env:DEV_BYPASS_AUTH = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### 4.3 Run runtime QA suite (writes txt artifacts)
```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
python .\run_qa_tests.py --base-url http://127.0.0.1:8010
```

### 4.4 Quick manual checks
```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
$token = (python .\agent\genToken.py 2>&1 | Select-String '^AccessToken:' | % { ($_ -replace '^AccessToken:\s*','').Trim() })
$body = @{ prompt = "2 thang gan day toi co giao dich nao la khong?" } | ConvertTo-Json -Compress
Invoke-WebRequest -Method POST -Uri "http://127.0.0.1:8010/chat/stream" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json; charset=utf-8" -Body $body
```

## 5) Deploy sequence after code is green

### 5.1 MCP deploy (if changed)
- Deploy service from `src/aws-finance-mcp-server` (App Runner or your current method).
- Verify:
  - `GET /mcp` returns healthy
  - `POST /mcp` `tools/list` includes updated schema
- Verify through gateway using existing smoke script.

### 5.2 Agent deploy
```powershell
cd C:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
# For local backend testing only:
$env:DEPLOY_SKIP_BACKEND_API_BASE_CHECK = "true"
$env:DEPLOY_BACKEND_API_BASE = "http://127.0.0.1:8010"
python .\deploy_agent.py
```

### 5.3 Post-deploy smoke
- Run `python .\run_qa_tests.py --base-url http://127.0.0.1:8010`
- Confirm `results.txt` PASS all required cases.
- Manual UI check in frontend chat: long markdown response should match backend SSE content (not truncated).

## 6) Acceptance criteria
- Dynamic timeframe is respected across all timeframe-sensitive tools.
- No false fallback to hardcoded `90d`/`180d` when user asks different windows.
- UI no longer truncates multiline answers.
- Policy behavior unchanged for investment recommendation deny cases.
- Test logs (`test_results_runtime_stream.txt`, `results.txt`) provide evidence for every claim.
