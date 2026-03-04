# Manual TODO - Complete 3 Phases + E2E

Date: February 27, 2026
Scope: Tasks that must be done manually (credentials, infra, deploy, approvals) to finish all 3 phases and run complete E2E.

---

## 0) Final Target

- Local development runs stably with the new structure.
- Staging runs true end-to-end (API -> Orchestrator -> Tool Plane -> External Stock Agent).
- All test suites pass (unit/integration/contract/e2e/workers/mcp).

---

## 1) Phase 0 - Foundation (manual tasks)

### 1.1 Required configuration (staging/prod)
- [ ] Provision env vars for external Stock Agent:
  - [ ] `STOCK_AGENT_EXTERNAL_ENABLED=true`
  - [ ] `STOCK_AGENT_EXTERNAL_BASE_URL`
  - [ ] `STOCK_AGENT_EXTERNAL_ENDPOINT_PATH`
  - [ ] `STOCK_AGENT_EXTERNAL_AUTH_TOKEN`
  - [ ] timeout/retry/circuit-breaker vars
- [ ] Provision token/endpoint for Gateway/MCP if using cloud path.

### 1.2 Deploy
- [ ] Redeploy Agent runtime (new code).
- [ ] Redeploy backend service.
- [ ] Redeploy finance MCP service.
- [ ] Redeploy workers.

### 1.3 Mandatory post-deploy validation
- [ ] Test invest flow with Stock Agent success.
- [ ] Test invest flow with Stock Agent failure and confirm fallback.
- [ ] Confirm trace fields exist in logs/response:
  - [ ] `trace_id`
  - [ ] `request_id`
  - [ ] `call_id`

---

## 2) Phase 1 - Hardening (manual tasks)

### 2.1 Policy/runtime mode decisions
- [ ] Finalize policy mode in real environments:
  - [ ] `POLICY_ADAPTER=simple` (temporary) or `cedar`
- [ ] If Cedar is enabled:
  - [ ] `CEDAR_POLICY_ENDPOINT`
  - [ ] `CEDAR_POLICY_AUTH_TOKEN`
  - [ ] Choose `CEDAR_POLICY_FAIL_OPEN` vs fail-closed

### 2.2 Auth mode decisions
- [ ] Finalize auth provider:
  - [ ] `AUTH_PROVIDER=jwt` (local/dev)
  - [ ] or `AUTH_PROVIDER=cognito` (staging/prod)
- [ ] If Cognito is enabled:
  - [ ] `COGNITO_USER_POOL_ID`
  - [ ] `COGNITO_CLIENT_ID`
  - [ ] `COGNITO_REGION`
  - [ ] Disable `AUTH_DEV_BYPASS` outside dev

### 2.3 Hardening tests
- [ ] Run network/tool-timeout fault tests to verify graceful degradation.
- [ ] Verify `reason_codes` in `response_meta` are meaningful and stable.

---

## 3) Phase 2/3 - Scale prep + AWS swap readiness (manual tasks)

### 3.1 Retrieval adapter (local vs OpenSearch)
- [ ] Finalize current mode:
  - [ ] `RETRIEVAL_ADAPTER=local` (recommended now to save cost)
- [ ] If enabling OpenSearch later:
  - [ ] `OPENSEARCH_ENDPOINT`
  - [ ] `OPENSEARCH_INDEX_NAME`
  - [ ] `OPENSEARCH_API_KEY`
  - [ ] mapping/index strategy (VN/EN)

### 3.2 Observability exporter
- [ ] Finalize mode:
  - [ ] `OBSERVABILITY_EXPORTER=structured` (local-first)
  - [ ] or `cloudwatch`
- [ ] If CloudWatch is enabled:
  - [ ] `CLOUDWATCH_ENABLED=true`
  - [ ] `CLOUDWATCH_LOG_GROUP`
  - [ ] `CLOUDWATCH_LOG_STREAM`
  - [ ] `CLOUDWATCH_REGION`
  - [ ] IAM permissions: `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`

### 3.3 Tier1 pipeline real infra
- [ ] Choose real queue (SQS/Kafka/etc).
- [ ] Choose real state store (Aurora/Supabase/etc).
- [ ] Choose alert channels (push/email/both).
- [ ] Finalize event schema from Tier2 -> Tier1.

### 3.4 CI/CD
- [ ] Confirm GitHub Actions is the primary CI.
- [ ] Provision CI secrets.
- [ ] Finalize timeout/budget for heavy dependency jobs.
- [ ] Enable release gate: fail if smoke/E2E fails.

---

