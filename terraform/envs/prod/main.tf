provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project
      ManagedBy   = "terraform"
      Stack       = "env-prod"
      Environment = "prod"
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

data "aws_eks_cluster_auth" "this" {
  name = data.terraform_remote_state.platform.outputs.cluster_name
}

data "aws_ecr_repository" "app" {
  name = var.ecr_repository_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this.token
}

module "app_env" {
  source = "../../modules/app-env"

  env_name                 = "prod"
  cluster_name             = data.terraform_remote_state.platform.outputs.cluster_name
  oidc_provider_arn        = data.terraform_remote_state.platform.outputs.oidc_provider_arn
  oidc_provider            = data.terraform_remote_state.platform.outputs.oidc_provider
  github_oidc_provider_arn = data.terraform_remote_state.platform.outputs.github_oidc_provider_arn
  github_repository_claim  = var.github_repository_claim

  # Prod deploys run in a GitHub Environment named "prod", which carries the manual
  # approval rule. Jobs that use an environment get an "environment:prod" subject
  # instead of a branch subject, so this role cannot be assumed from a branch push alone.
  github_subject = "environment:prod"

  ecr_repository_arn = data.aws_ecr_repository.app.arn
  # Prod never pushes new images; it only retags (promotes) one that QA already built.
  ecr_actions = [
    "ecr:BatchGetImage",
    "ecr:PutImage",
  ]

  # Keep a deleted prod secret recoverable for a week.
  secret_recovery_window_days = 7

  quota = {
    requests_cpu    = "1"
    requests_memory = "2Gi"
    limits_cpu      = "2"
    limits_memory   = "3Gi"
    pods            = "20"
    pvcs            = "3"
    storage         = "20Gi"
  }
}
