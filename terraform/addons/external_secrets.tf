# External Secrets Operator. The controller itself needs no AWS permissions:
# each environment namespace gets its own service account and IAM role (envs/* stacks)
# that a SecretStore references, so qa can only read qa secrets and prod only prod secrets.
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = var.external_secrets_chart_version

  values = [yamlencode({
    installCRDs = true
  })]

  # The ALB controller registers a mutating webhook on every Service. Install ESO only
  # after the controller is ready, otherwise ESO's Services are rejected ("no endpoints
  # available for service aws-load-balancer-webhook-service").
  depends_on = [helm_release.alb_controller]
}
