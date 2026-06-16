output "vpc_id" {
  description = "VPC ID used by the ECS service."
  value       = local.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs."
  value       = local.public_subnet_ids
}

output "alb_dns_name" {
  description = "ALB DNS name. Set this as BACKEND_API_BASE / backend_api_base in account-bootstrap after first deploy."
  value       = "${var.acm_certificate_arn != "" ? "https" : "http"}://${aws_lb.backend.dns_name}"
}

output "alb_arn" {
  description = "ALB ARN."
  value       = aws_lb.backend.arn
}

output "alb_security_group_id" {
  description = "Security group attached to the ALB."
  value       = aws_security_group.alb.id
}

output "tasks_security_group_id" {
  description = "Security group attached to ECS tasks."
  value       = aws_security_group.tasks.id
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.backend.name
}

output "task_definition_arn" {
  description = "ARN of the registered task definition revision."
  value       = aws_ecs_task_definition.backend.arn
}

output "log_group_name" {
  description = "CloudWatch log group name for backend task logs."
  value       = aws_cloudwatch_log_group.backend.name
}

output "next_commands" {
  description = "Suggested commands after apply."
  value = [
    "Set backend_api_base in account-bootstrap: ${var.acm_certificate_arn != "" ? "https" : "http"}://${aws_lb.backend.dns_name}",
    "Force new deployment: aws ecs update-service --cluster ${aws_ecs_cluster.this.name} --service ${aws_ecs_service.backend.name} --force-new-deployment --region ${var.aws_region}",
    "Check service health: aws ecs describe-services --cluster ${aws_ecs_cluster.this.name} --services ${aws_ecs_service.backend.name} --region ${var.aws_region} --output json",
    "Tail logs: aws logs tail ${aws_cloudwatch_log_group.backend.name} --follow --region ${var.aws_region}",
  ]
}
