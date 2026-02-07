# Ke Hoach Trien Khai va Test MCP Financial Tools (Local truoc, Cloud sau)

## Muc tieu
1. MCP financial tools chay dung va on dinh.
2. Du lieu dau vao lay tu Supabase seeded user that.
3. Agent local goi duoc qua MCP local (khong fallback mock).
4. Sau khi local pass, noi cloud: App Runner + AgentCore Gateway + AgentCore Runtime.

## Contract can giu on dinh

### MCP endpoint
- `GET /mcp` health
- `POST /mcp` JSON-RPC: `initialize`, `tools/list`, `tools/call`

### Financial tool names
- `spend_analytics_v1`
- `anomaly_signals_v1`
- `cashflow_forecast_v1`
- `jar_allocation_suggest_v1`
- `risk_profile_non_investment_v1`
- `suitability_guard_v1`

### Output envelope bat buoc moi tool
- `trace_id`
- `version`
- `params_hash`
- `sql_snapshot_ts`
- `audit` (`tool_name`, `duration_ms`, `policy_decision`)

### External engines fields
- `anomaly_signals_v1.external_engines`: `river_adwin`, `pyod_ecod`, `kats_cusum`
- `cashflow_forecast_v1.external_engines`: `darts_exponential_smoothing`

## Phase 1 - Chuan bi du lieu va env local

### 1) Xac nhan seed hop le
Kiem tra:
- `backend/tmp/seed_manifest_single_user.json`
- `backend/tmp/seed_validation_single_user.json`

Ky vong:
- `validation_summary.all_pass = true`
- Co `seed_user_id`

### 2) Cau hinh `backend/.env`
```env
SUPABASE_URL=<your-project-url>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SQL_TIMEOUT_SEC=20
DEV_BYPASS_AUTH=true
USE_DARTS_FORECAST=true
```

### 3) Cai dependencies backend
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## Phase 2 - Test MCP backend local truc tiep

### 1) Chay backend
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### 2) Health check
```powershell
Invoke-RestMethod -Method GET -Uri http://127.0.0.1:8010/mcp
```

### 3) tools/list check
```powershell
$body = @{ jsonrpc = "2.0"; id = "tools-1"; method = "tools/list" } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8010/mcp -ContentType "application/json" -Body $body
```

### 4) tools/call check tu dong cho 6 tools
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
.\backend\scripts\run_mcp_financial_smoke.ps1 -BaseUrl "http://127.0.0.1:8010"
```

Luu y:
- Script uu tien `seed_user_id` trong `backend/tmp/seed_manifest_single_user.json`.
- Neu muon test user khac, truyen `-SeedUserId` va token phu hop.

Neu muon chi dinh user:
```powershell
.\backend\scripts\run_mcp_financial_smoke.ps1 -BaseUrl "http://127.0.0.1:8010" -SeedUserId "<seed_user_id>"
```

## Phase 3 - Test agent local qua MCP local

### 1) Cau hinh `agent/.env`
```env
AGENTCORE_GATEWAY_ENDPOINT=http://127.0.0.1:8010/mcp
USE_LOCAL_MOCKS=false
BACKEND_API_BASE=http://127.0.0.1:8010
```

### 2) Chay agent local
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\agent
.\.venv\Scripts\python.exe main.py
```

### 3) Prompt test
- Summary: "Tom tat chi tieu 30 ngay"
- Risk: "Toi co rui ro chi tieu bat thuong khong?"
- Planning: "Phan bo jar thang nay giup toi"
- Invest/sell: "Toi co nen mua co phieu khong?" (phai education-only)

### 4) Ky vong
- `tool_calls` dung theo intent
- Co disclaimer + trace_id
- Khong dung mock data

## Phase 4 - Regression local

### Backend tests
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"
```

### Agent tests
```powershell
agent\.venv\Scripts\python.exe -m unittest discover -s agent\tests -p "test_*.py"
```

## Phase 5 - Cloud rollout (App Runner + Gateway)

### 1) Deploy backend moi len App Runner
Ky vong endpoint:
- `GET https://<backend-app-runner>/mcp`
- `POST https://<backend-app-runner>/mcp` (`tools/list`)

### 2) Cau hinh AgentCore Gateway
- Giu target cu: `kb-mcp`
- Them target moi: `finance-mcp -> https://<backend>/mcp`

### 3) Validate Gateway
- `tools/list` thay ca KB + financial tools (ten co the bi prefix theo target)

## Phase 6 - Runtime E2E that

### 1) Runtime env
- `AGENTCORE_GATEWAY_ENDPOINT=https://<gateway>/mcp`
- Tuyet doi khong dung localhost

### 2) Invoke runtime
- Dung JWT hop le
- Kiem tra tool chain di qua Gateway

### 3) Ky vong
- Financial output lay tu Supabase seeded user
- Co trace/disclaimer/citations theo policy

## Edge cases bat buoc kiem
1. Thieu table schema tren Supabase -> loi ro rang
2. `user_id` request khac auth subject -> Forbidden
3. Thieu du lieu lich su:
- `pyod_ecod.ready=false`
- `kats_cusum.ready=false`/`available=false`
- `darts` fallback ro rang
4. Tool name bi prefix tu Gateway target -> agent van resolve dung
5. DB timeout -> loi deterministic, khong crash toan flow

## Acceptance criteria
1. Local MCP pass ca 6 tools voi seeded user that
2. `anomaly_signals_v1` co output tu River/PyOD (+Kats state)
3. `cashflow_forecast_v1` co Darts adapter state/fallback
4. Agent local goi MCP local voi `USE_LOCAL_MOCKS=false`
5. Cloud pass: Runtime -> Gateway -> finance-mcp
6. Runtime that khong phu thuoc localhost
