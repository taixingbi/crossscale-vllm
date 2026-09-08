terraform {
  required_version = ">= 1.5.7, < 2.0"
  required_providers {
    aws  = { source = "hashicorp/aws", version = "~> 6.0" }
    helm = { source = "hashicorp/helm", version = "~> 3.0" }
  }
}
provider "aws" {
  region              = var.region
  allowed_account_ids = ["646821141010"]
}
data "aws_eks_cluster" "this" { name = var.cluster_name }
provider "helm" {
  kubernetes = {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--region", var.region, "--cluster-name", var.cluster_name]
    }
  }
}
resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "1.6.8"
  atomic     = true
  timeout    = 600
  values = [yamlencode({
    nodeSelector = { "karpenter.sh/controller" = "true" }
    settings = {
      clusterName       = var.cluster_name
      clusterEndpoint   = data.aws_eks_cluster.this.endpoint
      interruptionQueue = var.interruption_queue
    }
  })]
}
resource "helm_release" "device_plugin" {
  name       = "nvidia-device-plugin"
  namespace  = "kube-system"
  repository = "https://nvidia.github.io/k8s-device-plugin"
  chart      = "nvidia-device-plugin"
  version    = "0.17.1"
  atomic     = true
  values = [yamlencode({
    nodeSelector = { "node.kubernetes.io/instance-type" = "g5.xlarge" }
    tolerations  = [{ key = "nvidia.com/gpu", operator = "Exists", effect = "NoSchedule" }]
  })]
}
resource "helm_release" "keda" {
  name             = "keda"
  namespace        = "keda"
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = "2.17.2"
  atomic           = true
  timeout          = 600
}
resource "helm_release" "prometheus" {
  name             = "monitoring"
  namespace        = "monitoring"
  create_namespace = true
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  version          = "72.6.2"
  atomic           = true
  timeout          = 900
  values = [yamlencode({
    grafana      = { enabled = false }
    alertmanager = { enabled = false }
    prometheus = { prometheusSpec = {
      retention = "2d"
      additionalScrapeConfigs = concat([
        {
          job_name              = "crossscale-vllm"
          scrape_interval       = "5s"
          kubernetes_sd_configs = [{ role = "pod", namespaces = { names = ["crossscale"] } }]
          relabel_configs = [
            { source_labels = ["__meta_kubernetes_pod_label_app"], action = "keep", regex = "vllm" },
            { source_labels = ["__meta_kubernetes_pod_container_port_name"], action = "keep", regex = "http" },
            { source_labels = ["__meta_kubernetes_namespace"], target_label = "namespace" },
            { source_labels = ["__meta_kubernetes_pod_name"], target_label = "pod" }
          ]
        }
        ], length(var.gateway_metrics_targets) == 0 ? [] : [
        {
          job_name        = "crossscale-gateway"
          scrape_interval = "5s"
          static_configs  = [{ targets = var.gateway_metrics_targets }]
        }
      ])
    } }
  })]
}
resource "helm_release" "gpu_pool" {
  name             = "crossscale-gpu"
  namespace        = "crossscale"
  create_namespace = true
  chart            = "${path.module}/charts/gpu"
  atomic           = true
  values = [jsonencode({
    clusterName = var.cluster_name
    nodeRole    = var.node_role_name
    amiId       = var.gpu_ami_id
    gpuLimit    = var.gpu_limit
  })]
  depends_on = [helm_release.karpenter, helm_release.device_plugin]
}
