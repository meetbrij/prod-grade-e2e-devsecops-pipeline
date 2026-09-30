# End-to-End DevSecOps on AWS EKS

A production-grade DevSecOps project: a 3-tier Node.js application deployed to **AWS EKS** via **GitHub Actions**, with security scanning built into every pipeline, secretless AWS authentication, managed secrets, HTTPS routing, and full observability.

> **Status:** Planning phase. Architecture is documented; implementation has not started.

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

A User Management app (Add / View / Edit / Delete users) used as the workload:

| Tier | Technology |
|------|------------|
| Frontend | React 17, Webpack 5, Axios |
| Backend | Node.js 20, Express (REST API, port 5000) |
| Database | MySQL 8.0 |

API: `GET /api/users`, `POST /api/users`, `PUT /api/users/:id`, `DELETE /api/users/:id`.

## Architecture

```
Browser ──> Route 53 ──> ALB (ACM TLS) ──> Ingress ──> App pod (React + Node) ──> MySQL StatefulSet ──> EBS PV
                                                             ▲                          ▲
                        AWS Secrets Manager ─> ESO (IRSA) ─> K8s Secret (mysql-secret) ─┘
```

- **DNS/TLS:** registrar NS → Route 53 hosted zone → alias record to ALB; ACM certificate attached via Ingress annotation.
- **Secrets:** ESO syncs credentials from Secrets Manager into K8s Secrets using IRSA.
- **Storage:** `ebs-sc` StorageClass (gp2, `WaitForFirstConsumer`), 10Gi volume, `Retain`.
- **Observability:** kube-prometheus-stack, Promtail → Loki, OpenTelemetry → Tempo, all in Grafana.

## Branching & CI/CD

```
feature/* ──PR──> qa ──(QA sign-off, PR)──> main
                   │                          │
             QA pipeline                 Prod pipeline
```

**QA pipeline (on `qa`):** Gitleaks → parallel [Checkov (Terraform/K8s/Docker), Trivy FS (client/server), lint, tests] → SonarQube quality gate → build → Docker build (SHA tag) → parallel [Trivy image scan, SBOM] → push to registry → update QA manifest → deploy to EKS QA → manual QA validation.

**Prod pipeline (on `main`):** retag the QA-built image (SHA → `prod`) → push → update prod manifest → deploy to EKS prod → verify rollout.

Principles: security at every stage, **build once / promote the artifact**, immutable SHA-tagged images, parallel jobs for speed, controlled human-approved promotion.

## Planned Repository Layout

```
client/                 React frontend
server/                 Node.js + Express backend
Dockerfile              Multi-stage, non-root image
docker-compose.yml      Local full-stack run
k8s-manifests/
  qa/                   QA Deployment, Service, Ingress, MySQL StatefulSet, ESO resources
  prod/                 Production equivalents
terraform/              AWS infrastructure (EKS, IAM/OIDC, networking)
.github/workflows/      QA and prod pipelines
```

*(Layout is indicative; it will be finalized when source code is added.)*

## Local Development

```bash
docker-compose up --build -d     # app on http://localhost:5000
docker-compose logs -f app
docker-compose down -v           # stop and reset DB volume
```

Backend environment variables: `PORT`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.

## Prerequisites

AWS account, a registered domain, GitHub repository, Docker, `kubectl`, `awscli`, Terraform (if used), and a SonarQube instance or SonarCloud project.

## Notes

- `project-docs/` (course guides and diagrams) is intentionally excluded from version control via `.gitignore`.
- Never commit secrets. Credentials come from AWS Secrets Manager; CI authenticates to AWS via OIDC.

## Credits

Based on the DevOps Shack *End-to-End DevSecOps Mastery* course by Aditya Jaiswal ([devopsshack.com](https://devopsshack.com)).
