# KYC Document Intelligence on AWS EKS

A KYC document extraction service (FastAPI, Amazon Bedrock Claude, MySQL) delivered through a **DevSecOps pipeline**: GitHub Actions with Gitleaks, Checkov, Trivy, SBOM and SonarCloud; secretless AWS access through GitHub OIDC; External Secrets and IRSA; an ALB with Route 53 and ACM; and a Prometheus, Loki, Tempo and Grafana stack. It runs on one AWS EKS cluster with approval-gated promotion from `qa` to `prod`, and it is all provisioned with Terraform.

> **Status:** the platform is live. QA and prod run end to end, including the approval-gated promotion and the observability stack. The extraction service is deployed and its UI works, but **no accuracy evaluation has been run yet**: the AWS account's Bedrock quota for Anthropic models is currently zero, so uploads return 502 until an increase is approved. This README therefore contains **no accuracy numbers**. They will appear only when they come from a file committed in `app/eval/results/`.

## Intro

A bank onboarding a customer has to read identity documents and proofs of address, and the same facts get re-typed by hand. This service reads the document with an LLM and returns each field with a **confidence score**. Anything low-confidence, missing or malformed is flagged, so a person checks only what needs checking.

The project has two goals, in this order:

1. **The platform and pipeline.** A production-style way to ship a service to Kubernetes: scans on every change, no static cloud credentials, secrets kept out of Git and Terraform state, one artifact promoted from QA to prod, and logs, metrics and traces from day one.
2. **A realistic workload.** The service is deliberately built to the standards a regulated workload needs: documents are never stored, personal data never reaches logs or traces, and inference stays in India.

The pipeline is deliberately app-agnostic. The workload started as a sample Node app and was swapped for this service without redesigning the pipeline; the contract any app must meet is in [CLAUDE.md](CLAUDE.md).

## What it does

Seven steps from upload to a reviewed record. A person is in the loop at step 6, and only for fields that were flagged.

| # | Step | What happens |
|---|---|---|
| 1 | **Upload** | `POST /documents` with an ID document or proof of address (PNG, JPEG or PDF). The file type is checked by its magic bytes, not its extension, and the size is capped. |
| 2 | **Extract** | The file is sent to Claude on Amazon Bedrock through the Converse API. The model is forced to answer through one tool schema, so the output is structured fields rather than free text. |
| 3 | **Validate** | Each field is checked against its spec (formats, dates, cross-checks such as expiry after birth). Missing or malformed fields are marked. |
| 4 | **Score and flag** | Every field gets a confidence score. Below the threshold (default 0.85), missing or malformed means `needs_review`. |
| 5 | **Store** | MySQL keeps a SHA-256 hash of the upload, the extracted fields and the scores. The file itself is **never stored**. |
| 6 | **Review** | `GET /documents?needs_review=true` lists flagged documents. `PATCH /documents/{id}/fields/{name}` confirms or corrects one field. The built-in page at `/ui` does the same in a browser. |
| 7 | **Observe** | JSON logs go to Loki, traces to Tempo and metrics to Prometheus, with no personal data in any of them. |

### Document flow

```mermaid
flowchart TD
    START([Upload: ID document or proof of address]) --> check{Type, size and<br/>API key OK?}
    check -->|no| REJ([4xx error])
    check -->|yes| extract["Bedrock Converse call<br/>forced tool schema<br/>India-only inference profile"]
    extract -->|throttled or unavailable| ERR([502, error code only])
    extract --> validate[Validate fields<br/>formats, dates, cross-checks]
    validate --> score[Score each field<br/>flag low confidence, missing, malformed]
    score --> store[(MySQL<br/>SHA-256, fields, scores<br/>no file stored)]
    store --> flagged{Any field<br/>needs_review?}
    flagged -->|no| DONE([Result returned])
    flagged -->|yes| review{{"Person reviews<br/>/ui or PATCH field"}}
    review --> DONE
```

There is no path that auto-corrects a field. A person confirms or edits it, and the document content never changes what the service does: the prompt tells the model to ignore any instructions found inside a document.

## Application

One container image, one Deployment per environment.

