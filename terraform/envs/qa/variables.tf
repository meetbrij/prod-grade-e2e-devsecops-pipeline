variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "project" {
  type    = string
  default = "devsecops"
}

variable "state_bucket" {
  description = "Name of the Terraform state bucket (bootstrap output). Used to read the platform stack's outputs."
  type        = string
}

variable "platform_state_key" {
  type    = string
  default = "platform/terraform.tfstate"
}

variable "github_repository_claim" {
  description = "Repository as it appears in GitHub's OIDC subject claim: owner@ownerId/name@repoId. GitHub's immutable IDs stop a renamed or recreated repo from inheriting this role. Find it in the 'sub' claim of a workflow run."
  type        = string
  default     = "meetbrij@4499354/prod-grade-e2e-devsecops-pipeline@1397427060"
}

variable "ecr_repository_name" {
  type    = string
  default = "nodejs-app"
}
