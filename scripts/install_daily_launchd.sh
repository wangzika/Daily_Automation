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

TIME_VALUE="${1:-${AUTOMATION_TIME:-08:30}}"
if [[ ! "$TIME_VALUE" =~ ^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then
  echo "Usage: $0 [HH:MM]" >&2
  exit 2
fi

HOUR="${TIME_VALUE%%:*}"
MINUTE="${TIME_VALUE##*:}"
HOUR="$((10#$HOUR))"
MINUTE="$((10#$MINUTE))"

LABEL="com.codex.daily-gnss-slam-digest"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$PROJECT_DIR/outputs/logs"
mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_DIR/scripts/daily_automation.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd.err.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed launchd job: $LABEL"
echo "Schedule: daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
echo "Plist: $PLIST_PATH"
echo "Log dir: $LOG_DIR"
echo "Run once now with: launchctl kickstart -k gui/$(id -u)/$LABEL"
