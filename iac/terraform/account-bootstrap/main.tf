data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  name_prefix = "${var.project_name}-${var.app_env}"

  source_bucket_name = var.source_bucket_name != "" ? var.source_bucket_name : "bedrock-agentcore-codebuild-sources-${local.account_id}-${var.aws_region}"
  ecr_registry       = "${local.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"

  orchestrator_image_repo_uri = "${local.ecr_registry}/${var.orchestrator_ecr_repository_name}"
  specialist_image_repo_uri   = "${local.ecr_registry}/${var.specialist_ecr_repository_name}"
  backend_image_repo_uri      = "${local.ecr_registry}/${var.backend_ecr_repository_name}"

  cognito_user_pool_id = var.create_cognito ? aws_cognito_user_pool.this[0].id : var.existing_cognito_user_pool_id
  cognito_client_id    = var.create_cognito ? aws_cognito_user_pool_client.app[0].id : var.existing_cognito_client_id
  cognito_allowed_client_ids = length(var.cognito_allowed_client_ids) > 0 ? var.cognito_allowed_client_ids : [
    local.cognito_client_id
  ]
  cognito_allowed_client_ids_csv  = join(",", local.cognito_allowed_client_ids)
  cognito_allowed_client_ids_json = jsonencode(local.cognito_allowed_client_ids)

  codebuild_role_name             = "${local.name_prefix}-agentcore-codebuild"
  orchestrator_codebuild_project  = "${var.project_name}-orchestrator-runtime-builder"
  specialist_codebuild_project    = "${var.project_name}-specialist-agent-mcp-builder"
  orchestrator_source_bundle_key  = "${var.project_name}-orchestrator-runtime/source.zip"
  specialist_source_bundle_key    = "${var.project_name}-specialist-agent-mcp/source.zip"
  generated_dir                   = "${path.module}/generated"

  tags = merge(
    {
      Project     = var.project_name
      Environment = var.app_env
      ManagedBy   = "terraform"
      Component   = "account-bootstrap"
    },
    var.default_tags
  )
}

resource "aws_ecr_repository" "orchestrator" {
  name                 = var.orchestrator_ecr_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = var.force_delete_ecr_repositories

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "specialist" {
  name                 = var.specialist_ecr_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = var.force_delete_ecr_repositories

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "backend" {
  name                 = var.backend_ecr_repository_name
  image_tag_mutability = "MUTABLE"
  force_delete         = var.force_delete_ecr_repositories

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "repositories" {
  for_each = {
    orchestrator = aws_ecr_repository.orchestrator.name
    specialist   = aws_ecr_repository.specialist.name
    backend      = aws_ecr_repository.backend.name
  }

  repository = each.value

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the most recent 20 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_s3_bucket" "source" {
  bucket = local.source_bucket_name
}

resource "aws_s3_bucket_public_access_block" "source" {
  bucket = aws_s3_bucket.source.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "source" {
  bucket = aws_s3_bucket.source.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "source" {
  bucket = aws_s3_bucket.source.id

  rule {
    id     = "expire-codebuild-source-bundles"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = var.source_bundle_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_cognito_user_pool" "this" {
  count = var.create_cognito ? 1 : 0

  name = "${local.name_prefix}-users"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "app" {
  count = var.create_cognito ? 1 : 0

  name         = "${local.name_prefix}-app"
  user_pool_id = aws_cognito_user_pool.this[0].id

  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["email", "openid", "profile"]
  callback_urls                        = var.cognito_callback_urls
  logout_urls                          = var.cognito_logout_urls
  supported_identity_providers         = ["COGNITO"]

  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
