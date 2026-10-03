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

variable "github_repository" {
  description = "GitHub repository (owner/name) whose workflows may deploy to qa."
  type        = string
  default     = "meetbrij/prod-grade-e2e-devsecops-pipeline"
}

variable "ecr_repository_name" {
  type    = string
  default = "nodejs-app"
}
