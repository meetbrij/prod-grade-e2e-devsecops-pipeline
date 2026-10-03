variable "env_name" {
  description = "Environment name. Also used as the Kubernetes namespace and secret name prefix (for example qa, prod)."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS cluster OIDC provider (for IRSA)."
  type        = string
}

variable "oidc_provider" {
  description = "EKS cluster OIDC issuer without https:// (for IRSA trust conditions)."
  type        = string
}

variable "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider."
  type        = string
}

variable "github_repository_claim" {
  description = "The repository exactly as GitHub writes it in the OIDC subject claim, including the immutable owner and repository IDs: owner@ownerId/name@repoId."
  type        = string
}

variable "github_subject" {
  description = "OIDC subject suffix that may assume the deploy role, for example 'ref:refs/heads/qa' or 'environment:prod'."
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository the deploy role may use."
  type        = string
}

variable "ecr_actions" {
  description = "ECR repository actions granted to the deploy role. Push (qa) or retag (prod)."
  type        = list(string)
}

variable "secret_recovery_window_days" {
  description = "Days Secrets Manager keeps a deleted secret before removing it. 0 deletes immediately (lets qa be destroyed and recreated)."
  type        = number
  default     = 0
}

variable "quota" {
  description = "ResourceQuota for the namespace."
  type = object({
    requests_cpu    = string
    requests_memory = string
    limits_cpu      = string
    limits_memory   = string
    pods            = string
    pvcs            = string
    storage         = string
  })
  default = {
    requests_cpu    = "1"
    requests_memory = "2Gi"
    limits_cpu      = "2"
    limits_memory   = "3Gi"
    pods            = "20"
    pvcs            = "3"
    storage         = "10Gi"
  }
}

variable "container_defaults" {
  description = "LimitRange defaults applied to containers that do not set their own requests/limits."
  type = object({
    request_cpu    = string
    request_memory = string
    limit_cpu      = string
    limit_memory   = string
  })
  default = {
    request_cpu    = "100m"
    request_memory = "128Mi"
    limit_cpu      = "500m"
    limit_memory   = "512Mi"
  }
}