| Piece | Technology |
|-------|------------|
| Service | Python 3.12, FastAPI, SQLAlchemy, boto3 (Bedrock Converse API) |
| Model | Claude Haiku 4.5 by default, Sonnet 5 for the accuracy comparison, through India-only inference profiles (`in.` prefix): inference stays in `ap-south-1` and `ap-south-2` |
| Database | MySQL 8.0 StatefulSet (tables `documents` and `extractions`) |
| Review page | Built-in vanilla HTML and JS at `/ui`, with a strict Content Security Policy; values are rendered as text only |
| Observability | Prometheus metrics at `/metrics`, OpenTelemetry traces to Tempo, JSON logs to Loki |

**Endpoints:** `POST /documents`, `GET /documents`, `GET /documents/{id}`, `PATCH /documents/{id}/fields/{name}`, `GET /healthz`, `/metrics`, `/ui`, `/docs`.

**Key behaviours**
- **Flag, don't guess:** a field is never silently trusted. Low confidence, missing and malformed values all go to review.
- **Fail loudly and safely:** a Bedrock error becomes a 502 whose message is the AWS error code only, never document data. `/healthz` returns 503 when MySQL is unreachable, and the service waits up to 90 seconds for MySQL at start.
- **Optional API key:** when `KYC_API_KEY` is set, uploads and the review API require an `X-API-Key` header. It is **not enabled yet** (see Known gaps).

**Privacy by design**
- Uploaded files are processed in memory and **never stored**. Only a SHA-256 hash, the extracted fields and the scores are kept.
- Field values are never logged. A redacting filter backs that up, and a test reads the real log output to prove it. Trace spans carry only IDs, the model and token counts.
- Document content is untrusted input: the system prompt tells the model to ignore instructions inside a document, and the review page builds its DOM only with `textContent`. A test fails if `innerHTML`, `eval` or similar appears in the page script.
- AWS access is IRSA only. Each environment has a role that can invoke just the two India-only inference profiles and their underlying models.
- All test documents are synthetic and watermarked `SPECIMEN`. Never upload a real person's documents.

## Tech Stack

### Application

| Tool | What it is and why it is here |
|------|-------------------------------|
| Python 3.12, FastAPI | The API, the review page and the health and metrics endpoints |
| Amazon Bedrock (Claude Haiku 4.5, Sonnet 5) | Reads images and PDFs and extracts fields against a schema; keyless access through IRSA |
| SQLAlchemy Core, PyMySQL | Storage for documents and extractions; the app creates its own tables at start |
| prometheus-client, OpenTelemetry | Metrics at `/metrics` and traces to Tempo |
| pytest, ruff | 49 offline tests (no AWS or MySQL needed) and linting; both run in the pipeline |

### Infrastructure and Pipeline Tooling

*Type:* **Infra** = runs or provisions the platform; **Pipeline** = used in CI/CD; **Both** = spans the two.

