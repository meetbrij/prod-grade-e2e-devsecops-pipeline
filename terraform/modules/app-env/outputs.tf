output "namespace" {
  value = kubernetes_namespace_v1.this.metadata[0].name
}

output "secret_name" {
  description = "Secrets Manager secret to populate manually."
  value       = aws_secretsmanager_secret.mysql.name
}

output "eso_service_account" {
  description = "Service account the SecretStore in this namespace should reference."
  value       = kubernetes_service_account_v1.eso.metadata[0].name
}

output "eso_role_arn" {
  value = aws_iam_role.eso.arn
}

output "deploy_role_arn" {
  description = "Role the GitHub workflow assumes for this environment."
  value       = aws_iam_role.deploy.arn
}
