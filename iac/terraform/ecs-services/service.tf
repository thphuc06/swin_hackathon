locals {
  supabase_env = var.supabase_url != "" ? [
    { name = "SUPABASE_URL",              value = var.supabase_url },
    { name = "SUPABASE_SERVICE_ROLE_KEY", value = var.supabase_service_role_key }
  ] : []

  agentcore_env = var.agentcore_runtime_arn != "" ? [
    { name = "AGENTCORE_RUNTIME_ARN", value = var.agentcore_runtime_arn }
  ] : []
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name_prefix}-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.backend_task_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.backend_image
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = concat(
        [
          { name = "APP_ENV",                    value = var.app_env },
          { name = "AWS_REGION",                 value = var.aws_region },
          { name = "DEV_BYPASS_AUTH",            value = tostring(var.dev_bypass_auth) },
          { name = "COGNITO_USER_POOL_ID",       value = var.cognito_user_pool_id },
          { name = "COGNITO_CLIENT_ID",          value = var.cognito_client_id },
          { name = "COGNITO_ALLOWED_CLIENT_IDS", value = var.cognito_allowed_client_ids }
        ],
        local.agentcore_env,
        local.supabase_env
      )

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      # Give the app up to 30s to finish draining connections before SIGKILL.
      stopTimeout = 30
    }
  ])

  lifecycle {
    precondition {
      condition     = !(contains(["staging", "prod"], var.app_env) && var.dev_bypass_auth)
      error_message = "dev_bypass_auth must be false when app_env is staging or prod."
    }
  }
}

resource "aws_ecs_service" "backend" {
  name            = "${local.name_prefix}-backend"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"

  platform_version = "LATEST"

  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = var.assign_public_ip_to_tasks
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8080
  }

  health_check_grace_period_seconds = var.health_check_grace_period_seconds

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  depends_on = [
    aws_lb_listener.http_forward,
    aws_lb_listener.http_redirect,
    aws_lb_listener.https,
  ]
}
