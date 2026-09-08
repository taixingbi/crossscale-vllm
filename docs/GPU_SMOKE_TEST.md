# One-GPU S3 inference smoke test

Run the manual `addons-smoke.yml` workflow on `main` to plan and apply the add-ons,
then deploy and verify one Llama 3.1 8B Instruct replica:

```sh
gh workflow run addons-smoke.yml --repo taixingbi/crossscale-vllm --ref main
```

The workflow uses the existing OIDC deployment role and encrypted/versioned S3
bucket with a separate state key, `crossscale/addons.tfstate`. Its plan guard
rejects deletion/replacement and limits the GPU pool configuration to one GPU.
The overlay `deploy-overlays/smoke` sets one replica with Recreate rollout,
a 4,096-token context, four concurrent sequences, and eager execution. These
settings establish functionality; they are not the calibrated experiment profile.
Karpenter's pool limit is eventually consistent, not a strict billing quota.

The image is pinned to vLLM `v0.28.0-cu129-ubuntu2404` by digest. Model downloads
use the pinned S3 object versions documented in [model setup](MODEL_SETUP.md).
Gateway scraping is omitted until a load generator is available. Prometheus
still scrapes vLLM pods. The smoke test checks model identity, a chat completion,
and the vLLM metrics endpoint. It does not install a scaler or start load tests.

The EKS public endpoint retains its administrator allowlist. The workflow adds
only its runner's IPv4 `/32` temporarily and restores the original list in an
`always()` step. Addresses are masked and the original list stays in a private
runner temporary file. If a runner is forcibly lost, verify the EKS API allowlist
and remove its temporary entry. All infrastructure workflows share one concurrency
group to prevent conflicting changes while temporary access is active.

The additional deployment policy in `infra/iam/crossscale-addons-deploy.json`
manages only the separate state key and `crossscale-model-reader` role. The model
reader itself can read the model prefix and decrypt its KMS key through S3.
The model registry remains independently managed.

## After the test

A successful run leaves the GPU replica and add-ons running for inspection.
A failed run also preserves resources and state for diagnosis; failure does not
mean GPU charges stopped. Inspect pod events, init-container logs, vLLM logs,
and Karpenter logs before changing memory settings or retrying.

Before cluster destruction: delete the workload and GPU NodePool, wait for
NodeClaims and GPU EC2 instances to terminate, then destroy the add-ons root
using its own backend before destroying the cluster root. The old cluster-only
destroy scope does not include add-ons or Karpenter-created GPU instances.

Do not run the smoke workflow again after scaling experiments without reviewing
its one-GPU settings. Configure a gateway target and restore the intended
experiment context/concurrency before calibration and 2-to-4 GPU scaling.
