# Terraform

Infrastructure for the project, applied manually for now (later: plan on PR, apply behind an approval).

| Stack | Purpose | State |
|-------|---------|-------|
| `bootstrap/` | S3 bucket that stores state for all other stacks. Run once. | local file (gitignored) |
| `platform/` | VPC (single NAT), EKS 1.36, EBS CSI driver, ECR, GitHub OIDC provider, ACM certificate. **Applied.** | S3, key `platform/terraform.tfstate` |
| `addons/` | AWS Load Balancer Controller (with IAM role), External Secrets Operator, two gp3 StorageClasses. Written and validated, not yet applied. | S3, key `addons/terraform.tfstate` |
| `modules/app-env` | Reusable per-environment module (namespace, quota, secret shell, ESO identity, CI deploy role) | n/a |
| `envs/qa` | Instantiates the module for qa. Written and validated, not yet applied. | S3, key `envs/qa/terraform.tfstate` |
| `envs/prod` (planned) | Same module with prod inputs | S3, key `envs/prod/terraform.tfstate` |

## Understanding the EKS infrastructure

Three views of the same system. Solid boxes exist today (applied by the `platform` stack). Dashed boxes are planned.

### Key terms

| Term | What it is | In this project |
|------|------------|-----------------|
| **EKS control plane** | The Kubernetes "brain" (API server, etcd, scheduler). Run and patched by AWS, in an AWS-owned network, not inside your VPC. You never see its servers. | One control plane for the cluster `devsecops-eks` |
| **Node** | One EC2 virtual machine that runs your containers. Billed as a normal EC2 instance. | 2 nodes, type `t3a.medium`, one per availability zone |
| **Managed node group** | A named set of identical nodes managed by AWS through an Auto Scaling group. It keeps the count between a minimum and a maximum and replaces failed nodes. It is a grouping, not a separate machine. | One group, `default-...`: min 2, desired 2, max 3 |
| **Pod** | The smallest unit Kubernetes runs: one or more containers sharing a network address. Every pod runs on exactly one node. | System pods now; app and MySQL pods later |
| **Namespace** | A logical folder inside the cluster used to separate and name things (and to apply permissions and quotas). It is **not** a machine or a network. A namespace's pods can run on any node, and one node runs pods from many namespaces. | `kube-system` now; `qa`, `prod`, `external-secrets` planned |
| **DaemonSet** | A pod definition that Kubernetes runs once on every node. | `aws-node`, `kube-proxy`, `ebs-csi-node`, `eks-pod-identity-agent` |
| **Deployment** | A pod definition that Kubernetes runs N times and spreads across nodes as it sees fit. | `coredns` (2), `ebs-csi-controller` (2); later the app |

The one idea that resolves most confusion: **nodes are the physical layer, namespaces are the logical layer, and pods are the things that sit in both.** Every pod belongs to exactly one namespace and runs on exactly one node.

### View 1: AWS layout (what was built)

```mermaid
flowchart TB
    subgraph AWS["AWS account, region ap-south-1"]
        subgraph CP["EKS control plane<br/>managed by AWS, outside your VPC"]
            API["API server"]
            ETCD["etcd"]
            SCHED["Scheduler and controllers"]
        end

        subgraph VPC["VPC 10.0.0.0/16"]
            IGW["Internet gateway"]

            subgraph AZA["Availability zone ap-south-1a"]
                subgraph PUBA["Public subnet 10.0.48.0/24"]
                    NAT["NAT gateway<br/>the only one, shared by both zones"]
                    ALBA["ALB nodes, later"]
                end
                subgraph PRIVA["Private subnet 10.0.0.0/20"]
                    N1["Node 1<br/>EC2 t3a.medium"]
                end
            end

            subgraph AZB["Availability zone ap-south-1b"]
                subgraph PUBB["Public subnet 10.0.49.0/24"]
                    ALBB["ALB nodes, later"]
                end
                subgraph PRIVB["Private subnet 10.0.16.0/20"]
                    N2["Node 2<br/>EC2 t3a.medium"]
                end
            end
        end

        NG["Managed node group 'default'<br/>Auto Scaling group: min 2, desired 2, max 3"]

        subgraph SVC["Regional AWS services, outside the VPC"]
            ECR["ECR repository nodejs-app"]
            ACM["ACM certificate"]
            R53["Route 53 hosted zone<br/>existing, not managed by Terraform"]
            S3["S3 bucket: Terraform state"]
            OIDC["IAM OIDC providers<br/>GitHub Actions and the cluster"]
            SM["Secrets Manager, later"]
        end
    end

    NG -. "manages" .-> N1
    NG -. "manages" .-> N2
    N1 -->|"registers and takes instructions"| API
    N2 -->|"registers and takes instructions"| API
    N1 -->|"outbound internet via NAT"| NAT
    N2 -->|"outbound internet via NAT"| NAT
    NAT --> IGW
    ALBA --> IGW
    ALBB --> IGW
    N1 -. "pulls images, later" .-> ECR
    N2 -. "pulls images, later" .-> ECR

    style ALBA stroke-dasharray: 5 5
    style ALBB stroke-dasharray: 5 5
    style SM stroke-dasharray: 5 5
```

