variable "region" { type = string }
variable "cluster_name" { type = string }
variable "node_role_name" { type = string }
variable "interruption_queue" { type = string }
variable "gpu_ami_id" {
  description = "Pinned EKS AL2023 NVIDIA x86_64 AMI matching the cluster version and region."
  type        = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]{8}([0-9a-f]{9})?$", var.gpu_ami_id))
    error_message = "Provide a concrete AMI ID, not a moving latest alias."
  }
}
variable "gpu_limit" {
  type    = number
  default = 4
  validation {
    condition     = var.gpu_limit >= 1 && floor(var.gpu_limit) == var.gpu_limit
    error_message = "GPU limit must be a positive integer."
  }
}
variable "gateway_metrics_targets" {
  description = "host:port targets reachable from Prometheus pods; do not use localhost."
  type        = list(string)
  validation {
    condition     = length(var.gateway_metrics_targets) > 0
    error_message = "Supply at least one reachable gateway metrics target."
  }
}
