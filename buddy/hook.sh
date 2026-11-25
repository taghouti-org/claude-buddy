#!/bin/sh
# Forwards a Claude Code hook event (JSON on stdin) to the Claude Buddy avatar.
# Never blocks or fails a session: silent no-op when the avatar is not running.
S="${XDG_RUNTIME_DIR:-/tmp}/claude-buddy.sock"
[ -S "$S" ] || exit 0
timeout 1 nc -N -U "$S" >/dev/null 2>&1
exit 0
