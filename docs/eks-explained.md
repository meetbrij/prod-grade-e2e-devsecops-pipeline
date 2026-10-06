# The EKS infrastructure, explained

Three views of the same system, as it runs today: the AWS layout built by the `platform` stack, the pods on the nodes, and commands to look at it yourself. Pod placement in view 2 is illustrative, because Kubernetes decides where each pod runs.

## Key terms

| Term | What it is | In this project |
|------|------------|-----------------|
| **EKS control plane** | The Kubernetes "brain" (API server, etcd, scheduler). Run and patched by AWS, in an AWS-owned network, not inside your VPC. You never see its servers. | One control plane for the cluster `devsecops-eks` |
| **Node** | One EC2 virtual machine that runs your containers. Billed as a normal EC2 instance. | 2 nodes, type `t3a.large`, one per availability zone |
| **Managed node group** | A named set of identical nodes managed by AWS through an Auto Scaling group. It keeps the count between a minimum and a maximum and replaces failed nodes. It is a grouping, not a separate machine. | One group, `default-...`: min 2, desired 2, max 3 |
| **Pod** | The smallest unit Kubernetes runs: one or more containers sharing a network address. Every pod runs on exactly one node. | System pods, the KYC service, MySQL, the observability stack |
| **Namespace** | A logical folder inside the cluster used to separate and name things (and to apply permissions and quotas). It is **not** a machine or a network. A namespace's pods can run on any node, and one node runs pods from many namespaces. | `kube-system`, `external-secrets`, `monitoring`, `qa`, `prod` |
| **DaemonSet** | A pod definition that Kubernetes runs once on every node. | `aws-node`, `kube-proxy`, `ebs-csi-node`, `eks-pod-identity-agent` |
| **Deployment** | A pod definition that Kubernetes runs N times and spreads across nodes as it sees fit. | `coredns` (2), `ebs-csi-controller` (2), the KYC service (1 in qa, 2 in prod) |

The one idea that resolves most confusion: **nodes are the physical layer, namespaces are the logical layer, and pods are the things that sit in both.** Every pod belongs to exactly one namespace and runs on exactly one node.

## View 1: AWS layout (what was built)

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
                    ALBA["ALB nodes<br/>shared by qa and prod"]
                end
                subgraph PRIVA["Private subnet 10.0.0.0/20"]
                    N1["Node 1<br/>EC2 t3a.large"]
                end
            end

            subgraph AZB["Availability zone ap-south-1b"]
                subgraph PUBB["Public subnet 10.0.49.0/24"]
                    ALBB["ALB nodes<br/>shared by qa and prod"]
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
            SM["Secrets Manager<br/>qa and prod secrets"]
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
    N1 -. "pulls images" .-> ECR
    N2 -. "pulls images" .-> ECR

```

Reading it:
- The **control plane** sits outside your VPC. Nodes reach it over the network and register themselves.
- The **nodes** are in **private** subnets, so they have no public IP. They reach the internet (to pull images and call AWS APIs) through the single **NAT gateway**, which lives in a public subnet.
- The **ALB** (created by the AWS Load Balancer Controller from the Ingresses) goes in the **public** subnets and is the only thing the internet talks to.
- The **node group** is not a place. It is the rule that keeps the two nodes alive and replaces them if one fails.
- There is only one NAT gateway, so if zone `ap-south-1a` fails, the nodes in `ap-south-1b` lose outbound internet. This is the cost trade-off we accepted.

## View 2: pods on nodes (logical and physical together)

Colour shows the namespace. This is an illustrative snapshot: the scheduler placed most pods on one node when this was taken.

```mermaid
flowchart TB
    subgraph CLUSTER["EKS cluster devsecops-eks"]
        subgraph NODE1["Node 1 (ap-south-1a)"]
            direction TB
            a1["kube-system: aws-node, kube-proxy,<br/>ebs-csi-node, eks-pod-identity-agent"]
            c1["kube-system: coredns x2, ebs-csi-controller x2,<br/>aws-load-balancer-controller"]
            eso["external-secrets: operator, webhook,<br/>cert-controller"]
            mon1["monitoring: grafana, loki-0, tempo-0, alloy,<br/>alertmanager, operator, kube-state-metrics"]
            qa1["qa: kyc service"]
            qdb["qa: mysql-0"]
            pr1["prod: kyc service x2"]
        end
        subgraph NODE2["Node 2 (ap-south-1b)"]
            direction TB
            a2["kube-system: aws-node, kube-proxy,<br/>ebs-csi-node, eks-pod-identity-agent"]
            mon2["monitoring: prometheus-0, node-exporter"]
            pdb["prod: mysql-0"]
        end
    end

    classDef sys fill:#eceff1,stroke:#546e7a,color:#111
    classDef qa fill:#e3f2fd,stroke:#1565c0,color:#111
    classDef prod fill:#e8f5e9,stroke:#2e7d32,color:#111
    classDef addon fill:#fff3e0,stroke:#ef6c00,color:#111
    class a1,c1,a2 sys
    class qa1,qdb qa
    class pr1,pdb prod
    class eso,mon1,mon2 addon
```

Reading it:
- The **DaemonSet** pods (`aws-node`, `kube-proxy`, `ebs-csi-node`, `eks-pod-identity-agent`) run once on **every** node. That is why you see each of them twice.
- The **Deployment** pods (`coredns`, `ebs-csi-controller`, the KYC service) are spread across nodes by the Kubernetes scheduler. Where each one lands in this picture is illustrative: Kubernetes decides, and may move a pod to another node if a node fails.
- The `qa` and `prod` namespaces share the same two nodes. They are separated by namespace rules (permissions and quotas), not by separate machines. There are no NetworkPolicies yet (see [security gates](security-gates.md)). This is the cost trade-off of a single cluster.
- Each MySQL pod gets its own EBS volume, which lives in one availability zone. If that pod is rescheduled it must land on a node in the same zone as its volume.

## View 3: look at it yourself

```bash
kubectl get nodes -o wide          # the 2 nodes: zone, IP, version
kubectl get ns                     # the namespaces (logical folders)
kubectl get pods -A -o wide        # every pod, its namespace, and the NODE it runs on
kubectl get pods -A -o wide --field-selector spec.nodeName=<node-name>   # pods on one node
```

In the last pod listing, the `NAMESPACE` column is the logical view and the `NODE` column is the physical view of the same pods.

Back to the [documentation index](README.md).
