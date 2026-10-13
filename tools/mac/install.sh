#!/bin/bash
# Sets up the daily Dropbox check for the AFOOFT recipe site on this Mac.
#   bash install.sh          install (or reinstall) and run one check now
#   bash install.sh remove   stop the daily check
set -euo pipefail

WORK="$HOME/afooft-sync"
LABEL="com.afooft.recipe-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "remove" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Daily Dropbox check removed. $WORK was left in place."
  exit 0
fi

mkdir -p "$WORK"
[ -d "$WORK/source/.git" ] || git clone --depth 1 https://github.com/sbb151/afooft-recipes-source "$WORK/source"
[ -d "$WORK/website/.git" ] || git clone --depth 1 https://github.com/sbb151/afooft-recipes-website "$WORK/website"
for r in source website; do
  # commits from the check need an author; use the repo owner's GitHub no-reply address
  git -C "$WORK/$r" config user.name >/dev/null || git -C "$WORK/$r" config user.name "Sam"
  git -C "$WORK/$r" config user.email >/dev/null || git -C "$WORK/$r" config user.email "98620916+sbb151@users.noreply.github.com"
done

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$WORK/website/tools/mac/afooft_sync.py</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>$WORK/sync.log</string>
  <key>StandardErrorPath</key><string>$WORK/sync.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Running a first check now (macOS may ask to allow access to Dropbox)..."
/usr/bin/python3 "$WORK/website/tools/mac/afooft_sync.py"
echo "Done. The check now runs every day at 7:00 (or when the Mac next wakes). Log: $WORK/sync.log"
