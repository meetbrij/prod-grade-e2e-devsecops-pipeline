output "region" {
  value = var.region
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "oidc_provider_arn" {
  description = "EKS cluster OIDC provider (for IRSA roles)."
  value       = module.eks.oidc_provider_arn
}

output "oidc_provider" {
  description = "EKS cluster OIDC issuer without https:// (for IRSA trust conditions)."
  value       = module.eks.oidc_provider
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "certificate_arn" {
  value = aws_acm_certificate_validation.this.certificate_arn
}

output "github_oidc_provider_arn" {
  description = "GitHub Actions OIDC provider (for CI deploy role trust policies)."
  value       = local.github_oidc_provider_arn
}
