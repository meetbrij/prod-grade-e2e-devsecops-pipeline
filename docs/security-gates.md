# Security gates: what blocks the pipeline, and what is parked

Decision record for the QA pipeline's scanners (`.github/workflows/qa-cicd.yml`). Read this before turning a gate on or off, suppressing a finding, or adding a scanner.

## Current state

`ENFORCE_SCANS` is `"true"` (set in the workflow's top-level `env:`). With it on:

| Gate | Job | Blocks the run when | Notes |
|---|---|---|---|
| Gitleaks | `gitleaks-scan` | any secret is found in the full git history | Always blocking, independent of the flag |
| Checkov Kubernetes | `checkov-kubernetes` | a check fails on `k8-manifests/` | Skips are annotations in the manifests |
| Checkov Dockerfile | `checkov-dockerfile` | a check fails on `Dockerfile` | No suppressions needed |
| Checkov Terraform | `checkov-terraform` | a check fails on `terraform/` | Skips are inline comments in the `.tf` files |
| Trivy FS | `trivy-fs` | a HIGH or CRITICAL **fixable** vulnerability in `app/` dependencies | `--ignore-unfixed` |
| Trivy image | `trivy-image` | a HIGH or CRITICAL **fixable** vulnerability in the built image | `--ignore-unfixed` |
| SonarCloud | `sonarcloud` | the quality gate on new code fails (`-Dsonar.qualitygate.wait=true`) | New code only, so older findings do not block |
| Lint and tests | `lint`, `test` | `ruff check .` or `pytest` fails | Always blocking |

The SBOM job only generates an inventory and never blocks.

## How the flag works

`ENFORCE_SCANS` is read by the Checkov steps (`--soft-fail` is added only when it is not `"true"`), by both Trivy steps (`--exit-code 1` only when it is `"true"`) and by the Sonar step (`-Dsonar.qualitygate.wait`). One line controls all of them.

- **Turn blocking off (emergency or while onboarding something new):** change `ENFORCE_SCANS` to `"false"` in `qa-cicd.yml` through a PR. Findings are still reported in the job summary and the uploaded artifacts, they just do not fail the run. Turn it back on in the next PR. Do not leave it off.
- **Turn it on again:** set it to `"true"`, but first run the local check at the bottom of this page, or the first run will fail.

## Why `--ignore-unfixed`

The image is built on `python:3.12-slim` (Debian). On the day blocking was enabled, the image scan reported 44 HIGH findings, all in Debian base packages (util-linux, ncurses, libsystemd, perl-base and similar), and **none had a fixed version**. Failing the pipeline on a vulnerability that cannot be patched only teaches people to disable the gate. With `--ignore-unfixed` the gate blocks as soon as a fix exists, and the fix is then to rebuild on a patched base image or bump the dependency. The unfixed findings are still visible if you run Trivy without the flag.

## Suppressions (all deliberate, each with a reason next to the code)

A suppression must always carry its reason in the same place as the skip. Never skip a check silently.

**Kubernetes** (`k8-manifests/{qa,prod}/*.yaml`, `checkov.io/skipN` annotations)

| Check | Where | Reason |
|---|---|---|
| CKV_K8S_14 | app Deployment | The image tag is the git SHA, injected by kustomize at deploy time; the committed name is a placeholder |
| CKV_K8S_43 | app Deployment, MySQL | Images are promoted by immutable SHA tag (ECR tags are immutable); a digest would break retag promotion. MySQL is pinned to a version tag |
| CKV_K8S_15 | MySQL | The image is pinned to a version tag, so the default pull policy is acceptable |
| CKV_K8S_35 | app, MySQL | Secrets arrive through External Secrets `envFrom`; mounting them as files is a later hardening item |
| CKV_K8S_22 | MySQL | The official mysql image writes to its root filesystem; data lives on the PVC. (The app container does use a read-only root filesystem) |
| CKV_K8S_40 | MySQL | Runs as UID 999, the mysql user of the official image; data directory ownership depends on it |
| CKV2_K8S_6 | app, MySQL | No NetworkPolicy yet. **Parked, see below** |

**Terraform** (`#checkov:skip=` comments inside the resource or module block)

| Check | Where | Reason |
|---|---|---|
| CKV_AWS_149 | app-env secret | Default AWS-managed key is enough; a customer-managed KMS key adds cost |
| CKV2_AWS_57 | app-env secret | The secret is write-once: MySQL reads it only at first start, so automatic rotation would break the app |
| CKV_AWS_136 | ECR repository | AES256 encryption is on; a customer-managed key is parked |
| CKV_TF_1 | `eks`, `vpc` modules | Public registry modules pinned by version constraint; commit-hash pinning is parked |
| CKV_AWS_18, 144, 2_AWS_62 | state bucket | Access logging, cross-region replication and event notifications are not worth it for a single-user state bucket; CloudTrail records the API calls |
| CKV_AWS_145 | state bucket | SSE-S3 encryption is on; a customer-managed key is parked |

## Parked for later

- **NetworkPolicies** (CKV2_K8S_6). The right fix, but a wrong policy can cut off MySQL or the ALB. Add a default-deny policy per namespace plus allow rules (ALB to app, app to MySQL, app to the internet for Bedrock, Prometheus scrape), test in QA first, then remove the `CKV2_K8S_6` skips.
- **Secrets as files** instead of env vars (CKV_K8S_35), **image digests** (CKV_K8S_43), a **customer-managed KMS key** for ECR, Secrets Manager and the state bucket, and **commit-hash pinning** of Terraform modules.
- **Semgrep, cosign image signing and Kyverno admission enforcement** were considered and skipped on purpose.
- Branch protection is applied (see CLAUDE.md); required status checks on `qa` are still not possible because the pipeline's bot pushes the deployed tag to it.

## When a gate blocks a merge

1. Open the failed job's summary or download its report artifact (`checkov-*-report`, `trivy-*-report`).
2. **Real finding:** fix it. For a Trivy finding that has a fix, bump the dependency in `app/requirements.txt` (and rebuild) or move to a patched base image.
3. **Accepted risk:** add a suppression next to the code with a written reason, and add a row to the tables above in the same PR.
4. **Only if the pipeline must ship now:** set `ENFORCE_SCANS` to `"false"` in its own PR, ship, then restore it and fix the finding. Record why in the PR.

## Check locally before turning gates on or after changing a scanner

These match the versions used in CI. Run from the repo root with Docker running.

```bash
docker run --rm -v "$PWD:/src:ro" bridgecrew/checkov:3.2.531 -d /src/k8-manifests --framework kubernetes --compact --quiet
docker run --rm -v "$PWD:/src:ro" bridgecrew/checkov:3.2.531 -d /src/terraform --framework terraform --skip-path .terraform --compact --quiet
docker run --rm -v "$PWD:/src:ro" bridgecrew/checkov:3.2.531 -f /src/Dockerfile --framework dockerfile --compact --quiet
docker run --rm -v "$PWD:/src:ro" -w /src aquasec/trivy:0.57.1 fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 app
```

Each should report `Failed checks: 0` or exit 0. For the image scan, build it (`docker build -t kyc-scan:local .`, then `docker save kyc-scan:local -o img.tar`) and run `trivy image --input img.tar --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`.
