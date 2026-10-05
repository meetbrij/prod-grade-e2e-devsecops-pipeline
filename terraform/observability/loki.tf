resource "helm_release" "loki" {
  name       = "loki"
  namespace  = var.namespace
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki"
  version    = var.loki_chart_version
  timeout    = 600

  values = [templatefile("${path.module}/values/loki.yaml.tftpl", {
    storage_class     = var.storage_class
    logs_retention    = var.logs_retention
    loki_storage_size = var.loki_storage_size
  })]

  depends_on = [helm_release.kube_prometheus_stack]
}
