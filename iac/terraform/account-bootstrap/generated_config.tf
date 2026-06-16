resource "local_file" "deploy_settings" {
  filename = "${local.generated_dir}/deploy.settings.json"
  content = jsonencode({
    profile      = var.aws_profile
    appEnv       = var.app_env
    region       = var.aws_region
    accountId    = local.account_id
    sourceBucket = aws_s3_bucket.source.bucket
    gateway = {
      id                 = ""
      createTemplatePath = "ops/aws/gateway-create-specialist.json"
      targetTemplatePath = "ops/aws/gateway-target-create-specialist.template.json"
    }
    orchestrator = {
      policyAllowedTools    = var.policy_allowed_tools
      gatewayTimeoutSeconds = var.gateway_timeout_seconds
    }
    build = {
      defaultImageTagSuffix        = "arm64"
      specialistOptionalFinanceExtras = true
    }
  })
}

resource "local_file" "orchestrator_manifest" {
  filename = "${local.generated_dir}/orchestrator.runtime.manifest.json"
  content = jsonencode({
    name                 = "orchestrator"
    runtimeName          = var.orchestrator_runtime_name
    runtimeId            = ""
    sourceRoot           = "agent"
    buildspecPath        = "ops/aws/buildspec-orchestrator-arm64.yml"
    runtimeTemplatePath  = "ops/aws/runtime-create-orchestrator.template.json"
    codebuildProjectName = aws_codebuild_project.orchestrator.name
    sourceBundleKey      = local.orchestrator_source_bundle_key
    imageRepoUri         = aws_ecr_repository.orchestrator.repository_url
    templateBindings = {
      IMAGE_TAG                                     = "REPLACE_ME_IMAGE_TAG"
      IMAGE_REPO_URI                                = "REPLACE_ME_ORCHESTRATOR_IMAGE_REPO_URI"
      RUNTIME_ROLE_ARN                              = "REPLACE_ME_ORCHESTRATOR_RUNTIME_ROLE_ARN"
      CLIENT_TOKEN                                  = "REPLACE_ME_UNIQUE_ORCHESTRATOR_RUNTIME_CLIENT_TOKEN"
      APP_ENV                                       = "REPLACE_ME_APP_ENV"
      AWS_REGION                                    = "REPLACE_ME_AWS_REGION"
      BACKEND_API_BASE                              = "REPLACE_ME_BACKEND_API_BASE"
      GATEWAY_ENDPOINT                              = "REPLACE_ME_GATEWAY_ENDPOINT"
      COGNITO_DISCOVERY_URL                         = "REPLACE_ME_COGNITO_DISCOVERY_URL"
      COGNITO_ALLOWED_CLIENTS_JSON                  = "REPLACE_ME_COGNITO_ALLOWED_CLIENTS_JSON"
      COGNITO_USER_POOL_ID                          = "REPLACE_ME_COGNITO_USER_POOL_ID"
      COGNITO_CLIENT_ID                             = "REPLACE_ME_COGNITO_CLIENT_ID"
      COGNITO_ALLOWED_CLIENT_IDS                    = "REPLACE_ME_COGNITO_ALLOWED_CLIENT_IDS"
      COGNITO_REGION                                = "REPLACE_ME_COGNITO_REGION"
      POLICY_ALLOWED_TOOLS                          = "REPLACE_ME_POLICY_ALLOWED_TOOLS"
      GATEWAY_TIMEOUT_SECONDS                       = "REPLACE_ME_GATEWAY_TIMEOUT_SECONDS"
      STOCK_AGENT_EXTERNAL_ENABLED                  = "REPLACE_ME_STOCK_AGENT_EXTERNAL_ENABLED"
      STOCK_AGENT_EXTERNAL_URL                      = "REPLACE_ME_STOCK_AGENT_EXTERNAL_URL"
      STOCK_AGENT_EXTERNAL_BASE_URL                 = "REPLACE_ME_STOCK_AGENT_EXTERNAL_BASE_URL"
      STOCK_AGENT_EXTERNAL_ENDPOINT_PATH            = "REPLACE_ME_STOCK_AGENT_EXTERNAL_ENDPOINT_PATH"
      STOCK_AGENT_EXTERNAL_AUTH_TOKEN               = "REPLACE_ME_STOCK_AGENT_EXTERNAL_AUTH_TOKEN"
      STOCK_AGENT_EXTERNAL_MODEL_PROVIDER           = "REPLACE_ME_STOCK_AGENT_EXTERNAL_MODEL_PROVIDER"
      STOCK_AGENT_EXTERNAL_MODEL                    = "REPLACE_ME_STOCK_AGENT_EXTERNAL_MODEL"
      STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS  = "REPLACE_ME_STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS"
      STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS     = "REPLACE_ME_STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS"
    }
  })
}

