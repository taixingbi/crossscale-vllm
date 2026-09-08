#!/bin/sh
# Read a pinned S3 snapshot into a pod-local disk volume; never write to S3.
set -eu
: "${MODEL_BUCKET:?required}"
: "${MODEL_PREFIX:?required}"
MODEL_DIR=${MODEL_DIR:-/models/llama}
SNAPSHOT_FILE=${SNAPSHOT_FILE:-/model-bootstrap/model-snapshot.tsv}
mkdir -p "$MODEL_DIR"
while IFS="$(printf '\t')" read -r filename version bytes; do
  case "$filename" in ''|*[!a-zA-Z0-9._-]*|.*) echo 'Invalid snapshot filename' >&2; exit 1;; esac
  case "$bytes" in ''|*[!0-9]*) echo 'Invalid snapshot size' >&2; exit 1;; esac
  test -n "$version" && test "$version" != null
  target="$MODEL_DIR/$filename"
  # Atomic per-file replacement: an interrupted download is never used by vLLM.
  aws s3api get-object --bucket "$MODEL_BUCKET" --key "$MODEL_PREFIX/$filename" \
    --version-id "$version" "$target.partial" --no-cli-pager >/dev/null
  actual=$(wc -c < "$target.partial" | tr -d '[:space:]')
  test "$actual" = "$bytes" || { echo "Size mismatch: $filename" >&2; exit 1; }
  mv "$target.partial" "$target"
done < "$SNAPSHOT_FILE"
for filename in config.json tokenizer.json tokenizer_config.json model.safetensors.index.json \
  model-00001-of-00004.safetensors model-00002-of-00004.safetensors \
  model-00003-of-00004.safetensors model-00004-of-00004.safetensors; do
  test -s "$MODEL_DIR/$filename" || { echo "Missing model file: $filename" >&2; exit 1; }
done