## 4) Full E2E test checklist

## 4.1 Local (already runnable)
- [ ] `agent` tests:
  - `agent\.venv\Scripts\python.exe -m unittest discover -s agent\tests -p "test_*.py"`
- [ ] `finance-mcp` tests:
  - `backend\.venv\Scripts\python.exe -m unittest discover -s src\aws-finance-mcp-server\tests -p "test_*.py"`
- [ ] `workers` tests:
  - `python -m unittest discover -s workers\tests -p "test_*.py"`

## 4.2 Staging E2E (must be run manually)
- [ ] `/chat/stream` summary flow.
- [ ] `/chat/stream` planning flow.
- [ ] Invest flow + stock external success.
- [ ] Invest flow + stock external timeout/error fallback.
- [ ] Verify tool routing by intent bundle.
- [ ] Verify audit chain + trace correlation across services.

---

## 5) Definition of Done (3 phases)

- [ ] Local-first structure is stable, all tests are green.
- [ ] Staging true E2E passes for all core flows.
- [ ] Cloud adapters (if enabled) are config-driven, no core-code edits.
- [ ] CI runs by layer and blocks merge/release on failures.

---

## 6) Current recommended config (for fast, low-cost development)

- [ ] `RETRIEVAL_ADAPTER=local`
- [ ] `POLICY_ADAPTER=simple`
- [ ] `AUTH_PROVIDER=jwt`
- [ ] `AUTH_DEV_BYPASS=true` (dev only)
- [ ] `OBSERVABILITY_EXPORTER=structured`
- [ ] `CLOUDWATCH_ENABLED=false`

---

## 7) Add-on checklist for stable staging/cloud testing (not local-dependent)

### 7.1 Env profile and reset strategy
- [ ] Create clear env profiles:
  - [ ] `.env.local`
  - [ ] `.env.staging`
  - [ ] `.env.prod`
- [ ] Do not set global shell env vars manually; always load by profile.
- [ ] Add a quick reset script to return to default profile after tests.

### 7.2 Preflight before non-local E2E
- [ ] Confirm service health before tests:
  - [ ] Agent runtime endpoint
  - [ ] Backend endpoint
  - [ ] MCP/Gateway endpoint
  - [ ] Stock external endpoint
- [ ] Confirm MCP service is not paused (App Runner).
- [ ] Confirm token/secret validity and scope.
- [ ] Confirm reliability flags are enabled correctly:
  - [ ] `DEGRADED_MODE_ENABLED=true`
  - [ ] `GATEWAY_CIRCUIT_BREAKER_ENABLED=true`
  - [ ] `GATEWAY_BREAKER_FAILURE_THRESHOLD`
  - [ ] `GATEWAY_BREAKER_RESET_SECONDS`
- [ ] Confirm Bedrock guardrail config per environment:
  - [ ] `BEDROCK_GUARDRAIL_ID`
  - [ ] `BEDROCK_GUARDRAIL_VERSION`

### 7.3 Mandatory staging E2E matrix
- [ ] Query 1: "Toi muon phan bo danh muc nganh ngan hang phu hop khau vi rui ro vua."
  - [ ] Tool route is correct
  - [ ] No thrown exception
  - [ ] Safe disclaimer present
- [ ] Query 2: "So sanh 2 co phieu X va Y roi khuyen nghi ty trong."
  - [ ] Tool route is correct
  - [ ] No thrown exception
  - [ ] Safe disclaimer present
- [ ] Fault test A: MCP/Gateway unreachable
  - [ ] Agent still responds in degraded mode
  - [ ] Safety node does not hard-fail
- [ ] Fault test B: Stock external timeout/unavailable
  - [ ] Fallback payload + correct reason code

### 7.4 Mandatory runtime evidence (not just pass/fail)
- [ ] Save artifacts for every run:
  - [ ] request/response json
  - [ ] reason_codes
  - [ ] ordered tool_calls
  - [ ] tool_errors (if any)
- [ ] Full cross-service correlation IDs:
  - [ ] `trace_id`
  - [ ] `request_id`
  - [ ] `call_id`
- [ ] Confirm guardrail metadata in response/audit:
  - [ ] `guardrail_enabled`
  - [ ] `guardrail_id`
  - [ ] `guardrail_version`

### 7.5 CI gate for non-local tests
- [ ] Split `staging-smoke` and `staging-e2e` jobs (manual trigger or release branch trigger).
- [ ] Enforce release gate: block release if any of 3 mandatory cases fail (Q1/Q2/Gateway-down).
- [ ] Define timeout + retry policy to avoid false-fails.

