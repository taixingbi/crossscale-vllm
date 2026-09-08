variable "region" {
  type = string
  validation {
    condition     = var.region == "us-east-1"
    error_message = "Phase one is restricted to us-east-1."
  }
}
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
    condition     = var.gpu_limit >= 1 && var.gpu_limit <= 4 && floor(var.gpu_limit) == var.gpu_limit
    error_message = "Phase-one GPU limit must be an integer between 1 and 4."
  }
}
variable "gateway_metrics_targets" {
  description = "Reachable host:port targets; empty disables gateway scraping for inference-only smoke tests."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for target in var.gateway_metrics_targets : can(regex("^[^ :/]+:[0-9]+$", target)) && !startswith(target, "localhost:") && !startswith(target, "127.0.0.1:")])
    error_message = "Gateway metrics targets must be reachable host:port addresses, not localhost."
  }
}
