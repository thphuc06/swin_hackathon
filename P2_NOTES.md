# P2 Notes (Phase 3 pipeline)

Date: February 27, 2026

This note tracks Phase 3 (P2) status, with local-first scope and remaining items that need your decisions/actions later.

## 1) Implemented in this phase

- Added test layers for scale-prep adapters and boundaries:
  - `agent/tests/unit/test_retrieval_factory.py`
  - `agent/tests/unit/test_policy_adapters.py`
  - `agent/tests/unit/test_auth_factory.py`
  - `agent/tests/unit/test_audit_logger.py`
  - `workers/tests/test_tier1_runner.py`
- Expanded CI into layered jobs:
  - unit
  - integration
  - contract
  - e2e
  - finance-mcp
  - workers
  - file: `.github/workflows/ci.yml`
- Added adapter-switch runbook for local-first to AWS swap:
  - `iac/ADAPTER_SWITCHING_GUIDE.md`
  - linked from `iac/README.md`

## 2) Local-first status (current operating mode)

You can continue development fully local with:

- `RETRIEVAL_ADAPTER=local`
- `POLICY_ADAPTER=simple`
- `AUTH_PROVIDER=jwt`
- `AUTH_DEV_BYPASS=true`
- `OBSERVABILITY_EXPORTER=structured`
- `CLOUDWATCH_ENABLED=false`

No OpenSearch/Cedar/Cognito/CloudWatch infra is required for local iteration.

## 3) Incomplete items needing your action later

## 3.1 OpenSearch (optional, later)

- Need endpoint/index/auth choices.
- Need document mapping and analyzer strategy for VN/EN.

## 3.2 Cedar policy (optional, later)

- Need policy service endpoint and auth.
- Need final action/resource taxonomy.
- Need fail-open vs fail-closed policy for production mode.

## 3.3 Cognito (optional, later)

- Need user pool/client/region values.
- Need final rollout plan to disable `AUTH_DEV_BYPASS` outside dev.

## 3.4 CloudWatch exporter (optional, later)

- Need log group/stream/region and IAM permissions.
- Need retention and log cost policy.

## 3.5 CI environment specifics

- Need to confirm GitHub Actions is the final CI platform.
- Need CI secrets and timeout budgets for heavy MCP dependency install.

## 4) Recommended next engineering step

- Continue feature work in local-first mode.
- Keep adapter boundaries stable.
- Defer AWS activation until you explicitly start staging hardening/release prep.

