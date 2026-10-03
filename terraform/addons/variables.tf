variable "region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Project name, used for tags."
  type        = string
  default     = "devsecops"
}

variable "state_bucket" {
  description = "Name of the Terraform state bucket (bootstrap output). Used to read the platform stack's outputs."
  type        = string
}

variable "platform_state_key" {
  description = "State key of the platform stack."
  type        = string
  default     = "platform/terraform.tfstate"
}

variable "alb_controller_chart_version" {
  description = "Helm chart version of the AWS Load Balancer Controller."
  type        = string
  default     = "3.5.0"
}

variable "external_secrets_chart_version" {
  description = "Helm chart version of External Secrets Operator."
  type        = string
  default     = "2.11.0"
}
