#!/usr/bin/env bash
# Run one command with temporary credentials, without changing the parent shell.
# Usage: scripts/with-aws-role.sh ACCOUNT_ID_OR_ROLE_ARN COMMAND [ARG...]
set +x
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 ACCOUNT_ID_OR_ROLE_ARN COMMAND [ARG...]" >&2
  exit 2
fi

target="$1"
shift
if [[ "$target" =~ ^[0-9]{12}$ ]]; then
  role_arn="arn:aws:iam::${target}:role/${ORG_ACCESS_ROLE:-OrganizationAccountAccessRole}"
elif [[ "$target" =~ ^arn:aws(-[a-z]+)*:iam::[0-9]{12}:role/.+$ ]]; then
  role_arn="$target"
else
  echo "error: provide a 12-digit account ID or an IAM role ARN" >&2
  exit 2
fi

# AWS_PROFILE (if set) selects the source identity for this call.
credentials="$(aws sts assume-role \
  --role-arn "$role_arn" \
  --role-session-name crossscale \
  --duration-seconds 3600 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)"
IFS=$'\t' read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN <<< "$credentials"
unset credentials
if [[ -z "$AWS_ACCESS_KEY_ID" || -z "$AWS_SECRET_ACCESS_KEY" || -z "$AWS_SESSION_TOKEN" || "$AWS_SESSION_TOKEN" == None ]]; then
  echo "error: STS did not return complete temporary credentials" >&2
  exit 1
fi
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
# Do not let a source profile or web-identity configuration override the session.
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ROLE_ARN AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_SESSION_NAME
exec "$@"
