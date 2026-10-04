resource "helm_release" "tempo" {
  name       = "tempo"
  namespace  = var.namespace
  repository = "https://grafana.github.io/helm-charts"
  chart      = "tempo"
  version    = var.tempo_chart_version
  timeout    = 600

  values = [templatefile("${path.module}/values/tempo.yaml.tftpl", {
    storage_class      = var.storage_class
    traces_retention   = var.traces_retention
    tempo_storage_size = var.tempo_storage_size
  })]

  depends_on = [helm_release.kube_prometheus_stack]
}
