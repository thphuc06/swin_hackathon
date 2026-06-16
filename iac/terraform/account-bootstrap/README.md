# AWS Account Bootstrap Terraform

For the full end-to-end demo deployment, start with
[`../../../DEPLOY.md`](../../../DEPLOY.md). This file documents only the
account-bootstrap Terraform stack.

This Terraform stack creates the portable AWS foundation needed to move the
current Yofina/Jars MVP to another AWS account.

It intentionally provisions the stable AWS resources with Terraform and keeps
AgentCore Runtime/Gateway deployment on the existing `ops/aws/*.ps1` scripts.
Reason: AgentCore Runtime and Gateway control-plane support changes faster than
the Terraform AWS provider. The repo already has AWS CLI deployment scripts for
those resources, so this stack generates account-specific config for them.

## What This Creates

- ECR repositories:
  - `jars-orchestrator-runtime`
  - `jars-specialist-agent-mcp`
  - `jars-backend`
- S3 bucket for CodeBuild source bundles.
- CodeBuild projects for orchestrator and specialist runtime images.
- IAM roles for:
  - AgentCore orchestrator runtime
  - AgentCore specialist runtime
  - AgentCore gateway execution
  - CodeBuild image builders
  - ECS/Fargate backend execution and task access
- Optional Cognito user pool and app client.
- Generated deployment config files under `generated/`.

## What This Does Not Create

- AgentCore Runtime resources directly.
- AgentCore Gateway and Gateway target directly.
- AgentCore OAuth credential provider.
- Backend ECS/Fargate service directly; that is created by `iac/terraform/ecs-services`.
- Supabase/Aurora database.

Those are handled by existing deploy scripts or by external setup.

## Prerequisites

- Terraform `>= 1.5`
- AWS CLI v2 configured for the target account
- Docker available locally for backend image build
- PowerShell
- Permissions to create IAM, ECR, S3, CodeBuild, Cognito, ECS, EC2 networking, ALB, and CloudWatch resources
- AgentCore permissions for the deploy scripts

## First-Time Bootstrap

From this folder:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and set aws_profile/aws_region for the target account.
terraform init
terraform plan
terraform apply
```

Then sync generated config into the existing deployment layout:

```powershell
.\sync-generated-config.ps1
```

This writes:

- `ops/aws/deploy.settings.terraform.json`
- `ops/aws/orchestrator.runtime.manifest.json`
- `ops/aws/specialist.runtime.manifest.json`
- `ops/aws/backend.ecs.manifest.terraform.json`

The sync script backs up existing manifest files before overwriting them.

## After Bootstrap

After this stack applies, continue with the command sequence in
[`../../../DEPLOY.md`](../../../DEPLOY.md). That guide covers loading generated
env values, deploying AgentCore, building the backend image, deploying
ECS/Fargate, updating the orchestrator, and configuring the frontend.

## Existing Cognito

If the target account already has Cognito:

```hcl
create_cognito                 = false
existing_cognito_user_pool_id  = "us-east-1_..."
existing_cognito_client_id     = "..."
cognito_allowed_client_ids     = ["..."]
```

## Important Notes

- Do not put Supabase service-role keys or external agent tokens into
  `terraform.tfvars`. Terraform state is not a secret store.
- The AgentCore Gateway OAuth credential provider is currently expected to be
  created outside this Terraform stack, then supplied through
  `gateway_oauth_provider_arn` or `DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN`.
- After AgentCore creates new runtime/gateway IDs, pin them back into your
  deployment config if you want future updates to target the same resources.
- For production, tighten IAM policies further after the first successful
  migration by replacing wildcard AgentCore gateway/runtime ARNs with exact IDs.
