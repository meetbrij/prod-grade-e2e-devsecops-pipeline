provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "platform"
    }
  }
}

data "aws_availability_zones" "available" {
  #checkov:skip=CKV_AWS_394:The first az_count zones are used and the live subnets already exist; pinning zone names explicitly is parked
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}
