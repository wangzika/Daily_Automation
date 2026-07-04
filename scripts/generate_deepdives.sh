#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

USER_DEEPDIVE_LIMIT="${DEEPDIVE_LIMIT-}"
USER_DEEPDIVE_FIGURES="${DEEPDIVE_FIGURES-}"
USER_DEEPDIVE_OUTPUT_DIR="${DEEPDIVE_OUTPUT_DIR-}"
USER_DIGEST_DATE="${DIGEST_DATE-}"
USER_DIGEST_JSON="${DIGEST_JSON-}"
USER_AUTOMATION_PYTHON="${AUTOMATION_PYTHON-}"
USER_PYTHON_BIN="${PYTHON_BIN-}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

[[ -n "$USER_DEEPDIVE_LIMIT" ]] && DEEPDIVE_LIMIT="$USER_DEEPDIVE_LIMIT"
[[ -n "$USER_DEEPDIVE_FIGURES" ]] && DEEPDIVE_FIGURES="$USER_DEEPDIVE_FIGURES"
[[ -n "$USER_DEEPDIVE_OUTPUT_DIR" ]] && DEEPDIVE_OUTPUT_DIR="$USER_DEEPDIVE_OUTPUT_DIR"
[[ -n "$USER_DIGEST_DATE" ]] && DIGEST_DATE="$USER_DIGEST_DATE"
[[ -n "$USER_DIGEST_JSON" ]] && DIGEST_JSON="$USER_DIGEST_JSON"
[[ -n "$USER_AUTOMATION_PYTHON" ]] && AUTOMATION_PYTHON="$USER_AUTOMATION_PYTHON"
[[ -n "$USER_PYTHON_BIN" ]] && PYTHON_BIN="$USER_PYTHON_BIN"

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
