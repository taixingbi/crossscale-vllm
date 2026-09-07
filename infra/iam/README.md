# CrossScale GitHub OIDC bootstrap

Account: `646821141010`. Role: `crossscale-deploy`.

`crossscale-trust.json` allows GitHub OIDC only for `taixingbi/crossscale-vllm` on `refs/heads/main`, with audience `sts.amazonaws.com`. It uses the existing account OIDC provider. It does not grant local IAM users permission to assume this role; use the manual **AWS access** workflow to verify it.

The initial `crossscale-discovery.json` policy is read-only environment discovery. **This role cannot yet provision infrastructure or perform a full Terraform plan.** Add scoped provisioning/read permissions once the target region, cluster configuration, and remote state backend are selected. Do not attach the Bedrock role's unrelated account-creation and application permissions.

One-time setup with an authorized account identity, from the repository root:

```sh
aws iam create-role --role-name crossscale-deploy \
  --assume-role-policy-document file://infra/iam/crossscale-trust.json \
  --description 'CrossScale GitHub OIDC; main branch only' \
  --tags Key=Project,Value=crossscale Key=ManagedBy,Value=crossscale-bootstrap
aws iam put-role-policy --role-name crossscale-deploy --policy-name crossscale-discovery \
  --policy-document file://infra/iam/crossscale-discovery.json
gh variable set AWS_ROLE_ARN --repo taixingbi/crossscale-vllm \
  --body arn:aws:iam::646821141010:role/crossscale-deploy
gh workflow run aws-access.yml --repo taixingbi/crossscale-vllm --ref main
```

The bootstrap role is managed separately from the EKS Terraform roots so destroying an experiment does not remove GitHub authentication. The ordinary CI workflow remains credential-free and does not assume this role. No automatic deployment is enabled.
