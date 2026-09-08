# Cluster apply bootstrap

The user explicitly authorized this bootstrap and cluster apply. The dedicated bucket, provisioning policy, and two-hour maximum role session were activated on 2026-09-07. Earlier review runs were read-only; subsequent plan/apply runs use the persistent state backend.

- Create `crossscale-tfstate-646821141010-us-east-1` in account `646821141010`, region `us-east-1`, with S3-managed AES256 encryption, versioning, all public access blocked and a TLS-only bucket policy. It persists independently of the EKS cluster for recovery and teardown. State contains infrastructure metadata including the administrator CIDR and must remain private.
- Attach the inline `crossscale-provision` policy from `crossscale-provision.json` to the existing `crossscale-deploy` role. It permits regional network configuration, one CrossScale EKS cluster and its child resources, named CrossScale IAM roles/controller policy, required managed-policy attachments and service-linked roles, named interruption queues/rules, cluster logs, and the exact state/lock object paths. Some EC2 configuration operations apply across the target account/region because resource IDs are not known until creation. It does not grant AdministratorAccess, Organizations access, direct EC2 RunInstances, or permission to modify the deployment role itself.
- Increase the role's maximum session duration to two hours so EKS creation can finish in one OIDC session. Trust remains limited to the exact repository and main branch.

`infra/cluster/backend.hcl` defines the bucket/key and S3-native lockfile. The manual `terraform-apply.yml` workflow plans against persistent state, requires the real administrator CIDR secret, verifies the reviewed scope and rejects deletes/replacements before applying the exact saved plan. Only redacted plan text/JSON is uploaded as a short-lived artifact. State and the executable plan are not uploaded as Actions artifacts.

The applied scope is the first cluster stage: 1 EKS 1.34 cluster, 2 m5.large CPU system nodes and supporting network/IAM/logging/Karpenter infrastructure. It does not install Kubernetes add-ons or launch GPUs. Subsequent destruction requires a separate explicit authorization and appropriate deletion permissions.

## Recovery status

The first apply created the VPC (`vpc-01469cc72f51e24c3`), initial project roles/log group and VPC defaults; state was saved to S3. It failed before EKS or compute creation. Parent-VPC authorization is missing for EC2 CreateSubnet/CreateSecurityGroup/CreateRouteTable; the policy file now contains a proposed exact-VPC grant and project-tagged NAT parent-resource grant. These additions were explicitly authorized and applied to AWS.

The EIP quota API reports 5 while DescribeAddresses returns 7 existing allocations. One new NAT EIP requires requesting a limit of 8. No existing address will be released/reassigned. The user explicitly authorized the quota request, which was submitted with ID `f69534167ad64fa187c098ddd6d2e4c1WZFiQlu0` and was approved at 8. No existing addresses were modified.

## CPU launch authorization

Recovery run `34171752590` created the EKS control plane (ACTIVE), networking/NAT and Karpenter IAM/SQS resources, but CreateNodegroup failed. AWS authorization decoding identifies missing `ec2:RunInstances` for the deployment role. No node groups exist yet.

`crossscale-node-launch.json` was explicitly authorized and attached as the `crossscale-node-launch` inline policy: instance authorization is restricted to `m5.large` in us-east-1 using launch template `lt-0afe60b4ec48877c1`; supporting-resource permissions use that same launch template and the two CrossScale private subnets/node security group. This does not authorize GPU instance types. The Terraform scope check enforces the two-node count; IAM does not itself impose a two-instance count limit. The authorized recovery run is `34173386283`.
