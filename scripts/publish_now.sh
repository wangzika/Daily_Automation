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

MODE="${1:-${WECHAT_PUBLISH_MODE:-draft}}"
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

if [[ -n "${DIGEST_DATE:-}" ]]; then
  PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m daily_gnss_slam_digest \
    --output-dir "${DIGEST_OUTPUT_DIR:-outputs}" \
    --limit "${DIGEST_LIMIT:-5}" \
    --days-back "${DIGEST_DAYS_BACK:-180}" \
    --publish-mode "$MODE" \
    --issue-date "$DIGEST_DATE"
else
  PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m daily_gnss_slam_digest \
    --output-dir "${DIGEST_OUTPUT_DIR:-outputs}" \
    --limit "${DIGEST_LIMIT:-5}" \
    --days-back "${DIGEST_DAYS_BACK:-180}" \
    --publish-mode "$MODE"
fi