resource "local_file" "specialist_manifest" {
  filename = "${local.generated_dir}/specialist.runtime.manifest.json"
  content = jsonencode({
    name                 = "specialist"
    runtimeName          = var.specialist_runtime_name
    runtimeId            = ""
    sourceRoot           = "src/aws-specialist-agent-mcp-server"
    buildspecPath        = "ops/aws/buildspec-specialist-arm64.yml"
    runtimeTemplatePath  = "ops/aws/runtime-create-specialist-agent-mcp.template.json"
    codebuildProjectName = aws_codebuild_project.specialist.name
    sourceBundleKey      = local.specialist_source_bundle_key
    imageRepoUri         = aws_ecr_repository.specialist.repository_url
    templateBindings = {
      IMAGE_TAG                            = "REPLACE_ME_IMAGE_TAG"
      IMAGE_REPO_URI                       = "REPLACE_ME_SPECIALIST_IMAGE_REPO_URI"
      RUNTIME_ROLE_ARN                     = "REPLACE_ME_SPECIALIST_RUNTIME_ROLE_ARN"
      CLIENT_TOKEN                         = "REPLACE_ME_UNIQUE_SPECIALIST_RUNTIME_CLIENT_TOKEN"
      APP_ENV                              = "REPLACE_ME_APP_ENV"
      AWS_REGION                           = "REPLACE_ME_AWS_REGION"
      COGNITO_DISCOVERY_URL                = "REPLACE_ME_COGNITO_DISCOVERY_URL"
      COGNITO_ALLOWED_CLIENTS_JSON         = "REPLACE_ME_COGNITO_ALLOWED_CLIENTS_JSON"
      COGNITO_USER_POOL_ID                 = "REPLACE_ME_COGNITO_USER_POOL_ID"
      COGNITO_CLIENT_ID                    = "REPLACE_ME_COGNITO_CLIENT_ID"
      COGNITO_ALLOWED_CLIENT_IDS           = "REPLACE_ME_COGNITO_ALLOWED_CLIENT_IDS"
      COGNITO_SERVICE_CLIENT_IDS           = "REPLACE_ME_COGNITO_SERVICE_CLIENT_IDS"
      SUPABASE_URL                         = "REPLACE_ME_SUPABASE_URL"
      SUPABASE_SERVICE_ROLE_KEY            = "REPLACE_ME_SUPABASE_SERVICE_ROLE_KEY"
      STOCK_AGENT_EXTERNAL_ENABLED         = "REPLACE_ME_STOCK_AGENT_EXTERNAL_ENABLED"
      STOCK_AGENT_EXTERNAL_URL             = "REPLACE_ME_STOCK_AGENT_EXTERNAL_URL"
      STOCK_AGENT_EXTERNAL_BASE_URL        = "REPLACE_ME_STOCK_AGENT_EXTERNAL_BASE_URL"
      STOCK_AGENT_EXTERNAL_ENDPOINT_PATH   = "REPLACE_ME_STOCK_AGENT_EXTERNAL_ENDPOINT_PATH"
      STOCK_AGENT_EXTERNAL_MODEL_PROVIDER  = "REPLACE_ME_STOCK_AGENT_EXTERNAL_MODEL_PROVIDER"
      STOCK_AGENT_EXTERNAL_MODEL           = "REPLACE_ME_STOCK_AGENT_EXTERNAL_MODEL"
      STOCK_AGENT_EXTERNAL_AUTH_TOKEN      = "REPLACE_ME_STOCK_AGENT_EXTERNAL_AUTH_TOKEN"
      STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS = "REPLACE_ME_STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS"
    }
  })
}

