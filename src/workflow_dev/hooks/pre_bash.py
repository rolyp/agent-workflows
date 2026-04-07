#!/usr/bin/env python3
"""PreToolUse hook for Bash. Enforces protocol mode whitelist.

In protocol mode (default), only whitelisted commands are allowed.
Suspend with: ! python3 workflow_dev/workflow.py suspend-protocol
Resume with: ! python3 workflow_dev/workflow.py resume-protocol
"""

import json
import re
import sys
from pathlib import Path


# Read-only command prefixes (always allowed)
READ_ONLY = (
    "git log", "git status", "git diff", "git show",
    "git branch", "git remote", "git fetch",
    "cat ", "head ", "tail ", "ls", "wc ", "find ",
    "grep ", "rg ", "echo ",
    "python3 -m pytest",
    "gh issue view",
    "gh pr view",
    "gh run view",
    "gh run list",
)

# Workflow commands (always allowed)
WORKFLOW = (
    "python3 src/workflow_dev/workflow.py",
    "bash test/test.sh",
)


def _is_whitelisted(command: str) -> bool:
    """Check if a command matches the whitelist."""
    cmd = command.strip()
    for prefix in READ_ONLY + WORKFLOW:
        if cmd.startswith(prefix):
            return True
    return False


def _is_protocol_suspended() -> bool:
    """Check if protocol is suspended via state.json flag."""
    for state_path in [Path("state.json"), Path.cwd() / "state.json"]:
        if state_path.exists():
            try:
                sf = json.loads(state_path.read_text())
                if isinstance(sf, dict):
                    return sf.get("protocol_suspended", False)
            except (json.JSONDecodeError, OSError):
                pass
    return False


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")

    if not command:
        return

    if _is_protocol_suspended():
        return

    if _is_whitelisted(command):
        return

    print(
        f"Command blocked by protocol: {command[:80]}...\n"
        "Only read-only commands and workflow.py commands are allowed.\n"
        "Ask the Developer to suspend the protocol if needed.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
