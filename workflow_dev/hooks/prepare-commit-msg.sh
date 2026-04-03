#!/bin/bash
# Git prepare-commit-msg hook: prepends workflow state tag to commit messages.
# e.g. [refactor/code] Your commit message
#
# Reads the current label from state.json to determine the tag.

COMMIT_MSG_FILE="$1"
COMMIT_SOURCE="$2"

# Only modify user-initiated commits (not merges, squashes, etc.)
if [ -n "$COMMIT_SOURCE" ]; then
    exit 0
fi

# Find state.json relative to repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
STATE_FILE="$REPO_ROOT/state.json"

if [ ! -f "$STATE_FILE" ]; then
    exit 0
fi

# Extract mode from top frame; derive tag
TAG=$(python3 -c "
import json, sys
stack = json.loads(open('$STATE_FILE').read())
state = stack[-1]
mode = state.get('mode', '')
phase = state.get('phase', '')
if mode == 'refactor-code':
    print('[refactor/code]')
elif mode == 'expand-coverage':
    print('[refactor/test]')
elif phase == 'modifying':
    print('[modify]')
elif phase == 'review':
    print('[review]')
else:
    print('[idle]')
" 2>/dev/null)

if [ -z "$TAG" ]; then
    exit 0
fi

# Check if message already has a tag
if head -1 "$COMMIT_MSG_FILE" | grep -q '^\['; then
    exit 0
fi

# Prepend tag
sed -i '' "1s/^/$TAG /" "$COMMIT_MSG_FILE"
