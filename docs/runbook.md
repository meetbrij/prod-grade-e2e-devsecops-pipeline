# Runbook

Day-to-day operations for the platform. For the first-time build order see [terraform/README.md](../terraform/README.md); for symptoms and fixes see [troubleshooting.md](troubleshooting.md).

| I want to... | Go to |
|---|---|
| Ship a change to QA | [Release a change](#release-a-change) |
| Promote QA to production | [Promote to production](#promote-to-production) |
| Undo a bad prod release | [Roll back](#roll-back) |
| Stop paying for the nodes | [Pause and resume](#pause-and-resume) |
| Set up or recover a database secret | [Secrets](#secrets) |
| Tear it all down | [Destroy](#destroy) |

## Release a change

1. Branch from `qa`: `feature/DS-NNN-short-slug` (bug fixes: `bugfix/...`). Never branch from `main`.
2. Open a PR into `qa` and squash-merge it. A PR runs the scans, lint, tests, Sonar and the image build, but pushes and deploys nothing.
3. The merge to `qa` runs the full pipeline: scans, build, push to ECR, deploy to the `qa` namespace, then a bot commit (`ci: record deployed qa image <sha> [skip ci]`) records the deployed tag on `qa`.
4. Check QA: `https://qa-proj3-aigateway.bolarbrijesh.com/healthz` returns 200, and `/ui` loads.

Changes that only touch Markdown files or `docs/` skip both pipelines on purpose. A mixed change (docs and code) runs the pipeline as normal.

If a scan job blocks the run, see [security-gates.md](security-gates.md).

## Promote to production

1. Open a PR from `qa` to `main` and merge it with a **merge commit** (not squash).
2. The `Production CD Pipeline` starts. Its `prepare` job prints which QA-built image is being promoted: the SHA, the prod tag `prod-<sha>` and a link to the QA commit.
3. Open the run, check that SHA, then **approve** the pending `prod` deployment (GitHub Environment `prod`).
4. The workflow retags the image in ECR (same digest, no rebuild), deploys to the `prod` namespace and waits for the rollout.
5. Check `https://proj3-aigateway.bolarbrijesh.com/healthz`.

The prod tag is deliberately not committed back to the repo. What runs in prod is recorded by the ECR tag, the GitHub deployment record and the cluster.

A manual re-run (for example after a failed deploy) is available through **Run workflow** on the prod workflow. It still needs approval, and it deploys whatever SHA `qa` currently records.

## Roll back

Not exercised in this project yet; test it once in QA before relying on it.

- **Fastest, for prod:** `kubectl rollout undo deployment/nodejs-app -n prod` returns to the previous ReplicaSet in seconds. Check with `kubectl rollout status deployment/nodejs-app -n prod`.
- **Then fix forward.** The rollback is temporary: the next deploy puts the bad version back unless the cause is fixed. Open a `bugfix/*` PR into `qa`, let it deploy there, then promote it as above.
- For QA, the same command works with `-n qa`.
- Database changes are not undone by a rollback. The app creates its own tables and does not delete data.

## Pause and resume

Scaling the node group to zero stops the EC2 instances, which is the biggest cost that can be switched off. Everything else stays: the EKS control plane, the NAT gateway, the shared ALB and the EBS volumes, so the databases keep their data.

Find the node group name:

```bash
aws eks list-nodegroups --cluster-name devsecops-eks --region ap-south-1
```

Pause:

```bash
aws eks update-nodegroup-config --cluster-name devsecops-eks --region ap-south-1 \
  --nodegroup-name <node-group-name> --scaling-config minSize=0,maxSize=3,desiredSize=0
```

Resume:

```bash
aws eks update-nodegroup-config --cluster-name devsecops-eks --region ap-south-1 \
  --nodegroup-name <node-group-name> --scaling-config minSize=2,maxSize=3,desiredSize=2
```

While paused, pods are `Pending`, the ALB has no healthy targets and both sites answer 503. After resuming, nodes take a few minutes to join and the pods start by themselves. The instance IDs change, because new nodes are launched. While paused, `terraform plan` on `platform` shows the node group minimum as a change; resuming (or `terraform apply`) puts it back.

**A QA pipeline run while paused fails** at the rollout wait because there are no nodes. Resume first, then re-run the failed jobs.

What still costs money while paused: the EKS control plane (about 73 USD per month), the NAT gateway (about 35 USD plus data), the ALB (about 18 USD) and the EBS volumes. That is around two thirds of the running cost. For a longer break, [destroy](#destroy) instead; everything rebuilds from Terraform and the pipeline, but the databases start empty. These figures are estimates, so check the AWS pricing calculator.

## Secrets

Terraform creates each secret as an empty container (`qa/mysql-secret`, `prod/mysql-secret`) and never the values, so they stay out of Terraform state.

### Set the values (once per environment)

> **Run this exactly once per environment, and read the `--secret-id` before pressing Enter.** The QA and prod commands differ by one word.
>
> MySQL reads its passwords only the first time it starts on an empty volume. Changing the secret afterwards does **not** change the database. External Secrets copies the new value into the cluster within an hour, and the next app pod to start then fails with `Access denied`. This happened once in QA.

This generates random passwords and stores them without printing them or writing them anywhere permanent. Replace `<env>` with `qa` or `prod`:

```bash
ROOT=$(openssl rand -base64 24 | tr -d '/+=') ; APP=$(openssl rand -base64 24 | tr -d '/+=')
aws secretsmanager put-secret-value --region ap-south-1 --secret-id <env>/mysql-secret --secret-string \
"{\"MYSQL_ROOT_PASSWORD\":\"$ROOT\",\"MYSQL_DATABASE\":\"appdb\",\"MYSQL_USER\":\"appuser\",\"MYSQL_PASSWORD\":\"$APP\",\"DATABASE_URL\":\"mysql://appuser:$APP@mysql:3306/appdb\"}"
unset ROOT APP
```

### Recover from an overwritten secret

Move the previous version back. Version IDs come from `aws secretsmanager list-secret-version-ids --secret-id <env>/mysql-secret`:

```bash
aws secretsmanager update-secret-version-stage --region ap-south-1 --secret-id <env>/mysql-secret \
  --version-stage AWSCURRENT --move-to-version-id <previous-version-id> --remove-from-version-id <current-version-id>
```

Force External Secrets to sync, then restart the app:

```bash
kubectl annotate externalsecret mysql-external-secret -n <env> force-sync=$(date +%s) --overwrite
kubectl rollout restart deployment/nodejs-app -n <env>
```

### Rotate a database password on purpose

Change it in both places, in this order:
1. In MySQL, inside the pod: `ALTER USER 'appuser'@'%' IDENTIFIED BY '<new>';` (and the root password if needed).
2. In Secrets Manager: store the new value, and the updated `DATABASE_URL`.
3. Force the sync and restart the app as above.

### The GitHub deploy role variables

The role ARNs are repository **variables**, not secrets: Settings, Secrets and variables, Actions, Variables. `AWS_ROLE_TO_ASSUME_QA` and `AWS_ROLE_TO_ASSUME_PROD` hold the value of `terraform output deploy_role_arn` from `envs/qa` and `envs/prod`. The prod role also needs the GitHub Environment `prod` (Settings, Environments), with a required reviewer and deployment limited to the `main` branch.

## The KYC service keys and the model provider

Two more secrets per environment, set by hand once (Terraform creates only the empty containers):

| Secret | Holds | Read by |
|---|---|---|
| `<env>/kyc-api-key` | The `X-API-Key` that clients (including the review page) must send | Pod env `KYC_API_KEY`. **Not optional**: without the secret the pod does not start, so the API is never open |
| `<env>/llm-api-key` | The Anthropic API key, used only while `LLM_PROVIDER=anthropic` | Pod env `ANTHROPIC_API_KEY` |

Set the service key (generated, stored without printing it):

```bash
aws secretsmanager put-secret-value --region ap-south-1 --secret-id <env>/kyc-api-key \
  --secret-string "$(openssl rand -base64 32 | tr -d '/+=')"
```

Read it back when you need it for the review page or a request:

```bash
aws secretsmanager get-secret-value --region ap-south-1 --secret-id <env>/kyc-api-key --query SecretString --output text
```

Set the Anthropic key. `read -s` keeps it out of your shell history and off the screen:

```bash
printf "Anthropic API key: "; read -s KEY; echo
aws secretsmanager put-secret-value --region ap-south-1 --secret-id <env>/llm-api-key --secret-string "$KEY"
unset KEY
```

Values must exist **before** the deploy that references them. Otherwise External Secrets cannot create the Kubernetes Secret and the new pod stays in `CreateContainerConfigError` (the old pod keeps serving). To change a key later, store the new value, force the sync and restart:

```bash
kubectl annotate externalsecret kyc-api-key llm-api-key -n <env> force-sync=$(date +%s) --overwrite
kubectl rollout restart deployment/nodejs-app -n <env>
```

### Switch the model provider

The provider is the `LLM_PROVIDER` variable in `k8-manifests/<env>/app-deployment.yaml`: `anthropic` for the demo, `bedrock` for data residency (see [data-residency.md](data-residency.md)). Change it through a normal PR. For a quick test without a PR, `kubectl set env deployment/nodejs-app -n <env> LLM_PROVIDER=bedrock` works until the next deploy puts the manifest value back.

Check which one is active from the log line written at start:

```bash
kubectl logs deployment/nodejs-app -n <env> | grep "service started"
```

## Observability

Grafana is not exposed to the internet. Open it with a port-forward; the steps, the admin password and what to look at are in the main README under [Using Grafana](../README.md#using-grafana). Retention is 15 days for logs, metrics and traces.

The volumes were created on the `ebs-sc-retain` StorageClass and their reclaim policy was patched to `Delete`, so destroying the observability stack also removes them. A fresh install would use `ebs-sc-retain` again: patch the new PVs the same way (`kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'`) or set `storage_class` to `ebs-sc` before installing.

## Destroy

`terraform destroy` removes only resources recorded in that stack's state, that is, what Terraform created. Anything made by hand (Jenkins, IAM users, other VPCs, S3 buckets) is not in state and is never touched. Every managed resource is also tagged `ManagedBy=terraform`.

Deliberately **not** managed, so they survive a destroy:
- The Route 53 hosted zone `bolarbrijesh.com` and its existing records. Terraform adds and removes only the ACM validation records it creates. The manual alias records for the two hostnames are yours to delete.
- A pre-existing GitHub OIDC provider, if `create_github_oidc_provider = false`.

Safeguards: the state bucket has `prevent_destroy = true`, and `terraform plan -destroy` shows what a destroy would do.

Order, reverse of the build: `envs/prod`, `envs/qa`, `observability`, `addons`, `platform`. **Delete the Ingresses first and wait for the ALB to disappear**, otherwise the controller-created ALB blocks the VPC deletion:

```bash
kubectl delete ingress -A --all
```

The prod MySQL volume uses the `Retain` policy, so its EBS volume remains after a destroy and is deleted by hand if it is no longer needed.
