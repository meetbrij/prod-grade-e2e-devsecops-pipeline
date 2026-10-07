# Terraform

All AWS resources, cluster add-ons and namespaces are provisioned here. Terraform is applied by hand for now (a later step could plan on PR and apply behind an approval). The application manifests in `k8-manifests/` are deployed by the pipeline, not by Terraform.

Related docs: [operations runbook](../docs/runbook.md) (pause and resume, secrets, destroy), [EKS explained](../docs/eks-explained.md) (what the infrastructure looks like), [troubleshooting](../docs/troubleshooting.md).

## Stacks

Each stack has its own state in S3 (one bucket, one key per stack, native locking), so stacks can be applied and destroyed independently. All are applied.

| Stack | What it creates | State key |
|---|---|---|
| `bootstrap/` | The S3 bucket that holds state for every other stack. Run once. | `bootstrap/terraform.tfstate` |
| `platform/` | VPC with a single NAT gateway, EKS 1.36 and its managed node group, EBS CSI driver, ECR repository, GitHub OIDC provider, ACM certificate | `platform/terraform.tfstate` |
| `addons/` | AWS Load Balancer Controller (with its IAM role), External Secrets Operator, the StorageClasses `ebs-sc` (Delete) and `ebs-sc-retain` (Retain) | `addons/terraform.tfstate` |
| `observability/` | kube-prometheus-stack (Prometheus, Alertmanager, Grafana), Loki, Tempo and Grafana Alloy in the `monitoring` namespace | `observability/terraform.tfstate` |
| `modules/app-env` | The reusable per-environment module (below). No state of its own. | n/a |
| `envs/qa`, `envs/prod` | One instance of the module each | `envs/qa/...`, `envs/prod/...` |

### What the `app-env` module creates, per environment

| Resource | Purpose |
|---|---|
| Namespace | The environment's home. Pod Security: `baseline` enforced, `restricted` warns. |
| ResourceQuota and LimitRange | Caps total CPU, memory, pods and storage so one environment cannot starve the other. The LimitRange gives containers default requests and limits. |
| Secrets Manager secret `<env>/mysql-secret` | An empty container. The values are set by you, never by Terraform (see the [runbook](../docs/runbook.md#secrets)). |
| Secrets Manager secrets `<env>/kyc-api-key` and `<env>/llm-api-key` | Empty containers for the service's `X-API-Key` and the Anthropic API key. Values set by you. |
| IAM role `devsecops-eks-<env>-eso` and service account `<env>/eso` | Lets External Secrets read only that environment's three secrets. |
| IAM role `devsecops-eks-<env>-kyc-app` and service account `<env>/kyc-app` | Lets the KYC service call Amazon Bedrock through IRSA, limited to the two India-only `in.` inference profiles and their underlying models. |
| IAM role `devsecops-eks-<env>-github-deploy` | Assumed by GitHub Actions through OIDC. QA trusts the `qa` branch and can push to ECR; prod trusts the GitHub Environment `prod` and can only retag images. |
| EKS access entry for that role | Edit rights inside that namespace only, plus a namespaced Role for External Secrets objects. Nothing else in the cluster. |

## Prerequisites

- Terraform 1.10 or later.
- The AWS CLI on your PATH. The stacks that talk to the cluster (`addons`, `observability`, `envs/*`) get fresh credentials from `aws eks get-token` on every call, so a long apply cannot outlive a fixed token (those expire after 15 minutes).
- AWS credentials for an admin identity (a named profile or SSO), never keys in files: `export AWS_PROFILE=<your-profile>`, then check with `aws sts get-caller-identity`.
- If the account already has a `token.actions.githubusercontent.com` OIDC provider (IAM, Identity providers), set `create_github_oidc_provider = false` in `platform`'s `terraform.tfvars`. There can be only one per account.

## Build order

Every stack other than `bootstrap` follows the same four steps. Copy the two example files and put your state bucket name in them (both are gitignored):

```bash
cp backend.hcl.example backend.hcl
cp terraform.tfvars.example terraform.tfvars
```

Then:

```bash
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

Always read the plan before applying. In this order:

| # | Stack | Notes |
|---|---|---|
| 1 | `bootstrap` | `terraform init`, `terraform apply`, then `terraform output state_bucket` for the bucket name. State lives in S3 afterwards; to move a local state there use `terraform init -backend-config=backend.hcl -migrate-state` and answer `yes`. |
| 2 | `platform` | Takes 10 to 15 minutes. Afterwards: `aws eks update-kubeconfig --name devsecops-eks --region ap-south-1` and `kubectl get nodes`. |
| 3 | `addons` | Needs the cluster reachable. The Load Balancer Controller installs first, because External Secrets installs only once the controller's webhook is ready. |
| 4 | `observability` | Needs the `addons` StorageClasses. Sized for 2 nodes of `t3a.large`. |
| 5 | `envs/qa`, then `envs/prod` | The prod environment needs the GitHub Environment `prod` to exist first (see the [runbook](../docs/runbook.md#the-github-deploy-role-variables)). Then set the secret values and the two role variables. |

Checks after each step:

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller   # after addons
kubectl get pods -n external-secrets                                                    # after addons
kubectl get storageclass                                                                # after addons
kubectl get pods -n monitoring                                                          # after observability
```

After the first deploy, create the Route 53 alias records by hand, once per hostname (see the main README under [Manual DNS step](../README.md#manual-dns-step-one-time-per-hostname)).

### Adding a Bedrock model profile

The module takes `bedrock_inference_profile_ids` (set in `envs/qa/main.tf` and `envs/prod/main.tf`) and `bedrock_model_regions` (default `ap-south-1` and `ap-south-2`). Add a profile ID to the list, plan and apply both environments. The policy grants `bedrock:InvokeModel` on the profile and on the underlying foundation models in those two regions, conditioned on the profile ARN, so the model cannot be called directly.

## Conventions

- Every managed resource is tagged `ManagedBy=terraform`.
- No account ID, secret value or credential appears in any file; account IDs come from `data.aws_caller_identity`.
- The Route 53 hosted zone is a data source and is never created or destroyed.
- Checkov scans this directory in CI and blocks on findings. Accepted findings are suppressed with an inline `#checkov:skip=<ID>:<reason>` and listed in [security-gates.md](../docs/security-gates.md). Run `terraform fmt -recursive` before committing.
- Never delete a stack's `.terraform` directory to "clean up"; it holds the initialized backend and providers.

## Costs

Rough running cost is 150 to 180 USD per month for the control plane, one NAT gateway and two `t3a.large` nodes (estimate; check the AWS pricing calculator). [Pausing](../docs/runbook.md#pause-and-resume) saves the nodes only. Changing `node_instance_type` replaces the nodes (the new group comes up first, then the old one drains), and pods with EBS volumes restart on the new nodes.
