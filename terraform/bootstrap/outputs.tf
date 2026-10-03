output "state_bucket" {
  description = "Name of the Terraform state bucket. Use it in each stack's backend.hcl."
  value       = aws_s3_bucket.state.bucket
}

output "region" {
  value = var.region
}
