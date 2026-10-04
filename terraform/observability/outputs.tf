output "namespace" {
  value = var.namespace
}

output "grafana_port_forward" {
  description = "Command to open Grafana at http://localhost:3000 (user: admin)."
  value       = "kubectl port-forward -n ${var.namespace} svc/kube-prometheus-stack-grafana 3000:80"
}

output "grafana_admin_password_command" {
  description = "Command that prints the generated Grafana admin password."
  value       = "kubectl get secret kube-prometheus-stack-grafana -n ${var.namespace} -o jsonpath='{.data.admin-password}' | base64 -d; echo"
}
