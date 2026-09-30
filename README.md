# End-to-End DevSecOps on AWS EKS

A production-grade DevSecOps project: a 3-tier Node.js application deployed to **AWS EKS** via **GitHub Actions**, with security scanning built into every pipeline, secretless AWS authentication, managed secrets, HTTPS routing, and full observability.

> **Status:** Application code and initial Kubernetes manifests are in place. CI/CD workflows, infrastructure code, MySQL manifests, secrets integration and observability are still to be built.

## What You'll Build

- End-to-end CI/CD with GitHub Actions and branch-based promotion: `feature/*` → `qa` → `main`
- DevSecOps tooling in the pipelines: **Gitleaks**, **Trivy**, **Checkov**, **SBOM**, **SonarQube**
- Secretless AWS auth via **GitHub OIDC** (no static credentials) with secure EKS access
- Secrets management with **AWS Secrets Manager**, **External Secrets Operator**, and **IRSA**
- Stateful **MySQL** on Kubernetes using StatefulSets, Services, and persistent EBS storage
- Production-grade **EKS** architecture with **ALB**, **Route 53**, and **ACM** for HTTPS
- Observability with **Prometheus, Loki, Tempo, and Grafana** (metrics, logs, traces)
- Custom domain with ACM-issued TLS certificates wired into the Kubernetes Ingress

## The Application

A simple User Management app (Add / View / Edit / Delete users) serves as a placeholder workload to exercise the platform. It will later be replaced by an AI-based project (TBD), so the pipelines and manifests are designed to stay app-agnostic.

| Tier | Technology |
|------|------------|
| Frontend | React 17, Webpack 5, Axios |
| Backend | Node.js 20, Express 4, `mysql2` (REST API, port 5000) |
| Database | MySQL 8.0 |

API: `GET /api/users`, `POST /api/users`, `PUT /api/users/:id`, `DELETE /api/users/:id`.

## Architecture

### Request flow and workloads

```mermaid
flowchart TD
    U([User browser<br/>https://your-domain]) --> NC[Domain registrar<br/>NS delegation]
    NC --> R53[Route 53<br/>hosted zone + alias A record]
    R53 --> ALB[AWS ALB<br/>TLS termination, HTTP→HTTPS redirect]
    ACM[ACM certificate<br/>DNS-validated, auto-renew] -. attached via Ingress annotation .-> ALB
    ALBC[AWS Load Balancer Controller] -. provisions .-> ALB

    subgraph EKS[EKS cluster]
        ING[Ingress<br/>host + path routing]
        SVC[Service: ClusterIP]
        APP[App pod<br/>React + Node.js]
        DB[(MySQL StatefulSet<br/>headless Service :3306)]
        PV[(EBS PersistentVolume<br/>gp2, 10Gi, Retain)]
        SC[StorageClass ebs-sc<br/>WaitForFirstConsumer]
        ING --> SVC --> APP -->|SQL :3306| DB
        DB --- PV
        SC -. provisions .-> PV
    end

    ALB --> ING
```

### Secrets management

```mermaid
flowchart LR
    subgraph AWS[AWS]
        SM[(Secrets Manager<br/>qa/mysql-secret)]
        IAM[IAM role for ESO<br/>secretsmanager:GetSecretValue]
    end

    subgraph K8S[EKS cluster]
        SA[ServiceAccount<br/>IRSA annotation]
        ESO[External Secrets Operator]
        SS[SecretStore]
        ES[ExternalSecret]
        KS[K8s Secret<br/>mysql-secret]
        APP[App pod]
        MYSQL[MySQL pod]
        SA --> ESO --> SS --> ES --> KS
        KS -->|envFrom| APP
        KS -->|envFrom| MYSQL
    end

    SM --> IAM
    IAM -. AssumeRoleWithWebIdentity .-> SA
    ESO -->|GetSecretValue| SM
```

### Observability

```mermaid
flowchart TD
    W[Kubernetes workloads<br/>metrics, logs, traces]
    W --> KPS[kube-prometheus-stack]
    W --> PT[Promtail<br/>DaemonSet]
    W --> OT[OpenTelemetry SDK]
    KPS --> P[(Prometheus)]
    PT --> L[(Loki)]
    OT --> T[(Tempo)]
    P -->|metrics| G[Grafana]
    L -->|logs| G
    T -->|traces| G
    G --> ENG([DevOps / on-call engineer])
```

## Branching Strategy

```mermaid
gitGraph
    commit id: "v1.0.0" tag: "v1.0.0"
    branch qa
    checkout qa
    commit id: "qa base"
    branch feature/DS-421
    checkout feature/DS-421
    commit id: "feature work"
    checkout qa
    merge feature/DS-421 id: "PR (squash)"
    branch bugfix/DS-512
    checkout bugfix/DS-512
    commit id: "fix QA defect"
    checkout qa
    merge bugfix/DS-512 id: "PR (squash) "
    checkout main
    merge qa id: "release PR" tag: "v1.1.0"
    branch hotfix/INC-023
    checkout hotfix/INC-023
    commit id: "emergency fix"
    checkout main
    merge hotfix/INC-023 tag: "v1.1.1"
    checkout qa
    merge hotfix/INC-023 id: "back-sync"
```

