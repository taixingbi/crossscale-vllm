#!/bin/bash
# Dedicated unjoined EC2 builder only. No cluster identity or model is baked.
set -euo pipefail
exec > >(tee /var/log/crossscale-image-bake.log /dev/console) 2>&1
systemctl stop kubelet || true
systemctl start containerd
ctr --namespace k8s.io images pull public.ecr.aws/aws-cli/aws-cli:2.36.17
ctr --namespace k8s.io images pull docker.io/vllm/vllm-openai:v0.28.0-cu129-ubuntu2404@sha256:56b291b6179fe5e6e6ad5c509d362e745280ccdbe81ecbc0f5155b1cab0ebfc5
ctr --namespace k8s.io images list > /var/log/crossscale-baked-images.txt
test ! -f /var/lib/kubelet/pki/kubelet-client-current.pem
touch /var/lib/crossscale-image-bake.complete
echo CROSSSCALE_IMAGE_BAKE_COMPLETE
sync
shutdown -h now
