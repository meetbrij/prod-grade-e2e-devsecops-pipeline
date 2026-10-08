# Troubleshooting

Problems this project has actually hit, each with the symptom, the cause and the fix. For routine operations see the [runbook](runbook.md).

| Symptom | Section |
|---|---|
| Deploy job: `Not authorized to perform sts:AssumeRoleWithWebIdentity` | [GitHub OIDC](#github-actions-cannot-assume-the-aws-role) |
| Deploy job: `forbidden` on `externalsecrets` or `secretstores` | [External Secrets permissions](#deploy-forbidden-on-externalsecrets) |
| App pod: `Access denied for user` | [Overwritten secret](#app-pod-fails-with-access-denied) |
| Uploads return 502, or `eval.run` shows `ThrottlingException` | [Bedrock quota](#uploads-return-502-or-the-eval-throttles) |
| Uploads return 401 | [API key](#uploads-or-the-review-page-return-401) |
| New pod stuck in `CreateContainerConfigError` | [Missing secret](#new-pod-stuck-in-createcontainerconfigerror) |
| Pod exits at start with `ANTHROPIC_API_KEY is required` | [Provider config](#pod-exits-at-start-with-anthropic_api_key-is-required) |
| A scanner job fails the pipeline | [Scanner gates](#a-scanner-job-fails-the-pipeline) |
| Terraform: `the server has asked for the client to provide credentials` | [Expired token](#terraform-apply-fails-midway-with-client-credentials) |
| A Helm release is stuck `pending-install` | [Stuck Helm release](#a-helm-release-is-stuck-in-pending-install) |
| Both sites return 503 | [Paused cluster](#both-sites-return-503) |
| `mysql-0` stays Pending after a restart; the app crash-loops | [CPU and zone](#mysql-0-stays-pending-after-a-restart) |
| The prod URL does not load | [Wrong hostname](#the-prod-url-does-not-load) |
| QA deploy job times out at the rollout | [Rollout timeout](#the-qa-deploy-job-times-out-at-the-rollout) |
| Grafana is empty or the login fails | [Grafana](../README.md#using-grafana) |

## GitHub Actions cannot assume the AWS role

**Symptom:** `Not authorized to perform sts:AssumeRoleWithWebIdentity`.

**Cause:** GitHub now issues OIDC subjects with immutable IDs, for example `repo:<owner>@<ownerId>/<repo>@<repoId>:ref:refs/heads/qa`, not `repo:owner/repo:...`. A trust policy written in the old form no longer matches. A job that uses a GitHub Environment presents `environment:prod` instead of a branch subject.

**Fix:** the trust policies use the ID form through the `github_repository_claim` variable in `envs/qa` and `envs/prod`. If it fails again, print the real `sub` claim from a run's token and compare it with the role's trust policy. The QA role must trust `refs/heads/qa` and the prod role `environment:prod`.

## Deploy forbidden on externalsecrets

**Symptom:** `kubectl apply` fails with `forbidden` on `externalsecrets` or `secretstores` in the deploy job.

**Cause:** the EKS `AmazonEKSEditPolicy` does not cover custom resources.

**Fix:** already in place. The access entry maps the deploy role to the Kubernetes group `<env>-deployers`, and a namespaced Role and RoleBinding from the `app-env` module grant that group only those two resources in its own namespace. If this reappears, check that `envs/<env>` was applied.

## App pod fails with Access denied

**Symptom:** a new app pod crash-loops with `Access denied for user 'appuser'`, while the old pod keeps working.

**Cause:** the secret `<env>/mysql-secret` was overwritten after MySQL first started. MySQL ignores later changes, but External Secrets copies the new value into the cluster.

**Fix:** move the previous secret version back and force a sync, as in the [runbook](runbook.md#recover-from-an-overwritten-secret). Never run the "set secret values" command twice.

## Uploads return 502 or the eval throttles

**Symptom:** `POST /documents` returns 502, or `python -m eval.run` prints `ERROR bedrock call failed: ThrottlingException` for every document.

**Cause:** the Bedrock per-minute quota for the model is 0 in this account (the new-account default). The `in.` profiles use the plain "Cross-region model inference" quotas, not the "Global cross-region" ones.

**Fix:** check the applied values, in `ap-south-1`:

```bash
aws service-quotas get-service-quota --region ap-south-1 --service-code bedrock --quota-code L-58BE175A --query Quota.Value
```

Codes: `L-CCA5DF70` Haiku 4.5 requests per minute, `L-58BE175A` Haiku 4.5 tokens per minute, `L-D4FBCF4E` Sonnet 5 tokens per minute. A request with status `CASE_OPENED` is waiting on an AWS support case, not approved. Make sure you look at `ap-south-1`. Other error codes name the cause: `AccessDeniedException` means the IAM policy or the model access, `ValidationException` usually a wrong model or profile ID.

## Uploads or the review page return 401

**Cause:** the service requires `X-API-Key`. The review page has a key field (kept only in the browser's session storage); API clients send the header.

**Fix:** read the key (see the [runbook](runbook.md#the-kyc-service-keys-and-the-model-provider)) and enter it in the page or send `-H "X-API-Key: <key>"`. If it is correct and still fails, the pod may be holding an older value: force the sync and restart.

## New pod stuck in CreateContainerConfigError

**Cause:** the pod references the Secret `kyc-api-key` (and optionally `llm-api-key`), which External Secrets creates only after the Secrets Manager secret has a value. This is the expected result of deploying before setting the values; the old pod keeps serving.

**Fix:** set the values as in the [runbook](runbook.md#the-kyc-service-keys-and-the-model-provider), then force the sync: `kubectl annotate externalsecret kyc-api-key llm-api-key -n <env> force-sync=$(date +%s) --overwrite`. The pod starts by itself. Check with `kubectl describe externalsecret kyc-api-key -n <env>`.

## Pod exits at start with ANTHROPIC_API_KEY is required

**Cause:** `LLM_PROVIDER=anthropic` but the key is empty. The service stops at start on purpose rather than falling back to another provider.

**Fix:** set `<env>/llm-api-key` and sync, or set `LLM_PROVIDER=bedrock`. An unknown `LLM_PROVIDER` value also stops the service; the message names the allowed values.

## Uploads return 502 with the Anthropic provider

The pod log shows the error class only, for example `anthropic call failed: AuthenticationError` (wrong or revoked key), `RateLimitError` (too many requests) or `BadRequestError` (often an exhausted credit balance or an invalid model name). Check the credit balance and the key in the Anthropic console.

## A scanner job fails the pipeline

See [security-gates.md](security-gates.md), section "When a gate blocks a merge". A new Checkov release can add a check that fails a file nobody touched, because CI installs the newest 3.x. Fix it or suppress it with a written reason.

## Terraform apply fails midway with client credentials

**Symptom:** `the server has asked for the client to provide credentials`.

**Cause:** a cluster token from `data.aws_eks_cluster_auth` lasts 15 minutes and is frozen into a saved plan.

**Fix:** the providers now authenticate with `exec` (`aws eks get-token`) on every call. The AWS CLI must be on your PATH, and your AWS credentials must be valid.

## A Helm release is stuck in pending-install

**Symptom:** a Helm release (this happened with Loki) sits in `pending-install` after a failed apply, and Terraform cannot continue.

**Fix:**

```bash
helm uninstall <release> -n <namespace>
terraform state rm helm_release.<name>
```

Then apply again. Check the state address first with `terraform state list`.

## mysql-0 stays Pending after a restart

**Symptom:** `mysql-0` is `Pending` and the app pod is in `CrashLoopBackOff` with `Can't connect to MySQL server on 'mysql'` in its previous log (`kubectl logs deployment/nodejs-app -n <env> --previous`).

**Cause:** the MySQL disk is an EBS volume in one availability zone, so the pod can run only on the node in that zone. `kubectl describe pod mysql-0 -n <env>` shows `Insufficient cpu` for that node and `didn't match PersistentVolume's node affinity` for the other. That node was full on CPU *requests* (it happened with 1750m of 1930m used while MySQL needs 250m). The app is not the problem; it exits after waiting 90 seconds for the database and recovers by itself once MySQL runs.

**Fix:** free CPU on the node in the volume's zone. Find the zone with `kubectl get pv <name> -o jsonpath='{.spec.nodeAffinity}'`, list what is on that node, and scale down or repair pods that hold requests but serve nothing (stuck `Init`, `CrashLoopBackOff` or `CreateContainerConfigError` pods). If it keeps recurring, trim CPU requests to match real use or raise the node group to three nodes. Details in the [runbook](runbook.md#capacity-and-restarts).

## The prod URL does not load

**Cause:** the prod host is `proj3-aigateway.bolarbrijesh.com`, with no `prod-` prefix. Only the QA host has a prefix (`qa-proj3-aigateway…`). A name with no Route 53 record never resolves.

**Fix:** use the host in the Ingress: `kubectl get ingress -A`.

## Both sites return 503

**Cause:** the node group is scaled to zero, so there are no pods and the ALB has no healthy targets.

**Fix:** [resume](runbook.md#pause-and-resume) the node group and wait a few minutes. Check `kubectl get nodes` and `kubectl get pods -A`.

## The QA deploy job times out at the rollout

**Cause and fix:** look at why the new pod is not ready.

```bash
kubectl get pods -n qa
kubectl describe pod <pod> -n qa
kubectl logs <pod> -n qa
```

Common reasons: the cluster is paused (no nodes); the `kyc-app` service account does not exist because `envs/qa` was not applied after the module gained the Bedrock role; or `Access denied` from MySQL (see above). The startup probe allows about three minutes, and the app waits up to 90 seconds for MySQL.

## ESO installs fail with a webhook error

**Symptom:** `terraform apply` for `addons` fails installing External Secrets because the Load Balancer Controller's webhook is not ready.

**Fix:** already handled with `depends_on` (External Secrets installs after the controller). If it recurs, wait a minute and apply again.
