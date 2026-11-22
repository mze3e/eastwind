#!/usr/bin/env bash
# Verify an exported chain with both implementations, then reject an edited copy.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/check_evidence.sh EXPORT.json" >&2
  exit 2
fi
artifact=$1
edited=$(mktemp "${TMPDIR:-/tmp}/eastwind-edited.XXXXXX")
trap 'rm -f -- "$edited"' EXIT
uv run --no-sync kognita evidence verify --file "$artifact"
uv run --no-sync eastwind evidence verify --file "$artifact" --with-npm
uv run --no-sync eastwind evidence tamper --file "$artifact" -o "$edited"
if uv run --no-sync kognita evidence verify --file "$edited"; then
  echo 'Python verifier accepted edited evidence' >&2
  exit 1
fi
if npx --yes @kognita/verify@0.9.0 "$edited"; then
  echo 'npm verifier accepted edited evidence' >&2
  exit 1
fi
if uv run --no-sync eastwind evidence verify --file "$edited" --with-npm; then
  echo 'Combined verifier accepted edited evidence' >&2
  exit 1
fi
echo 'Both verifiers rejected the edited copy.'