### 7.6 Post-test runbook
- [ ] Restore env profile to standard values.
- [ ] Re-pause cloud resources that should be paused for cost control.
- [ ] Record test results + opened issues in release notes/test report.

### 7.7 Recommended additions for repeatable stability
- [ ] Have resettable staging test data (seed script/idempotent) to avoid drifting results.
- [ ] Maintain expected assertion table per flow (`status`, `fallback_used`, key `reason_codes`).
- [ ] Maintain dedicated non-local runner scripts:
  - [ ] `scripts/preflight_staging.ps1`
  - [ ] `scripts/run_staging_smoke.ps1`
  - [ ] `scripts/run_staging_e2e.ps1`

---

## 8) Phase 2 implementation status (code-level) + remaining manual actions

### 8.1 Implemented in code (local/runtime)
- [x] Session memory integrated into runtime flow:
  - load before planner/router
  - save after respond/memory_update
  - TTL + redaction + max-turn constraints
- [x] Tool-level tracing emitted for every tool call:
  - start/end
  - latency_ms
  - status
  - retry_count (if available)
  - error_code
- [x] Added tool-metrics snapshot aggregation (`ok_rate`, `failure_rate`, `p50/p95 latency`, `error_codes`) from tool trace events.
- [x] Added integration tests for memory/tracing paths.

### 8.2 Remaining staging/prod actions
- [ ] Set session memory env:
  - [ ] `SESSION_MEMORY_ENABLED=true`
  - [ ] `SESSION_MEMORY_TTL_SECONDS`
  - [ ] `SESSION_MEMORY_MAX_TURNS`
  - [ ] `SESSION_MEMORY_REDACT_KEYS`
- [ ] Choose observability exporter mode:
  - [ ] `OBSERVABILITY_EXPORTER=structured` or `cloudwatch`
  - [ ] If `cloudwatch`: verify IAM + log group/stream/region
- [ ] Run follow-up tests with the same `session_id` on staging to verify memory reuse.
- [ ] Verify `tool_call` and `session_memory` trace events are present in logs/exporter.

### 8.3 Checklist to enable real model calls later
- [ ] Enable model routing:
  - [ ] `BEDROCK_MODEL_ID`
  - [ ] `RESPONSE_MODE=llm_shadow` (safe rollout first)
  - [ ] then `RESPONSE_MODE=llm_enforce` after stability
- [ ] Enable guardrail fully:
  - [ ] `BEDROCK_GUARDRAIL_ID`
  - [ ] `BEDROCK_GUARDRAIL_VERSION`
- [ ] Re-run mandatory staging tests (Q1/Q2/Gateway-down) before release.

---

## 9) Live Staging Runbook (Model + MCP + Gateway + Auth) - Ordered Steps

Use this section in exact order when you are ready for real cloud calls.

### 9.1 Required inputs before starting
- [ ] Agent runtime/base URL.
- [ ] Backend API URL.
- [ ] Gateway/MCP endpoint.
- [ ] External Stock Agent endpoint.
- [ ] Valid auth token (user token) and/or auth provider config.
- [ ] AWS account/region access for Bedrock and (optional) CloudWatch.

### 9.2 Environment profile for live staging
- [ ] Core runtime:
  - [ ] `ORCHESTRATOR_V2_ENABLED=true`
  - [ ] `DEGRADED_MODE_ENABLED=true`
- [ ] Model + guardrail:
  - [ ] `AWS_REGION`
  - [ ] `BEDROCK_MODEL_ID`
  - [ ] `RESPONSE_MODE=llm_shadow` (first rollout)
  - [ ] `BEDROCK_GUARDRAIL_ID`
  - [ ] `BEDROCK_GUARDRAIL_VERSION`
- [ ] Gateway + MCP:
  - [ ] `AGENTCORE_GATEWAY_ENDPOINT`
  - [ ] `AGENTCORE_GATEWAY_TOOL_NAME`
  - [ ] `DEFAULT_USER_TOKEN` (if startup tool-registry prewarm is required)
- [ ] Reliability:
  - [ ] `GATEWAY_CIRCUIT_BREAKER_ENABLED=true`
  - [ ] `GATEWAY_BREAKER_FAILURE_THRESHOLD`
  - [ ] `GATEWAY_BREAKER_RESET_SECONDS`
  - [ ] `GATEWAY_TIMEOUT_SECONDS`
  - [ ] `TOOL_EXECUTION_TIMEOUT`
