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
mkdir -p "$LOG_DIR"
: > "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1

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
STATUS=0
STEP_LINES=()
GITHUB_STATUS="GitHub push skipped."
GITHUB_COMMIT_URL=""

run_step() {
  local label="$1"
  shift
  echo
  echo "==> $label"
  "$@"
  local rc=$?
  STEP_LINES+=("$label: exit $rc")
  if [[ $rc -ne 0 && $STATUS -eq 0 ]]; then
    STATUS=$rc
  fi
  return 0
}

validate_mode() {
  local mode="$1"
  [[ "$mode" == "none" || "$mode" == "draft" || "$mode" == "publish" ]]
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
    git init
    git branch -M "${GITHUB_BRANCH:-main}"
    git remote add origin "$remote_url"
  fi

  if ! git remote get-url origin >/dev/null 2>&1; then
    if [[ -z "$remote_url" ]]; then
      GITHUB_STATUS="GitHub push skipped: origin remote is missing and GITHUB_REPO_URL is not set."
      echo "$GITHUB_STATUS"
      return 0
    fi
    git remote add origin "$remote_url"
  fi

  if ! git config user.name >/dev/null; then
    git config user.name "${GIT_AUTHOR_NAME:-GNSS Paper Bot}"
  fi
  if ! git config user.email >/dev/null; then
    git config user.email "${GIT_AUTHOR_EMAIL:-automation@example.local}"
  fi

  git add .gitignore .env.example README.md pyproject.toml scripts src tests outputs
  if git diff --cached --quiet; then
    GITHUB_STATUS="GitHub push skipped: no file changes to commit."
    echo "$GITHUB_STATUS"
    return 0
  fi

  git commit -m "${GIT_COMMIT_MESSAGE:-daily digest ${RUN_DATE}}"
  local branch
  branch="$(git branch --show-current)"
  if [[ -z "$branch" ]]; then
    branch="${GITHUB_BRANCH:-main}"
    git branch -M "$branch"
  fi
  git push -u origin "$branch"

  local sha
  local remote
  sha="$(git rev-parse --short HEAD)"
  remote="$(git remote get-url origin)"
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
  if [[ -f "$DIGEST_JSON" ]]; then
    run_step "Generate deep-dive articles and WeChat drafts" ./scripts/generate_deepdives.sh "$DEEPDIVE_MODE"
  else
    echo "Deep-dive generation skipped: digest JSON does not exist: $DIGEST_JSON" >&2
    STEP_LINES+=("Generate deep-dive articles and WeChat drafts: skipped, missing digest JSON")
    if [[ $STATUS -eq 0 ]]; then
      STATUS=2
    fi
  fi
  run_step "Commit and push generated files to GitHub" push_to_github
fi

{
  echo "每日 GNSS/SLAM 自动化已完成。"
  echo "日期：$RUN_DATE"
  echo "结果码：$STATUS"
  echo "公众号后台草稿箱：${WECHAT_BACKEND_URL:-https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&action=list&lang=zh_CN}"
  echo "本地日志：$PROJECT_DIR/$LOG_FILE"
  echo "每日推荐 JSON：$PROJECT_DIR/$DIGEST_JSON"
  echo "$GITHUB_STATUS"
  if [[ -n "$GITHUB_COMMIT_URL" ]]; then
    echo "GitHub commit：$GITHUB_COMMIT_URL"
  fi
  echo
  echo "步骤："
  printf '%s\n' "${STEP_LINES[@]}"
} > "$SUMMARY_FILE"

"$PYTHON" -m daily_gnss_slam_digest.notify \
  --subject "每日 GNSS/SLAM 自动化完成｜${RUN_DATE}" \
  --body-file "$SUMMARY_FILE" || true

echo
echo "Daily GNSS/SLAM automation finished with status $STATUS"
exit "$STATUS"
