# The registry bucket remains owned by huggingface-s3-model-registry.
locals {
  model_bucket = "huggingface-model-registry-646821141010-us-east-1"
  model_prefix = "inference/meta-llama/Llama-3.1-8B-Instruct"
  model_key    = "arn:aws:kms:us-east-1:646821141010:key/38e70831-38c2-4967-9d5e-29352b62a876"
}
resource "aws_iam_role" "model_reader" {
  name = "${var.cluster_name}-model-reader"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = { StringEquals = {
        "aws:RequestTag/eks-cluster-arn"            = data.aws_eks_cluster.this.arn
        "aws:RequestTag/kubernetes-namespace"       = "crossscale"
        "aws:RequestTag/kubernetes-service-account" = "vllm-model-reader"
      } }
    }]
  })
  tags = { Project = "crossscale", ManagedBy = "terraform" }
}
resource "aws_iam_role_policy" "model_reader" {
  name = "read-pinned-llama-snapshot"
  role = aws_iam_role.model_reader.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObjectVersion"]
        Resource = "arn:aws:s3:::${local.model_bucket}/${local.model_prefix}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = local.model_key
        Condition = {
          StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" }
          StringLike = { "kms:EncryptionContext:aws:s3:arn" = [
            "arn:aws:s3:::${local.model_bucket}",
            "arn:aws:s3:::${local.model_bucket}/${local.model_prefix}/*"
          ] }
        }
      }
    ]
  })
}
resource "aws_eks_pod_identity_association" "model_reader" {
  cluster_name    = var.cluster_name
  namespace       = "crossscale"
  service_account = "vllm-model-reader"
  role_arn        = aws_iam_role.model_reader.arn
  depends_on      = [aws_iam_role_policy.model_reader]
}
output "model_reader_role_arn" { value = aws_iam_role.model_reader.arn }
