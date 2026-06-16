variable "project_name" {
  description = "Short project prefix used for AWS resource names."
  type        = string
  default     = "jars"
}

variable "app_env" {
  description = "Application environment, for example staging or prod."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["local", "demo", "staging", "prod"], var.app_env)
    error_message = "app_env must be one of: local, demo, staging, prod."
  }
}

variable "aws_region" {
  description = "AWS region for the target account."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Optional AWS CLI profile name written into generated deploy.settings.json. Leave empty if you prefer passing -Profile to scripts."
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Extra tags applied to created resources."
  type        = map(string)
  default     = {}
}

variable "force_delete_ecr_repositories" {
  description = "Allow Terraform destroy to delete ECR repositories even if images exist. Keep false outside throwaway accounts."
  type        = bool
  default     = false
}

variable "source_bucket_name" {
  description = "Optional S3 bucket name for CodeBuild source bundles. Leave empty for a deterministic account/region name."
  type        = string
  default     = ""
}

variable "source_bundle_expiration_days" {
  description = "How long CodeBuild source zip files should remain in the source bucket."
  type        = number
  default     = 14
}

variable "orchestrator_ecr_repository_name" {
  description = "ECR repository name for the AgentCore orchestrator runtime image."
  type        = string
  default     = "jars-orchestrator-runtime"
}

variable "specialist_ecr_repository_name" {
  description = "ECR repository name for the specialist MCP runtime image."
  type        = string
  default     = "jars-specialist-agent-mcp"
}

variable "backend_ecr_repository_name" {
  description = "ECR repository name for the FastAPI backend image."
  type        = string
  default     = "jars-backend"
}

variable "orchestrator_runtime_name" {
  description = "AgentCore Runtime name for the orchestrator."
  type        = string
  default     = "JarsOrchestratorRuntime"
}

variable "specialist_runtime_name" {
  description = "AgentCore Runtime name for the specialist MCP server."
  type        = string
  default     = "JarsSpecialistMcp"
}

variable "gateway_name" {
  description = "AgentCore Gateway name to create through the existing AWS CLI script."
  type        = string
  default     = "jars-specialist-gateway"
}

variable "backend_service_name" {
  description = "ECS service name for the FastAPI backend."
  type        = string
  default     = "jars-backend"
}

variable "backend_api_base" {
  description = "Backend API base URL passed into the orchestrator runtime. Use a placeholder for first deploy, then set to the ALB DNS name output from ecs-services and re-apply."
  type        = string
  default     = "https://replace-after-backend-deploy.example.invalid"
}

variable "policy_allowed_tools" {
  description = "Comma-separated allowlist passed to the orchestrator simple policy adapter."
  type        = string
  default     = "spend_analytics_v1,cashflow_forecast_v1,jar_allocation_suggest_v1,anomaly_signals_v1,risk_profile_non_investment_v1,recurring_cashflow_detect_v1,goal_feasibility_v1,what_if_scenario_v1,run_service_agent_v1,run_stock_agent_v1,suitability_guard_v1"
}

variable "gateway_timeout_seconds" {
  description = "Timeout used by the orchestrator when calling the AgentCore Gateway."
  type        = string
  default     = "90"
}

variable "create_cognito" {
  description = "Create a new Cognito user pool and app client. Set false to wire an existing pool/client."
  type        = bool
  default     = true
}

variable "existing_cognito_user_pool_id" {
  description = "Existing Cognito user pool ID when create_cognito is false."
  type        = string
  default     = ""
}

variable "existing_cognito_client_id" {
  description = "Existing Cognito app client ID when create_cognito is false."
  type        = string
  default     = ""
}

variable "cognito_allowed_client_ids" {
  description = "Explicit allowed Cognito app client IDs. Leave empty to use the created/existing app client."
  type        = list(string)
  default     = []
}

variable "cognito_callback_urls" {
  description = "Callback URLs for the generated Cognito app client."
  type        = list(string)
  default     = ["http://localhost:3000/callback"]
}

variable "cognito_logout_urls" {
  description = "Logout URLs for the generated Cognito app client."
  type        = list(string)
  default     = ["http://localhost:3000/logout"]
}

variable "gateway_oauth_provider_arn" {
  description = "AgentCore Gateway OAuth credential provider ARN. Leave empty and set DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN later if it is created outside Terraform."
  type        = string
  default     = ""
}

variable "stock_agent_external_enabled" {
  description = "Whether external stock-agent integration is enabled."
  type        = string
  default     = "false"
}

variable "stock_agent_external_url" {
  description = "Optional full external stock-agent URL."
  type        = string
  default     = ""
}

variable "stock_agent_external_base_url" {
  description = "Optional external stock-agent base URL."
  type        = string
  default     = ""
}

variable "stock_agent_external_endpoint_path" {
  description = "External stock-agent endpoint path."
  type        = string
  default     = "/ask"
}

variable "stock_agent_external_model_provider" {
  description = "External stock-agent model provider."
  type        = string
  default     = "bedrock"
}

variable "stock_agent_external_model" {
  description = "External stock-agent model name."
  type        = string
  default     = "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "stock_agent_external_timeout_seconds" {
  description = "Specialist stock-agent external timeout."
  type        = string
  default     = "10"
}

variable "stock_agent_external_connect_timeout_seconds" {
  description = "Orchestrator stock-agent external connect timeout."
  type        = string
  default     = "2"
}

variable "stock_agent_external_read_timeout_seconds" {
  description = "Orchestrator stock-agent external read timeout."
  type        = string
  default     = "8"
}