| Tool | What it is and the problem it solves here | Type |
|------|-------------------------------------------|------|
| GitHub and GitHub Actions | Source, branch-based promotion (`feature/*` to `qa` to `main`) and the CI/CD workflows, versioned and reviewed like code | Pipeline |
| GitHub OIDC | Workflows assume AWS IAM roles with short-lived tokens, so no static AWS keys exist in GitHub | Pipeline |
| Docker | One immutable image per commit, so the artifact tested in QA is what runs in prod | Pipeline |
| Amazon ECR | Private registry in `ap-south-1` next to EKS; SHA-tagged images and `prod-<sha>` promotions, no separate registry credentials | Both |
| Gitleaks | Scans the full history for committed secrets; the first gate | Pipeline |
| Trivy | Scans dependencies and the built image for known CVEs | Pipeline |
| Checkov | Static analysis of Terraform, Kubernetes manifests and the Dockerfile | Pipeline |
| SBOM (CycloneDX, from Trivy) | A software bill of materials for every image | Pipeline |
| SonarCloud | Static analysis with a Quality Gate on new code | Pipeline |
| kubectl and kustomize | Apply the manifests, rewrite the image name and tag at deploy time, and wait for the rollout so a failed deploy fails the job | Pipeline |
| Terraform | VPC, EKS, IAM, ECR, ACM and per-environment resources as code; remote state in S3 with native locking (`use_lockfile`) | Infra |
| AWS IAM and IRSA | Least-privilege roles for CI (separate QA and prod deployers) and for pods (External Secrets, Bedrock access) | Infra |
| Amazon VPC and NAT gateway | Public and private subnets; one NAT gateway as a cost decision | Infra |
| Amazon EKS and Kubernetes | Managed control plane, two `t3a.large` nodes, namespaces `qa` and `prod` | Infra |
| Helm | Installs the cluster add-ons: ALB controller, External Secrets Operator, kube-prometheus-stack, Loki, Tempo, Alloy | Infra |
| AWS Load Balancer Controller and ALB | Turns Ingress resources into one shared, internet-facing ALB that terminates TLS and routes by host | Infra |
| Amazon Route 53 | An existing hosted zone is reused; one manual alias record per hostname points at the shared ALB | Infra |
| AWS Certificate Manager | Free, auto-renewing certificate validated through DNS; the ALB controller finds it by hostname | Infra |
| Amazon EBS and CSI driver | Persistent gp3 volumes for MySQL and the observability stack | Infra |
| AWS Secrets Manager and External Secrets Operator | Credentials stay out of Git and Terraform state; each environment's role can read only its own secret | Infra |
| Prometheus and Alertmanager | Cluster and app metrics (kube-prometheus-stack) | Infra |
| Loki and Grafana Alloy | Log storage (15 days) and the collector that ships every pod's logs; Alloy replaces the end-of-life Promtail | Infra |
| Tempo and OpenTelemetry | Distributed tracing: the app emits OTLP, Tempo stores it | Infra |
| Grafana | One place for metrics, logs and traces, reached with `kubectl port-forward` | Infra |
| AWS CloudTrail | Audit log of role assumptions and API calls, including pipeline deployments | Infra |

Deliberately not used: Semgrep, cosign image signing and Kyverno policy enforcement. They are optional hardening and are left out to keep the pipeline simple.

## Architecture

### Request flow and workloads

One EKS cluster, one shared ALB, two environment namespaces.

```mermaid
flowchart TD
    U([User browser<br/>qa-proj3-aigateway.bolarbrijesh.com<br/>proj3-aigateway.bolarbrijesh.com]) --> R53[Route 53<br/>existing public hosted zone]
    R53 --> ALB[Shared AWS ALB<br/>TLS termination, HTTP to HTTPS redirect, host routing]
    ACM[ACM certificate<br/>DNS-validated, discovered by hostname] -. attached .-> ALB
    ALBC[AWS Load Balancer Controller] -. provisions and updates .-> ALB

    subgraph EKS[Single EKS cluster, ap-south-1]
        subgraph QA[qa namespace]
            INGQ[Ingress] --> SVCQ[Service: ClusterIP]
            SVCQ --> APPQ[KYC service pod]
            APPQ -->|SQL :3306| DBQ[(MySQL StatefulSet)]
            DBQ --- PVQ[(EBS gp3 volume)]
        end
        subgraph PROD[prod namespace]
            INGP[Ingress] --> SVCP[Service: ClusterIP]
            SVCP --> APPP[KYC service pod x2]
            APPP -->|SQL :3306| DBP[(MySQL StatefulSet)]
            DBP --- PVP[(EBS gp3 volume<br/>reclaim: Retain)]
        end
    end

    ALB -->|Ingress group: one ALB for both| INGQ
    ALB --> INGP
    APPQ -. IRSA .-> BR[Amazon Bedrock<br/>in. inference profile<br/>ap-south-1 and ap-south-2 only]
    APPP -. IRSA .-> BR
```

### Secrets management

External Secrets Operator runs once per cluster. Each environment namespace has its own service account, IAM role and secret: the QA role can read only `qa/mysql-secret`, and the prod role only `prod/mysql-secret`.

