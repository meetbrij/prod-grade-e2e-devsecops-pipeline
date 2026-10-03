provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project
      ManagedBy   = "terraform"
      Stack       = "env-qa"
      Environment = "qa"
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

  env_name                 = "qa"
  cluster_name             = data.terraform_remote_state.platform.outputs.cluster_name
  oidc_provider_arn        = data.terraform_remote_state.platform.outputs.oidc_provider_arn
  oidc_provider            = data.terraform_remote_state.platform.outputs.oidc_provider
  github_oidc_provider_arn = data.terraform_remote_state.platform.outputs.github_oidc_provider_arn
  github_repository_claim  = var.github_repository_claim

  # QA deploys run from the qa branch.
  github_subject = "ref:refs/heads/qa"

  ecr_repository_arn = data.aws_ecr_repository.app.arn
  # QA pushes new images.
  ecr_actions = [
    "ecr:BatchCheckLayerAvailability",
    "ecr:BatchGetImage",
    "ecr:CompleteLayerUpload",
    "ecr:GetDownloadUrlForLayer",
    "ecr:InitiateLayerUpload",
    "ecr:PutImage",
    "ecr:UploadLayerPart",
  ]

  # qa can be destroyed and recreated without waiting out a deletion window.
  secret_recovery_window_days = 0
}
