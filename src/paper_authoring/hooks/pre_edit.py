#!/usr/bin/env python3
"""PreToolUse hook for Edit. Dispatches to the active workflow's check_edit."""

import json
import sys
from pathlib import Path

# Add agent-workflows to path for imports
sys.path.insert(0, str(Path.cwd() / "workflow" / "agent-workflows" / "src"))
from dispatch import get_workflow


def main() -> None:
    tool_input = json.load(sys.stdin)
    inputs = tool_input.get("tool_input", {})
    file_path = inputs.get("file_path", "")
    old_string = inputs.get("old_string")
    new_string = inputs.get("new_string")
    if not file_path:
        return

    try:
        workflow = get_workflow(Path.cwd())
    except Exception:
        return  # fail open if workflow can't be constructed

    allowed, message = workflow.check_edit(file_path, old_string, new_string)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
