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

variable "namespace" {
  description = "Namespace for the whole observability stack."
  type        = string
  default     = "monitoring"
}

variable "storage_class" {
  description = "StorageClass for the stack's volumes. ebs-sc-retain keeps the volume if a claim is deleted. The live PVs were patched to Delete; use ebs-sc on a fresh install."
  type        = string
  default     = "ebs-sc-retain"
}

variable "metrics_retention" {
  description = "How long Prometheus keeps metrics."
  type        = string
  default     = "15d"
}

variable "logs_retention" {
  description = "How long Loki keeps logs (Go duration, hours)."
  type        = string
  default     = "360h" # 15 days
}

variable "traces_retention" {
  description = "How long Tempo keeps traces (Go duration, hours)."
  type        = string
  default     = "360h" # 15 days
}

variable "prometheus_storage_size" {
  type    = string
  default = "20Gi"
}

variable "loki_storage_size" {
  type    = string
  default = "10Gi"
}

variable "tempo_storage_size" {
  type    = string
  default = "10Gi"
}

variable "kube_prometheus_stack_chart_version" {
  type    = string
  default = "91.9.0"
}

variable "loki_chart_version" {
  type    = string
  default = "7.3.0"
}

variable "tempo_chart_version" {
  type    = string
  default = "1.24.4"
}

variable "alloy_chart_version" {
  type    = string
  default = "1.13.0"
}
