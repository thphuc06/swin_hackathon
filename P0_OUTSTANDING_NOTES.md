# P0 Outstanding Notes (As of February 27, 2026)

This file summarizes what is **not fully completed yet** for P0 after the refactor implementation.

## 1) Done in code (already implemented)

- P0 orchestrator flow modules are in place and wired:
  - `intake -> plan -> safety -> select_agent -> execute_tools -> aggregate -> respond -> persist_memory`
- External Stock Agent client module exists with:
  - auth header support
  - timeout
  - retry
  - circuit-breaker
  - fallback payload (`stock_agent_unavailable_fallback`)
- Tool protocol hardening added:
  - correlation headers
  - idempotency key generation
  - typed error mapping
- Tier-1 workers refactored to avoid deleted backend imports.
- New tests added and currently passing locally:
  - agent tests + integration/contract/e2e additions
  - finance MCP tests

## 2) Not fully completed yet (must-do before real UAT/production)

## 2.1 External Stock Agent real connection

- Not yet verified against your **actual hosted Stock Agent server**.
- Need real env/secrets and live smoke test for:
  - base URL
  - auth token/JWT
  - real request/response schema compatibility
  - timeout/retry behavior under real latency
  - circuit-breaker behavior under repeated failures

Required env vars (runtime):

- `STOCK_AGENT_EXTERNAL_ENABLED=true`
- `STOCK_AGENT_EXTERNAL_BASE_URL=<real-url>`
- `STOCK_AGENT_EXTERNAL_ENDPOINT_PATH=/v1/stock/advisory` (or your real path)
- `STOCK_AGENT_EXTERNAL_AUTH_TOKEN=<real-token>`
- timeout/retry tuning vars (`*_TIMEOUT_SECONDS`, `*_MAX_RETRIES`, etc.)

## 2.2 Runtime deploy/redeploy

- Code changed locally only; still need redeploy:
  - Bedrock AgentCore runtime image/code
  - backend service
  - finance MCP service
  - workers (if deployed separately)

Without redeploy, production/staging will still run old behavior.

## 2.3 Real end-to-end validation in deployed environment

- Local tests pass, but still need deployed E2E validation:
  - API `/chat/stream` -> AgentCore -> Gateway/MCP -> response
  - invest prompt path with real stock external call success
  - invest prompt path fallback when stock service is down
  - trace/correlation IDs across logs

## 2.4 Config + secret management

- Need to register/update runtime env and secret source (SSM/Secrets Manager or deployment env):
  - stock agent credentials
  - gateway endpoint/token
  - backend/mcp URLs
- Need environment-specific values for `dev/staging/prod`.

## 2.5 Gateway + tool registry runtime check

- Need to verify live Gateway `tools/list` resolves tool names as expected in deployed env.
- Ensure prefixed tool names (if any) still resolve to:
  - `suitability_guard_v1`
  - `risk_profile_non_investment_v1`
  - other finance tools used by bundles

## 2.6 Worker execution path in real infra

- Worker code now uses MCP client (`workers/mcp_client.py`) but queue/event infra execution is not validated in cloud yet.
- Need to test with real trigger events and MCP auth path.

## 3) Partial items kept intentionally for compatibility (not blockers for P0 demo)

- Retrieval abstraction files were added, but runtime path still uses legacy `kb_retrieve` directly to keep existing tests/backward compatibility stable.
- Policy engine is currently a simple MVP hook (`SimplePolicyEngine`), not Cedar-equivalent semantics.
- Session memory module exists, but full memory read/write orchestration is still minimal (mainly audit write path).
- CloudWatch/managed observability exporters are not wired yet (structured hooks exist only).

## 4) Quick go-live checklist (recommended order)

1. Set all stock-agent and runtime env vars in staging.
2. Redeploy AgentCore runtime + backend + MCP + workers.
3. Run staging smoke tests for 4 flows:
   - summary
   - planning
   - invest with stock success
   - invest with stock fallback
4. Verify logs/traces include `trace_id`, `request_id`, `call_id`.
5. Tune retry/timeout/circuit-breaker thresholds using real latency/error data.
6. Freeze config and promote to production.

## 5) Suggested follow-up (P1 handoff)

- Upgrade policy hook to stronger allow/deny rules per tool/action.
- Complete retrieval adapter wiring (`IndexClient`) end-to-end.
- Strengthen contract tests against live stock staging endpoint.
- Add deployment pipeline checks that block release when P0 smoke tests fail.

## 6) TODO list to finish P0

Legend:

- `[BLOCKER]`: must complete before UAT/go-live.
- `[NON-BLOCKER]`: can be deferred while coding next phases.

### A. Environment and integration

- [ ] `[BLOCKER]` Set staging/prod secrets and env vars for Stock Agent external.
- [ ] `[BLOCKER]` Validate real Stock Agent contract against hosted server (success + error + timeout payloads).
- [ ] `[BLOCKER]` Tune stock client timeout/retry/circuit-breaker from real latency metrics.

### B. Deploy and runtime activation

- [ ] `[BLOCKER]` Redeploy AgentCore runtime using the refactored code.
- [ ] `[BLOCKER]` Redeploy backend API and finance MCP service.
- [ ] `[BLOCKER]` Redeploy workers using MCP client path.

### C. Staging validation

- [ ] `[BLOCKER]` Run smoke test for 4 intent flows: summary, planning, invest success, invest fallback.
- [ ] `[BLOCKER]` Validate trace propagation: `trace_id`, `request_id`, `call_id` in all services.
- [ ] `[BLOCKER]` Validate gateway `tools/list` resolution with real prefixed tool names.

### D. CI and quality gate

- [ ] `[NON-BLOCKER]` Add deploy-time smoke check script for external stock endpoint.
- [ ] `[NON-BLOCKER]` Add pipeline gate to fail release when P0 smoke tests fail.
- [ ] `[NON-BLOCKER]` Add regression test for worker event path in deployed environment.

### E. Compatibility debt (known and accepted for P0 demo)

- [ ] `[NON-BLOCKER]` Switch runtime retrieval calls from direct `kb_retrieve` to `IndexClient` adapter.
- [ ] `[NON-BLOCKER]` Expand policy hook from `SimplePolicyEngine` toward Cedar-compatible semantics.
- [ ] `[NON-BLOCKER]` Promote memory module from minimal audit write to full session memory lifecycle.

## 7) Can we continue Phase 2 without finishing all TODOs?

Short answer: **Yes for development, No for release**.

- You can continue coding Phase 2 now if the goal is architecture/features.
- You should not release to real users until all `[BLOCKER]` TODOs above are completed.
- Recommended path:
  1. Continue Phase 2 in branch/staging.
  2. Before merge-to-release, close all `[BLOCKER]` items.
