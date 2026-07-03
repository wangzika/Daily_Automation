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

END_DATE="${1:-${DIGEST_DATE:-$(date +%F)}}"

if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m daily_gnss_slam_digest.weekly \
  --input-dir "${DIGEST_OUTPUT_DIR:-outputs}" \
  --output-dir "${WEEKLY_OUTPUT_DIR:-outputs/weekly}" \
  --end-date "$END_DATE" \
  --days "${WEEKLY_SUMMARY_DAYS:-7}"