resource "local_file" "backend_manifest" {
  filename = "${local.generated_dir}/backend.ecs.manifest.json"
  content = jsonencode({
    name                  = "backend"
    serviceType           = "ecs-fargate"
    serviceName           = var.backend_service_name
    sourceRoot            = "backend"
    dockerfilePath        = "backend/Dockerfile"
    dockerPlatform        = "linux/amd64"
    imageRepoUri          = aws_ecr_repository.backend.repository_url
    defaultImageTagSuffix = "backend"
    ecsExecutionRoleArn   = aws_iam_role.ecs_execution.arn
    ecsTaskRoleArn        = aws_iam_role.backend_task.arn
    terraformDir          = "iac/terraform/ecs-services"
  })
}

resource "local_file" "deploy_env_ps1" {
  filename = "${local.generated_dir}/deploy.env.ps1"
  content  = <<-EOT
    $env:DEPLOY_APP_ENV = "${var.app_env}"
    $env:DEPLOY_COGNITO_USER_POOL_ID = "${local.cognito_user_pool_id}"
    $env:DEPLOY_COGNITO_CLIENT_ID = "${local.cognito_client_id}"
    $env:DEPLOY_COGNITO_ALLOWED_CLIENT_IDS = "${local.cognito_allowed_client_ids_csv}"
    $env:DEPLOY_COGNITO_SERVICE_CLIENT_IDS = "${local.cognito_client_id}"
    $env:DEPLOY_ORCHESTRATOR_RUNTIME_ROLE_ARN = "${aws_iam_role.orchestrator_runtime.arn}"
    $env:DEPLOY_SPECIALIST_RUNTIME_ROLE_ARN = "${aws_iam_role.specialist_runtime.arn}"
    $env:DEPLOY_GATEWAY_ROLE_ARN = "${aws_iam_role.gateway_execution.arn}"
    $env:DEPLOY_GATEWAY_NAME = "${var.gateway_name}"
    $env:DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN = "${var.gateway_oauth_provider_arn}"
    $env:DEPLOY_ECS_EXECUTION_ROLE_ARN = "${aws_iam_role.ecs_execution.arn}"
    $env:DEPLOY_BACKEND_TASK_ROLE_ARN = "${aws_iam_role.backend_task.arn}"
    $env:DEPLOY_BACKEND_IMAGE_REPO_URI = "${aws_ecr_repository.backend.repository_url}"
    $env:DEPLOY_BACKEND_SERVICE_NAME = "${var.backend_service_name}"
    $env:DEPLOY_BACKEND_API_BASE = "${var.backend_api_base}"
    $env:DEPLOY_POLICY_ALLOWED_TOOLS = "${var.policy_allowed_tools}"
    $env:DEPLOY_GATEWAY_TIMEOUT_SECONDS = "${var.gateway_timeout_seconds}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_ENABLED = "${var.stock_agent_external_enabled}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_URL = "${var.stock_agent_external_url}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_BASE_URL = "${var.stock_agent_external_base_url}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_ENDPOINT_PATH = "${var.stock_agent_external_endpoint_path}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_MODEL_PROVIDER = "${var.stock_agent_external_model_provider}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_MODEL = "${var.stock_agent_external_model}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS = "${var.stock_agent_external_timeout_seconds}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS = "${var.stock_agent_external_connect_timeout_seconds}"
    $env:DEPLOY_STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS = "${var.stock_agent_external_read_timeout_seconds}"

    # Set these outside Terraform so secrets do not land in terraform.tfstate:
    # $env:DEPLOY_SUPABASE_URL = "https://..."
    # $env:DEPLOY_SUPABASE_SERVICE_ROLE_KEY = "..."
    # $env:DEPLOY_STOCK_AGENT_EXTERNAL_AUTH_TOKEN = "..."
    # If gateway_oauth_provider_arn was left empty:
    # $env:DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN = "arn:aws:bedrock-agentcore:..."
  EOT
}
