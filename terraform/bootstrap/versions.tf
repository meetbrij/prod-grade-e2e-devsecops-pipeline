terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The state bucket this stack creates also stores this stack's own state, under its own key.
  # Partial config: supply bucket/region via `-backend-config=backend.hcl`.
  # First run (bucket does not exist yet): comment this block out, apply, then
  # restore it and run `terraform init -backend-config=backend.hcl -migrate-state`.
  backend "s3" {}
}
