#!/usr/bin/env bash
# Open the desired real app screen first, then capture it. Does not fake pairing or toggle state.
set -euo pipefail
TOOL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${PLAY_PROJECT_ROOT:-$PWD}"
if [[ "${1:-}" == '--project' ]]; then ROOT="${2:?project directory}"; shift 2; fi
ROOT="$(cd "$ROOT" && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/android-sdk}}"
SERIAL="${1:?usage: capture_play_screenshots.sh <adb-serial> <01-setup|02-privacy|03-toggle|name>}"
NAME="${2:?provide a screenshot name}"
[[ "$NAME" =~ ^[a-zA-Z0-9-]+$ ]] || { echo 'Use letters, numbers and hyphens for the name.' >&2; exit 1; }
ADB="${ADB_BINARY:-$SDK/platform-tools/adb}"
"$ADB" -s "$SERIAL" get-state > /dev/null
METADATA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata_path"])' "$ROOT/play/release.json")"
mkdir -p "$ROOT/build/play-captures" "$ROOT/$METADATA/ko-KR/images/phoneScreenshots"
RAW="$ROOT/build/play-captures/$NAME.png"
"$ADB" -s "$SERIAL" exec-out screencap -p > "$RAW"
java -Djava.awt.headless=true "$TOOL_ROOT/tools/StoreScreenshot.java" "$RAW" "$ROOT/$METADATA/ko-KR/images/phoneScreenshots/$NAME.png"
echo "Saved $NAME (actual device capture; raw original in build/play-captures)"
