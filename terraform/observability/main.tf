provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "observability"
    }
  }
}

data "terraform_remote_state" "platform" {
  backend = "s3"

  config = {
    bucket = var.state_bucket
    key    = var.platform_state_key
    region = var.region
  }
}

data "aws_eks_cluster" "this" {
  name = data.terraform_remote_state.platform.outputs.cluster_name
}

provider "helm" {
  kubernetes = {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
    # Short-lived credentials are fetched on every call (a fixed token expires after 15 minutes).
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", data.terraform_remote_state.platform.outputs.cluster_name, "--region", var.region]
    }
  }
}

locals {
  # In-cluster service addresses the components use to find each other.
  loki_url  = "http://loki.${var.namespace}.svc.cluster.local:3100"
  tempo_url = "http://tempo.${var.namespace}.svc.cluster.local:3200"
}
