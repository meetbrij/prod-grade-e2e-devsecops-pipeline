# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Status

**Source code imported; DevSecOps implementation not started.** The sample app (`client/`, `server/`, `Dockerfile`, `sonar-project.properties`) and initial `k8-manifests/` are in the repo and may be outdated. No workflows, Terraform, MySQL manifests, ESO resources or observability config exist yet. Do not scaffold, generate, or modify infrastructure, pipelines, or application code until the user gives explicit instructions.

`project-docs/` holds reference material (architecture guides, diagrams, branching and environment PDFs). It is **gitignored**: never commit it, never make the repo depend on it, and do not copy its contents verbatim into committed files. Read it for context only.

## Project Summary

Production-grade DevSecOps project on AWS: a sample 3-tier User Management app (React + Node/Express + MySQL) deployed to **AWS EKS** through **GitHub Actions** CI/CD with branch-based promotion (feature → `qa` → `main`), embedded security scanning, secretless AWS auth, external secrets management, HTTPS via ALB/Route 53/ACM, and a full observability stack.

**The 3-tier app is a placeholder workload.** The goal is the platform and pipeline. Once established, the app will be replaced by an AI-based project (TBD). Keep pipelines, manifests and infra app-agnostic (parameterize image name, ports, health paths, env vars, hostnames; avoid coupling to MySQL/React specifics outside the app's own directories) and don't invest in polishing the sample app.

## Decisions

- **Scope:** two environments only, `qa` and `prod`. `dev` and `ppd` are out of scope, but pipelines/manifests should be parameterized by environment so they can be added later (the README documents how).
- **Region:** `ap-south-1` for all project resources (EKS, ECR, ACM, Secrets Manager, Route 53 records). A separate Jenkins server exists in `us-east-1` and is unrelated to this project; do not couple to it.
- **Registry:** private **Amazon ECR** in `ap-south-1`, same region as EKS (no cross-region transfer cost). Use one repository per app, immutable tags, scan-on-push optional (Trivy is the gate). Costs are low (storage per GB-month; pulls in-region are free); add a lifecycle policy to expire old untagged/SHA images.
- **Terraform state:** remote backend in a dedicated S3 bucket in `ap-south-1` (versioning, encryption, public access blocked) with S3 native locking (`use_lockfile = true`, Terraform 1.10+); no DynamoDB table. Separate state per environment/cluster (qa and prod must not share a state file). The state bucket is created by a small bootstrap step outside the main configuration. State files must never be committed.
- **Image tags:** QA builds are tagged `<git-sha>`; promotion retags the same image digest as `prod-<sha>` in the same ECR repo (no rebuild, no cross-registry copy). Never `latest`.

## Application (placeholder)

| Tier | Tech | Notes |
|------|------|-------|
| Frontend | React 17, Webpack 5, Babel, Axios | `npm run build` in `client/` produces `bundle.js` in `client/public/`; served statically by Express |
| Backend | Node.js 20 + Express 4.17, `mysql2`, cors | Port 5000 (`PORT`); REST API `GET/POST /api/users`, `PUT/DELETE /api/users/:id` |
| Database | MySQL 8.0 | Table `users(id, name, email UNIQUE, role ENUM('Admin','User'))`, created on startup via `CREATE TABLE IF NOT EXISTS` |

Backend env vars: `PORT`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `NODE_ENV`. On K8s `DB_HOST` is the MySQL Service name. Never hardcode credentials.

Layout: `client/` (`src/`, `public/`), `server/` (`server.js` entrypoint, `config/db.js`, `models/`, `controllers/`, `routes/`), root `Dockerfile` (single stage, `node:20-alpine`, builds client then copies `client/public` into `server/public`, non-root `appuser`, port 5000), `sonar-project.properties`, `k8-manifests/{qa,prod}/` (directory is `k8-manifests`, not `k8s-manifests`). There is no `docker-compose.yml`, no tests, no lint config, and no `.github/`.

Local: run MySQL separately, then `cd server && npm start`; build the frontend with `cd client && npm run build`.

### Existing k8-manifests (observed)
- Deployment `nodejs-app` (1 replica, port 5000), Service `nodejs-service` (ClusterIP 5000), ALB Ingress with ACM cert and `ssl-redirect: 443`. qa and prod differ only in namespace, image tag, cert ARN and host.
- Image is a Docker Hub-style reference with `imagePullSecrets: regcred`; this must move to ECR (node IAM/IRSA pulls from ECR, so no pull secret is needed).
- DB config comes from Secret `mysql-secret` (keys `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `DATABASE_URL`); `DB_HOST=mysql`.
- Missing: MySQL StatefulSet/headless Service/StorageClass, ExternalSecret/SecretStore, resource requests/limits, probes, securityContext, Namespaces, NetworkPolicies.

### Code issues noticed (not yet fixed; raise before changing)
- `qa/app-svc.yaml` has no `namespace` (prod does), so the Service would land in `default`.
- Manifests contain a real AWS account ID, ACM ARNs and domains; parameterize them.
- `server.js` requires `body-parser` but it is not in `server/package.json` (works only via Express's transitive dep).
- `server/app.js`, `routes/users.js`, `routes/userRoutes.js`, `controllers/`, `models/` appear to duplicate logic inlined in `server.js`; confirm which is live. `db.js` falls back to `root`/`password` defaults.
- Dockerfile is not multi-stage (build tooling stays in the final image) and uses `npm install` instead of `npm ci`.
- `client/public/bundle.js` is a build artifact present in the tree (ignored by `.gitignore`).

## Target Architecture

- **Compute (2-environment model):** one non-prod EKS cluster hosting the `qa` namespace, and a separate dedicated prod EKS cluster hosting the `prod` namespace. Managed node groups; resource quotas/limit ranges and network policies per namespace. DR is provisioned on demand from IaC, not kept running.
- **IAM isolation:** IAM Role A (QA deployer) may deploy only to non-prod namespaces; IAM Role B (PROD deployer) only to the prod namespace on the prod cluster, gated by a GitHub Environments manual-approval rule. QA and prod pipelines must never share a role; CloudTrail audits assume-role events.
- **Ingress/DNS/TLS:** AWS Load Balancer Controller provisions an internet-facing ALB (target-type `ip`), TLS terminated with an **ACM** cert (DNS-validated, referenced via `alb.ingress.kubernetes.io/certificate-arn`), HTTP→HTTPS redirect. **Route 53** hosted zone with alias A record → ALB; the domain registrar delegates NS to Route 53. Hosts like `qa.<domain>`.
- **App workload:** Deployment behind a ClusterIP Service.
- **Database:** MySQL as **StatefulSet** (`mysql-0`) + headless Service (3306); StorageClass `ebs-sc` (gp2, `WaitForFirstConsumer`), 10Gi EBS PV, reclaim `Retain` (AZ-locked).
- **Secrets:** AWS Secrets Manager (e.g. `qa/mysql-secret`) → **External Secrets Operator** (SecretStore + ExternalSecret, auth via **IRSA**, refresh ~1h) → K8s Secret `mysql-secret` consumed via `envFrom` by App and MySQL pods.
- **Auth to AWS from CI:** GitHub **OIDC** → IAM role via STS. No static AWS keys anywhere. Trust policy scoped to this repo and to the `qa`/`main` branches; permissions minimal (`eks:DescribeCluster`, ECR auth/push).
- **Observability:** kube-prometheus-stack (Prometheus + Alertmanager), **Loki** + Promtail (logs), **Tempo** + OpenTelemetry SDK (traces), **Grafana** as the single pane. Loki/Tempo are authoritative; ELK/Jaeger are not used.

## Branching & Promotion

| Branch | From | Into | Notes |
|---|---|---|---|
| `main` | permanent | n/a | protected, no direct push, tagged `vMAJOR.MINOR.PATCH` on each release |
| `qa` | `main` | `main` | permanent integration branch; auto-deployed to QA; sync with `main` after every release/hotfix |
| `feature/*` | `qa` | `qa` | squash merge, 1 peer review, delete after merge |
| `bugfix/*` | `qa` | `qa` | defects found in QA; add regression test; never into `main` |
| `hotfix/*` | `main` | `main` **and** `qa` | P0/P1 only; 1 senior + SRE; patch-version tag |

- Naming: lowercase, `<type>/<ticket-id>-<short-slug>` (e.g. `feature/DS-421-user-auth`).
- PR gates: Feature/Bugfix PR = 1 reviewer, lint + unit tests + SAST + build, squash. Release PR (`qa`→`main`) = 2 seniors + QA lead sign-off, full regression + security scan, merge commit (no squash). Hotfix PR = 1 senior + SRE, smoke tests, merge commit.
- Never branch `feature/*` or `bugfix/*` from `main`. Never push directly to `main` or `qa`.
- Direct deploys to prod are impossible; `main` is authorized only after QA validation and PR approval.

## CI/CD Design

**QA pipeline** (trigger: push/merge to `qa`), in order:
1. Gitleaks (full history; hard gate)
2. Parallel: Checkov (Terraform, Kubernetes, Dockerfile), Trivy FS (client, server), lint (client, server), client tests
3. SonarQube analysis + Quality Gate
4. Client build → Docker build (tagged with **git commit SHA**)
5. Parallel: Trivy image scan, SBOM generation
6. Push to ECR
7. Update image tag in `k8-manifests/qa/` and commit back (GitOps)
8. Deploy to the EKS QA namespace (`kubectl apply`, `kubectl rollout status`)
9. Manual QA / smoke tests / sign-off

**Prod pipeline** (trigger: merge to `main`), deliberately minimal, **build once, promote the artifact**:
retag the QA image (`<sha>` → `prod-<sha>`) in ECR → update `k8-manifests/prod/` tag → deploy to the EKS prod namespace → verify rollout. No rebuild, no re-scan.

Rules to preserve:
- Pipelines live in `.github/workflows/`; branch conditions must prevent `qa` pushes from triggering a prod deploy.
- Separate manifests per env: `k8-manifests/qa/` and `k8-manifests/prod/` (different resources, replicas, ingress, env, probes).
- Environment-specific values (namespace, cluster, role ARN, host, cert ARN, replicas) must be inputs/variables rather than hardcoded, so `dev`/`ppd` can be added without restructuring.
- High/Critical Trivy findings, Gitleaks hits, and failed Sonar quality gates fail the pipeline. No bypass flags.
- Use rolling updates for zero downtime.

## Conventions for Claude

- **Wait for instructions** before implementing anything. Propose, don't presume.
- No secrets, tokens, real account IDs, or credentials in any file. Use placeholders (`<AWS_ACCOUNT_ID>`, `<DOMAIN>`, `<CERT_ARN>`).
- Prefer least-privilege IAM, non-root containers, pinned image/action versions, resource requests/limits, and readiness/liveness probes.
- Keep Terraform, K8s manifests, and workflows Checkov/Trivy-clean; explain and justify any suppression.
- Ask before destructive or outward-facing actions (git push, cloud resource creation, deleting files).
- When source files arrive, verify them against this document and flag drift rather than silently overwriting either.

## Open Questions

- SonarQube: self-hosted instance or SonarCloud?
- Infrastructure provisioning: Terraform (the Checkov Terraform scan assumes it) or eksctl/manual?
- Confirm the non-prod and prod clusters should be separate (per the environment model) versus one cluster with two namespaces, given cost.
