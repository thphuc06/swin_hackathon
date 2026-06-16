resource "aws_codebuild_project" "orchestrator" {
  name          = local.orchestrator_codebuild_project
  description   = "Builds and pushes the AgentCore orchestrator runtime image."
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 60
  queued_timeout = 480

  artifacts {
    type = "NO_ARTIFACTS"
  }

  cache {
    type = "NO_CACHE"
  }

  environment {
    type                        = "ARM_CONTAINER"
    image                       = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    compute_type                = "BUILD_GENERAL1_MEDIUM"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "IMAGE_REPO_URI"
      value = local.orchestrator_image_repo_uri
      type  = "PLAINTEXT"
    }

    environment_variable {
      name  = "IMAGE_REPO_REGISTRY"
      value = local.ecr_registry
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.source.bucket}/${local.orchestrator_source_bundle_key}"
    buildspec = "buildspec.yml"
  }
}

resource "aws_codebuild_project" "specialist" {
  name           = local.specialist_codebuild_project
  description    = "Builds and pushes the specialist MCP AgentCore runtime image."
  service_role   = aws_iam_role.codebuild.arn
  build_timeout  = 60
  queued_timeout = 480

  artifacts {
    type = "NO_ARTIFACTS"
  }

  cache {
    type = "NO_CACHE"
  }

  environment {
    type                        = "ARM_CONTAINER"
    image                       = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    compute_type                = "BUILD_GENERAL1_MEDIUM"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "IMAGE_REPO_URI"
      value = local.specialist_image_repo_uri
      type  = "PLAINTEXT"
    }

    environment_variable {
      name  = "IMAGE_REPO_REGISTRY"
      value = local.ecr_registry
      type  = "PLAINTEXT"
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.source.bucket}/${local.specialist_source_bundle_key}"
    buildspec = "buildspec.yml"
  }
}
