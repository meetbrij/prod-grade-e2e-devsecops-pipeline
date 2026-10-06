# Terraform

Infrastructure for the project, applied manually for now (later: plan on PR, apply behind an approval).

| Stack | Purpose | State |
|-------|---------|-------|
| `bootstrap/` | S3 bucket that stores state for all other stacks. Run once. | S3, key `bootstrap/terraform.tfstate` (migrated from a local file) |
| `platform/` | VPC (single NAT), EKS 1.36, EBS CSI driver, ECR, GitHub OIDC provider, ACM certificate. **Applied.** | S3, key `platform/terraform.tfstate` |
| `addons/` | AWS Load Balancer Controller (with IAM role), External Secrets Operator, two gp3 StorageClasses. Written and validated, not yet applied. | S3, key `addons/terraform.tfstate` |
| `modules/app-env` | Reusable per-environment module (namespace, quota, secret shell, ESO identity, CI deploy role) | n/a |
| `observability/` | Prometheus + Alertmanager + Grafana, Loki (logs), Tempo (traces), Grafana Alloy (log collector), all in the `monitoring` namespace. Written and validated, not yet applied. | S3, key `observability/terraform.tfstate` |
| `envs/qa` | Instantiates the module for qa. **Applied.** | S3, key `envs/qa/terraform.tfstate` |
| `envs/prod` | Same module with prod inputs. Written and validated, not yet applied. | S3, key `envs/prod/terraform.tfstate` |

## Understanding the EKS infrastructure

Three views of the same system. Solid boxes exist today (applied by the `platform` stack). Dashed boxes are planned.

### Key terms

| Term | What it is | In this project |
|------|------------|-----------------|
| **EKS control plane** | The Kubernetes "brain" (API server, etcd, scheduler). Run and patched by AWS, in an AWS-owned network, not inside your VPC. You never see its servers. | One control plane for the cluster `devsecops-eks` |
| **Node** | One EC2 virtual machine that runs your containers. Billed as a normal EC2 instance. | 2 nodes, type `t3a.large`, one per availability zone |
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
                    N1["Node 1<br/>EC2 t3a.large"]
                end
            end

            subgraph AZB["Availability zone ap-south-1b"]
                subgraph PUBB["Public subnet 10.0.49.0/24"]
                    ALBB["ALB nodes, later"]
                end
                subgraph PRIVB["Private subnet 10.0.16.0/20"]
                    N2["Node 2<br/>EC2 t3a.large"]
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
- The AWS CLI on your PATH. The stacks that talk to the cluster (`addons`, `observability`, `envs/*`) get fresh cluster credentials from `aws eks get-token` on every call, so a long apply cannot outlive a fixed token (those expire after 15 minutes).
- AWS credentials for an admin identity (a named profile or SSO). Never put keys in files:
  `export AWS_PROFILE=<your-profile>` and confirm with `aws sts get-caller-identity`.

## Migrate the bootstrap state into S3 (one-time)

The bootstrap stack originally kept its state in a local file, which exists only on one machine. To move it into the bucket it created:

```bash
cd terraform/bootstrap
cp backend.hcl.example backend.hcl       # set bucket = <state_bucket>
terraform init -backend-config=backend.hcl -migrate-state
```

Answer `yes` when asked to copy the existing state. Afterwards `terraform plan` should show no changes, and the local `terraform.tfstate` is no longer used (keep it until you have confirmed the plan is clean, then delete it).

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

### Apply the observability stack

First apply the larger nodes (this replaces the two nodes, so QA and prod restart briefly):

```bash
cd terraform/platform
terraform plan -out=tfplan      # expect the node group to be replaced
terraform apply tfplan
```

Then the stack (it needs the cluster reachable and your AWS credentials, like `addons`):

```bash
cd terraform/observability
cp backend.hcl.example backend.hcl             # set bucket = <state_bucket>
cp terraform.tfvars.example terraform.tfvars   # set state_bucket = <state_bucket>
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

| Component | What it is | Storage |
|-----------|------------|---------|
| kube-prometheus-stack | Prometheus (15 day retention), Alertmanager (no receivers), Grafana, node-exporter, kube-state-metrics | Prometheus 20Gi |
| Loki | Single-instance log store, 15 day retention | 10Gi |
| Tempo | Single-instance trace store, OTLP on 4317/4318, 15 day retention | 10Gi |
| Grafana Alloy | Reads every pod's logs through the Kubernetes API and ships them to Loki (replaces Promtail, which reached end-of-life on 2026-03-02) | none |

All volumes are gp3 and were created on the `ebs-sc-retain` StorageClass. Because the AI-log-analysis project was dropped, their
reclaim policy was patched to `Delete` in place (`kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'`),
so deleting a claim or destroying this stack also removes the EBS volume. The StorageClass name in the claim is unchanged
(it cannot be edited on a StatefulSet), and a fresh install would again use `ebs-sc-retain`: patch the new PVs the same way, or
change `storage_class` to `ebs-sc` before that install.
Nothing is exposed to the internet; Grafana is reached with a port-forward.

Open Grafana:

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
```

then browse to `http://localhost:3000`, user `admin`. The password is generated by the chart and is not stored in Terraform
or Git; print it with:

