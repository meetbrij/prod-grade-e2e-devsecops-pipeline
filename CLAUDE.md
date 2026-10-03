# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Status

**Source code imported; DevSecOps implementation not started.** The sample app (`client/`, `server/`, `Dockerfile`, `sonar-project.properties`) and initial `k8-manifests/` are in the repo and may be outdated. GitHub Actions workflows exist in `.github/workflows/` (`qa-cicd.yml`, `prod-cd.yaml`) but were imported from the course and have not been reviewed against this document yet. Terraform for `bootstrap`, `platform`, `addons` and `envs/qa` is applied; `envs/prod` is written but not yet applied. The QA pipeline (scans through ECR push and EKS deploy) works end to end; `prod-cd.yaml` is still the disabled course version and must be rewritten. No MySQL manifests (the drafts are only in project-docs), MySQL manifests, ESO resources or observability config exist yet. Do not scaffold, generate, or modify infrastructure, pipelines, or application code until the user gives explicit instructions.

`project-docs/` holds reference material (architecture guides, diagrams, branching and environment PDFs). It is **gitignored**: never commit it, never make the repo depend on it, and do not copy its contents verbatim into committed files. Read it for context only.

## Project Summary

Production-grade DevSecOps project on AWS: a sample 3-tier User Management app (React + Node/Express + MySQL) deployed to **AWS EKS** through **GitHub Actions** CI/CD with branch-based promotion (feature → `qa` → `main`), embedded security scanning, secretless AWS auth, external secrets management, HTTPS via ALB/Route 53/ACM, and a full observability stack.

