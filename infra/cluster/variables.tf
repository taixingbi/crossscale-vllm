variable "region" {
  type    = string
  default = "us-east-1"
  validation {
    condition     = var.region == "us-east-1"
    error_message = "Phase one is restricted to us-east-1."
  }
}
variable "cluster_name" {
  type    = string
  default = "crossscale"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,39}$", var.cluster_name))
    error_message = "Use a lowercase cluster name of at most 40 characters."
  }
}
variable "kubernetes_version" {
  description = "Select an EKS version supported in your region and compatible with the pinned add-ons."
  type        = string
}
variable "admin_cidrs" {
  description = "Public API allowlist, including the machine running the addons root."
  type        = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for cidr in var.admin_cidrs : can(cidrnetmask(cidr)) && !endswith(cidr, "/0")])
    error_message = "Provide explicit IPv4 CIDRs; unrestricted /0 access is not allowed."
  }
}
