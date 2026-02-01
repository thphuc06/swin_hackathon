# IaC Skeleton (MVP)

This folder is a placeholder for post-hackathon scale. It is not wired to the
current deployment flow.

## Targets

- AgentCore Runtime (agent container + entrypoint)
- AgentCore Gateway (MCP tools)
- AgentCore Policy Engine (Cedar)
- IAM roles, ECR, CloudWatch logs

## Option A: CDK (recommended)

- `iac/cdk` to host CDK app

## Option B: Terraform

- `iac/terraform` to host Terraform modules

## MVP Deploy

Use AgentCore Starter Toolkit from `agent/` for now, and configure Gateway
targets separately (point to the MCP server `/mcp` endpoint).
