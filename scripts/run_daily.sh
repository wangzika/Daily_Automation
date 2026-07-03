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

if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m daily_gnss_slam_digest \
  --output-dir "${DIGEST_OUTPUT_DIR:-outputs}" \
  --limit "${DIGEST_LIMIT:-5}" \
  --days-back "${DIGEST_DAYS_BACK:-180}" \
  --publish-mode "${WECHAT_PUBLISH_MODE:-none}"
