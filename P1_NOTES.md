# P1 Notes (Phase 2 kickoff - incomplete items needing your action)

Date: February 27, 2026

This note captures what is still incomplete after starting Phase 2 implementation, especially items that require your decisions, credentials, or infrastructure actions.

## 0) Locked Decision (current)

- Development mode: **local-first**
- Release mode: **not now**
- Cost control: keep Knowledge Base on local retrieval (`RETRIEVAL_ADAPTER=local`)
- Do not require OpenSearch/Cedar/Cognito/CloudWatch activation in current development loop.

Recommended local-first flags:

- `RETRIEVAL_ADAPTER=local`
- `POLICY_ADAPTER=simple`
- `AUTH_PROVIDER=jwt`
- `AUTH_DEV_BYPASS=true` (dev only)
- `OBSERVABILITY_EXPORTER=structured`
- `CLOUDWATCH_ENABLED=false`

## 1) What was implemented in this Phase 2 kickoff

- Added AWS-ready retrieval adapter:
  - `agent/retrieval/opensearch_index.py`
  - `agent/retrieval/factory.py`
- Added Cedar-compatible policy adapter:
  - `agent/policy/cedar_adapter.py`
  - `agent/policy/contracts.py`
  - `agent/policy/engine.py` now supports adapter switch via `POLICY_ADAPTER`
- Added auth provider abstraction and Cognito adapter:
  - `agent/infra/auth/provider.py`
  - `agent/infra/auth/jwt_provider.py`
  - `agent/infra/auth/cognito_provider.py`
  - `agent/infra/auth/factory.py`
- Added observability exporter layer with CloudWatch hook:
  - `agent/observability/audit_logger.py`
  - `agent/observability/exporters/cloudwatch_exporter.py`
  - `agent/observability/exporters/noop_exporter.py`
- Added Tier1 pipeline skeleton boundary:
  - `workers/tier1/...` (contracts, adapters, processor, runner)
- Added CI scaffold:
  - `.github/workflows/ci.yml`

## 2) Items requiring your specification or action

## 2.1 OpenSearch adapter activation (your input required)

You need to provide:

- `OPENSEARCH_ENDPOINT`
- `OPENSEARCH_INDEX_NAME`
- Auth mode and key/token for OpenSearch access
- Index mapping decisions:
  - document fields (`content`, `title`, `metadata.intent`, `metadata.doc_type`)
  - analyzer/language strategy (VN/EN)

Without these, retrieval remains on local adapter.

## 2.2 Cedar policy service integration (your input required)

You need to provide:

- `CEDAR_POLICY_ENDPOINT` (real authorization service URL)
- Auth mechanism for Cedar endpoint (`CEDAR_POLICY_AUTH_TOKEN` or alternative)
- Policy mode decision:
  - fail-open (`CEDAR_POLICY_FAIL_OPEN=true`) for lower risk of outage impact
  - fail-closed (`false`) for stricter compliance
- Canonical action/resource taxonomy for policy rules
  - action IDs for tool calls
  - resource IDs and principal context schema

Without this, runtime uses simple policy engine.

## 2.3 Cognito auth switch (your input required)

You need to provide:

- `AUTH_PROVIDER=cognito`
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `COGNITO_REGION` (if not derivable)

Decision required:

- Keep `AUTH_DEV_BYPASS` enabled in dev only, disabled in staging/prod.

Without this, runtime uses JWT local provider.

## 2.4 CloudWatch exporter activation (your input required)

You need to provide:

- `OBSERVABILITY_EXPORTER=cloudwatch` (or keep structured/noop)
- `CLOUDWATCH_ENABLED=true`
- `CLOUDWATCH_LOG_GROUP`
- `CLOUDWATCH_LOG_STREAM`
- `CLOUDWATCH_REGION`
- IAM permissions for runtime role:
  - `logs:CreateLogGroup`
  - `logs:CreateLogStream`
  - `logs:PutLogEvents`

Without this, trace exporting stays local/noop.

## 2.5 CI/CD environment setup (your action required)

You need to confirm:

- Git platform (GitHub Actions expected by `.github/workflows/ci.yml`)
- Secret names for CI environments
- Whether heavy dependencies in `src/aws-finance-mcp-server/requirements.txt` are acceptable in CI runtime budget

Optional decision:

- Split fast checks vs heavy checks into separate workflows.

## 2.6 Tier1 pipeline rollout scope (your decision required)

Current `workers/tier1` is a skeleton only. You need to decide:

- Queue target (SQS/Kafka/other)
- State store target (Aurora/Supabase)
- Alert channels for MVP (push/email/both)
- Event contract from Tier2 to Tier1 (schema + trigger thresholds)

## 3) Non-blocking technical debts left intentionally

- Graph runtime retrieval still defaults local path unless adapter switch is changed.
- Cedar/OpenSearch/Cognito/CloudWatch adapters are not connected to live infrastructure yet.
- Tier1 skeleton is not wired to deployed queue/state services yet.

## 4) Recommended next actions (order)

1. Confirm env values and architecture choices in sections 2.1-2.4.
2. Enable adapters one-by-one in staging:
   - Cognito -> Cedar -> OpenSearch -> CloudWatch
3. Run staging smoke + failure-mode tests after each adapter switch.
4. Decide Tier1 infra targets, then wire real adapters under `workers/tier1/adapters`.
