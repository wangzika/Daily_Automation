#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1
export PATH="$PROJECT_DIR/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

RUN_DATE="${DIGEST_DATE:-$(date +%F)}"
LOG_DIR="${AUTOMATION_LOG_DIR:-outputs/logs}"
LOG_FILE="$LOG_DIR/${RUN_DATE}-daily-automation.log"
SUMMARY_FILE="$LOG_DIR/${RUN_DATE}-daily-automation-summary.txt"
LOCK_DIR="${AUTOMATION_LOCK_DIR:-$LOG_DIR/.daily-automation.lock}"
mkdir -p "$LOG_DIR"
: > "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1

cleanup_lock() {
  if [[ -n "${LOCK_ACQUIRED:-}" ]]; then
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_ACQUIRED=1
    echo "$$" > "$LOCK_DIR/pid"
    trap cleanup_lock EXIT
    return 0
  fi

  local lock_pid=""
  if [[ -f "$LOCK_DIR/pid" ]]; then
    lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  fi
  if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
    echo "Another daily automation run is already active with pid $lock_pid." >&2
    exit 75
  fi

  echo "Found stale automation lock; replacing it."
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_ACQUIRED=1
    echo "$$" > "$LOCK_DIR/pid"
    trap cleanup_lock EXIT
    return 0
  fi

  echo "Could not acquire automation lock: $LOCK_DIR" >&2
  exit 75
}

if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

export DIGEST_DATE="$RUN_DATE"
export DIGEST_JSON="${DIGEST_JSON:-outputs/${RUN_DATE}-gnss-slam-digest.json}"
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

WECHAT_MODE="${AUTOMATION_WECHAT_MODE:-${WECHAT_PUBLISH_MODE:-draft}}"
DEEPDIVE_MODE="${AUTOMATION_DEEPDIVE_MODE:-$WECHAT_MODE}"
WEEKLY_SUMMARY_ENABLED="${WEEKLY_SUMMARY_ENABLED:-1}"
WEEKLY_SUMMARY_DAY="${WEEKLY_SUMMARY_DAY:-5}"
STATUS=0
STEP_LINES=()
WARNINGS=()
GITHUB_STATUS="GitHub push skipped."
GITHUB_COMMIT_URL=""
GITHUB_REPO_WEB_URL=""
LAST_STEP_RC=0

run_step() {
  local label="$1"
  shift
  local start_ts
  local end_ts
  local elapsed
  echo
  echo "==> $label"
  start_ts="$(date +%s)"
  "$@"
  local rc=$?
  end_ts="$(date +%s)"
  elapsed=$((end_ts - start_ts))
  LAST_STEP_RC=$rc
  if [[ $rc -eq 0 ]]; then
    STEP_LINES+=("$label: OK (${elapsed}s)")
  else
    STEP_LINES+=("$label: FAILED exit $rc (${elapsed}s)")
  fi
  if [[ $rc -ne 0 && $STATUS -eq 0 ]]; then
    STATUS=$rc
  fi
  return 0
}

validate_mode() {
  local mode="$1"
  [[ "$mode" == "none" || "$mode" == "draft" || "$mode" == "publish" ]]
}

is_enabled() {
  local value="$1"
  [[ "$value" != "0" && "$value" != "false" && "$value" != "False" && "$value" != "no" && "$value" != "off" ]]
}

