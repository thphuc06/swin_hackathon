# Adapter Switching Guide (Local-First -> AWS Swap)

This is not the deploy runbook. For the end-to-end AWS demo deployment, use
[`../DEPLOY.md`](../DEPLOY.md).

This guide explains how to keep development local and switch to AWS adapters later without changing core logic.

## 1) Local-first baseline (recommended now)

Set these env vars in `agent/.env`:

```env
RETRIEVAL_ADAPTER=local
POLICY_ADAPTER=simple
AUTH_PROVIDER=jwt
AUTH_DEV_BYPASS=true
OBSERVABILITY_EXPORTER=structured
CLOUDWATCH_ENABLED=false
```

Behavior:

- Retrieval: local KB markdown files
- Policy: in-process simple allowlist engine
- Auth: lightweight JWT provider for local runs
- Observability: structured logs only

## 2) Switch to OpenSearch retrieval

```env
RETRIEVAL_ADAPTER=opensearch
OPENSEARCH_ENDPOINT=https://<endpoint>
OPENSEARCH_INDEX_NAME=agent-kb
OPENSEARCH_API_KEY=<api-key>
OPENSEARCH_TIMEOUT_SECONDS=3.0
OPENSEARCH_VERIFY_TLS=true
```

Module used: `agent/retrieval/opensearch_index.py`

## 3) Switch to Cedar policy service

```env
POLICY_ADAPTER=cedar
CEDAR_POLICY_ENDPOINT=https://<policy-endpoint>
CEDAR_POLICY_AUTH_TOKEN=<token>
CEDAR_POLICY_TIMEOUT_SECONDS=2.0
CEDAR_POLICY_FAIL_OPEN=true
```

Module used: `agent/policy/cedar_adapter.py`

## 4) Switch to Cognito auth provider

```env
AUTH_PROVIDER=cognito
AUTH_DEV_BYPASS=false
COGNITO_USER_POOL_ID=<pool-id>
COGNITO_CLIENT_ID=<client-id>
COGNITO_REGION=<region>
```

Module used: `agent/infra/auth/cognito_provider.py`

## 5) Switch to CloudWatch exporter

```env
OBSERVABILITY_EXPORTER=cloudwatch
CLOUDWATCH_ENABLED=true
CLOUDWATCH_LOG_GROUP=/aws/agentcore/runtime
CLOUDWATCH_LOG_STREAM=advisory-runtime
CLOUDWATCH_REGION=us-east-1
```

Module used: `agent/observability/exporters/cloudwatch_exporter.py`

## 6) Recommended rollout order

1. Cognito auth
2. Cedar policy
3. OpenSearch retrieval
4. CloudWatch exporter

Enable one adapter at a time in staging, run smoke tests, then proceed to the next.

