# Terraform command reference

Run commands from the repository root. The cluster configuration targets AWS account
`646821141010`, region `us-east-1`, and EKS cluster `crossscale`.

## Current deployment status

The cluster infrastructure was destroyed successfully in
[workflow run 34174929876](https://github.com/taixingbi/crossscale-vllm/actions/runs/34174929876).
Terraform state was verified empty; both CPU instances were terminated, and the
EKS cluster, VPC, NAT gateway, and EIP were removed. No GPU workloads had been deployed.
The S3 state bucket and `crossscale-deploy` role were retained. Temporary deletion
permissions were revoked after cleanup. This records the completed teardown, not a live status check.

## GitHub Actions with AWS AssumeRole

This is the configured deployment path. GitHub Actions assumes `crossscale-deploy`
using OIDC restricted to this repository's `main` branch. It uses repository variable
`AWS_ROLE_ARN` and secret `EKS_ADMIN_CIDR` (one administrator IPv4 `/32`).

```sh
# Check OIDC access.
gh workflow run aws-access.yml --repo taixingbi/crossscale-vllm --ref main

# Generate a review plan; does not apply.
gh workflow run terraform-plan.yml --repo taixingbi/crossscale-vllm --ref main

# Create a fresh plan, check the cluster scope, and apply it.
gh workflow run terraform-apply.yml --repo taixingbi/crossscale-vllm --ref main

# Find a run and watch it; replace RUN_ID with its numeric ID.
gh run list --repo taixingbi/crossscale-vllm --limit 5
gh run watch RUN_ID --repo taixingbi/crossscale-vllm --exit-status
```

Apply creates billable infrastructure: one EKS cluster, two `m5.large` CPU nodes,
and networking. It does not deploy GPU nodes or the Helm add-ons. The apply guard
rejects deletion and replacement. Review artifacts contain redacted text/JSON;
executable plans are not uploaded.

## Local Terraform prerequisites

Local commands require an AWS identity authorized for the intended operation and
access to the state bucket. The OIDC-only `crossscale-deploy` role cannot be assumed
by a local IAM user through `scripts/with-aws-role.sh` under its current trust policy.
Use the GitHub workflows above unless separate local access has been configured.
Do not change role trust just to run these examples.

Use Terraform `1.15.6` to match the workflows and support the S3 native lockfile.
The backend configuration is `infra/cluster/backend.hcl`:

- Bucket: `crossscale-tfstate-646821141010-us-east-1`
- State key: `crossscale/cluster.tfstate`
- Encryption and native state locking enabled

## Initialize and validate locally

```sh
aws sts get-caller-identity
terraform -chdir=infra/cluster init -backend-config=backend.hcl -lockfile=readonly
terraform fmt -check -recursive infra
terraform -chdir=infra/cluster validate
```

Confirm the identity belongs to the intended account before planning or applying.

## Plan and apply locally

Create an ignored local variable file, restrict its permissions, and edit
`admin_cidrs` to your actual administrator IPv4 `/32` before planning:

```sh
# Run the copy only if terraform.tfvars does not already exist.
test -f infra/cluster/terraform.tfvars || cp infra/cluster/phase1.tfvars.example infra/cluster/terraform.tfvars
chmod 600 infra/cluster/terraform.tfvars
# Edit infra/cluster/terraform.tfvars before continuing.

terraform -chdir=infra/cluster plan -out=cluster.tfplan
terraform -chdir=infra/cluster show cluster.tfplan

# After reviewing the saved plan:
terraform -chdir=infra/cluster apply cluster.tfplan
```

The example CIDR is a documentation placeholder. Keep the actual CIDR, variable
files, state, and saved plans private; local plan output is not automatically
redacted. The `-chdir` option means `cluster.tfplan` is saved inside `infra/cluster`.

## Inspect deployed resources

```sh
terraform -chdir=infra/cluster state list
terraform -chdir=infra/cluster output -json addons
terraform -chdir=infra/cluster output -raw configure_kubectl
aws eks describe-cluster --name crossscale --region us-east-1 --query 'cluster.{name:name,status:status,version:version}'
aws eks list-nodegroups --cluster-name crossscale --region us-east-1
```

Cluster queries and outputs require an existing deployment; after destruction,
state is empty and cluster queries return not found.

## Destroy cluster infrastructure

For a local identity with the required deletion permissions, initialize the same
backend and use the same variable file as deployment:

```sh
terraform -chdir=infra/cluster plan -destroy -out=destroy.tfplan
terraform -chdir=infra/cluster show destroy.tfplan

# After reviewing the exact resources to be deleted:
terraform -chdir=infra/cluster apply destroy.tfplan
terraform -chdir=infra/cluster state list
```

An empty state list confirms Terraform no longer tracks resources in this root.
Verify AWS cleanup too. Keep the independently bootstrapped state bucket and
OIDC deployment role; this root does not manage them.

The existing GitHub destroy workflow can be dispatched with:

```sh
gh workflow run terraform-destroy.yml --repo taixingbi/crossscale-vllm --ref main
```

Before using it for a future deployment, review and update
`infra/cluster/destroy-scope.json` and `infra/iam/crossscale-destroy.json` from the
current state, then authorize the required temporary deletion permissions.
These files contain exact resource IDs from the completed teardown; newly created
resources will have different IDs. The guard rejects unreviewed resources and any
creation or update. The temporary policy is currently absent from AWS, so this
workflow is not ready to destroy a newly created environment without that setup.

## If GPU workloads and add-ons are deployed later

First stop the load generator and remove the workload and NodePool while Karpenter
and its IAM permissions still exist. Wait for GPU NodeClaims and EC2 instances to
terminate. Destroy the add-ons root before the cluster root.

The add-ons root requires its own durable backend before deployment; it does not
share the cluster state key. See [the infrastructure guide](../infra/README.md)
for add-on configuration and the full workload cleanup sequence.
