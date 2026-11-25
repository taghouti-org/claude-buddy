#!/bin/sh
# Installs Claude Buddy and the VRM viewer for the current user. No root needed.
#   ./install.sh                 install or update
#   ./install.sh --autostart     also start the avatar at login
#   ./install.sh --hooks         also add the Claude Code hooks to ~/.claude/settings.json (a backup is kept)
#   ./install.sh --uninstall     remove everything this script installed (hooks are left for you to remove)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SHARE="$HOME/.local/share"; BIN="$HOME/.local/bin"; APPS="$SHARE/applications"; AUTO="$HOME/.config/autostart"
PY=/usr/bin/python3

if [ "$1" = "--uninstall" ]; then
  rm -rf "$SHARE/claude-buddy" "$SHARE/vrm-viewer"
  rm -f "$BIN/claude-buddy" "$BIN/vrm-viewer" "$APPS/claude-buddy.desktop" "$APPS/vrm-viewer.desktop" "$AUTO/claude-buddy.desktop"
  echo "Removed. If you added the hooks, delete the claude-buddy entries from ~/.claude/settings.json."
  exit 0
fi

$PY - <<'PYEOF' || { echo "Missing system packages. On Debian/Ubuntu: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 python3-numpy netcat-openbsd"; exit 1; }
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1"); gi.require_foreign("cairo")
PYEOF

mkdir -p "$SHARE/claude-buddy/web" "$SHARE/vrm-viewer" "$BIN" "$APPS"
cp "$HERE/buddy/claude_buddy.py" "$HERE/buddy/hook.sh" "$SHARE/claude-buddy/"
cp "$HERE/buddy/web/avatar.html" "$SHARE/claude-buddy/web/"
cp "$HERE/viewer/vrm_viewer.py" "$HERE/viewer/index.html" "$SHARE/vrm-viewer/"
rm -rf "$SHARE/claude-buddy/web/lib" "$SHARE/vrm-viewer/lib"
cp -r "$HERE/vendor/lib" "$SHARE/claude-buddy/web/lib"
cp -r "$HERE/vendor/lib" "$SHARE/vrm-viewer/lib"
chmod +x "$SHARE/claude-buddy/hook.sh"

printf '#!/bin/sh\nexec %s "%s/claude-buddy/claude_buddy.py" "$@"\n' "$PY" "$SHARE" > "$BIN/claude-buddy"
printf '#!/bin/sh\nexec %s "%s/vrm-viewer/vrm_viewer.py" "$@"\n' "$PY" "$SHARE" > "$BIN/vrm-viewer"
chmod +x "$BIN/claude-buddy" "$BIN/vrm-viewer"
printf '[Desktop Entry]\nType=Application\nName=Claude Buddy\nComment=Animated desktop avatar for Claude Code\nExec=%s/claude-buddy\nIcon=face-smile\nCategories=Utility;\n' "$BIN" > "$APPS/claude-buddy.desktop"
printf '[Desktop Entry]\nType=Application\nName=VRM Viewer\nComment=View .vrm and .glb 3D avatars\nExec=%s/vrm-viewer %%f\nIcon=applications-graphics\nCategories=Graphics;Viewer;\n' "$BIN" > "$APPS/vrm-viewer.desktop"

for arg in "$@"; do
  case "$arg" in
    --autostart)
      mkdir -p "$AUTO"
      printf '[Desktop Entry]\nType=Application\nName=Claude Buddy\nExec=%s/claude-buddy\nX-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n' "$BIN" > "$AUTO/claude-buddy.desktop"
      echo "Autostart enabled." ;;
    --hooks)
      $PY - "$SHARE/claude-buddy/hook.sh" <<'PYEOF'
import json, os, shutil, sys, time
hook = sys.argv[1]
path = os.path.expanduser("~/.claude/settings.json")
data = json.load(open(path)) if os.path.exists(path) else {}
if os.path.exists(path):
    shutil.copy(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
hooks = data.setdefault("hooks", {})
for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification", "Stop", "SessionEnd"):
    groups = hooks.setdefault(event, [])
    if not any(h.get("command") == hook for g in groups for h in g.get("hooks", [])):
        groups.append({"hooks": [{"type": "command", "command": hook, "timeout": 3}]})
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(data, open(path, "w"), indent=2)
print("Hooks added to", path)
PYEOF
      ;;
  esac
done

echo "Installed. Start it with: claude-buddy"
[ -f "$SHARE/claude-buddy/avatar.vrm" ] || echo "No 3D model yet: it runs with the built-in 2D character. Copy a VRM to $SHARE/claude-buddy/avatar.vrm to use your own."