**The 3-tier app is a placeholder workload.** The goal is the platform and pipeline. Once established, the app will be replaced by an AI-based project (TBD). Keep pipelines, manifests and infra app-agnostic (parameterize image name, ports, health paths, env vars, hostnames; avoid coupling to MySQL/React specifics outside the app's own directories) and don't invest in polishing the sample app.

## Decisions

- **Scope:** two environments only, `qa` and `prod`. `dev` and `ppd` are out of scope, but pipelines/manifests should be parameterized by environment so they can be added later (the README documents how).
- **Region:** `ap-south-1` for all project resources (EKS, ECR, ACM, Secrets Manager, Route 53 records). A separate Jenkins server exists in `us-east-1` and is unrelated to this project; do not couple to it.
- **Registry:** private **Amazon ECR** in `ap-south-1`, same region as EKS (no cross-region transfer cost). Use one repository per app, immutable tags, scan-on-push optional (Trivy is the gate). Costs are low (storage per GB-month; pulls in-region are free); add a lifecycle policy to expire old untagged/SHA images.
- **Terraform state:** remote backend in a dedicated S3 bucket in `ap-south-1` (versioning, encryption, public access blocked) with S3 native locking (`use_lockfile = true`, Terraform 1.10+); no DynamoDB table. Separate state per environment/cluster (qa and prod must not share a state file). The state bucket is created by a small bootstrap step outside the main configuration. State files must never be committed.
- **DNS:** reuse the existing public Route 53 hosted zone for `bolarbrijesh.com` (zone ID `Z07282781O1NN543FLL11`); reference it as a Terraform data source, never create or destroy it. Prod host: `proj3-aigateway.bolarbrijesh.com`. QA host: proposed `qa-proj3-aigateway.bolarbrijesh.com` (single-level, so a SAN or `*.bolarbrijesh.com` cert covers it). DNS alias records are created **manually, once per hostname** after the first deploy (alias A records to the ALB; no cost). No ExternalDNS. If the ALB is recreated, the aliases must be updated; do not delete all Ingresses in the group casually.
- **ALB:** one shared ALB for both environments via an Ingress group (`alb.ingress.kubernetes.io/group.name`), with host-based rules. Accepts shared blast radius for lower cost.
- **TLS:** ACM certificate (DNS-validated in the zone) covering both hostnames (SANs, or `*.bolarbrijesh.com`). Do not hardcode `certificate-arn` in manifests; rely on the ALB controller's certificate discovery by hostname.
- **Networking:** nodes in private subnets with a **single NAT gateway** (cost decision); public subnets tagged for ALB discovery.
- **Secret values:** Terraform creates Secrets Manager secrets and IAM roles but never password values (they would end up in state). Set values out-of-band or use write-only attributes (Terraform 1.11+). ESO uses one service account and IAM role per environment namespace, each limited to that environment's secret.
- **Storage:** StorageClass `ebs-sc` uses gp3 with the EBS CSI driver add-on (needs its own IAM role); reclaim `Retain` for prod, `Delete` for qa.
- **Terraform layout:** `terraform/bootstrap` (state bucket, local state), `terraform/platform` (VPC + single NAT, EKS, EBS CSI driver, ECR, GitHub OIDC provider, ACM cert), `terraform/addons` (Helm: ALB controller, ESO; StorageClass; separate stack so Helm/Kubernetes providers do not depend on a cluster created in the same apply), `terraform/modules/app-env` (namespace, ESO role, secret shell, deploy role + EKS access entry), `terraform/envs/{qa,prod}`; separate state per stack. `bootstrap` and `platform` are applied; `addons` is applied (ALB controller, ESO, StorageClasses; ESO installs after the ALB controller because the controller's Service webhook must be ready); ``modules/app-env` and `envs/qa` are applied; `envs/prod` is written and validated (not yet applied). ESO chart installs with no AWS role of its own; per-env service accounts and roles live in `envs/*`. Two StorageClasses exist because reclaim policy is per class: `ebs-sc` (Delete, qa) and `ebs-sc-retain` (Retain, prod). Terraform owns AWS resources, add-ons and namespaces; the pipeline deploys `k8-manifests/`. Verify the namespace-scoped EKS Edit policy can create ESO `SecretStore`/`ExternalSecret` objects; if not, Terraform applies them.
- **GitHub OIDC subject format:** GitHub now issues subjects with immutable IDs, for example `repo:meetbrij@<ownerId>/<repo>@<repoId>:ref:refs/heads/qa`, not `repo:owner/name:...`. Trust policies must use the ID form (`github_repository_claim` variable in `envs/*`); the old form fails with "Not authorized to perform sts:AssumeRoleWithWebIdentity". Read the real `sub` from a run's token if it fails again.
- **Deploy role and CRDs:** `AmazonEKSEditPolicy` does not cover custom resources (confirmed: forbidden on `externalsecrets`/`secretstores`). The access entry therefore also maps the role to the Kubernetes group `<env>-deployers`, and a namespaced Role/RoleBinding in the `app-env` module grants that group only `externalsecrets` and `secretstores` in its own namespace. Same pattern for prod.
- **Prod environment (written, not applied):** same shared cluster, namespace `prod`, host `proj3-aigateway.bolarbrijesh.com`, secret `prod/mysql-secret`, StorageClass `ebs-sc-retain` (Retain), 10Gi MySQL volume, 2 app replicas with a zero-unavailability rolling update, 7-day secret recovery window. Prod deploy role: trust subject `environment:prod`, ECR permissions are retag-only (`BatchGetImage`, `PutImage`), EKS edit access scoped to `prod` plus the External Secrets Role. A GitHub Environment named `prod` with required reviewers must exist before the prod workflow can assume the role; its role ARN goes in the repo variable `AWS_ROLE_TO_ASSUME_PROD`.
- **Prod deploy role trust:** a job using a GitHub Environment presents an `environment:prod` OIDC subject instead of a branch subject; the prod role's trust policy must match that. The QA role trusts `refs/heads/qa`. CI roles need ECR push (qa) and image get/put for retagging (prod), not just `eks:DescribeCluster`.
- **EKS:** version 1.36 (latest in standard support as of Oct 2026; cluster upgrade policy is `STANDARD`, not the module default `EXTENDED`; stay within standard support to avoid extended-support charges, so plan upgrades before the end-of-standard-support date). Managed node group of 2 × `t3a.medium` (min 2, max 3) for now; observability will need larger nodes. Cluster name `devsecops-eks`. Public API endpoint stays open (CIDR `0.0.0.0/0`) because GitHub-hosted runners have no fixed IPs; access is controlled by IAM and EKS access entries.
- **Terraform safety:** the Terraform identity is the IAM user running it with AWS credentials from a local profile (never keys in files). `terraform destroy` only removes resources in state; manually created resources (Jenkins, IAM users, etc.) are never touched. The Route 53 hosted zone is a data source only. All managed resources are tagged `ManagedBy=terraform`. The state bucket has `prevent_destroy`. Do not put the AWS account ID in files; use `data.aws_caller_identity`. The GitHub OIDC provider is account-wide: `create_github_oidc_provider=false` if one already exists.
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

### App contract (what the platform expects from any app)

The sample app is a placeholder. Any replacement (for example the planned AI project) should meet this contract so it slots in with only a Dockerfile and a few settings, and the pipeline, manifests and Terraform stay unchanged:

1. **One container image**, built from the `Dockerfile` at the repo root with `docker build .`, listening on a single HTTP port (today 5000). The port is set by the `PORT` environment variable; the manifests reference the container port by name (`http`), so changing the port means editing one `containerPort` in `app-deployment.yaml` per environment.
2. **Health endpoint:** `GET /healthz` returns 200 when the app can serve traffic (and checks its dependencies if it needs them). The sample app has none and uses `/`; the probes and the ALB health check path (`alb.ingress.kubernetes.io/healthcheck-path`) must be switched to `/healthz` when the app is swapped.
3. **Configuration only through environment variables.** No config files baked in per environment and no secrets in the image. Secrets arrive as environment variables from the Kubernetes Secret created by External Secrets from `<env>/mysql-secret` in Secrets Manager. If the new app needs other secrets, add keys to that Secrets Manager secret (the manifests pull all keys), or add a second secret and ExternalSecret.
4. **Runs as a non-root user** (the manifests run as UID 10001 with all capabilities dropped and `allowPrivilegeEscalation: false`), and should tolerate a read-only root filesystem except for `/tmp`.
5. **Starts without its database being ready and retries**, or exits non-zero so Kubernetes restarts it. The sample app exits and relies on restarts.
6. **Logs to stdout/stderr** (Promtail/Loki collects them) and, ideally, exposes Prometheus metrics at `/metrics` and emits OpenTelemetry traces (OTLP) to Tempo.
7. **Stateless.** Persistent data lives in the database; the app can run as 2+ replicas behind the ALB (prod runs 2).
8. **Database:** MySQL is the current choice (`DB_HOST=mysql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DATABASE_URL`). A different database means replacing the StatefulSet manifests and secret keys, nothing in Terraform except possibly the secret contents.
9. **Pipeline hooks the repo must provide:** a lint script (`npm run lint` or equivalent), a test command, a `sonar-project.properties` with the right sources, and lockfiles checked in. The workflow's lint/test jobs currently call `npm run lint --if-present` and `npm test --if-present`; a non-Node language needs those two jobs adapted.
10. **Single image per commit.** A multi-service app needs a build matrix, one ECR repository per service, and per-service image entries in `kustomization.yaml`; that is a pipeline change, not a drop-in swap.

### k8-manifests status
- `k8-manifests/qa/` is rewritten for the new platform: `secretstore.yaml`, `external-secret.yaml` (pulls `qa/mysql-secret` into the Secret `mysql-secret`), `mysql-svc.yaml` (headless) and `mysql-statefulset.yaml` (5Gi on `ebs-sc`), `app-deployment.yaml`, `app-svc.yaml` (ClusterIP 80 to container port `http`/5000), `app-ingress.yaml` (shared ALB group `devsecops-shared`, host `qa-proj3-aigateway.bolarbrijesh.com`, no certificate ARN), and `kustomization.yaml`. All render and pass a server-side dry run.
- Image handling: the Deployment uses the bare name `nodejs-app`; `kustomization.yaml` `images:` rewrites it. The deploy step must run `kustomize edit set image nodejs-app=<registry>/nodejs-app:<git-sha>` (registry host and tag set at deploy time, so no account ID is committed). The committed default tag `unset` is intentionally not deployable.
- The app pieces cannot be applied until an image exists in ECR (pushed by the pipeline). The MySQL and secret pieces can be applied manually first to prove the chain.
- `k8-manifests/prod/` mirrors `qa/` with these deliberate differences: namespace and secret key `prod`, host `proj3-aigateway.bolarbrijesh.com`, `ebs-sc-retain` with 10Gi, 2 app replicas with `maxUnavailable: 0`. Its committed image tag is `unset`; the prod pipeline sets it to `prod-<qa sha>`.
- Still missing everywhere: NetworkPolicies, PodDisruptionBudgets, a dedicated app health endpoint. The MySQL pod and the app do not set `readOnlyRootFilesystem` (the app needs a writable `HOME`, MySQL writes under `/var/run`); revisit when the app is replaced.
- The deploy role has namespace-scoped `AmazonEKSEditPolicy` plus a namespaced Role for External Secrets objects (see Decisions).

### Code issues noticed (not yet fixed; raise before changing)
- `server.js` requires `body-parser` but it is not in `server/package.json` (works only via Express's transitive dep).
- `server/app.js`, `routes/users.js`, `routes/userRoutes.js`, `controllers/`, `models/` appear to duplicate logic inlined in `server.js`; confirm which is live. `db.js` falls back to `root`/`password` defaults.
- Dockerfile is not multi-stage (build tooling stays in the final image) and uses `npm install` instead of `npm ci`.
- `client/public/bundle.js` is a build artifact present in the tree (ignored by `.gitignore`).

## Target Architecture

- **Compute:** a **single EKS cluster** (cost decision) with two namespaces, `qa` and `prod`. Managed node groups; resource quotas/limit ranges and network policies per namespace so qa cannot starve or reach prod. DR is provisioned on demand from IaC, not kept running. If stronger isolation is needed later, prod can move to its own cluster; keep cluster name and kubeconfig as per-environment variables so that move does not change pipeline structure.
- **IAM isolation:** IAM Role A (QA deployer) is mapped via an EKS access entry scoped to the `qa` namespace only; IAM Role B (PROD deployer) is scoped to the `prod` namespace only and gated by a GitHub Environments manual-approval rule. QA and prod pipelines must never share a role, and Role A must have no access to `prod`. Because the cluster is shared, this AWS/EKS access scoping plus namespace RBAC is the isolation boundary. CloudTrail audits assume-role events.
- **Ingress/DNS/TLS:** AWS Load Balancer Controller provisions an internet-facing ALB (target-type `ip`), TLS terminated with an **ACM** cert discovered by hostname, HTTP→HTTPS redirect. Alias records in the existing **Route 53** zone are created manually (see Decisions).
- **App workload:** Deployment behind a ClusterIP Service.
- **Database:** MySQL as **StatefulSet** (`mysql-0`) + headless Service (3306); StorageClass `ebs-sc` (gp3, `WaitForFirstConsumer`), small EBS PV (5Gi is enough for qa), AZ-locked.
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
3. SonarCloud analysis + Quality Gate
4. Client build → Docker build (tagged with **git commit SHA**)
5. Parallel: Trivy image scan, SBOM generation (CycloneDX via Trivy), both run against the image archive built in step 4 so the scanned image is the one pushed
6. Push to ECR (push to `qa` only, never on PRs; assumes the QA role via OIDC using the `AWS_ROLE_TO_ASSUME_QA` repo variable; skips the push if the SHA tag already exists because tags are immutable)
7. Deploy to the EKS QA namespace: render `k8-manifests/qa` in a temp copy with the registry and SHA tag, `kubectl apply -k`, then `kubectl rollout status` for MySQL and the app. The registry host (account ID) is never written to the repo.
8. After a successful rollout, commit the deployed tag (`newTag` in `k8-manifests/qa/kustomization.yaml`) back to `qa` as `github-actions[bot]` with `[skip ci]`, so the repo records what is deployed and the prod pipeline can read which QA image to promote.
9. Manual QA / smoke tests / sign-off. After the first deploy, create the Route 53 alias records manually.

**Prod pipeline** (trigger: merge to `main`), deliberately minimal, **build once, promote the artifact**:
read the QA-built SHA from `k8-manifests/qa/kustomization.yaml` (`newTag`) → retag the image (`<sha>` → `prod-<sha>`) in ECR → update `k8-manifests/prod/` tag → deploy to the EKS prod namespace → verify rollout. No rebuild, no re-scan.

Rules to preserve:
- Pipelines live in `.github/workflows/`; branch conditions must prevent `qa` pushes from triggering a prod deploy.
- Separate manifests per env: `k8-manifests/qa/` and `k8-manifests/prod/` (different resources, replicas, ingress, env, probes).
- Environment-specific values (namespace, cluster, role ARN, host, replicas) must be inputs/variables rather than hardcoded, so `dev`/`ppd` can be added without restructuring.
- High/Critical Trivy findings, Gitleaks hits, and failed Sonar quality gates fail the pipeline. No bypass flags.
- Use rolling updates for zero downtime.

## Conventions for Claude

- **Wait for instructions** before implementing anything. Propose, don't presume.
- No secrets, tokens, real account IDs, or credentials in any file. Use placeholders (`<AWS_ACCOUNT_ID>`, `<DOMAIN>`, `<CERT_ARN>`).
- Prefer least-privilege IAM, non-root containers, pinned image/action versions, resource requests/limits, and readiness/liveness probes.
- Keep Terraform, K8s manifests, and workflows Checkov/Trivy-clean; explain and justify any suppression.
- Ask before destructive or outward-facing actions (git push, cloud resource creation, deleting files).
- When source files arrive, verify them against this document and flag drift rather than silently overwriting either.

## Parked Work (backlog)

- **Enforce scanners:** `ENFORCE_SCANS` is `"false"` in `qa-cicd.yml`, so Checkov and Trivy only report. Must be set to `"true"` before the prod pipeline goes live or the real app replaces the sample app. Findings from the first run: Checkov Dockerfile 1 (no HEALTHCHECK); Checkov Kubernetes 41 across 19 checks (securityContext, resources, probes, imagePullPolicy, automountServiceAccountToken, default-namespace Service in `qa/app-svc.yaml`, NetworkPolicy); Trivy client 10 HIGH (axios 0.21.4), Trivy server 4 HIGH (body-parser, path-to-regexp). Plan: fix these on the replacement app and the reworked manifests rather than the placeholder. Suppress with written justification: CKV_K8S_43 (image digest; conflicts with SHA-tag promotion) and CKV_K8S_35 (secrets via ESO `envFrom`).
- **Lint/test jobs** run `npm run lint --if-present` / `npm test --if-present`, so they pass trivially until the app defines scripts.
- **SonarCloud:** the repo is public, so SonarCloud's free tier analyzes all branches and PRs. Organization `meetbrij`, project key `meetbrij_prod-grade-e2e-devsecops-pipeline`, token in the `SONAR_TOKEN` repo secret. Automatic Analysis is turned off (pipeline-based analysis only) and `qa` is added as a long-lived branch in the project settings. The quality gate blocks the pipeline only when `ENFORCE_SCANS` is `"true"`. The gate applies to new code, so the first-scan findings on the sample app (33 issues) do not fail it.

## Open Questions

- QA hostname: confirm `qa-proj3-aigateway.bolarbrijesh.com` (or another name).
