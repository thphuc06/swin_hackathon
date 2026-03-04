# Tech Stack + System Flow (Snapshot theo code hiện tại)

_Cập nhật: 2026-03-04_

## 1) Tóm tắt nhanh

Hệ thống của bạn hiện đang theo kiến trúc nhiều tầng:

`Frontend (Next.js)` -> `Backend BFF (FastAPI, SSE)` -> `Agent Runtime (Bedrock AgentCore + LangGraph)` -> `AgentCore Gateway (MCP JSON-RPC)` -> `Finance MCP Server (FastAPI)` -> `Supabase (REST)`

Ngoài luồng trên, agent còn có **KB local trong repo** để trích dẫn/chính sách dịch vụ, và có `workers/` cho Tier1 signals/alerts.

## 2) Tech stack chi tiết

## 2.1 Frontend (`frontend/`)
- Framework: `Next.js 14.2.5` + `React 18.3.1`
- UI: `TailwindCSS 3.4.10`
- Markdown render trong chat: `react-markdown`, `remark-gfm`
- TypeScript: `5.5.4`

## 2.2 Backend BFF (`backend/`)
- Framework: `FastAPI 0.112.2`, `Uvicorn 0.30.6`
- Auth: `python-jose 3.3.0` (JWT/Cognito verify)
- HTTP client: `requests 2.32.3`
- Data lớp backend hiện tại: `InMemoryStore` (goals/risk/notifications/audit) + client Supabase REST (khi cần)
- Cơ chế response chat: `SSE streaming` qua `/chat/stream`

## 2.3 Agent Runtime (`agent/`)
- Runtime container: `bedrock-agentcore`
- Orchestration: `LangGraph 0.2.53`
- LLM routing/synthesis: AWS Bedrock (`boto3`)
- Validation: `jsonschema`
- Retry/fault tolerance: `tenacity`, circuit-breaker nội bộ cho Gateway
- Session memory: in-memory TTL store
- Observability: trace events + exporter (CloudWatch/noop)

## 2.4 MCP tài chính (`src/aws-finance-mcp-server/`)
- Framework: `FastAPI`
- Giao thức: MCP dạng `JSON-RPC` tại `POST /mcp`
- Dữ liệu: `Supabase REST`
- Analytics libs: `numpy`, `pandas`, `statsmodels`, `u8darts`, `river`, `pyod`, `ruptures`

## 2.5 KB Retrieval MCP (`src/aws-kb-retrieval-server/`)
- Node.js + TypeScript MCP server
- Dùng AWS Bedrock Knowledge Base Retrieve API
- **Lưu ý:** code agent hiện tại mặc định dùng **KB local**, server này là tùy chọn

## 2.6 Workers (`workers/`)
- Python workers cho aggregation/trigger + Tier1 alert pipeline
- MCP client nội bộ để gọi finance tools
- Queue/state adapter hiện là in-memory (skeleton để swap SQS/DB sau)

## 2.7 AWS/Infra tích hợp
- Amazon Bedrock AgentCore Runtime
- AgentCore Gateway
- Cognito JWT
- Supabase
- App Runner (cho MCP server)
- IaC: mới ở mức skeleton (`iac/`), chưa là pipeline deploy chính

## 3) Flow hệ thống hiện tại

## 3.1 Flow chat chính (đang chạy thật)
1. Frontend gọi `POST /chat/stream` ở backend.
2. Backend verify JWT (hoặc bypass dev), sau đó forward prompt đến Agent Runtime.
3. Agent entrypoint resolve `authorization`, `user_id`, `session_id`.
4. Orchestrator chạy graph theo phase (v2 wrapper):
   - `intake` (encoding gate)
   - `plan` (intent extraction + routing)
   - `safety` (suitability guard)
   - `select_agent`
   - `execute_tools` (tool bundle theo intent, chạy song song)
   - `aggregate` (context + KB)
   - `respond` (LLM/template/fallback)
   - `persist_memory` (audit + session memory)
5. Tool calls đi qua AgentCore Gateway (`tools/list`, `tools/call`) -> Finance MCP -> Supabase.
6. Backend stream ngược SSE về frontend gồm body + metadata (`Trace`, `Tools`, `Citations`, `Disclaimer`, `ResponseMode`, `Fallback`, `ReasonCodes`).

