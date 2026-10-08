# Decision log

The choices behind this project, with the reason and what each one costs. Most are cost or simplicity decisions made on purpose. When a trade-off stops being acceptable, the last column says what would change it. The main README lists the same items in short form under "Known gaps and trade-offs".

## Platform

| Decision | Why | What it costs | Revisit when |
|---|---|---|---|
| **One EKS cluster, two namespaces** (`qa`, `prod`) | An EKS control plane costs about 73 USD per month; a second one would nearly double the fixed cost | qa and prod share the control plane, nodes and blast radius. Isolation is IAM, EKS access entries, namespace RBAC and quotas | Real production traffic, or a compliance need for hard isolation |
| **One shared ALB** for both environments (Ingress group, host-based rules) | An ALB costs about 18 USD per month plus usage | One ALB failure or misconfiguration affects both hostnames | Same trigger as above |
| **A single NAT gateway** | About 35 USD per month instead of one per zone | If zone `ap-south-1a` fails, nodes in `ap-south-1b` lose outbound internet | Production use |
| **Two `t3a.large` nodes shared by two projects** | Keeps the fixed cost low | CPU requests leave thin headroom, and zone-pinned MySQL disks mean a full node in the wrong zone blocks a database after a restart | A third node, or trimmed requests |
| **Public EKS API endpoint** open to `0.0.0.0/0` | GitHub-hosted runners have no fixed IP addresses | The API is reachable from the internet; access relies on IAM and access entries | Self-hosted runners with fixed IPs, or a private endpoint with a VPN |
| **Region `ap-south-1`** for everything | Closest region with Bedrock Claude through India-only inference profiles | All data stays in India, which is not a UAE region (see [data residency](#data-residency) below) | A UAE deployment |
| **Manual Route 53 alias records**, no ExternalDNS | Two hostnames, set once; the zone is shared with other projects | If the ALB is ever recreated the aliases must be updated by hand | More hostnames or frequent ALB changes |
| **No certificate ARN in manifests**; the ALB controller discovers the ACM certificate by hostname | No account-specific value in a public repo | The certificate must cover the hostnames or discovery silently falls back | n/a |
| **Terraform applied by hand**; the pipeline deploys only manifests | Infrastructure changes are rare and worth reading before applying | No automated plan on PR | More contributors |
| **S3 state with native locking**, no DynamoDB table | Terraform 1.10 or later supports `use_lockfile`; one less resource | Needs Terraform 1.10+ | n/a |

## Pipeline and security

| Decision | Why | What it costs | Revisit when |
|---|---|---|---|
| **Build once, promote the artifact**: prod retags the QA image in ECR | Prod runs the exact bytes that passed QA, with no rebuild and no rescan | The prod pipeline trusts the QA pipeline's checks | n/a |
| **No static AWS keys anywhere**: GitHub OIDC, IRSA | Nothing long-lived to leak | Trust policies must match GitHub's `sub` claim format exactly | n/a |
| **Image, ECR repository and Deployment still named `nodejs-app`** | They were named for the sample app this project replaced; renaming touches the pipeline, Terraform and manifests | A misleading name | A deliberate rename PR |
| **Scanners block** (`ENFORCE_SCANS` on) with justified suppressions and `--ignore-unfixed` | Findings must stop a release, but a CVE with no available fix cannot be fixed by anyone | A newly disclosed unfixed CVE is not caught until a fix exists | See [security-gates.md](security-gates.md) |
| **No NetworkPolicies yet** | A wrong policy can cut off MySQL or the ALB; parked until tested in QA | Any pod can reach any other pod | Before real data |
| **Branch protection light on `qa`**: force-push and deletion blocked, no PR requirement | The pipeline's bot commits the deployed tag to `qa` | Anyone with write access can push straight to `qa` | A ruleset that lets the `github-actions` app bypass a PR rule |
| **Skipped: Semgrep, cosign image signing, Kyverno** | Optional hardening; not needed for a working pipeline | No signature verification at admission | Real supply-chain requirements |
| **Docs-only changes skip the pipeline** | No build, scan and redeploy for a Markdown edit | A secret committed in a docs-only change is only caught by the next full run | See [security-gates.md](security-gates.md) |

## Secrets

| Decision | Why | What it costs |
|---|---|---|
| **Secret values are set by hand, once**; Terraform creates only the empty container | Values in Terraform would end up in state | A manual step per environment |
| **Secret values are write-once** | MySQL reads its passwords only on first start with an empty volume | Rotation needs `ALTER USER` first (see the [runbook](runbook.md#secrets)) |
| **One IAM role and service account per environment** for External Secrets | The qa role can never read the prod secret | More roles to manage |
| **`X-API-Key` required on the KYC service**, from `<env>/kyc-api-key`; the pod will not start without it | The public endpoint spends real money once a model key exists | Clients and the review page must send the key; rotation is by hand |

## The KYC service

| Decision | Why | What it costs |
|---|---|---|
| **Uploaded files are never stored**; only a SHA-256 hash, the fields and the scores | Minimizes personal data held | A document cannot be re-processed or re-inspected later |
| **A provider switch (`LLM_PROVIDER`): Anthropic API for the demo, Bedrock for residency** | The Bedrock quota for this account is zero and could not be raised in time. Both providers share the prompt, schema and scoring, so switching is one setting | The demo sends synthetic documents to a third party; Bedrock is not yet exercised end to end. See [data-residency.md](data-residency.md) |
| **India-only `in.` inference profiles**, never `global.` | Inference stays in `ap-south-1` and `ap-south-2` | Fewer regions to absorb load; separate quotas |
| **Sonnet 5 for the deployed demo; Haiku 4.5 as the code default** | The eval on 18 synthetic documents measured 99.0% field accuracy for Sonnet 5 against 92.0% for Haiku 4.5, with about the same latency | Sonnet costs more per token (check current pricing). Switching back is the `ANTHROPIC_MODEL` setting. The Bedrock model setting (`BEDROCK_MODEL_ID`) is separate and still points at Haiku, because the Bedrock quota requests were made for it |
| **Minimal review workflow**: flag, then confirm or correct a field | Enough to show human-in-the-loop | No assignment, audit trail or queue prioritization |
| **Document content is untrusted**: the prompt says to ignore instructions inside documents, and the page renders values as text only | Prompt injection and XSS through uploaded files | Not a guarantee; the eval does not test adversarial documents yet |
| **A built-in review page** instead of a separate frontend | One container, no build step | Basic, no authentication beyond the optional API key |

## Observability

| Decision | Why | What it costs |
|---|---|---|
| **Grafana Alloy instead of Promtail** | Promtail reached end-of-life on 2026-03-02 | n/a |
| **Single-instance Loki and Tempo on EBS** | Simple and cheap | One pod failure means a gap in logs or traces; no S3 backend |
| **Grafana reached by port-forward**, not exposed | No public surface | Only people with cluster access can look |
| **No Alertmanager receivers**, no ServiceMonitor yet | Notifications and `/metrics` scraping are not wired up | Nobody is alerted; the app's own metrics are not collected |
| **15 day retention** | Enough for debugging | Older data is gone |

## Data residency

See [data-residency.md](data-residency.md) for the provider switch, why the demo uses the Anthropic API, and what changes for a bank with residency requirements.

Back to the [documentation index](README.md).
