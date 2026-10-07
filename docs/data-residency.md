# Data residency: how the model provider is chosen

The service can answer through two providers, selected by one setting, `LLM_PROVIDER`. This page explains why the project supports both, what each one means for where a document goes, and what to change for a bank with residency requirements.

## The short version

| | `bedrock` (default in code) | `anthropic` (current demo setting) |
|---|---|---|
| Where the document goes | Amazon Bedrock in your own AWS account, in `ap-south-1` | The Anthropic API, outside AWS |
| Where inference runs | With an `in.` inference profile, only `ap-south-1` and `ap-south-2` (India) | Anthropic's infrastructure, location not under your control |
| How the service authenticates | IRSA, no secret at all | An API key in Secrets Manager, synced by External Secrets |
| What you need | Bedrock model access and a non-zero quota | An API key and prepaid credit |
| Fit for real customer documents | Yes, subject to your own compliance review | **No.** Synthetic documents only |

The demo runs on `anthropic` because the Bedrock quota for this AWS account is zero and could not be raised in time. **That is a temporary demo choice, not an architecture decision.** The platform is built for Bedrock: the IAM role, the India-only inference profiles and the Terraform for them are in place in both environments.

## Switching providers

It is a configuration change, with no code change and no rebuild:

1. In `k8-manifests/<env>/app-deployment.yaml`, set `LLM_PROVIDER` to `bedrock` (the Bedrock model ID and region are already set there).
2. Merge through the normal pipeline. The pods restart and use Bedrock through their IRSA role.
3. Optionally delete the `llm-api-key` secret afterwards. With `bedrock` selected nothing reads it.

The service refuses to start with an unknown provider, or with `anthropic` selected and no key, so a half-configured switch fails at once instead of silently falling back.

## What stays identical across providers

The same system prompt, the same forced tool schema, the same validation and the same confidence scoring. Only the transport differs, so accuracy results measured on one provider carry over, and both write the model ID into the stored record so a result can be traced to the model that produced it. The evaluation harness takes `--provider bedrock|anthropic` for the same reason.

## What changes for a bank with residency requirements

**Do not use the `anthropic` provider.** Documents would leave your AWS account and the country. Use Bedrock and decide where inference may run:

1. **Pick the Region that matches the requirement.** This project uses `ap-south-1`. A UAE bank would deploy in `me-central-1` (UAE), where Amazon Bedrock is available.
2. **Check what the inference profile guarantees.** The `in.` profiles used here keep inference in two Indian Regions. According to AWS's announcement, Claude models in the Middle East (UAE and Bahrain) are offered through **global** cross-Region inference, which can route a request to any supported Region worldwide. AWS states that customer data is not stored in the destination Region, but processing is not confined to the UAE. Whether that satisfies a given regulator or contract is a compliance decision. Confirm the current options with AWS before committing, because model and Region availability changes.
3. **If processing must stay in the country,** the choices narrow: an in-Region model offered in that Region, or a model hosted in the bank's own environment. Both are a different engineering effort from flipping a flag, and neither is built here.
4. **Keep everything else in-region too.** Stored fields in MySQL, logs in Loki and traces in Tempo stay in the cluster's Region. The service already avoids storing uploaded files and keeps personal values out of logs and traces.
5. **Re-run the accuracy evaluation** on the model that will actually be deployed, with documents representative of the bank's population. The results in this repository come from synthetic documents and say nothing about real-world accuracy.

Under UAE data-protection rules and central-bank guidance, the details of what is permitted (cross-border transfer, outsourcing, model governance) belong to the bank's compliance and legal teams. This page records engineering options and does not claim compliance.

## Honest limits

- The `anthropic` demo route sends documents to a third party. It is acceptable here only because every document is synthetic and watermarked `SPECIMEN`.
- The `bedrock` route has not run end to end in this account yet because of the quota, so its accuracy and latency are not measured here.
- No claim in this repository is a compliance attestation.

Back to the [documentation index](README.md).