```bash
kubectl get secret kube-prometheus-stack-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

In Grafana, Explore has the **Loki** data source (try `{namespace="qa"}`), the **Prometheus** data source holds metrics, and
**Tempo** is ready but stays empty until an app sends OpenTelemetry traces. The kube-prometheus-stack dashboards (for example
"Kubernetes / Compute Resources / Namespace (Pods)") already show qa and prod.

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

### Secret values: set once, never overwrite

> **Run the "set secret values" command exactly once per environment, and read the `--secret-id` before pressing Enter.**
> The QA command uses `qa/mysql-secret` and the prod command uses `prod/mysql-secret`; they differ by one word.
>
> MySQL reads `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD` only the first time it starts on an empty volume. Changing the
> secret afterwards does **not** change the database passwords. External Secrets copies the new value into the cluster
> within an hour, and the next app pod to start then fails with `Access denied` while MySQL still has the old password.
> (This happened once in QA; Secrets Manager had kept the previous version, which made the recovery easy.)

**If a secret was overwritten by mistake**, move the previous version back (version IDs come from
`aws secretsmanager list-secret-version-ids --secret-id <env>/mysql-secret`):

```bash
aws secretsmanager update-secret-version-stage --region ap-south-1 --secret-id <env>/mysql-secret \
  --version-stage AWSCURRENT --move-to-version-id <previous-version-id> --remove-from-version-id <current-version-id>
kubectl annotate externalsecret mysql-external-secret -n <env> force-sync=$(date +%s) --overwrite
kubectl rollout restart deployment/nodejs-app -n <env>
```

**To change a database password on purpose (rotation)**, change it in both places, in this order:
1. In MySQL: `ALTER USER 'appuser'@'%' IDENTIFIED BY '<new>';` (and the root password if needed), run inside the pod.
2. In Secrets Manager: store the new value (and the updated `DATABASE_URL`).
3. Force the sync and restart the app as above.

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

### Apply the prod environment

Same module as QA, with prod inputs (retag-only ECR permissions, an `environment:prod` trust subject, a 7-day secret recovery window).

Before the first apply, create the **GitHub Environment** the role trusts: repository Settings, Environments, New environment, name it exactly `prod`, add yourself under Required reviewers, and restrict deployment branches to `main`. Then:

```bash
cd terraform/envs/prod
cp backend.hcl.example backend.hcl             # set bucket = <state_bucket>
cp terraform.tfvars.example terraform.tfvars   # set state_bucket = <state_bucket>
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

Then set the prod secret values (same command as QA with `prod/mysql-secret`):

```bash
ROOT=$(openssl rand -base64 24 | tr -d '/+=') ; APP=$(openssl rand -base64 24 | tr -d '/+=')
aws secretsmanager put-secret-value --region ap-south-1 --secret-id prod/mysql-secret --secret-string \
"{\"MYSQL_ROOT_PASSWORD\":\"$ROOT\",\"MYSQL_DATABASE\":\"appdb\",\"MYSQL_USER\":\"appuser\",\"MYSQL_PASSWORD\":\"$APP\",\"DATABASE_URL\":\"mysql://appuser:$APP@mysql:3306/appdb\"}"
unset ROOT APP
```

and add the repo variable `AWS_ROLE_TO_ASSUME_PROD` with the value of `terraform output deploy_role_arn`.
The prod credentials are different from QA's because each run generates new random passwords.

## Pause and resume (without destroying)

Scaling the node group to zero stops the EC2 instances, which is the biggest hourly cost you can switch off.
Everything else stays: the EKS control plane, the NAT gateway, the shared ALB and the EBS volumes (so the databases keep their data).

```bash
# find the node group name
aws eks list-nodegroups --cluster-name devsecops-eks --region ap-south-1

# pause
aws eks update-nodegroup-config --cluster-name devsecops-eks --region ap-south-1 \
  --nodegroup-name <node-group-name> --scaling-config minSize=0,maxSize=3,desiredSize=0

# resume
aws eks update-nodegroup-config --cluster-name devsecops-eks --region ap-south-1 \
  --nodegroup-name <node-group-name> --scaling-config minSize=2,maxSize=3,desiredSize=2
```

While paused, pods are Pending, the ALB has no healthy targets and both sites answer 503. After resuming, nodes take a few
minutes to join and the pods start again by themselves. While paused, `terraform plan` on `platform` shows the node group
minimum as a change; resuming (or `terraform apply`) puts it back.

Roughly what keeps costing while paused: EKS control plane (about 73 USD/month), NAT gateway (about 35 USD plus data),
ALB (about 18 USD), EBS volumes and logs (a few USD). That is around two thirds of the running cost, so pausing saves
only the nodes. For a longer break, destroy instead (below); everything rebuilds from Terraform and the pipeline, but the
databases start empty. Figures are estimates; check the AWS pricing calculator.

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
- **Cost while running:** EKS control plane, one NAT gateway and two t3a.large nodes add up to roughly
  150 to 180 USD per month (estimate; check the AWS pricing calculator). Run `terraform destroy` when idle.
- **Node size:** t3a.large (2 vCPU, 8 GiB) nodes carry qa, prod, the add-ons and the observability stack. Changing `node_instance_type` replaces the nodes (new group first, then the old one is drained); pods with EBS volumes restart on the new nodes.
