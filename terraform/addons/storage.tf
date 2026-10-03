# gp3 StorageClasses for the EBS CSI driver (installed by the platform stack).
# StorageClass reclaim policy is fixed per class, so there are two:
#   ebs-sc        -> Delete (qa: volumes are cleaned up with their claims)
#   ebs-sc-retain -> Retain (prod: volumes survive claim deletion)
resource "kubernetes_storage_class_v1" "ebs_sc" {
  metadata {
    name = "ebs-sc"
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type      = "gp3"
    fsType    = "ext4"
    encrypted = "true"
  }
}

resource "kubernetes_storage_class_v1" "ebs_sc_retain" {
  metadata {
    name = "ebs-sc-retain"
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Retain"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type      = "gp3"
    fsType    = "ext4"
    encrypted = "true"
  }
}
