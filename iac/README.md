# IaC

For the full demo deployment sequence, use [`../DEPLOY.md`](../DEPLOY.md).
This file is only a short index of the infrastructure folders.

## Targets

- AgentCore Runtime (agent container + entrypoint)
- AgentCore Gateway (MCP tools)
- AgentCore Policy Engine (Cedar)
- IAM roles, ECR, CloudWatch logs

## Current Account-Migration Path

Use the Terraform bootstrap stack:

- `iac/terraform/account-bootstrap`

It creates the portable AWS foundation for a new account:

- ECR repositories
- S3 source bundle bucket
- CodeBuild image builders
- IAM roles for AgentCore Runtime, Gateway, CodeBuild, and ECS/Fargate
- Optional Cognito user pool/client
- Generated deployment config for the existing `ops/aws` scripts

AgentCore Runtime/Gateway creation still uses the existing AWS CLI scripts under
`ops/aws` because AgentCore provider coverage changes faster than the stable AWS
resources above.

Start here:

```powershell
cd iac/terraform/account-bootstrap
Copy-Item terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
.\sync-generated-config.ps1
```

## Adapter Switching

For local-first development and future AWS swap-in strategy, see:

- `iac/ADAPTER_SWITCHING_GUIDE.md`
