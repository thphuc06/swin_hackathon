# Deploy Guide

This is the single command guide for deploying the demo end to end:

```text
Frontend -> ALB -> ECS/Fargate Backend -> AgentCore Orchestrator -> Gateway -> Specialist MCP -> Planner/Service/Stock
```

Use this file when you want to deploy or test the AWS demo. The other docs are references:

- `README.md`: architecture and development overview.
- `iac/README.md`: short IaC index.
- `iac/terraform/account-bootstrap/README.md`: Terraform stack details.
- `iac/ADAPTER_SWITCHING_GUIDE.md`: local-vs-AWS adapter notes, not the main deploy runbook.

## Prerequisites

- AWS CLI v2 configured for the target account.
- Terraform `>= 1.5`.
- Docker running locally.
- PowerShell.
- Permissions for IAM, ECR, S3, CodeBuild, Cognito, ECS/Fargate, EC2 networking, ALB, CloudWatch, and AgentCore.
- Supabase URL and service-role key for planner/service data.
- AgentCore Gateway OAuth credential provider ARN. Terraform does not create this yet.

Run all backend commands from:

```powershell
cd C:\HCMUS\FINTECH\ius_backend_agent_mcp
```

## 1. Bootstrap AWS Foundation

This creates ECR repos, IAM roles, CodeBuild projects, optional Cognito, and generated deploy config.

```powershell
cd iac\terraform\account-bootstrap
Copy-Item terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
app_env     = "staging"
aws_region  = "us-east-1"
aws_profile = "<your-aws-profile>"

create_cognito = true

# First deploy can keep this placeholder. You will replace it after ECS creates the ALB.
backend_api_base = "https://replace-after-backend-deploy.example.invalid"

# Optional. If blank, set DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN later in PowerShell.
gateway_oauth_provider_arn = ""
```

Apply:

```powershell
terraform init
terraform plan
terraform apply
.\sync-generated-config.ps1
cd ..\..\..
```

Useful outputs:

```powershell
terraform -chdir=iac\terraform\account-bootstrap output
```

## 2. Load Deploy Environment

Load Terraform-generated values:

```powershell
. .\iac\terraform\account-bootstrap\generated\deploy.env.ps1
```

Use this generated PowerShell file for the deploy flow. Do not rely on any
local `ops/aws/deploy.env` file; that path is ignored and can contain stale
operator-specific values.

Set secrets outside Terraform:

```powershell
$env:DEPLOY_SUPABASE_URL = "https://<project>.supabase.co"
$env:DEPLOY_SUPABASE_SERVICE_ROLE_KEY = "<supabase-service-role-key>"
$env:DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN = "arn:aws:bedrock-agentcore:<region>:<account-id>:token-vault/default/oauth2credentialprovider/<provider-id>"
```

For the normal demo, keep direct external stock disabled so stock questions route through the orchestrator and specialist fallback:

```powershell
$env:DEPLOY_STOCK_AGENT_EXTERNAL_ENABLED = "false"
$env:DEPLOY_STOCK_AGENT_EXTERNAL_URL = ""
```

## 3. Deploy AgentCore Workflow

This deploys:

- Specialist AgentCore Runtime.
- AgentCore Gateway and target.
- Orchestrator AgentCore Runtime.

```powershell
.\ops\aws\deploy_full_aws.ps1 `
  -SettingsPath ops/aws/deploy.settings.terraform.json `
  -CreateGatewayIfMissing
```

Save the printed value:

```text
Backend AGENTCORE_RUNTIME_ARN: arn:aws:bedrock-agentcore:...
```

You will put that ARN into the backend ECS Terraform config. The deploy script
also pins the created runtime IDs and gateway ID into `ops/aws/*.json` so later
updates target the same AgentCore resources.

## 4. Build And Push Backend Image

Resolve the backend ECR repository:

```powershell
$bootstrap = terraform -chdir=iac\terraform\account-bootstrap output -json | ConvertFrom-Json
$backendRepo = $bootstrap.ecr_repositories.value.backend
$region = $bootstrap.region.value
$accountId = $bootstrap.account_id.value
$backendImage = "${backendRepo}:latest-backend"
```

Login to ECR:

```powershell
aws ecr get-login-password --region $region `
  | docker login --username AWS --password-stdin "${accountId}.dkr.ecr.${region}.amazonaws.com"
```

Build and push:

```powershell
docker build --platform linux/amd64 -t $backendImage -f backend/Dockerfile .
docker push $backendImage
```

## 5. Deploy Backend ECS/Fargate

Create backend Terraform vars:

```powershell
cd iac\terraform\ecs-services
Copy-Item terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with values from `account-bootstrap` output and the AgentCore deploy:

```hcl
app_env    = "staging"
aws_region = "us-east-1"

backend_image = "<backend-ecr-uri>:latest-backend"

ecs_execution_role_arn = "arn:aws:iam::<account-id>:role/jars-staging-ecs-execution"
backend_task_role_arn  = "arn:aws:iam::<account-id>:role/jars-staging-backend-task"

cognito_user_pool_id       = "us-east-1_XXXXXXXXX"
cognito_client_id          = "xxxxxxxxxxxxxxxxxxxxxxxxxx"
cognito_allowed_client_ids = "xxxxxxxxxxxxxxxxxxxxxxxxxx"

agentcore_runtime_arn = "arn:aws:bedrock-agentcore:..."

supabase_url              = "https://<project>.supabase.co"
supabase_service_role_key = "<supabase-service-role-key>"

# Important: staging/prod must use real Cognito auth.
dev_bypass_auth = false
```

Apply:

```powershell
terraform init
terraform plan
terraform apply
```

Save the backend URL:

```powershell
$backendUrl = terraform output -raw alb_dns_name
$backendUrl
cd ..\..\..
```

Smoke test:

```powershell
Invoke-WebRequest -UseBasicParsing "$backendUrl/health"
```

## 6. Update Orchestrator With Real Backend URL

The first orchestrator deploy used a placeholder backend URL. Redeploy only the orchestrator with the real ALB URL:

```powershell
. .\iac\terraform\account-bootstrap\generated\deploy.env.ps1
$backendUrl = terraform -chdir=iac\terraform\ecs-services output -raw alb_dns_name

$env:DEPLOY_SUPABASE_URL = "https://<project>.supabase.co"
$env:DEPLOY_SUPABASE_SERVICE_ROLE_KEY = "<supabase-service-role-key>"
$env:DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN = "arn:aws:bedrock-agentcore:<region>:<account-id>:token-vault/default/oauth2credentialprovider/<provider-id>"
$env:DEPLOY_BACKEND_API_BASE = $backendUrl

.\ops\aws\deploy_full_aws.ps1 `
  -Component Orchestrator `
  -SettingsPath ops/aws/deploy.settings.terraform.json
```

## 7. Prepare Demo User And Data

Before opening the frontend, make sure you have:

- A Cognito user who can sign in through the frontend.
- Supabase finance/advisory data aligned to that user or to the current demo data mapping.

If you are using the existing helper flow, start from these scripts:

```powershell
# Create or align the advisory principal when needed.
python backend/scripts/provision_advisory_principal.py

# Generate/verify an AccessToken for live backend script testing.
python agent/genToken.py
```

You can also create the Cognito user manually in AWS Console for a quick demo,
but the user still needs finance data available to the planner/service path.

## 8. Configure Frontend For E2E Demo

From the frontend repo:

```powershell
cd C:\HCMUS\FINTECH\ius_financial_ui
Copy-Item .env.example .env
```

Edit `.env`:

