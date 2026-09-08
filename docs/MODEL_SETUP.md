# Load Llama 3.1 8B Instruct from S3

The workload reads the existing registry at:

```text
s3://huggingface-model-registry-646821141010-us-east-1/inference/meta-llama/Llama-3.1-8B-Instruct/
```

The separate [registry project](https://github.com/taixingbi/huggingface-s3-model-registry)
owns uploads, the bucket, and model access through Hugging Face. CrossScale does
not modify that bucket or require an HF token at inference time.

## Download and startup

`deploy/model-snapshot.tsv` pins ten S3 object versions (16,069,722,669 bytes):
four safetensors shards, their index, and model/tokenizer configuration. The
current registry prefix is mutable; version IDs keep this deployment on the
reviewed snapshot even if the registry publishes newer objects. Retain these
versions in the registry's lifecycle policy. These S3 versions do not identify
the original Hugging Face commit; record that separately in experiment provenance.

An AWS CLI init container runs `deploy/download-model.sh`, downloads each version
into a disk-backed `emptyDir`, checks its byte count, and checks required files.
Failed downloads block vLLM startup. Size checks detect truncation; they are not
a cryptographic checksum audit. Container retries replace partial files; new
pods download the snapshot again. The 25 GiB volume is per pod, not a persistent
or node-shared cache. Record download time when measuring cold scale-out.

vLLM mounts `/models/llama` read-only, uses offline Hugging Face settings, and
serves the API model name `meta-llama/Llama-3.1-8B-Instruct`.

## AWS permissions

`infra/addons/model-reader.tf` defines a dedicated `crossscale-model-reader` role
and EKS Pod Identity association for `crossscale/vllm-model-reader`. Its trust is
restricted to that service account, namespace, and cluster ARN. It allows only:

- `s3:GetObjectVersion` within this model prefix.
- `kms:Decrypt` for the observed registry key, through regional S3 with this
  bucket's encryption context (including S3 Bucket Keys).

There are no model upload, deletion, bucket administration, or Terraform-state
permissions. The registry's generic `registry-read` role is not changed.
The EKS Pod Identity agent must be installed, and the KMS key policy must allow
this same-account role's IAM grant. If the registry changes encryption keys,
review and update the reader policy for all pinned versions.

## Deploy

First configure the add-ons root's separate durable Terraform backend and ensure
its deployment role can create/pass `crossscale-model-reader`, manage its inline
policy, and create its Pod Identity association. Plan and apply the add-ons
through the authorized deployment path. The cluster-only workflow does not apply
this root. Supply the gateway metrics target and verify the GPU runtime is ready.

The vLLM image is pinned by digest. Use the [one-GPU smoke workflow](GPU_SMOKE_TEST.md) for initial validation; the following base deployment requests two GPUs:

```sh
# The namespace is created by the add-ons GPU-pool release.
kubectl kustomize deploy > /tmp/crossscale-vllm.yaml
kubectl --context YOUR_CONTEXT apply -k deploy
kubectl --context YOUR_CONTEXT -n crossscale get pods -l app=vllm
kubectl --context YOUR_CONTEXT -n crossscale logs POD_NAME -c download-model
kubectl --context YOUR_CONTEXT -n crossscale logs POD_NAME -c vllm
```

Use `-k deploy`, not `-f deploy/vllm.yaml`: Kustomize generates the bootstrap
ConfigMap from the downloader and snapshot, and hashes its name so snapshot
changes trigger a rollout. Scaler manifests are deliberately not included;
install one separately after calibration. Applying this deployment requests two GPUs.

Validate startup and inference on the selected A10G 24 GB hardware. The existing
32,768-token context and 12 GiB host-memory limit have not been live validated for
this model. Preserve the model identity, record any memory tuning, and recalibrate.

This change provides the S3 loader and Terraform access configuration. It has not
yet applied the reader role/add-ons or deployed vLLM to the cluster.
