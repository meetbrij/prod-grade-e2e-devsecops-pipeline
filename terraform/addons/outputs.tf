output "alb_controller_role_arn" {
  value = aws_iam_role.alb_controller.arn
}

output "storage_classes" {
  value = [kubernetes_storage_class_v1.ebs_sc.metadata[0].name, kubernetes_storage_class_v1.ebs_sc_retain.metadata[0].name]
}