Reading it:
- The **control plane** sits outside your VPC. Nodes reach it over the network and register themselves.
- The **nodes** are in **private** subnets, so they have no public IP. They reach the internet (to pull images and call AWS APIs) through the single **NAT gateway**, which lives in a public subnet.
- The **ALB** (created later by the AWS Load Balancer Controller) goes in the **public** subnets and is the only thing the internet talks to.
- The **node group** is not a place. It is the rule that keeps the two nodes alive and replaces them if one fails.
- There is only one NAT gateway, so if zone `ap-south-1a` fails, the nodes in `ap-south-1b` lose outbound internet. This is the cost trade-off we accepted.

### View 2: pods on nodes (logical and physical together)

Colour shows the namespace. The system pods (grey) exist today. Anything dashed is planned.

```mermaid
flowchart TB
    subgraph CLUSTER["EKS cluster devsecops-eks"]
        subgraph NODE1["Node 1 (ap-south-1a)"]
            direction TB
            a1["kube-system: aws-node"]
            k1["kube-system: kube-proxy"]
            e1["kube-system: ebs-csi-node"]
            p1["kube-system: eks-pod-identity-agent"]
            c1["kube-system: coredns"]
            cc1["kube-system: ebs-csi-controller"]
            alb1["kube-system: aws-load-balancer-controller"]
            qa1["qa: app pod"]
            qdb["qa: mysql-0"]
            pr1["prod: app pod"]
        end
        subgraph NODE2["Node 2 (ap-south-1b)"]
            direction TB
            a2["kube-system: aws-node"]
            k2["kube-system: kube-proxy"]
            e2["kube-system: ebs-csi-node"]
            p2["kube-system: eks-pod-identity-agent"]
            c2["kube-system: coredns"]
            cc2["kube-system: ebs-csi-controller"]
            eso["external-secrets: operator"]
            qa2["qa: app pod"]
            pdb["prod: mysql-0"]
            pr2["prod: app pod"]
        end
    end

    classDef sys fill:#eceff1,stroke:#546e7a,color:#111
    classDef qa fill:#e3f2fd,stroke:#1565c0,color:#111,stroke-dasharray: 5 5
    classDef prod fill:#e8f5e9,stroke:#2e7d32,color:#111,stroke-dasharray: 5 5
    classDef addon fill:#fff3e0,stroke:#ef6c00,color:#111,stroke-dasharray: 5 5
    class a1,k1,e1,p1,c1,cc1,a2,k2,e2,p2,c2,cc2 sys
    class qa1,qdb,qa2 qa
    class pr1,pr2,pdb prod
    class alb1,eso addon
```

Reading it:
- The **DaemonSet** pods (`aws-node`, `kube-proxy`, `ebs-csi-node`, `eks-pod-identity-agent`) run once on **every** node. That is why you see each of them twice.
- The **Deployment** pods (`coredns`, `ebs-csi-controller`, the app) are spread across nodes by the Kubernetes scheduler. Where each one lands in this picture is illustrative: Kubernetes decides, and may move a pod to another node if a node fails.
- The `qa` and `prod` namespaces share the same two nodes. They are separated by namespace rules (permissions, quotas, network policies), not by separate machines. This is the cost trade-off of a single cluster.
- Each MySQL pod gets its own EBS volume, which lives in one availability zone. If that pod is rescheduled it must land on a node in the same zone as its volume.

### View 3: look at it yourself

```bash
kubectl get nodes -o wide          # the 2 nodes: zone, IP, version
kubectl get ns                     # the namespaces (logical folders)
kubectl get pods -A -o wide        # every pod, its namespace, and the NODE it runs on
kubectl get pods -A -o wide --field-selector spec.nodeName=<node-name>   # pods on one node
```

