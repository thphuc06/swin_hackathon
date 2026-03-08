# Agent Progress and Optimization Plan

Date: 2026-03-08
Owner: Fintech AgentCore team
Scope: current bundle-router architecture (not server-side Responses orchestration)

## 1) Current Progress Snapshot

### 1.1 Current architecture running
- Frontend -> Backend `/chat/stream` -> AgentCore Runtime (AWS) -> AgentCore Gateway -> Finance MCP -> Supabase.
- Evidence: `SETUP_E2E_AWS_REAL_UNIFIED.md` section `1) Current flow in this codebase`.

### 1.2 What agent can do now
| Capability | Status | Evidence | Notes |
|---|---|---|---|
| AWS runtime invocation + SSE response | Working | `backend/tmp/e2e_finance_20260307_233317_en_summary_30d.txt` (`HTTP_STATUS: 200`) | End-to-end response stream works. |
| Bundle-based tool routing by intent | Working | `agent/router/policy.py` (`TOOL_BUNDLE_MAP`) | Intents mapped to deterministic tool bundles. |
| Finance tool execution via gateway/MCP | Working (partial) | `backend/tmp/e2e_finance_20260307_233317_en_summary_30d.txt` (`Tools: suitability_guard_v1, jar_allocation_suggest_v1, cashflow_forecast_v1, spend_analytics_v1`) | Summary path can execute multiple tools. |
| Safety guard flow | Working | `agent/graph.py` (`suitability_guard`) and E2E outputs showing `suitability_guard_v1` | Guard runs early and consistently. |
| Clarification flow for ambiguous prompt | Working | E2E files with `ResponseFallback: clarification_pending` | Clarify question is returned correctly. |
| Session ID propagation | Working | `agent/main.py` (`_resolve_session_id`) | Reads from payload/header and passes into runtime state. |
| In-memory short-term session memory | Working but limited | `agent/memory/session_memory.py` (`InMemoryTTLStore`) | Process-local only, not shared across runtime instances. |

### 1.3 What is not stable yet
| Issue | Current impact | Evidence |
|---|---|---|
| Intent extraction returns invalid JSON on many prompts | Falls back to clarification even for obvious risk/scenario prompts | `ResponseReasonCodes: ... invalid_json ... structured_invalid_no_rule_fallback` in multiple E2E outputs |
| Vietnamese prompt encoding quality in test path | Prompt corruption can lower routing accuracy | Files around `backend/tmp/e2e_finance_20260307_234014_*` show mojibake text |
| Response synthesizer parse/grounding fallback still happens | Output quality degrades to fallback renderer | `ResponseFallback: answer_synthesis_failed` in `en_summary_30d` output |
| Session memory not durable/cross-instance | Clarify follow-up can break under scaling/restart | `agent/memory/session_memory.py` uses local RAM store |

### 1.4 Important current-state clarification
- Codebase currently does **not** show active server-side Responses dynamic path.
- Current route logic is bundle policy in `agent/router/policy.py` + `agent/graph.py`.
- `TOOL_ORCHESTRATION_MODE` does not appear in current source search, so that env is likely non-effective right now.

## 2) MCP User ID / Auth State (for planning)

- MCP supports optional fixed user override via `FINANCE_MCP_FIXED_USER_ID` in `src/aws-finance-mcp-server/app/mcp.py`.
- If `FINANCE_MCP_FIXED_USER_ID` is set, MCP rewrites both auth `sub` and tool `user_id`.
- Current local file `src/aws-finance-mcp-server/.env` does not show `FINANCE_MCP_FIXED_USER_ID` set.
- Current local file has `DEV_BYPASS_AUTH=true`, which is demo mode and not strict production auth behavior.

## 3) Optimization Priorities (Recommended)

### P0 (must fix first)
1. Stabilize intent extraction JSON validity.
2. Reduce unnecessary clarification for clear risk/scenario prompts.
3. Ensure UTF-8 normalization in test and runtime input path to avoid mojibake.
4. Make short-term memory durable across runtime instances (AgentCore Memory integration).

