variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Project name, used for tags and resource names."
  type        = string
  default     = "devsecops"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "devsecops-eks"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Keep within standard support to avoid extended-support charges."
  type        = string
  default     = "1.36"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to use."
  type        = number
  default     = 2
}

variable "node_instance_type" {
  description = "Instance type for the managed node group."
  type        = string
  default     = "t3a.medium"
}

variable "node_min_size" {
  type    = number
  default = 2
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_max_size" {
  type    = number
  default = 3
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. GitHub-hosted runners have no fixed IPs, so this stays open; access is still controlled by IAM and EKS access entries."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ecr_repository_name" {
  description = "ECR repository for the application image."
  type        = string
  default     = "nodejs-app"
}

variable "create_github_oidc_provider" {
  description = "Create the account-wide GitHub Actions OIDC provider. Set to false if one already exists in this AWS account (only one per URL is allowed)."
  type        = bool
  default     = true
}

variable "hosted_zone_id" {
  description = "ID of the EXISTING Route 53 public hosted zone. Referenced as a data source only; never created or destroyed here."
  type        = string
  default     = "Z07282781O1NN543FLL11"
}

variable "certificate_domains" {
  description = "Hostnames covered by the ACM certificate (first is the primary name, the rest are SANs)."
  type        = list(string)
  default = [
    "proj3-aigateway.bolarbrijesh.com",
    "qa-proj3-aigateway.bolarbrijesh.com",
  ]
}