In the last pod listing, the `NAMESPACE` column is the logical view and the `NODE` column is the physical view of the same pods.

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

### Apply the add-ons

Run this after the platform stack. If you pulled the support-policy change (`upgrade_policy = STANDARD`), apply `platform` again first; it is an in-place change.

```bash
cd terraform/addons
cp backend.hcl.example backend.hcl        # set bucket = <state_bucket>
cp terraform.tfvars.example terraform.tfvars   # set state_bucket = <state_bucket>
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

This stack needs the cluster to be reachable (it uses your AWS credentials to get a short-lived token). It installs:

| Add-on | Namespace | Notes |
|--------|-----------|-------|
| AWS Load Balancer Controller | `kube-system` | IRSA role and the upstream IAM policy; 1 replica |
| External Secrets Operator | `external-secrets` | No AWS role of its own; per-environment roles come with `envs/*` |
| StorageClass `ebs-sc` | cluster-wide | gp3, encrypted, reclaim `Delete` (qa) |
| StorageClass `ebs-sc-retain` | cluster-wide | gp3, encrypted, reclaim `Retain` (prod) |

Verify:

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
kubectl get pods -n external-secrets
kubectl get storageclass
```

### Apply the QA environment

```bash
cd terraform/envs/qa
cp backend.hcl.example backend.hcl             # set bucket = <state_bucket>
cp terraform.tfvars.example terraform.tfvars   # set state_bucket = <state_bucket>
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

Creates, per environment:

| Resource | Purpose |
|----------|---------|
| Namespace `qa` | Logical home for the environment. Pod Security: `baseline` enforced, `restricted` warns. |
| ResourceQuota and LimitRange | Caps the namespace's total CPU, memory, pods and storage so qa cannot starve prod. The LimitRange gives containers default requests and limits. |
| Secrets Manager secret `qa/mysql-secret` | An empty container. The values are set by you (below), never by Terraform. |
| IAM role `devsecops-eks-qa-eso` and service account `qa/eso` | Lets External Secrets Operator read only `qa/mysql-secret`. |
| IAM role `devsecops-eks-qa-github-deploy` | Assumed by GitHub Actions on the `qa` branch. It can describe the cluster and push to ECR. |
| EKS access entry for that role | Edit rights inside the `qa` namespace only, nothing else in the cluster. |

### Set the QA secret values (once, manually)

Terraform creates the empty secret; you fill it in. This generates random passwords and stores them without
printing them or writing them anywhere permanent:

```bash
ROOT=$(openssl rand -base64 24 | tr -d '/+=') ; APP=$(openssl rand -base64 24 | tr -d '/+=')
aws secretsmanager put-secret-value --region ap-south-1 --secret-id qa/mysql-secret --secret-string \
"{\"MYSQL_ROOT_PASSWORD\":\"$ROOT\",\"MYSQL_DATABASE\":\"appdb\",\"MYSQL_USER\":\"appuser\",\"MYSQL_PASSWORD\":\"$APP\",\"DATABASE_URL\":\"mysql://appuser:$APP@mysql:3306/appdb\"}"
unset ROOT APP
```

Then add the role ARN as a GitHub **variable** (not a secret; it is not sensitive) so the workflow can assume it:
Settings, Secrets and variables, Actions, Variables, new variable `AWS_ROLE_TO_ASSUME_QA` with the value of
`terraform output deploy_role_arn`.

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
- Destroy in reverse order: `envs/*`, `addons`, `platform`. Run `kubectl delete ingress -A --all` first, then wait for the ALB to disappear. Delete Kubernetes Ingresses first
  (`kubectl delete ingress -A --all`), otherwise ALBs created by the controller block VPC deletion.

## Before the first apply

- **GitHub OIDC provider:** only one per account. If the AWS console (IAM, Identity providers) already shows
  `token.actions.githubusercontent.com`, set `create_github_oidc_provider = false` in `terraform.tfvars`.
- **Cost while running:** EKS control plane, one NAT gateway and two t3a.medium nodes add up to roughly
  150 to 180 USD per month (estimate; check the AWS pricing calculator). Run `terraform destroy` when idle.
- **Node size:** t3a.medium is enough for the app and add-ons; the observability stack will need larger nodes.
