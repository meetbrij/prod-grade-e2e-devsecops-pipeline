# Installed first: it provides the CRDs (ServiceMonitor, PrometheusRule) the others may use,
# and Grafana, which is wired to Loki and Tempo through additional data sources.
resource "helm_release" "kube_prometheus_stack" {
  name             = "kube-prometheus-stack"
  namespace        = var.namespace
  create_namespace = true
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  version          = var.kube_prometheus_stack_chart_version
  timeout          = 900

  values = [templatefile("${path.module}/values/kube-prometheus-stack.yaml.tftpl", {
    namespace               = var.namespace
    storage_class           = var.storage_class
    metrics_retention       = var.metrics_retention
    prometheus_storage_size = var.prometheus_storage_size
    loki_url                = local.loki_url
    tempo_url               = local.tempo_url
  })]
}