```mermaid
flowchart LR
    subgraph AWS[AWS]
        SMQ[(Secrets Manager<br/>qa/mysql-secret)]
        SMP[(Secrets Manager<br/>prod/mysql-secret)]
        IAMQ[IAM role: ESO qa<br/>reads qa/mysql-secret only]
        IAMP[IAM role: ESO prod<br/>reads prod/mysql-secret only]
        IAMB[IAM role: kyc-app<br/>bedrock:InvokeModel on two profiles only]
        SMQ --- IAMQ
        SMP --- IAMP
    end
    subgraph K8S[Single EKS cluster]
        ESO[External Secrets Operator]
        subgraph QA[qa namespace]
            SAQ[ServiceAccount, IRSA] --> SSQ[SecretStore] --> ESQ[ExternalSecret] --> KSQ[K8s Secret mysql-secret]
            KSQ -->|envFrom| QAPODS[App and MySQL pods]
            SAA[ServiceAccount kyc-app, IRSA] --> QAPODS
        end
        subgraph PROD[prod namespace]
            SAP[ServiceAccount, IRSA] --> SSP[SecretStore] --> ESP[ExternalSecret] --> KSP[K8s Secret mysql-secret]
            KSP -->|envFrom| PRODPODS[App and MySQL pods]
        end
        ESO --> SSQ
        ESO --> SSP
    end
    IAMQ -. AssumeRoleWithWebIdentity .-> SAQ
    IAMP -. AssumeRoleWithWebIdentity .-> SAP
    IAMB -. AssumeRoleWithWebIdentity .-> SAA
```

Terraform creates the secret shell and the IAM roles but never the password values, which are set out-of-band so they never land in Terraform state. **Secret values are write-once:** MySQL reads its passwords only on first start, so overwriting a value later breaks the next app pod. The recovery and rotation procedures are in [terraform/README.md](terraform/README.md). Images are pulled from ECR using the node group's IAM role, so no image pull secret exists.

### Observability

```mermaid
flowchart TD
    W[KYC service pods and MySQL]
    W -->|JSON logs, no field values| ALLOY[Grafana Alloy] --> LOKI[(Loki)] --> G[Grafana]
    W -->|OTLP traces: IDs, model, token counts| TEMPO[(Tempo)] --> G
    W -->|"/metrics"| PROM[(Prometheus)] --> G
    G --> ENG([DevOps or on-call engineer])
```

Prometheus does not scrape `/metrics` yet because no ServiceMonitor exists (see Known gaps).

### Using Grafana

Grafana is deliberately not exposed to the internet. You reach it from your own machine through a port-forward, which tunnels
`localhost` to the Grafana pod in the cluster. You need `kubectl` pointed at the cluster
(`aws eks update-kubeconfig --name devsecops-eks --region ap-south-1` once) and your AWS credentials set.

**1. Get the admin password.** The chart generates a random one when it is installed. It is stored only in the cluster
(never in Terraform or Git), so read it from the Kubernetes Secret:

```bash
kubectl get secret kube-prometheus-stack-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

**2. Open the tunnel.** Leave this running in its own terminal (stop it with Ctrl+C):

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
```

If port 3000 is already in use, pick another local port, for example `3001:80`, and browse to that port instead.

**3. Log in.** Browse to <http://localhost:3000>. Username `admin`, password from step 1.

**4. Where to look**

| What | Where in Grafana | Try |
|------|------------------|-----|
| Logs (Loki) | Explore, data source **Loki** | `{namespace="qa"}` or `{namespace="prod", app="nodejs-app"}`. Add `\|= "error"` to filter. |
| Metrics (Prometheus) | Explore, data source **Prometheus** | `sum by (namespace) (container_memory_working_set_bytes)` |
| Dashboards | Dashboards, then browse | **Kubernetes / Compute Resources / Namespace (Pods)** (pick `qa` or `prod`), **Kubernetes / Compute Resources / Cluster**, **Node Exporter / Nodes** |
| Traces (Tempo) | Explore, data source **Tempo** | Search by service `kyc-document-intelligence`. Each upload shows the HTTP request and the Bedrock call (model, tokens, latency; no personal data). |

Retention is 15 days for logs, metrics and traces. Data lives on `gp3` volumes, so it survives pod restarts and node replacement. The
volumes were created on `ebs-sc-retain`, then their reclaim policy was patched to `Delete`, so destroying the stack also removes them.

**Other consoles (optional)**, each in its own terminal:

```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090     # Prometheus: http://localhost:9090
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093   # Alertmanager: http://localhost:9093
```

**If you forget or want to change the password.** Reading the Secret (step 1) always shows the current generated password.
To set your own, run the following once. It changes it inside Grafana's database; the Secret keeps showing the original
generated value, so note the new one yourself:

```bash
kubectl exec -n monitoring deploy/kube-prometheus-stack-grafana -c grafana -- grafana cli admin reset-admin-password '<new-password>'
```

