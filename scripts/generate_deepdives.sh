#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

MODE="${1:-none}"
LIMIT="${DEEPDIVE_LIMIT:-3}"
TODAY="${DIGEST_DATE:-$(date +%F)}"
INPUT_JSON="${DIGEST_JSON:-outputs/${TODAY}-gnss-slam-digest.json}"

if [[ "$MODE" != "none" && "$MODE" != "draft" && "$MODE" != "publish" ]]; then
  echo "Usage: $0 [none|draft|publish]" >&2
  exit 2
fi

if [[ -n "${AUTOMATION_PYTHON:-}" ]]; then
  PYTHON="$AUTOMATION_PYTHON"
elif [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON="$PYTHON_BIN"
elif [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m daily_gnss_slam_digest.deepdive \
  --input-json "$INPUT_JSON" \
  --output-dir "${DEEPDIVE_OUTPUT_DIR:-outputs/deepdives}" \
  --limit "$LIMIT" \
  --figures "${DEEPDIVE_FIGURES:-2}" \
  --publish-mode "$MODE"