## 3.2 Flow routing và response
- Intents hỗ trợ: `summary`, `risk`, `planning`, `scenario`, `invest`, `out_of_scope`
- Router: semantic extraction + policy thresholds + clarify question (tối đa theo config)
- Safety: `suitability_guard_v1` luôn chạy sớm
- Response:
  - `template`
  - `llm_shadow` (mặc định code): chạy LLM pipeline nhưng trả body legacy
  - `llm_enforce`: trả trực tiếp LLM grounded response
- Nếu synthesis/grounding fail: fallback facts-only renderer

## 3.3 Flow KB/retrieval
- Mặc định: KB markdown local (`kb/*.md` + `kb_index.csv`) được load vào memory
- Có dynamic service matcher:
  - signal-based matching
  - optional semantic embedding (Titan embedding model)
- Adapter retrieval có thể swap sang OpenSearch qua env

## 3.4 Flow Tier1 workers
- `aggregate_worker`: gọi recurring + forecast, tạo signals
- `trigger_worker`: tính runway/risk flags từ forecast
- `tier1 runner`: event -> processor -> alert store (in-memory)

## 4) Hệ thống hiện tại làm được gì

## 4.1 Advisory chat có kiểm soát
- Hỏi đáp tài chính cá nhân theo ngữ cảnh user
- Clarifying question khi intent chưa đủ rõ
- Trả kèm trace/citation/disclaimer/tool chain
- Hỗ trợ prompt tiếng Việt (có lớp chống mojibake + cleanup wording)

## 4.2 9 financial tools qua MCP Gateway
1. `spend_analytics_v1`: tổng quan thu/chi/net cashflow, top merchant, budget drift
2. `anomaly_signals_v1`: phát hiện bất thường chi tiêu/thu nhập/category/runway bằng thống kê + OSS detectors
3. `cashflow_forecast_v1`: forecast `daily_30` hoặc `weekly_12`, có confidence band
4. `jar_allocation_suggest_v1`: gợi ý phân bổ jar theo thu nhập/goal/hành vi
5. `risk_profile_non_investment_v1`: risk band phi đầu tư (volatility, runway, overspend)
6. `suitability_guard_v1`: chặn execution/recommendation buy-sell, education-only
7. `recurring_cashflow_detect_v1`: phát hiện khoản recurring + drift alerts
8. `goal_feasibility_v1`: đánh giá khả thi mục tiêu tiết kiệm
9. `what_if_scenario_v1`: so sánh biến thể scenario với baseline

## 4.3 Safety/compliance/reliability
- Suitability guard bắt buộc trước khi execute bundle
- Policy engine cho phép deny tool theo adapter (`simple` / `cedar`)
- Grounding validator chống số liệu không có fact
- Circuit breaker + degraded fallback cho Gateway/tool failures
- Audit payload ghi lại routing, evidence, answer plan, tool chain

## 4.4 API backend đang expose
- `POST /chat/stream`
- `POST /goals`
- `GET|POST /risk-profile`
- `GET|POST /notifications`
- `POST /audit`, `GET /audit/{trace_id}`
- `GET /health`

## 4.5 UI hiện có
- Màn chat: kết nối thật tới backend stream
- Dashboard/Transfer/Inbox/Login: chủ yếu dữ liệu mock/demo UI

## 5) Trạng thái thực tế: phần production vs phần demo

## 5.1 Đang sẵn sàng chạy E2E chính
- Chat -> backend -> runtime -> gateway -> finance MCP -> Supabase
- Tool orchestration + trace/audit + disclaimer flow
- Suitability guard cho các truy vấn mang tính đầu tư

## 5.2 Còn ở mức mock/skeleton/chưa harden hoàn toàn
- Nhiều màn frontend ngoài chat vẫn dùng mock data
- Backend store cho goals/risk/notifications/audit đang in-memory
- Session memory của agent là in-memory TTL (không durable qua restart)
- IaC chưa là đường deploy chính (mới skeleton)
- Stock external agent có code nhưng mặc định feature flag đang tắt
- Agent auth provider mặc định là `jwt` lightweight decode; verify Cognito đầy đủ cần bật adapter `cognito`

## 6) Kết luận ngắn

Codebase hiện tại là một **MVP advisory platform có luồng chat thật và tooling tài chính khá đầy đủ**, tập trung mạnh vào:
- orchestration + safety,
- deterministic financial analytics qua MCP,
- explainability (trace/citations/reason codes).

Điểm cần ưu tiên tiếp theo nếu muốn production cứng: thay phần in-memory bằng persistent store, nối các màn frontend còn mock vào API thật, và chuẩn hóa IaC/deploy pipeline.