**If a page is empty or the login fails:**
- Check the pods are running: `kubectl get pods -n monitoring` (everything should be `Running`).
- Logs missing: `kubectl logs -n monitoring deploy/alloy -c alloy --tail=50` should show no `level=error` lines.
- Password rejected: re-read it from the Secret; do not trust an old copy, because reinstalling the chart can generate a new one.

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
    A([Merge to qa]) --> B[Gitleaks<br/>secret detection, hard gate]
    B --> C1[Checkov: Terraform]
    B --> C2[Checkov: Kubernetes]
    B --> C3[Checkov: Dockerfile]
    B --> C4[Trivy FS: app]
    C1 & C2 & C3 & C4 --> D1[Lint: ruff]
    C1 & C2 & C3 & C4 --> D2[Tests: pytest]
    D1 & D2 --> E[SonarCloud<br/>quality gate]
    E --> G[Docker build<br/>tag = git SHA]
    G --> H1[Trivy image scan]
    G --> H2[SBOM generation]
    H1 & H2 --> I[Push to Amazon ECR<br/>qa only, via OIDC role]
    I --> K[Deploy to EKS qa namespace<br/>kubectl apply, wait for rollout]
    K --> J[Commit deployed tag back to qa<br/>kustomization.yaml newTag]
    J --> L{Manual QA<br/>and sign-off}
    L -->|bugs found| M[bugfix branch] --> A
    L -->|approved| N([PR: qa to main])
```

### Production pipeline (on merge to `main`)

Continuous delivery only: nothing is rebuilt, rescanned or retested.

```mermaid
flowchart LR
    A([Merge to main]) --> B[Read QA-built SHA<br/>from qa kustomization.yaml]
    B --> C{{Approval gate<br/>GitHub Environment prod}}
    C --> D[Retag image in ECR<br/>sha to prod-sha, same digest]
    D --> E[Deploy to EKS prod namespace<br/>via prod OIDC role]
    E --> F[Wait for rollout]
    F --> G([Live in production])
```

The approval screen shows exactly which QA image is being promoted. The prod role can only retag in ECR and deploy to the `prod` namespace.

Images live in a private ECR repository in the same region as EKS. QA builds are tagged with the git SHA; promotion retags the same image as `prod-<sha>`, so prod runs the exact bytes that passed QA.

Principles: security at every stage, **build once and promote the artifact**, immutable SHA-tagged images (never `latest`), parallel jobs for speed, human-approved promotion to prod.

## Environments and Access

Two environments, `qa` and `prod`, run as separate namespaces on a single EKS cluster to keep costs down. Isolation comes from namespaces, resource quotas and separate IAM deployer roles, each mapped to its own namespace through EKS access entries. All resources live in `ap-south-1`. Disaster recovery is provisioned on demand from the Terraform code rather than kept running.

```mermaid
flowchart LR
    GH[GitHub Actions] -->|OIDC| RA[IAM Role A<br/>QA deployer]
    GH -->|OIDC + approval| RB[IAM Role B<br/>PROD deployer]
    RA -->|push images| ECR[(Amazon ECR)]
    RB -->|retag sha to prod-sha| ECR
    subgraph EKS[Single EKS cluster]
        NQ[qa namespace]
        NP[prod namespace]
    end
    RA -->|access entry: qa only| NQ
    RB -->|access entry: prod only| NP
    ECR -. image pull via node role .-> EKS
```

The QA and prod pipelines never share an IAM role, and the QA role has no permissions on the `prod` namespace. Because both environments share one cluster, they also share the control plane and nodes. If stronger isolation is needed later, prod can move to its own cluster without changing the pipeline design.

## Infrastructure as Code (Terraform)

AWS resources, cluster add-ons and namespaces are provisioned with Terraform. The application manifests in `k8-manifests/` are deployed by the pipeline. QA is built first, and prod reuses the same environment module with different inputs.

```mermaid
flowchart TD
    B[bootstrap<br/>S3 state bucket, created once] --> P
    P[platform stack<br/>VPC + single NAT, EKS 1.36, EBS CSI,<br/>ECR, GitHub OIDC provider, ACM certificate] --> A
    A[addons stack<br/>ALB controller, External Secrets Operator,<br/>StorageClasses] --> O
    A --> Q
    A --> R
    O[observability stack<br/>Prometheus, Loki, Tempo, Alloy, Grafana]
    Q[envs/qa<br/>app-env module: namespace, ESO role,<br/>secret shell, Bedrock role, deploy role + access entry]
    R[envs/prod<br/>same module, prod inputs]
    Z[(Existing Route 53 hosted zone<br/>referenced as data source)] -.-> P
