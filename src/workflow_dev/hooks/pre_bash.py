#!/usr/bin/env python3
"""PreToolUse hook for Bash. Enforces protocol mode whitelist.

In protocol mode (default), only whitelisted commands are allowed.
Suspend with: ! python3 scripts/suspend-protocol.py
Resume with: python3 src/workflow_dev/workflow.py resume-protocol
"""

import json
import sys
from pathlib import Path

# Add agent-workflows root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from workflow_dev.workflow import WorkflowDev


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")

    if not command:
        return

    wd = WorkflowDev(Path.cwd())
    if wd.is_protocol_suspended():
        return

    allowed, message = wd.check_bash(command)
    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
