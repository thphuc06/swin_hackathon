variable "project_name" {
  description = "Short project prefix used for AWS resource names."
  type        = string
  default     = "jars"
}

variable "app_env" {
  description = "Application environment (staging or prod)."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["local", "demo", "staging", "prod"], var.app_env)
    error_message = "app_env must be one of: local, demo, staging, prod."
  }
}

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "default_tags" {
  description = "Extra tags applied to all resources."
  type        = map(string)
  default     = {}
}

# ─── VPC ───────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the new VPC. Used only when create_vpc = true."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Exactly two AZs to place public subnets and spread tasks across."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "Exactly two availability zones are required."
  }
}

variable "create_vpc" {
  description = "Create a new VPC and public subnets. Set false and supply existing_vpc_id / existing_public_subnet_ids to reuse an existing VPC."
  type        = bool
  default     = true
}

variable "existing_vpc_id" {
  description = "Existing VPC ID. Required when create_vpc = false."
  type        = string
  default     = ""
}

variable "existing_public_subnet_ids" {
  description = "Two existing public subnet IDs in different AZs. Required when create_vpc = false."
  type        = list(string)
  default     = []
}

# ─── Task networking ───────────────────────────────────────────────────

variable "assign_public_ip_to_tasks" {
  description = "Assign public IPs to Fargate tasks so they can reach ECR and external services (Supabase, Bedrock) without a NAT gateway. Set false when tasks run in private subnets behind NAT."
  type        = bool
  default     = true
}

# ─── ALB ───────────────────────────────────────────────────────────────

variable "alb_idle_timeout" {
  description = "ALB idle-connection timeout in seconds. 120 accommodates long-running SSE/streaming AI responses."
  type        = number
  default     = 120
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN to enable an HTTPS listener with HTTP→HTTPS redirect. Leave empty for HTTP only (not suitable for production)."
  type        = string
  default     = ""
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks that may reach the ALB listener(s)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ─── ECS / Task definition ─────────────────────────────────────────────

variable "backend_image" {
  description = "Full ECR image URI with tag, e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/jars-backend:latest-backend."
  type        = string
}

variable "backend_cpu" {
  description = "Fargate task CPU units (256, 512, 1024, 2048, 4096)."
  type        = number
  default     = 1024
}

variable "backend_memory" {
  description = "Fargate task memory in MiB. Must be a valid pairing with backend_cpu."
  type        = number
  default     = 2048
}

variable "backend_desired_count" {
  description = "Desired number of running backend task replicas."
  type        = number
  default     = 1
}

variable "health_check_grace_period_seconds" {
  description = "Seconds ECS waits before the ALB health check is enforced after a new task starts."
  type        = number
  default     = 60
}

# ─── IAM roles (outputs of account-bootstrap) ──────────────────────────

variable "ecs_execution_role_arn" {
  description = "ARN of the ECS execution role created by account-bootstrap (iam_role_arns.ecs_execution)."
  type        = string
}

variable "backend_task_role_arn" {
  description = "ARN of the backend ECS task role created by account-bootstrap (iam_role_arns.backend_task)."
  type        = string
}

# ─── Application config ────────────────────────────────────────────────

variable "cognito_user_pool_id" {
  description = "Cognito user pool ID injected as APP_ENV variable into the backend container."
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito app client ID injected into the backend container."
  type        = string
}

variable "cognito_allowed_client_ids" {
  description = "Comma-separated Cognito client IDs injected into the backend container."
  type        = string
}

variable "agentcore_runtime_arn" {
  description = "AgentCore Runtime ARN injected into the backend container. Can be set to empty on first deploy and updated once the runtime is created."
  type        = string
  default     = ""
}

variable "supabase_url" {
  description = "Supabase project URL injected as a plaintext env var into the backend container."
  type        = string
  default     = ""
}

variable "supabase_service_role_key" {
  description = "Supabase service-role key injected as a plaintext env var. Stored in tfstate — acceptable for demo/MVP."
  type      = string
  default   = ""
  sensitive = true
}

variable "dev_bypass_auth" {
  description = "Set DEV_BYPASS_AUTH=true in the container to skip Cognito auth. For demo/testing only."
  type        = bool
  default     = false
}
