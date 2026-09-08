# AWS experiment environment

Two Terraform roots keep cluster creation separate from Kubernetes authentication:

- `cluster/`: a dedicated VPC, two private subnets, one NAT gateway, EKS, two CPU system nodes, and Karpenter IAM/Pod Identity/interruption resources.
- `addons/`: Karpenter, NVIDIA device plugin, KEDA, Prometheus, and an on-demand `g5.xlarge` NodePool. GPUs are provisioned only when workloads require them. The vLLM Deployment and baseline-specific ScaledObject stay in `deploy/`; Terraform never owns their replica counts.

Prerequisites: Terraform >= 1.5.7, AWS CLI credentials with infrastructure provisioning permissions, kubectl, a selected EKS Kubernetes version, and an EKS AL2023 NVIDIA x86_64 AMI for that version in your region. The AWS identity applying `cluster/` receives cluster administrator access; use the same identity for `addons/`, or explicitly grant another identity access first. EKS and chart versions must be checked together before changing the pinned versions.

## AWS AssumeRole

Use the same temporary-credential pattern as [bedrock-tenants](https://github.com/taixingbi/bedrock-tenants/blob/main/scripts/deploy-member.sh). The wrapper assumes a role, then runs one command with credentials shared by Terraform and the Helm provider's `aws eks get-token` subprocess. It does not modify your AWS config or parent shell. Source credentials must already be available through the AWS CLI; set `AWS_PROFILE` if needed.

```sh
# Replace the example account with the intended deployment account.
export TARGET_ACCOUNT_ID=123456789012
scripts/with-aws-role.sh "$TARGET_ACCOUNT_ID" aws sts get-caller-identity
scripts/with-aws-role.sh "$TARGET_ACCOUNT_ID" terraform -chdir=infra/cluster plan -out=cluster.tfplan
# After reviewing the plan:
scripts/with-aws-role.sh "$TARGET_ACCOUNT_ID" terraform -chdir=infra/cluster apply cluster.tfplan
```

An account ID selects `OrganizationAccountAccessRole` by default; override `ORG_ACCESS_ROLE` or pass a full IAM role ARN as the first argument. Use the same wrapper and role for add-on plans/applies, kubectl commands, and teardown. Run the generated `aws eks update-kubeconfig` command through the wrapper as well. Do not add `--profile` to child commands: that could select the source identity instead of the assumed role. The existing role must permit the requested EKS/network/IAM operations and its trust policy must allow your source identity.

Sessions last one hour and are not refreshed by the wrapper. Run a fresh invocation for each operation; operations exceeding one hour need a refreshable AWS role profile instead. Do not add a second Terraform provider `assume_role` block when using the wrapper: the provider and CLI should use the same already-assumed identity.

The reference repository also supports GitHub OIDC. Our CI remains credential-free validation; this change does not copy its automatic deployments or create accounts/roles. A future deployment workflow needs a role whose OIDC trust explicitly permits this repository.

## Phase-one review plan (no apply)

The selected scope is account `646821141010`, `us-east-1`, EKS `1.34`, and on-demand `g5.xlarge` (one A10G per node). The existing vLLM/KEDA manifests request two initial replicas and allow four maximum, one GPU per replica. The GPU pool limit is capped at four by input validation, but Karpenter limits remain eventually consistent, not a hard billing cap. The smaller host has 4 vCPU/16 GiB RAM, so vLLM requests 2 CPU/10 GiB and has a 12 GiB memory limit to leave room for Kubernetes/system daemons. Validate model startup memory and recalibrate throughput on this hardware.

Cluster Terraform creates two `m5.large` CPU system nodes for controllers/monitoring in addition to the later 2–4 GPUs. GPU instances only appear when the add-ons and vLLM workload are subsequently deployed; the first cluster plan creates zero GPUs. No ECR repository is needed for the current public images. No customer-managed KMS key is created: EKS >=1.28 provides AWS-owned envelope encryption by default. Pod Identity is used instead of a separate cluster IRSA provider. See [AWS encryption documentation](https://docs.aws.amazon.com/eks/latest/userguide/envelope-encryption.html).

The manual **Terraform review plan** workflow assumes the CrossScale OIDC role and plans `cluster/` against the dedicated encrypted S3 backend. It uses `phase1.tfvars.example` with an administrator CIDR override from the repository secret `EKS_ADMIN_CIDR`. Without that secret it falls back to documentation CIDR `203.0.113.10/32`. The workflow requires a single IPv4 `/32`, masks it in logs, and redacts it from both exported plan formats. The actual IP is never committed to source. The original initial-create review used empty state; new runs refresh the persistent deployment state. It uploads plan text/JSON for three days and does not upload the executable plan or run apply. Provisioning permissions were separately authorized; only the manual **Terraform cluster apply** workflow executes apply after checking scope. The full add-ons plan requires an actual EKS endpoint, so it cannot be produced before the cluster exists; Helm chart rendering and Terraform validation cover that stage for now.

```sh
gh workflow run terraform-plan.yml --repo taixingbi/crossscale-vllm --ref main
```

Before any later apply: verify the actual administrator CIDR, select a reachable gateway host and pinned vLLM image/model, verify the configured remote state and provisioning scope, and generate a fresh plan. The reviewed public NVIDIA AMI is `ami-0c126bbe79be20f0a` (EKS 1.34 AL2023 x86_64 NVIDIA, us-east-1, queried 2026-09-07). Karpenter is pinned to `1.6.8`, in the 1.34-compatible release line; live readiness is not yet tested. The EKS version and CPU-node AMI/add-on selections are visible in the actual plan.

## Configure and review

Run from the repository root. Copy the examples and replace every placeholder:

```sh
cp infra/cluster/terraform.tfvars.example infra/cluster/terraform.tfvars
cp infra/addons/terraform.tfvars.example infra/addons/terraform.tfvars
terraform -chdir=infra/cluster init -backend-config=backend.hcl
terraform -chdir=infra/cluster validate
terraform -chdir=infra/cluster plan -out=cluster.tfplan
```

Choose your actual public API CIDR, region, cluster name, and supported Kubernetes version. Select a specific GPU AMI rather than a moving alias; keep its ID and the resolved system AMI/add-on versions with your experiment records. EKS-managed add-ons initially resolve a compatible version, so rebuilding the same configuration later may resolve newer add-on or system AMI versions. This configuration alone does not guarantee identical experimental environments.

Applying creates billable resources: EKS, CPU instances, NAT, storage and subsequently GPU instances. The single NAT gateway is an experiment cost tradeoff, not a high-availability design. The cluster root uses `backend.hcl` for its dedicated encrypted/versioned S3 bucket with native state locking. Add-ons still need a separate durable backend before their deployment. State, local variable files and saved plans are ignored; commit both provider lock files.

## Create cluster, then install add-ons

After reviewing the plan:

```sh
terraform -chdir=infra/cluster apply cluster.tfplan
terraform -chdir=infra/cluster output -json addons > infra/addons/cluster.auto.tfvars.json
terraform -chdir=infra/cluster output -raw configure_kubectl
# Run the aws eks update-kubeconfig command printed above.
terraform -chdir=infra/addons init
terraform -chdir=infra/addons validate
terraform -chdir=infra/addons plan -out=addons.tfplan
terraform -chdir=infra/addons apply addons.tfplan
```

The add-ons machine needs access to the EKS API from an allowed CIDR. `gateway_metrics_targets` must be an address reachable from Prometheus pods (for example the private IP and port of a load-generator host). Provision that host separately. Prometheus scrapes vLLM pods individually and attaches the `namespace` label needed by the queue query. It scrapes gateway targets with job `crossscale-gateway` every five seconds. The service address remains `http://prometheus-operated.monitoring.svc:9090`, matching the existing scaler YAML. Prometheus uses ephemeral storage here; export any data needed beyond the run.

Follow [S3 model setup](../docs/MODEL_SETUP.md) and pin the vLLM image in `deploy/vllm.yaml`. Apply it with an explicit context, then install **one** appropriate scaler according to the root README. Verify the Prometheus targets and metrics before measuring a run. Do not reapply `deploy/vllm.yaml` during an autoscaled run: its initial `replicas` field can reset the HPA's value.

```sh
kubectl --context YOUR_CONTEXT apply -k deploy
kubectl --context YOUR_CONTEXT get nodepool,ec2nodeclass
kubectl --context YOUR_CONTEXT -n crossscale get pods -o wide
# Example for B6; do not install both scaler files:
kubectl --context YOUR_CONTEXT apply -f deploy/slo-keda.yaml
```

GPU capacity is fixed to the instance type selected by the existing workload manifest. Changing hardware requires updating both. The NodePool defaults to four GPUs; Karpenter limits are eventually consistent and can briefly overshoot during concurrent provisioning, so this is not a hard AWS spending cap. Voluntary disruptions and expiration are disabled to avoid changing experiment timing; forced interruptions remain possible. Empty nodes are intentionally retained until explicit cleanup. Cold/warm resets remain an experiment procedure, not a Terraform apply operation. Upgrade CRDs deliberately when changing Karpenter/KEDA/Prometheus chart versions; Helm does not generally upgrade chart `crds/` resources automatically.

## Teardown

Stop the gateway/load generator and remove the experiment resources. Keep Karpenter and its IAM resources alive while it terminates GPU nodes:

```sh
kubectl --context YOUR_CONTEXT -n crossscale delete scaledobject vllm --ignore-not-found
kubectl --context YOUR_CONTEXT -n crossscale delete deployment vllm --ignore-not-found
kubectl --context YOUR_CONTEXT delete nodepool crossscale-gpu --ignore-not-found --wait=true
kubectl --context YOUR_CONTEXT get nodeclaims
# Wait until the GPU NodeClaims/nodes and their EC2 instances have terminated.
terraform -chdir=infra/addons destroy
terraform -chdir=infra/cluster destroy
```

Do not destroy the cluster first or remove NodeClaim finalizers to skip cleanup; dynamically created instances must be terminated by Karpenter before its controller/IAM resources disappear.

## Local validation

```sh
terraform fmt -check -recursive infra
terraform -chdir=infra/cluster init -backend=false
terraform -chdir=infra/cluster validate
terraform -chdir=infra/addons init -backend=false
terraform -chdir=infra/addons validate
helm lint infra/addons/charts/gpu --set clusterName=crossscale,nodeRole=crossscale-gpu,amiId=ami-0123456789abcdef0,gpuLimit=4
```

When updating providers, refresh checksums for both developer Macs and Linux CI, and commit the updated lock files:

```sh
terraform -chdir=infra/cluster providers lock -platform=darwin_arm64 -platform=linux_amd64
terraform -chdir=infra/addons providers lock -platform=darwin_arm64 -platform=linux_amd64
```

Validation does not prove AWS permissions, quotas, regional capacity, AMI compatibility, or live readiness. No cloud resources are created by these checks.

References: [EKS module Karpenter example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/v21.0.0/examples/karpenter), [Karpenter NodePools](https://karpenter.sh/docs/concepts/nodepools/), [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin).