- [ ] Authentication:
  - [ ] `AUTH_PROVIDER=jwt` or `AUTH_PROVIDER=cognito`
  - [ ] If Cognito: `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_REGION`
  - [ ] `AUTH_DEV_BYPASS=false` outside dev
- [ ] Session memory + observability:
  - [ ] `SESSION_MEMORY_ENABLED=true`
  - [ ] `SESSION_MEMORY_TTL_SECONDS`
  - [ ] `SESSION_MEMORY_MAX_TURNS`
  - [ ] `SESSION_MEMORY_REDACT_KEYS`
  - [ ] `OBSERVABILITY_EXPORTER=structured` or `cloudwatch`
  - [ ] If CloudWatch: `CLOUDWATCH_ENABLED=true` + log group/stream/region + IAM

### 9.3 Step-by-step execution

#### Step 1 - Bring services online
- [ ] Unpause/start MCP service (App Runner).
- [ ] Confirm backend and agent runtime are deployed with latest code.
- [ ] Confirm stock external service is reachable (if enabled).

#### Step 2 - Preflight health check
- [ ] Check backend health endpoint.
- [ ] Check agent runtime reachability.
- [ ] Check gateway endpoint reachability.
- [ ] Check all secrets/tokens are loaded into runtime env.

#### Step 3 - Authentication smoke
- [ ] Positive auth: call one basic chat request with valid token -> request succeeds.
- [ ] Negative auth: call with invalid/expired token -> request fails by auth policy.

#### Step 4 - Gateway/MCP smoke (real tool path)
- [ ] Send a prompt expected to call at least one MCP-backed tool.
- [ ] Confirm response has `tool_calls` and no uncaught exception.
- [ ] Confirm `reason_codes` do not indicate unexpected policy/tool denial.

#### Step 5 - Live model smoke (real Bedrock)
- [ ] Send a prompt that goes through model path.
- [ ] Confirm `response_meta.model_id` is populated.
- [ ] Confirm `guardrail_enabled/guardrail_id/guardrail_version` are present.
- [ ] Keep `RESPONSE_MODE=llm_shadow` during first validation pass.

#### Step 6 - Mandatory business queries (live)
- [ ] Query 1: "Toi muon phan bo danh muc nganh ngan hang phu hop khau vi rui ro vua."
  - [ ] has safe disclaimer
  - [ ] no hard failure
  - [ ] route/tool behavior is expected
- [ ] Query 2: "So sanh 2 co phieu X va Y roi khuyen nghi ty trong."
  - [ ] has safe disclaimer
  - [ ] no hard failure
  - [ ] route/tool behavior is expected

#### Step 7 - Failure drills (must pass)
- [ ] Drill A (Gateway/MCP down): temporarily make MCP unreachable.
  - [ ] Agent still returns safe degraded response.
  - [ ] Safety node does not crash.
- [ ] Drill B (stock external down): force stock external timeout/unavailable.
  - [ ] Fallback path is used.
  - [ ] Reason codes and disclaimers remain correct.

#### Step 8 - Session memory follow-up test
- [ ] Send request A with `session_id=S1`.
- [ ] Send follow-up request B with same `session_id=S1`.
- [ ] Confirm follow-up behavior uses prior context safely.
- [ ] Send request C with `session_id=S2` and verify isolation from S1.

#### Step 9 - Observability verification
- [ ] Confirm `tool_call` start/end trace events exist.
- [ ] Confirm `session_memory` loaded/saved events exist.
- [ ] Confirm trace correlation IDs exist end-to-end: `trace_id`, `request_id`, `call_id`.
- [ ] If CloudWatch enabled, confirm logs are exported successfully.

#### Step 10 - Release decision
- [ ] If all checks pass in `llm_shadow`, switch to `RESPONSE_MODE=llm_enforce` in staging.
- [ ] Re-run mandatory Query1/Query2 + Gateway-down before prod promotion.

### 9.4 Suggested pass/fail gate for this runbook
- [ ] 0 uncaught exceptions on mandatory + failure drills.
- [ ] 100% requests return response with disclaimer in invest flows.
- [ ] Gateway down drill returns degraded-safe output (not hard failure).
- [ ] Auth negative test denies correctly.
- [ ] Tool traces and correlation IDs are present.

### 9.5 Fast rollback profile (if live test regresses)
- [ ] Set `RESPONSE_MODE=template`.
- [ ] Keep `DEGRADED_MODE_ENABLED=true`.
- [ ] Set `STOCK_AGENT_EXTERNAL_ENABLED=false` if stock external is unstable.
- [ ] Keep guardrail config enabled while rollback is active.
