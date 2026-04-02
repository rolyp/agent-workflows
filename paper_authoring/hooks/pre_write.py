#!/usr/bin/env python3
"""PreToolUse hook for Write. Dispatches to the active workflow's check_write."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "workflow" / "agent-workflows"))
from dispatch import get_workflow


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    try:
        workflow = get_workflow(Path.cwd())
    except Exception:
        return  # fail open if workflow can't be constructed

    allowed, message = workflow.check_write(file_path)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
