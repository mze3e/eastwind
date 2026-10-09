#!/usr/bin/env bash
# Install Eastwind (Python >= 3.12, uv.lock) and build the static talk page.
# The page builder clears OPENAI_API_KEY and uses the offline echo model only.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if command -v uv >/dev/null 2>&1; then
  # The CLI imports the showcase, and that imports kognita.testing, which
  # imports pytest. The dev extra is the install the projector runbook uses.
  uv sync --frozen --extra dev
  uv run --no-sync python scripts/build_demo_page.py
else
  echo "uv unavailable; installing with pip into .venv" >&2
  py=""
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
        py="$candidate"
        break
      fi
    fi
  done
  if [[ -z "$py" ]]; then
    echo "Python >= 3.12 is required." >&2
    exit 1
  fi
  "$py" -m venv .venv
  .venv/bin/python -m pip install --disable-pip-version-check ".[dev]"
  .venv/bin/python scripts/build_demo_page.py
fi

test -s public/index.html
