# Terraform

Infrastructure for the project, applied manually for now (later: plan on PR, apply behind an approval).

| Stack | Purpose | State |
|-------|---------|-------|
| `bootstrap/` | S3 bucket that stores state for all other stacks. Run once. | local file (gitignored) |
| `platform/` | VPC (single NAT), EKS 1.36, EBS CSI driver, ECR, GitHub OIDC provider, ACM certificate | S3, key `platform/terraform.tfstate` |
| `addons/` (planned) | AWS Load Balancer Controller, External Secrets Operator, StorageClass | S3 |
| `envs/qa`, `envs/prod` (planned) | Per-environment namespace, ESO role, secret shell, CI deploy role | S3, one key per env |

## Prerequisites

- Terraform >= 1.10
- AWS credentials for an admin identity (a named profile or SSO). Never put keys in files:
  `export AWS_PROFILE=<your-profile>` and confirm with `aws sts get-caller-identity`.

## Apply

```bash
# 1. Bootstrap (once)
cd terraform/bootstrap
terraform init
terraform apply
terraform output state_bucket      # note the bucket name

# 2. Platform
cd ../platform
cp backend.hcl.example backend.hcl # set bucket = <state_bucket>
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

EKS creation takes about 10 to 15 minutes. Afterwards:

```bash
aws eks update-kubeconfig --name devsecops-eks --region ap-south-1
kubectl get nodes
```

## Destroy: what is and is not touched

`terraform destroy` removes only resources recorded in that stack's state, that is, resources Terraform created.
Anything you created by hand (Jenkins, the `automate.ec2` IAM user, other VPCs, S3 buckets, etc.) is not in
state and is never touched. Every managed resource is also tagged `ManagedBy=terraform`.

Deliberately NOT managed (read-only data sources, so they survive destroy):
- The Route 53 hosted zone `bolarbrijesh.com` and its existing records. Terraform only adds and removes the
  ACM validation records it creates.
- A pre-existing GitHub OIDC provider, if `create_github_oidc_provider = false`.

Safeguards:
- The state bucket has `prevent_destroy = true`.
- Check what a destroy will do before running it: `terraform plan -destroy`.
- Destroy in reverse order: `envs/*`, `addons`, `platform`. Delete Kubernetes Ingresses first
  (`kubectl delete ingress -A --all`), otherwise ALBs created by the controller block VPC deletion.

## Before the first apply

- **GitHub OIDC provider:** only one per account. If the AWS console (IAM, Identity providers) already shows
  `token.actions.githubusercontent.com`, set `create_github_oidc_provider = false` in `terraform.tfvars`.
- **Cost while running:** EKS control plane, one NAT gateway and two t3a.medium nodes add up to roughly
  150 to 180 USD per month (estimate; check the AWS pricing calculator). Run `terraform destroy` when idle.
- **Node size:** t3a.medium is enough for the app and add-ons; the observability stack will need larger nodes.
