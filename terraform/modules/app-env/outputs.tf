output "namespace" {
  value = kubernetes_namespace_v1.this.metadata[0].name
}

output "secret_name" {
  description = "Secrets Manager secret to populate manually."
  value       = aws_secretsmanager_secret.mysql.name
}

output "kyc_api_key_secret_name" {
  description = "Secrets Manager secret holding the X-API-Key clients must send. Populate manually."
  value       = aws_secretsmanager_secret.kyc_api_key.name
}

output "llm_api_key_secret_name" {
  description = "Secrets Manager secret holding the Anthropic API key. Populate manually."
  value       = aws_secretsmanager_secret.llm_api_key.name
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

output "app_service_account" {
  description = "Service account the app Deployment should use (null when Bedrock access is disabled)."
  value       = local.bedrock_enabled ? kubernetes_service_account_v1.app[0].metadata[0].name : null
}

output "app_role_arn" {
  value = local.bedrock_enabled ? aws_iam_role.app[0].arn : null
}
