#!/bin/bash
# Git post-commit hook: records the commit SHA in the active step frame.
# This ensures end-step links to the correct commit.

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
STATE_FILE="$REPO_ROOT/state.json"

if [ ! -f "$STATE_FILE" ]; then
    exit 0
fi

SHA=$(git rev-parse HEAD)

python3 -c "
import json, sys
sf = json.loads(open('$STATE_FILE').read())
if not isinstance(sf, dict) or 'stack' not in sf:
    sys.exit(0)
stack = sf['stack']
if len(stack) > 1 and stack[-1].get('step'):
    stack[-1]['last_commit'] = '$SHA'
    open('$STATE_FILE', 'w').write(json.dumps(sf, indent=2) + '\n')
" 2>/dev/null
