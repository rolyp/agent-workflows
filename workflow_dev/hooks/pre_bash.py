#!/usr/bin/env python3
"""PreToolUse hook for Bash. Blocks commands that directly manipulate state.json."""

import json
import sys


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")

    if "state.json" in command:
        # Allow workflow.py commands (they go through the proper API)
        if "workflow.py" in command or "workflow_dev/workflow.py" in command:
            return
        print(
            "Direct manipulation of state.json is blocked. "
            "Use workflow.py commands to change workflow state.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