```

Each stack has its own remote state in S3 with native locking, so qa and prod can be applied or destroyed independently of each other and of the shared platform. `terraform destroy` only removes what Terraform created. The hosted zone is a data source and is never touched. The runbook (apply order, pause and resume, secret rotation, destroy safety) is in [terraform/README.md](terraform/README.md).

### Manual DNS step (one-time per hostname)

The ALB is created by the AWS Load Balancer Controller when the first Ingress is applied, so its address is only known after the first deploy. After that:

1. Find the ALB DNS name: `kubectl get ingress -n qa` (the `ADDRESS` column; the shared ALB serves both environments).
2. In the Route 53 hosted zone for `bolarbrijesh.com`, create an **A record with Alias enabled** for each hostname (`qa-proj3-aigateway.bolarbrijesh.com`, `proj3-aigateway.bolarbrijesh.com`), pointing at that ALB (region `ap-south-1`).

The ALB keeps its address as long as the Ingress group exists. If the ALB is deleted and recreated, update the alias records.

## Extending to More Environments (dev, ppd)

Only `qa` and `prod` are in scope today. The pipelines are driven by per-environment configuration, so adding `dev` or `ppd` does not require restructuring:

1. **Namespace and manifests:** copy `k8-manifests/qa/` to `k8-manifests/<env>/` and adjust namespace, replicas, resources and host. The shared ALB group and certificate discovery mean no per-environment ALB or certificate ARN is needed, as long as the ACM certificate covers the new hostname.
2. **Environment config:** add the environment's values (namespace, cluster name, IAM role ARN, host, ECR repo) as GitHub Environment variables or a workflow matrix entry instead of hardcoding them.
3. **Branch mapping:** decide which branch deploys to it and add that trigger to the workflow.
4. **AWS access:** instantiate the `app-env` module for the new environment. Never give a non-prod role access to `prod`.
5. **Secrets:** each environment gets its own Secrets Manager entry (`<env>/mysql-secret`) through that module.
6. **DNS and TLS:** add the hostname to the ACM certificate's SANs and create a one-time alias record to the shared ALB.
7. **Approvals:** add a GitHub Environment with required reviewers if the environment should be gated.

## Evaluation

Accuracy is measured on a **golden set of 18 synthetic, watermarked SPECIMEN documents**: 10 ID cards and 8 proofs of address, some degraded and some as PDFs, generated from a fixed seed and committed in `app/eval/golden/` with their labels. The runner sends each one through the real extraction code and reports, per model (Haiku 4.5 and Sonnet 5):

- **Field accuracy** and **document accuracy** (all fields right)
- **Accuracy of fields passed without review**: how right the unflagged fields are
- **Wrong fields caught by the review flag**: the rate at which mistakes were flagged
- Breakdowns by difficulty, document type and field, plus latency and token counts

**Results: none yet.** The run needs Bedrock quota, which is zero today. When the quota is approved, the run is:

```bash
cd app && .venv/bin/python -m eval.run --models haiku --limit 1   # one document first
.venv/bin/python -m eval.run                                       # then the full comparison
```

It writes `app/eval/results/RESULTS.md`, which will be committed and summarized here. With 18 documents the numbers will be illustrative, not statistical. Details are in [app/eval/README.md](app/eval/README.md).

## Repository Layout

```
CLAUDE.md                Rules, decisions and the app contract for Claude Code
app/
  kyc/                   FastAPI service (extraction, validation, storage, PII-safe logging, review page)
  tests/                 pytest suite (no AWS or MySQL needed)
  eval/                  Golden set generator, scoring and the Haiku vs Sonnet accuracy runner
Dockerfile               Multi-stage Python image; non-root (UID 10001), port 5000
sonar-project.properties SonarCloud project config
k8-manifests/
  qa/                    App, MySQL, SecretStore and ExternalSecret, Ingress (qa namespace), kustomization.yaml
  prod/                  Same for the prod namespace (2 replicas, retained storage)
