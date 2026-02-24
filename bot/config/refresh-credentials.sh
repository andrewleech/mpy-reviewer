#!/bin/bash
# Copy the currently active Claude Code credentials into the bot's config
# volume. The bot's orchestrator sets CLAUDE_CONFIG_DIR=/config/claude-oauth/
# so claude -p looks for .claude.json and .credentials.json there.
#
# No container restart needed — new credentials take effect on the next
# claude -p invocation.
#
# Usage:
#   ./bot/config/refresh-credentials.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$SCRIPT_DIR/claude-oauth"

# Source locations (Claude Code defaults)
CLAUDE_JSON="$HOME/.claude.json"
CREDENTIALS_JSON="$HOME/.claude/.credentials.json"

# Fallback: .claude.json might be inside ~/.claude/
if [[ ! -f "$CLAUDE_JSON" ]]; then
    CLAUDE_JSON="$HOME/.claude/.claude.json"
fi

if [[ ! -f "$CLAUDE_JSON" ]]; then
    echo "Error: Cannot find .claude.json in ~/.claude.json or ~/.claude/.claude.json" >&2
    exit 1
fi

if [[ ! -f "$CREDENTIALS_JSON" ]]; then
    echo "Error: Cannot find $CREDENTIALS_JSON" >&2
    exit 1
fi

mkdir -p "$TARGET_DIR"

# Extract only the oauthAccount section (don't copy full config with history/prefs)
python3 -c "
import json, sys
with open('$CLAUDE_JSON') as f:
    full = json.load(f)
minimal = {k: v for k, v in full.items() if k == 'oauthAccount'}
if not minimal:
    print('Error: no oauthAccount in config', file=sys.stderr)
    sys.exit(1)
with open('$TARGET_DIR/.claude.json', 'w') as f:
    json.dump(minimal, f, indent=2)
"

cp "$CREDENTIALS_JSON" "$TARGET_DIR/.credentials.json"

# Lock down permissions
chmod 700 "$TARGET_DIR"
chmod 600 "$TARGET_DIR/.claude.json" "$TARGET_DIR/.credentials.json"

# Show what was copied
EMAIL=$(python3 -c "import json; print(json.load(open('$TARGET_DIR/.claude.json'))['oauthAccount']['emailAddress'])")
echo "Credentials copied for: $EMAIL"
echo "Target: $TARGET_DIR/"
