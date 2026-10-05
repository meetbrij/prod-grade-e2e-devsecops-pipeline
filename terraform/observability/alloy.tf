# Log collector. Installed after Loki so the first pushes have somewhere to land.
resource "helm_release" "alloy" {
  name       = "alloy"
  namespace  = var.namespace
  repository = "https://grafana.github.io/helm-charts"
  chart      = "alloy"
  version    = var.alloy_chart_version
  timeout    = 600

  values = [templatefile("${path.module}/values/alloy.yaml.tftpl", {
    loki_url = local.loki_url
  })]

  depends_on = [helm_release.loki]
}