.github/workflows/       QA and prod pipelines (GitHub Actions)
terraform/               AWS infrastructure (see terraform/README.md)
  bootstrap/             S3 state bucket
  platform/              VPC, EKS, ECR, OIDC provider, ACM certificate
  addons/                ALB controller, ESO, StorageClasses
  observability/         Prometheus, Loki, Tempo, Alloy, Grafana
  modules/app-env/       Per-environment module: namespace, quota, secret shell, ESO and Bedrock roles, deploy role
  envs/qa, envs/prod/    Environment instantiations
```

## Local Development

Run the tests and the linter (no AWS or MySQL needed):

```bash
cd app && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest && .venv/bin/ruff check .
```

Run the service against real Bedrock with a local SQLite database (needs AWS credentials with Bedrock access and a quota for the model):

```bash
KYC_DATABASE_URL="sqlite+pysqlite:///kyc-local.db" AWS_REGION=ap-south-1 \
  .venv/bin/uvicorn kyc.main:get_app --factory --port 5000
```

Then open <http://localhost:5000/ui> (or `/docs`). Use the synthetic documents in `app/eval/golden/` and never real personal documents.

Settings (environment variables): `PORT`, `AWS_REGION`, `BEDROCK_MODEL_ID` (default `in.anthropic.claude-haiku-4-5-20251001-v1:0`), `CONFIDENCE_THRESHOLD` (0.85), `MAX_UPLOAD_BYTES`, `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (or `KYC_DATABASE_URL`), `KYC_API_KEY` (optional), `OTEL_EXPORTER_OTLP_ENDPOINT` (optional), `LOG_LEVEL`.

Container image:

```bash
docker build -t nodejs-app .
```

The image, ECR repository and Deployment are still named `nodejs-app`, from the sample app this service replaced, so the pipeline needed no changes.

## Prerequisites

- **To develop:** Python 3.12 and Docker.
- **For live extraction:** an AWS account with Amazon Bedrock access to Claude Haiku 4.5 and a non-zero quota (see Known gaps).
- **To deploy:** an AWS account (region `ap-south-1`) and credentials to apply the Terraform stacks once, a registered domain with a Route 53 hosted zone, a GitHub repository with Actions, a SonarCloud project, Terraform 1.10 or later, `kubectl` and the AWS CLI. After the first apply, the pipeline uses OIDC only.

## Known gaps

- **Bedrock quota:** every Anthropic per-minute quota in this account is 0 (new-account default), so the deployed service returns 502 on uploads and the evaluation cannot run. Increases for Haiku 4.5 are requested; the Sonnet 5 request still needs a retry.
- **API key is off:** the service supports `X-API-Key`, but the manifests do not set it yet, so `/ui` and the API are open on the public hostnames. That is acceptable only while the quota is zero and only synthetic documents are used. It must be enabled before the first real upload.
- **Scanners report, they do not block:** `ENFORCE_SCANS` is off, so Checkov and Trivy only report today. Gitleaks is a hard gate. The Sonar quality gate blocks only once enforcement is on.
- **Not yet in place:** NetworkPolicies, PodDisruptionBudgets, and a ServiceMonitor so Prometheus scrapes `/metrics`.
- **Shared blast radius:** `qa` and `prod` share one cluster, one ALB and two nodes. This is a cost decision, and the isolation boundary is IAM plus namespace RBAC.
- **Branch protection is deferred:** `qa` may only block force-push and deletion, because the pipeline's bot commits the deployed tag to it.
- **Region and data-residency note:** the write-up on why `ap-south-1`, and what changes for a UAE bank, is pending the evaluation results.

## Roadmap

| Step | Scope | Status |
|------|-------|--------|
| Platform | EKS, ALB, ACM, secrets, QA and prod pipelines, observability | done, live |
| KYC service | Extraction API, per-field confidence, PII-safe logs and traces, review page | done, deployed |
| Accuracy evaluation | Golden set and runner built; numbers pending | waiting on Bedrock quota |
| API key | `<env>/kyc-api-key` secret, ExternalSecret and a required env var | next, before any real upload |
| Region note | Region choice and UAE data-residency changes, with the eval results | pending |
| Hardening | Enforce scanners, NetworkPolicies, ServiceMonitor, branch protection | deferred |
