#!/usr/bin/env python3
"""PreToolUse hook for Bash. Dispatches to the active workflow's check_bash."""

import json
import sys
from pathlib import Path

# Add agent-workflows to path for imports
sys.path.insert(0, str(Path.cwd() / "workflow" / "agent-workflows" / "src"))
from dispatch import get_workflow


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")
    if not command:
        return

    try:
        workflow = get_workflow(Path.cwd())
    except FileNotFoundError:
        return  # project doesn't use this workflow — allow through
    except Exception as e:
        print(f"Workflow construction failed: {e}", file=sys.stderr)
        sys.exit(2)  # fail closed

    allowed, message = workflow.check_bash(command)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
