data "aws_iam_policy_document" "agentcore_assume_role" {
  statement {
    sid     = "AllowBedrockAgentCoreAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:*"]
    }
  }
}

data "aws_iam_policy_document" "codebuild_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}


resource "aws_iam_role" "orchestrator_runtime" {
  name               = "${local.name_prefix}-agentcore-orchestrator-runtime"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume_role.json
}

resource "aws_iam_role" "specialist_runtime" {
  name               = "${local.name_prefix}-agentcore-specialist-runtime"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume_role.json
}

resource "aws_iam_role" "gateway_execution" {
  name               = "${local.name_prefix}-agentcore-gateway-execution"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume_role.json
}

resource "aws_iam_role" "codebuild" {
  name               = local.codebuild_role_name
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}


data "aws_iam_policy_document" "runtime_common" {
  statement {
    sid    = "ECRTokenAccess"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "CloudWatchLogsRuntime"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:*"
    ]
  }

  statement {
    sid    = "XRayAndMetrics"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets"
    ]
    resources = ["*"]
  }

  statement {
    sid       = "CloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

  statement {
    sid    = "BedrockModelInvocation"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:*"
    ]
  }

  statement {
    sid    = "AgentCoreWorkloadTokens"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
      "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:workload-identity-directory/default",
      "arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:workload-identity-directory/default/workload-identity/*"
    ]
  }
}

data "aws_iam_policy_document" "orchestrator_runtime" {
  source_policy_documents = [data.aws_iam_policy_document.runtime_common.json]

  statement {
    sid    = "ECRImageAccessOrchestrator"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = [aws_ecr_repository.orchestrator.arn]
  }

  statement {
    sid    = "InvokeAgentCoreGateway"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeGateway"
    ]
    resources = ["arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:gateway/*"]
  }
}

data "aws_iam_policy_document" "specialist_runtime" {
  source_policy_documents = [data.aws_iam_policy_document.runtime_common.json]

  statement {
    sid    = "ECRImageAccessSpecialist"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = [aws_ecr_repository.specialist.arn]
  }
}

resource "aws_iam_role_policy" "orchestrator_runtime" {
  name   = "${local.name_prefix}-agentcore-orchestrator-runtime"
  role   = aws_iam_role.orchestrator_runtime.id
  policy = data.aws_iam_policy_document.orchestrator_runtime.json
}

resource "aws_iam_role_policy" "specialist_runtime" {
  name   = "${local.name_prefix}-agentcore-specialist-runtime"
  role   = aws_iam_role.specialist_runtime.id
  policy = data.aws_iam_policy_document.specialist_runtime.json
}

data "aws_iam_policy_document" "gateway_execution" {
  statement {
    sid    = "PolicyEngineConfiguration"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:GetPolicyEngine"
    ]
    resources = ["arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:policy-engine/*"]
  }

  statement {
    sid    = "PolicyEngineAuthorization"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:AuthorizeAction",
      "bedrock-agentcore:PartiallyAuthorizeActions"
    ]
    resources = [
      "arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:policy-engine/*",
      "arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:gateway/*"
    ]
  }

  statement {
    sid    = "CloudWatchAndXRay"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "SecretsForGatewayOutboundAuth"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:${var.project_name}/${var.app_env}/*"]
  }

  statement {
    sid    = "InvokeAgentCoreRuntimeTarget"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeAgentRuntime"
    ]
    resources = ["arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:runtime/*"]
  }
}

resource "aws_iam_role_policy" "gateway_execution" {
  name   = "${local.name_prefix}-agentcore-gateway-execution"
  role   = aws_iam_role.gateway_execution.id
  policy = data.aws_iam_policy_document.gateway_execution.json
}

data "aws_iam_policy_document" "codebuild" {
  statement {
    sid    = "CloudWatchLogsForCodeBuild"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/codebuild/${local.orchestrator_codebuild_project}",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/codebuild/${local.orchestrator_codebuild_project}:*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/codebuild/${local.specialist_codebuild_project}",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/codebuild/${local.specialist_codebuild_project}:*"
    ]
  }

  statement {
    sid    = "SourceBucketAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.source.arn,
      "${aws_s3_bucket.source.arn}/*"
    ]
  }

  statement {
    sid    = "ECRAuthorization"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ECRPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart"
    ]
    resources = [
      aws_ecr_repository.orchestrator.arn,
      aws_ecr_repository.specialist.arn
    ]
  }
}

resource "aws_iam_role_policy" "codebuild" {
  name   = "${local.name_prefix}-codebuild"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild.json
}

# ─── ECS: execution role (Fargate agent – ECR pull, log writes, secret injection) ───

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "ecs_execution" {
  statement {
    sid       = "ECRTokenAccess"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ECRImagePull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = [aws_ecr_repository.backend.arn]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/ecs/${var.project_name}-${var.app_env}*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/ecs/${var.project_name}-${var.app_env}*:log-stream:*"
    ]
  }

}

resource "aws_iam_role_policy" "ecs_execution" {
  name   = "${local.name_prefix}-ecs-execution"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution.json
}

# ─── ECS: backend task role (application code – Bedrock, AgentCore, Secrets) ───

resource "aws_iam_role" "backend_task" {
  name               = "${local.name_prefix}-backend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "backend_task" {
  statement {
    sid    = "BedrockInvocation"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:*"
    ]
  }

  statement {
    sid    = "AgentCoreInvoke"
    effect = "Allow"
    actions = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [
      "arn:aws:bedrock-agentcore:${var.aws_region}:${local.account_id}:runtime/*"
    ]
  }

  statement {
    sid    = "SecretsRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${local.account_id}:secret:${var.project_name}/${var.app_env}/*"
    ]
  }
}

resource "aws_iam_role_policy" "backend_task" {
  name   = "${local.name_prefix}-backend-task"
  role   = aws_iam_role.backend_task.id
  policy = data.aws_iam_policy_document.backend_task.json
}