```env
VITE_API_BASE_URL=http://<backend-alb-dns>
VITE_CHAT_STREAM_URL=http://<backend-alb-dns>/chat/stream
VITE_STOCK_AGENT_URL=
VITE_AWS_REGION=us-east-1
VITE_COGNITO_CLIENT_ID=<cognito-app-client-id>
VITE_COGNITO_CLIENT_SECRET=
```

Run:

```powershell
npm install
npm run dev
```

Open:

```text
http://localhost:8080
```

## 9. Test The Agentic Demo

Use advisor chat, not direct stock mode. Prompt:

```text
Analyze my financial situation and build a 12-month roadmap to buy a laptop while keeping my emergency fund safe.
```

Expected path:

```text
React UI -> ALB -> FastAPI /chat/stream -> AgentCore Orchestrator -> Gateway -> Specialist MCP -> Planner/Service/Stock -> SSE response
```

Useful checks:

```powershell
# Backend health
Invoke-WebRequest -UseBasicParsing "$backendUrl/health"

# Backend ECS service health
terraform -chdir=C:\HCMUS\FINTECH\ius_backend_agent_mcp\iac\terraform\ecs-services output

# Backend logs
$logGroup = terraform -chdir=C:\HCMUS\FINTECH\ius_backend_agent_mcp\iac\terraform\ecs-services output -raw log_group_name
aws logs tail $logGroup --follow --region us-east-1
```

In the browser, open Network tab and inspect `/chat/stream`. The stream should include assistant text plus metadata such as trace/tool/roadmap payload lines.

## Redeploy Cheatsheet

Agent or specialist code changed:

```powershell
cd C:\HCMUS\FINTECH\ius_backend_agent_mcp
. .\iac\terraform\account-bootstrap\generated\deploy.env.ps1
$env:DEPLOY_SUPABASE_URL = "https://<project>.supabase.co"
$env:DEPLOY_SUPABASE_SERVICE_ROLE_KEY = "<supabase-service-role-key>"
$env:DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN = "arn:aws:bedrock-agentcore:..."
$env:DEPLOY_BACKEND_API_BASE = "http://<backend-alb-dns>"

.\ops\aws\deploy_full_aws.ps1 `
  -SettingsPath ops/aws/deploy.settings.terraform.json `
  -CreateGatewayIfMissing
```

The script updates the existing AgentCore runtimes when the manifest files
contain pinned runtime IDs. If you re-run `sync-generated-config.ps1`, check
that the runtime IDs and gateway ID are still present before redeploying.

Backend code changed:

```powershell
cd C:\HCMUS\FINTECH\ius_backend_agent_mcp
docker build --platform linux/amd64 -t $backendImage -f backend/Dockerfile .
docker push $backendImage

$cluster = terraform -chdir=iac\terraform\ecs-services output -raw ecs_cluster_name
$service = terraform -chdir=iac\terraform\ecs-services output -raw ecs_service_name
aws ecs update-service --cluster $cluster --service $service --force-new-deployment --region us-east-1
```

Frontend code changed:

```powershell
cd C:\HCMUS\FINTECH\ius_financial_ui
npm run build
npm run dev
```

## Troubleshooting

- `401` or `403` from `/chat/stream`: confirm the frontend has a Cognito AccessToken, `VITE_COGNITO_CLIENT_ID` is correct, and backend `cognito_allowed_client_ids` includes that app client.
- Backend fails startup with `DEV_BYPASS_AUTH`: set `dev_bypass_auth = false` when `app_env` is `staging` or `prod`.
- Backend returns missing `AGENTCORE_RUNTIME_ARN`: set `agentcore_runtime_arn` in `iac/terraform/ecs-services/terraform.tfvars` and re-apply.
- ALB health check fails: inspect ECS task logs with `aws logs tail`, then verify container port `8080`, `/health`, Supabase env vars, and IAM roles.
- Gateway deploy fails: check `DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN` and AgentCore permissions.
- Stock specialist returns education-only fallback: that is acceptable for the demo unless you explicitly configured an external stock service.