### P1
1. Improve answer synthesis stability (less `answer_invalid_json`, less grounding false positives).
2. Tighten risk/scenario routing heuristics and slot requirements.
3. Improve fallback answer quality when LLM output parse fails.

### P2
1. Add stronger observability dashboard: route reason, parse errors, tool latency, fallback rate by intent.
2. Add automated regression suite for VI/EN prompts and clarify-follow-up multi-turn.
3. Latency/cost optimization for tool bundles and retries.

## 4) Execution Plan (No code changes yet)

### Phase 0 - Baseline and guardrails (0.5 day)
1. Freeze baseline metrics from current E2E: fallback ratio, clarify ratio, tool-call success, p95 latency.
2. Define pass/fail thresholds for each intent (`summary`, `risk`, `planning`, `scenario`).
3. Lock one reproducible test pack (VI + EN + follow-up turns).

Exit criteria:
- Team can compare every next deploy against same metrics.

### Phase 1 - Router and input hardening (1-2 days)
1. Add strict pre-parse normalization for prompt text (UTF-8 + NFC) before extraction.
2. Improve extraction retry policy with explicit JSON repair step and deterministic fallback parser.
3. Adjust risk/scenario intent override weights to reduce false clarification.
4. Keep clarify only when truly missing required slot (ex: scenario horizon).

Exit criteria:
- Clarification fallback for clear prompts drops significantly.
- Risk/scenario prompts route to expected bundles in >=90% smoke cases.

### Phase 2 - Response synthesizer stabilization (1 day)
1. Harden synthesizer parse pipeline (structured parse -> repair -> constrained fallback).
2. Tune grounding validator to reduce false `grounding_failed` on safe numeric tokens.
3. Add short raw-output diagnostics (truncated) for parse failures.

Exit criteria:
- `answer_synthesis_failed` materially reduced.
- More responses stay in full LLM synthesis path.

### Phase 3 - AgentCore Memory migration (1-2 days)
1. Replace `InMemoryTTLStore` adapter with AgentCore Memory-backed adapter.
2. Use identity mapping:
- `actor_id = end-user id` (prefer JWT `sub`, or backend-verified end-user id for M2M flow).
- `session_id = chat session/thread id`.
3. Persist and retrieve `pending_clarification`, last intent, and compact turn summaries.
4. Keep local-memory fallback behind feature flag for rollback safety.

Exit criteria:
- Follow-up turn works across runtime restarts/instance shifts.
- Clarification continuation is stable in cloud runtime.

### Phase 4 - Auth/data consistency cleanup (0.5-1 day)
1. Decide final mode for MCP auth (`DEV_BYPASS_AUTH=false` for hardened path).
2. Keep `FINANCE_MCP_FIXED_USER_ID` only for demo/seed mapping.
3. Define production user mapping policy from Cognito identity to data `user_id`.

Exit criteria:
- Tool data scope is consistent and auditable per user.

## 5) Suggested KPI targets

| KPI | Current trend | Target |
|---|---|---|
| Clarification fallback rate for clear prompts | High on risk/scenario | < 15% |
| Intent extraction invalid_json rate | Visible in reason codes | < 5% |
| Answer synthesis fallback rate | Present in summary flow | < 10% |
| Multi-turn clarify continuation success | Not stable in cloud | >= 95% |
| Tool-call success rate (bundle intents) | Partial | >= 98% |

## 6) Immediate next action checklist

1. Confirm this plan scope and priority order.
2. Execute Phase 0 metrics baseline from latest deployed runtime.
3. Implement Phase 1 + Phase 2 together in one branch.
4. Run controlled redeploy and compare KPI deltas.
5. If stable, start Phase 3 AgentCore Memory migration.

---

If needed, this document can be split into:
- `CURRENT_STATUS.md` (snapshot)
- `MIGRATION_PLAN.md` (execution)
- `RUNBOOK.md` (deploy and test steps)