| Branch | Created from | Merged into | Environment |
|--------|--------------|-------------|-------------|
| `main` | permanent | n/a | Production |
| `qa` | `main` | `main` | QA |
| `feature/*` | `qa` | `qa` | pre-merge |
| `bugfix/*` | `qa` | `qa` | QA |
| `hotfix/*` | `main` | `main` + `qa` | Production (emergency) |

Naming: `<type>/<ticket-id>-<short-slug>` in lowercase with hyphens; releases are tagged `vMAJOR.MINOR.PATCH`.

## CI/CD Pipelines

### QA pipeline (on merge to `qa`)

```mermaid
flowchart TD
    A([Merge to qa]) --> B[Gitleaks<br/>secret detection]
    B --> C1[Checkov: Terraform]
    B --> C2[Checkov: Kubernetes]
    B --> C3[Checkov: Dockerfile]
    B --> C4[Trivy FS: client]
    B --> C5[Trivy FS: server]
    C1 & C2 & C3 & C4 & C5 --> D1[Client lint]
    C1 & C2 & C3 & C4 & C5 --> D2[Server lint]
    C1 & C2 & C3 & C4 & C5 --> D3[Client tests]
    D1 & D2 & D3 --> E[SonarQube<br/>quality gate]
    E --> F[Client build]
    F --> G[Docker build<br/>tag = git SHA]
    G --> H1[Trivy image scan]
    G --> H2[SBOM generation]
    H1 & H2 --> I[Push to Amazon ECR]
    I --> J[Update image tag in QA manifest]
    J --> K[Deploy to EKS qa namespace<br/>via OIDC role]
    K --> L{Manual QA<br/>and sign-off}
    L -->|bugs found| M[bugfix branch] --> A
    L -->|approved| N([PR: qa → main])
```

### Production pipeline (on merge to `main`)

```mermaid
flowchart LR
    A([Merge to main]) --> B[Approval gate<br/>GitHub Environment]
    B --> C[Retag QA image in ECR<br/>sha → prod-sha]
    C --> E[Update prod manifest]
    E --> F[Deploy to EKS prod<br/>via prod OIDC role]
    F --> G([Rollout verified])
```

Images live in a private Amazon ECR repository in the same region as EKS. QA builds are tagged with the git SHA; promotion retags the same image as `prod-<sha>` (no rebuild, no rescan).

Principles: security at every stage, **build once / promote the artifact**, immutable SHA-tagged images, parallel jobs for speed, controlled human-approved promotion.

## Environments and Access

Two environments: a non-prod EKS cluster running the `qa` namespace and a separate dedicated prod cluster running the `prod` namespace. All resources live in `ap-south-1`. Disaster recovery is provisioned on demand from IaC rather than kept running.

```mermaid
flowchart LR
    GH[GitHub Actions] -->|OIDC| RA[IAM Role A<br/>QA deployer]
    GH -->|OIDC + approval| RB[IAM Role B<br/>PROD deployer]
    RA --> NP[Non-prod EKS cluster<br/>qa namespace]
    RB --> PC[Prod EKS cluster<br/>prod namespace]
```

The QA and prod pipelines never share an IAM role.

## Extending to More Environments (dev, ppd)

Only `qa` and `prod` are in scope today. The pipelines are meant to be driven by per-environment configuration so adding `dev` or `ppd` does not require restructuring:

1. **Namespace and manifests:** copy `k8-manifests/qa/` to `k8-manifests/<env>/` and adjust namespace, replicas, resources, host and cert ARN.
2. **Environment config:** add the environment's values (namespace, cluster name, IAM role ARN, host, ACM cert ARN, ECR repo) as GitHub Environment variables, or as a matrix entry in the workflow, instead of hardcoding them.
3. **Branch mapping:** decide which branch deploys to it (for example `feature/*` to `dev`, `qa` to `qa`, a pre-merge state of `main` to `ppd`) and add that trigger to the workflow's environment matrix.
4. **AWS access:** extend the non-prod IAM deployer role's trust policy and namespace permissions to include the new namespace. Never give it access to `prod`.
5. **Cluster add-ons:** create the namespace with its resource quota and network policies, plus its own SecretStore/ExternalSecret and Secrets Manager entry (`<env>/mysql-secret`).
6. **DNS/TLS:** add a `<env>.<domain>` record in Route 53 and issue or reuse an ACM certificate.
7. **Approvals:** add a GitHub Environment with the required reviewers if the environment should be gated.

## Repository Layout

```
client/                 React frontend (Webpack build)
server/                 Node.js + Express backend (config, models, controllers, routes)
Dockerfile              Builds client, bundles into server image; runs as non-root
sonar-project.properties SonarQube project config
k8-manifests/
  qa/                   App Deployment, Service, Ingress (qa namespace)
  prod/                 Same for prod namespace
.github/workflows/      (planned) QA and prod pipelines
terraform/              (planned) AWS infrastructure
```

## Local Development

```bash
# Backend (needs a reachable MySQL)
cd server && npm install && npm start      # http://localhost:5000

# Frontend bundle
cd client && npm install && npm run build
```

Backend environment variables: `PORT`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.

Container image:

```bash
docker build -t nodejs-app .
docker run -p 5000:5000 -e DB_HOST=<mysql-host> -e DB_USER=<user> -e DB_PASSWORD=<password> -e DB_NAME=<db> nodejs-app
```

## Prerequisites

AWS account (region `ap-south-1`), a registered domain, GitHub repository, Docker, `kubectl`, `awscli`, Terraform (if used), and a SonarQube instance or SonarCloud project.
