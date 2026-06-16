output "account_id" {
  description = "Target AWS account ID."
  value       = local.account_id
}

output "region" {
  description = "Target AWS region."
  value       = var.aws_region
}

output "source_bucket" {
  description = "S3 bucket used by deployment scripts for CodeBuild source zips."
  value       = aws_s3_bucket.source.bucket
}

output "ecr_repositories" {
  description = "ECR repository URLs for deploy scripts."
  value = {
    orchestrator = aws_ecr_repository.orchestrator.repository_url
    specialist   = aws_ecr_repository.specialist.repository_url
    backend      = aws_ecr_repository.backend.repository_url
  }
}

output "iam_role_arns" {
  description = "IAM roles consumed by AgentCore, Gateway, CodeBuild, and ECS."
  value = {
    orchestrator_runtime = aws_iam_role.orchestrator_runtime.arn
    specialist_runtime   = aws_iam_role.specialist_runtime.arn
    gateway_execution    = aws_iam_role.gateway_execution.arn
    codebuild            = aws_iam_role.codebuild.arn
    ecs_execution        = aws_iam_role.ecs_execution.arn
    backend_task         = aws_iam_role.backend_task.arn
  }
}

output "cognito" {
  description = "Cognito IDs used by backend, orchestrator, specialist runtime, and AgentCore custom JWT authorizer."
  value = {
    user_pool_id       = local.cognito_user_pool_id
    app_client_id      = local.cognito_client_id
    allowed_client_ids = local.cognito_allowed_client_ids
    discovery_url      = "https://cognito-idp.${var.aws_region}.amazonaws.com/${local.cognito_user_pool_id}/.well-known/openid-configuration"
  }
}

output "generated_files" {
  description = "Generated config files for the existing ops/aws deployment scripts."
  value = {
    deploy_settings       = local_file.deploy_settings.filename
    orchestrator_manifest = local_file.orchestrator_manifest.filename
    specialist_manifest   = local_file.specialist_manifest.filename
    backend_manifest      = local_file.backend_manifest.filename
    deploy_env_ps1        = local_file.deploy_env_ps1.filename
  }
}

output "next_commands" {
  description = "High-level next commands after terraform apply."
  value = [
    "powershell -ExecutionPolicy Bypass -File .\\sync-generated-config.ps1",
    ". .\\generated\\deploy.env.ps1",
    "Set DEPLOY_SUPABASE_URL and DEPLOY_SUPABASE_SERVICE_ROLE_KEY outside Terraform.",
    "Run .\\ops\\aws\\deploy_full_aws.ps1 -SettingsPath ops/aws/deploy.settings.terraform.json -CreateGatewayIfMissing from the repo root."
  ]
}
