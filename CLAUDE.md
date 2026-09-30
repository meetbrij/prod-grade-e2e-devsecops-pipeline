# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Status

**Planning / documentation phase.** Implementation has NOT started. Do not scaffold, generate, or modify infrastructure, pipelines, or application code until the user gives explicit instructions. The user will copy the application source code and other files into this repo; some may be outdated and will be updated on request.

`project-docs/` holds the reference material (course guides + architecture diagrams). It is **gitignored** — never commit it, never reference it as a repo dependency, and do not copy its contents verbatim into committed files. Read it for context only.

## Project Summary

Production-grade DevSecOps project on AWS: a 3-tier User Management app (React + Node/Express + MySQL) deployed to **AWS EKS** through **GitHub Actions** CI/CD with branch-based promotion (feature → `qa` → `main`), embedded security scanning, secretless AWS auth, external secrets management, HTTPS via ALB/Route 53/ACM, and a full observability stack.

Source material: DevOps Shack "End-to-End DevSecOps Mastery" course (Aditya Jaiswal).

## Application (3-Tier)

| Tier | Tech | Notes |
|------|------|-------|
| Frontend | React 17, Webpack 5, Babel, Axios | `npm run build` in `client/` produces `bundle.js` in `client/public/`; served statically by Express |
| Backend | Node.js 20 + Express 4.17, body-parser, cors, `mysql` npm pkg | Port 5000 (`PORT`); REST API `GET/POST /api/users`, `PUT/DELETE /api/users/:id` |
| Database | MySQL 8.0 | Table `users(id, name, email UNIQUE, role ENUM('Admin','User'))`, created on startup via `CREATE TABLE IF NOT EXISTS` |

Backend env vars: `PORT`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `NODE_ENV`. In Docker Compose `DB_HOST=mysql`; on K8s it is the MySQL Service name. Never hardcode credentials.

Expected layout (per docs; verify against actual files once code is added): `client/`, `server/` (MVC: `config/db.js`, `routes/`, `server.js`), root `Dockerfile` (multi-stage, non-root, `node:20-alpine`), `docker-compose.yml`.

Local: `docker-compose up --build -d`; reset data with `docker-compose down -v`.

## Target Architecture

- **Compute:** EKS cluster + managed node groups. Separate `qa` and `prod` namespaces (docs discuss QA/prod clusters/namespaces; confirm with user before assuming one cluster).
- **Ingress/DNS/TLS:** AWS Load Balancer Controller provisions an internet-facing ALB (target-type `ip`), TLS terminated with an **ACM** cert (DNS-validated, referenced via `alb.ingress.kubernetes.io/certificate-arn`), HTTP→HTTPS redirect. **Route 53** hosted zone with alias A record → ALB; domain registrar (Namecheap) delegates NS to Route 53. Hosts like `qa.<domain>`; `/` and `/api` route to the app Service.
- **App workload:** single App pod (React + Node) behind ClusterIP Service (port 80), Deployment.
- **Database:** MySQL as **StatefulSet** (`mysql-0`) + headless Service (3306); StorageClass `ebs-sc` (gp2, `WaitForFirstConsumer`), 10Gi EBS PV, reclaim `Retain` (AZ-locked).
- **Secrets:** AWS Secrets Manager (e.g. `qa/mysql-secret`) → **External Secrets Operator** (SecretStore + ExternalSecret, auth via **IRSA**, refresh ~1h) → K8s Secret `mysql-secret` consumed via `envFrom` by both App and MySQL pods. A separate manually-created `docker-registry` ImagePullSecret is used by the App pod only.
- **Auth to AWS from CI:** GitHub **OIDC** → IAM role via STS. No static AWS keys anywhere. Trust policy scoped to this repo and to `qa`/`main` branches; permissions minimal (`eks:DescribeCluster`, registry auth/push).
- **Observability:** kube-prometheus-stack (Prometheus + Alertmanager), **Loki** + Promtail (logs), **Tempo** + OpenTelemetry SDK (traces), **Grafana** as the single pane.

## Branching & Promotion

- `feature/*` (branched from `qa`) → PR → `qa` → PR (after QA sign-off) → `main` (protected).
- Bugs found in QA: `bugfix` branch → merge back to `qa` → re-triggers QA pipeline.
- Direct deploys to prod are impossible; `main` is authorized only after QA validation and PR approval.

## CI/CD Design

**QA pipeline** (trigger: push/merge to `qa`), in order:
1. Gitleaks (full history; hard gate)
2. Parallel: Checkov (Terraform, Kubernetes, Dockerfile), Trivy FS (client, server), lint (client, server), client tests
3. SonarQube analysis + Quality Gate
4. Client build → Docker build (image tagged with **git commit SHA**, never `latest`)
5. Parallel: Trivy image scan, SBOM generation
6. Push to QA registry (GHCR or ECR)
7. Update image tag in `k8s-manifests/qa/` and commit back (GitOps)
8. Deploy to EKS QA namespace (`kubectl apply`, `kubectl rollout status`)
9. Manual QA / smoke tests / sign-off

**Prod pipeline** (trigger: merge to `main`) — deliberately minimal, **build once, promote the artifact**:
retag QA image (SHA → `prod`) → push to prod registry → update `k8s-manifests/prod/` tag → deploy to EKS prod namespace → verify rollout. No rebuild, no re-scan.

Rules to preserve:
- Pipelines live in `.github/workflows/`; branch conditions must prevent `qa` pushes from triggering prod deploy.
- Separate manifests per env: `k8s-manifests/qa/` and `k8s-manifests/prod/` (different resources, replicas, ingress, env, probes).
- High/Critical Trivy findings, Gitleaks hits, and failed Sonar quality gates fail the pipeline. No bypass flags.
- Use rolling updates for zero downtime.

## Conventions for Claude

- **Wait for instructions** before implementing anything. Propose, don't presume.
- No secrets, tokens, real account IDs, or credentials in any file. Use placeholders (`<AWS_ACCOUNT_ID>`, `<DOMAIN>`, `<CERT_ARN>`).
- Prefer least-privilege IAM, non-root containers, pinned image/action versions, resource requests/limits, and readiness/liveness probes.
- Keep Terraform, K8s manifests, and workflows Checkov/Trivy-clean; explain and justify any suppression.
- Ask before destructive or outward-facing actions (git push, cloud resource creation, deleting files).
- When source files arrive, verify them against this document and flag drift rather than silently overwriting either.

## Known Doc Inconsistencies (resolve with user when relevant)

- Course guide's monitoring section mentions **ELK/Jaeger**; the project brief and monitoring diagram specify **Loki + Tempo + Promtail + OTel**. Treat **Loki/Tempo** as authoritative.
- Course text says "10-stage" QA pipeline; the app architecture doc says "15 jobs, 5 security scanners". The diagram's job breakdown is the more detailed source.
- Registry is "GHCR or ECR" in the guide; SonarQube (hosted vs SonarCloud) and Terraform vs manual infra provisioning are not specified. Confirm before implementing.
- Secrets Manager region in the diagram is `ap-south-1`; confirm the target region.
