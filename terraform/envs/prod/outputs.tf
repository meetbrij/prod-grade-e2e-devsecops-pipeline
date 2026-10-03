output "namespace" {
  value = module.app_env.namespace
}

output "secret_name" {
  value = module.app_env.secret_name
}

output "eso_service_account" {
  value = module.app_env.eso_service_account
}

output "eso_role_arn" {
  value = module.app_env.eso_role_arn
}

output "deploy_role_arn" {
  description = "Set as the AWS_ROLE_TO_ASSUME_PROD variable in GitHub."
  value       = module.app_env.deploy_role_arn
}
