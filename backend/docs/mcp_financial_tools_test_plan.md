# Runtime -> Gateway -> MCP -> Frontend Demo Plan (Demo-first)

## 1) Scope
Flow muc tieu:
- `Frontend local` -> `Backend local /chat/stream`
- Backend invoke `AgentCore Runtime`
- Runtime call `AgentCore Gateway`
- Gateway route den `finance-mcp` + `kb-mcp`

No API contract change:
- `POST /chat/stream` (backend)
- `POST /mcp` (finance-mcp)

## 2) Required contracts

### 2.1 Runtime env (bat buoc)
- `AWS_REGION=us-east-1`
- `BEDROCK_MODEL_ID=<model>`
- `BEDROCK_KB_ID=<kb-id>`
- `AGENTCORE_GATEWAY_ENDPOINT=https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com`
- `USE_LOCAL_MOCKS=false`
- `BACKEND_API_BASE=<reachable-url>`
- `LOG_LEVEL=info`

### 2.2 Gateway contract
- Target `finance-mcp` synced.
- Tool names co the co prefix: `finance-mcp___<tool_name>`.
- Agent auto resolve prefix bang `tools/list`.

### 2.3 Demo auth mode
- `finance-mcp`: `DEV_BYPASS_AUTH=true`
- Gateway outbound auth cho `finance-mcp`: `No authorization`
- Gateway inbound auth van dung JWT Cognito.

## 3) Phase 0 - Baseline checks

### 3.1 finance-mcp App Runner
```powershell
Invoke-RestMethod -Method GET -Uri "https://<finance-mcp-app-runner>/health"
$body = @{jsonrpc="2.0";id="1";method="tools/list"} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method POST -Uri "https://<finance-mcp-app-runner>/mcp" -ContentType "application/json" -Body $body
```
Ky vong: co du 9 finance tools.

### 3.2 Gateway
Dung AccessToken:
```powershell
$token = "<cognito-access-token>"
$gw = "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
$body = @{jsonrpc="2.0";id="tools-1";method="tools/list"} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method POST -Uri $gw -Headers @{Authorization="Bearer $token"} -ContentType "application/json" -Body $body
```
Ky vong: thay `finance-mcp___...` (9 tools) va `...___retrieve_from_aws_kb`.

### 3.3 Security hard requirement
- Rotate `SUPABASE_SERVICE_ROLE_KEY` neu da lo.
- Update key moi vao App Runner env cua `finance-mcp`.

## 4) Phase 1 - Deploy runtime config

Deploy runtime tu `agent`:
```bash
cd agent
agentcore deploy --auto-update-on-conflict \
  --env AWS_REGION=us-east-1 \
  --env BEDROCK_MODEL_ID=<model-id> \
  --env BEDROCK_KB_ID=<kb-id> \
  --env AGENTCORE_GATEWAY_ENDPOINT=https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com \
  --env USE_LOCAL_MOCKS=false \
  --env BACKEND_API_BASE=<reachable-url> \
  --env LOG_LEVEL=info
```

Sau deploy:
- lay runtime ARN.
- set `AGENTCORE_RUNTIME_ARN` trong `backend/.env`.

## 5) Phase 2 - Backend local stream proxy

### 5.1 `backend/.env`
- `AGENTCORE_RUNTIME_ARN=<runtime-arn>`
- `COGNITO_USER_POOL_ID=<pool-id>`
- `COGNITO_CLIENT_ID=<client-id>`
- `AWS_REGION=us-east-1`
- `DEV_BYPASS_AUTH=false`

### 5.2 Run backend
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### 5.3 Smoke `/chat/stream`
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\backend
.\scripts\run_chat_stream_smoke.ps1 -BackendBaseUrl "http://127.0.0.1:8010" -AuthToken "<access-token>" -Prompt "Tom tat chi tieu 30 ngay"
```

## 6) Phase 3 - Frontend local demo

### 6.1 `frontend/.env.local`
```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8010
```

### 6.2 Run frontend
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\frontend
npm run dev
```

### 6.3 Demo prompts
- `Tom tat chi tieu 30 ngay`
- `Lap ke hoach tiet kiem 60 trieu trong 6 thang`
- `Gia su giam an ngoai 15 phan tram thi dong tien thay doi sao?`
- `Toi co nen mua co phieu X ngay hom nay khong?`

Ky vong:
- co trace id
- co disclaimer
- co citations

## 7) Phase 4 - Mandatory E2E scripts

### 7.1 Direct finance-mcp smoke
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\src\aws-finance-mcp-server
$seed = (Get-Content ..\..\backend\tmp\seed_manifest_single_user.json | ConvertFrom-Json).seed_user_id
.\scripts\run_finance_mcp_smoke.ps1 -BaseUrl "https://<finance-mcp-app-runner>" -SeedUserId $seed
```

### 7.2 Gateway smoke (new script)
```powershell
cd c:\HCMUS\PYTHON\jars-fintech-agentcore-mvp\src\aws-finance-mcp-server
$seed = (Get-Content ..\..\backend\tmp\seed_manifest_single_user.json | ConvertFrom-Json).seed_user_id
.\scripts\run_gateway_finance_smoke.ps1 `
  -GatewayEndpoint "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com" `
  -SeedUserId $seed `
  -AuthToken "<access-token>"
```

Ky vong:
- tools/list pass
- call `spend_analytics_v1` pass
- call `what_if_scenario_v1` pass

## 8) Acceptance criteria
1. Runtime calls Gateway only (no localhost).
2. Gateway calls `finance-mcp` and returns SQL truth numbers.
3. 3 new tools work in agent orchestration:
- `recurring_cashflow_detect_v1`
- `goal_feasibility_v1`
- `what_if_scenario_v1`
4. Frontend demo pass 4 prompts with trace + disclaimer.
5. Old leaked secret is rotated.

## 9) Error map and fix
1. `401 Missing token` at finance-mcp:
- demo mode: set `DEV_BYPASS_AUTH=true`, gateway outbound `No authorization`.

2. `Tool ... not found`:
- sync target in Gateway.

3. Runtime timeout:
- set reachable `BACKEND_API_BASE` in runtime env.

4. Frontend `/chat/stream` 401:
- missing/invalid Cognito AccessToken.

## 10) Hardening after demo
1. Turn `DEV_BYPASS_AUTH=false` on finance-mcp.
2. Add proper outbound auth from Gateway to finance-mcp.
3. Keep user scope mapping deterministic (`sub`/principal).
4. Move `SUPABASE_SERVICE_ROLE_KEY` to Secrets Manager.
5. Add Cedar deny rules for invest/buy/sell execution intent.
