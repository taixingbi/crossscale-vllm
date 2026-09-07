terraform {
  required_version = ">= 1.5.7, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = var.cluster_name, ManagedBy = "terraform" } }
}

data "aws_availability_zones" "available" {
  state = "available"
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.0.1"

  name               = var.cluster_name
  cidr               = "10.42.0.0/16"
  azs                = slice(data.aws_availability_zones.available.names, 0, 2)
  private_subnets    = ["10.42.0.0/20", "10.42.16.0/20"]
  public_subnets     = ["10.42.128.0/24", "10.42.129.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
  public_subnet_tags = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
    "karpenter.sh/discovery"          = var.cluster_name
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.0.0"

  name                                     = var.cluster_name
  kubernetes_version                       = var.kubernetes_version
  endpoint_public_access                   = true
  endpoint_private_access                  = true
  endpoint_public_access_cidrs             = var.admin_cidrs
  enable_cluster_creator_admin_permissions = true
  vpc_id                                   = module.vpc.vpc_id
  subnet_ids                               = module.vpc.private_subnets
  addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
  }
  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 2
      max_size       = 2
      desired_size   = 2
      labels         = { "karpenter.sh/controller" = "true" }
    }
  }
  node_security_group_tags = { "karpenter.sh/discovery" = var.cluster_name }
}

module "karpenter" {
  source                          = "terraform-aws-modules/eks/aws//modules/karpenter"
  version                         = "21.0.0"
  cluster_name                    = module.eks.cluster_name
  node_iam_role_name              = "${var.cluster_name}-gpu"
  node_iam_role_use_name_prefix   = false
  create_pod_identity_association = true
}

output "addons" {
  description = "Write this JSON output to ../addons/cluster.auto.tfvars.json after applying."
  value = {
    region             = var.region
    cluster_name       = module.eks.cluster_name
    node_role_name     = module.karpenter.node_iam_role_name
    interruption_queue = module.karpenter.queue_name
  }
}

output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
