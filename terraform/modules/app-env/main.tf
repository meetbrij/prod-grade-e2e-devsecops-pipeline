# Everything one environment needs on the shared cluster:
# namespace + quota, secret shell + ESO identity, and the CI deploy role.

data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

# ---------------------------------------------------------------- namespace

resource "kubernetes_namespace_v1" "this" {
  metadata {
    name = var.env_name

    labels = {
      environment = var.env_name
      # Baseline is enforced; restricted only warns so we can see what to tighten.
      "pod-security.kubernetes.io/enforce" = "baseline"
      "pod-security.kubernetes.io/warn"    = "restricted"
    }
  }
}

resource "kubernetes_resource_quota_v1" "this" {
  metadata {
    name      = "${var.env_name}-quota"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"           = var.quota.requests_cpu
      "requests.memory"        = var.quota.requests_memory
      "limits.cpu"             = var.quota.limits_cpu
      "limits.memory"          = var.quota.limits_memory
      "pods"                   = var.quota.pods
      "persistentvolumeclaims" = var.quota.pvcs
      "requests.storage"       = var.quota.storage
    }
  }
}

# Without defaults, a pod that sets no requests/limits is rejected once a quota exists.
resource "kubernetes_limit_range_v1" "this" {
  metadata {
    name      = "${var.env_name}-defaults"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }

  spec {
    limit {
      type = "Container"

      default = {
        cpu    = var.container_defaults.limit_cpu
        memory = var.container_defaults.limit_memory
      }

      default_request = {
        cpu    = var.container_defaults.request_cpu
        memory = var.container_defaults.request_memory
      }
    }
  }
}

# ------------------------------------------------- secret shell + ESO identity

# The secret container only. The values (DB credentials) are set out-of-band so they
# never enter Terraform state.
resource "aws_secretsmanager_secret" "mysql" {
  name                    = "${var.env_name}/mysql-secret"
  description             = "MySQL credentials for the ${var.env_name} environment. Values are set manually."
  recovery_window_in_days = var.secret_recovery_window_days
}

data "aws_iam_policy_document" "eso_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider}:sub"
      values   = ["system:serviceaccount:${var.env_name}:eso"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eso" {
  name               = "${var.cluster_name}-${var.env_name}-eso"
  assume_role_policy = data.aws_iam_policy_document.eso_assume.json
}

data "aws_iam_policy_document" "eso_read_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.mysql.arn]
  }
}

resource "aws_iam_role_policy" "eso" {
  name   = "read-${var.env_name}-mysql-secret"
  role   = aws_iam_role.eso.id
  policy = data.aws_iam_policy_document.eso_read_secret.json
}

# The service account a SecretStore in this namespace references to reach AWS.
resource "kubernetes_service_account_v1" "eso" {
  metadata {
    name      = "eso"
    namespace = kubernetes_namespace_v1.this.metadata[0].name

    annotations = {
      "eks.amazonaws.com/role-arn" = aws_iam_role.eso.arn
    }
  }
}

# ------------------------------------------------------------ CI deploy role

data "aws_iam_policy_document" "deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository_claim}:${var.github_subject}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.cluster_name}-${var.env_name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_assume.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "DescribeCluster"
    actions   = ["eks:DescribeCluster"]
    resources = [data.aws_eks_cluster.this.arn]
  }

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "EcrRepository"
    actions   = var.ecr_actions
    resources = [var.ecr_repository_arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-${var.env_name}"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# Kubernetes access: edit rights inside this environment's namespace only.
resource "aws_eks_access_entry" "deploy" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.deploy.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "deploy" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.deploy.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = [var.env_name]
  }

  depends_on = [aws_eks_access_entry.deploy]
}