github_commit_url() {
  local remote="$1"
  local sha="$2"
  if [[ "$remote" == git@github.com:* ]]; then
    local path="${remote#git@github.com:}"
    path="${path%.git}"
    echo "https://github.com/${path}/commit/${sha}"
  elif [[ "$remote" == https://github.com/* ]]; then
    local path="${remote#https://github.com/}"
    path="${path%.git}"
    echo "https://github.com/${path}/commit/${sha}"
  fi
}

github_repo_url() {
  local remote="$1"
  if [[ "$remote" == git@github.com:* ]]; then
    local path="${remote#git@github.com:}"
    path="${path%.git}"
    echo "https://github.com/${path}"
  elif [[ "$remote" == https://github.com/* ]]; then
    local path="${remote#https://github.com/}"
    path="${path%.git}"
    echo "https://github.com/${path}"
  fi
}

warn_missing_optional_command() {
  local command_name="$1"
  local note="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    WARNINGS+=("$command_name not found: $note")
  fi
}

push_to_github() {
  if ! command -v git >/dev/null 2>&1; then
    GITHUB_STATUS="GitHub push skipped: git command not found."
    echo "$GITHUB_STATUS"
    return 0
  fi

  local remote_url="${GITHUB_REPO_URL:-${GITHUB_REPO_SSH:-}}"

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ -z "$remote_url" ]]; then
      GITHUB_STATUS="GitHub push skipped: this folder is not a git repo and GITHUB_REPO_URL is not set."
      echo "$GITHUB_STATUS"
      return 0
    fi
    git init || return $?
    git branch -M "${GITHUB_BRANCH:-main}" || return $?
    git remote add origin "$remote_url" || return $?
  fi

  if ! git remote get-url origin >/dev/null 2>&1; then
    if [[ -z "$remote_url" ]]; then
      GITHUB_STATUS="GitHub push skipped: origin remote is missing and GITHUB_REPO_URL is not set."
      echo "$GITHUB_STATUS"
      return 0
    fi
    git remote add origin "$remote_url" || return $?
  fi

  if ! git config user.name >/dev/null; then
    git config user.name "${GIT_AUTHOR_NAME:-GNSS Paper Bot}" || return $?
  fi
  if ! git config user.email >/dev/null; then
    git config user.email "${GIT_AUTHOR_EMAIL:-automation@example.local}" || return $?
  fi

  git add .gitignore .env.example README.md pyproject.toml scripts src tests outputs || return $?
  if git diff --cached --quiet; then
    GITHUB_STATUS="GitHub push skipped: no file changes to commit."
    echo "$GITHUB_STATUS"
    return 0
  fi

  git commit -m "${GIT_COMMIT_MESSAGE:-daily digest ${RUN_DATE}}" || return $?
  local branch
  branch="$(git branch --show-current)"
  if [[ -z "$branch" ]]; then
    branch="${GITHUB_BRANCH:-main}"
    git branch -M "$branch" || return $?
  fi

  if git fetch origin "$branch" >/dev/null 2>&1; then
    if git rev-parse --verify "origin/$branch" >/dev/null 2>&1; then
      git rebase "origin/$branch" || return $?
    fi
  else
    echo "GitHub pre-push fetch skipped or failed; push will report the final result."
  fi

  git push -u origin "$branch" || return $?

  local sha
  local remote
  sha="$(git rev-parse --short HEAD)" || return $?
  remote="$(git remote get-url origin)" || return $?
  GITHUB_REPO_WEB_URL="$(github_repo_url "$remote")"
  GITHUB_COMMIT_URL="$(github_commit_url "$remote" "$sha")"
  if [[ -n "$GITHUB_COMMIT_URL" ]]; then
    GITHUB_STATUS="GitHub pushed: $GITHUB_COMMIT_URL"
  else
    GITHUB_STATUS="GitHub pushed commit: $sha"
  fi
  echo "$GITHUB_STATUS"
}

echo "Daily GNSS/SLAM automation started at $(date '+%F %T')"
echo "Project: $PROJECT_DIR"
echo "Run date: $RUN_DATE"
echo "Digest JSON: $DIGEST_JSON"
echo "WeChat mode: $WECHAT_MODE"
echo "Deep-dive mode: $DEEPDIVE_MODE"
echo "Weekly summary: $WEEKLY_SUMMARY_ENABLED on weekday $WEEKLY_SUMMARY_DAY"

acquire_lock
warn_missing_optional_command "pdftotext" "PDF text extraction may be weaker."
warn_missing_optional_command "pdfimages" "Paper figure extraction may be weaker."
warn_missing_optional_command "pdftoppm" "PDF page fallback rendering may be unavailable."

if ! validate_mode "$WECHAT_MODE"; then
  echo "Invalid AUTOMATION_WECHAT_MODE: $WECHAT_MODE" >&2
  STATUS=2
fi
if ! validate_mode "$DEEPDIVE_MODE"; then
  echo "Invalid AUTOMATION_DEEPDIVE_MODE: $DEEPDIVE_MODE" >&2
  STATUS=2
fi

if [[ $STATUS -eq 0 ]]; then
  run_step "Generate daily digest and WeChat draft" ./scripts/publish_now.sh "$WECHAT_MODE"
  DIGEST_RC=$LAST_STEP_RC
  if [[ -f "$DIGEST_JSON" ]]; then
    if [[ $DIGEST_RC -ne 0 ]]; then
      WARNINGS+=("Daily digest step exited $DIGEST_RC, but $DIGEST_JSON exists, so deep-dive generation continued.")
    fi
    run_step "Generate deep-dive articles and WeChat drafts" ./scripts/generate_deepdives.sh "$DEEPDIVE_MODE"
    if is_enabled "$WEEKLY_SUMMARY_ENABLED" && [[ "$(date -j -f "%F" "$RUN_DATE" "+%u" 2>/dev/null || date -d "$RUN_DATE" "+%u" 2>/dev/null || date "+%u")" == "$WEEKLY_SUMMARY_DAY" ]]; then
      run_step "Generate weekly hot-topic summary" ./scripts/generate_weekly_summary.sh "$RUN_DATE"
    fi
  else
    echo "Deep-dive generation skipped: digest JSON does not exist: $DIGEST_JSON" >&2
    STEP_LINES+=("Generate deep-dive articles and WeChat drafts: skipped, missing digest JSON")
    if [[ $STATUS -eq 0 ]]; then
      STATUS=2
    fi
  fi
  run_step "Commit and push generated files to GitHub" push_to_github
fi

if [[ $STATUS -eq 0 ]]; then
  SUMMARY_STATUS_TEXT="成功"
else
  SUMMARY_STATUS_TEXT="失败"
fi

{
  echo "每日 GNSS/SLAM 自动化${SUMMARY_STATUS_TEXT}。"
  echo "日期：$RUN_DATE"
  echo "结果码：$STATUS"
  echo "公众号后台草稿箱：${WECHAT_BACKEND_URL:-https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&action=list&lang=zh_CN}"
  echo "本地日志：$PROJECT_DIR/$LOG_FILE"
  echo "每日推荐 JSON：$PROJECT_DIR/$DIGEST_JSON"
  echo "$GITHUB_STATUS"
  if [[ -n "$GITHUB_REPO_WEB_URL" ]]; then
    echo "GitHub 仓库：$GITHUB_REPO_WEB_URL"
  fi
  if [[ -n "$GITHUB_COMMIT_URL" ]]; then
    echo "GitHub commit：$GITHUB_COMMIT_URL"
  fi
  if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    echo
    echo "提醒："
    printf '%s\n' "${WARNINGS[@]}"
  fi
  echo
  echo "步骤："
  printf '%s\n' "${STEP_LINES[@]}"
  echo
  echo "最近日志："
  tail -n "${AUTOMATION_LOG_TAIL_LINES:-60}" "$LOG_FILE"
} > "$SUMMARY_FILE"

"$PYTHON" -m daily_gnss_slam_digest.notify \
  --subject "每日 GNSS/SLAM 自动化${SUMMARY_STATUS_TEXT}｜${RUN_DATE}" \
  --body-file "$SUMMARY_FILE" || true

echo
echo "Daily GNSS/SLAM automation finished with status $STATUS"
exit "$STATUS"
