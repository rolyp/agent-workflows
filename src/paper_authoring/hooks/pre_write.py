#!/usr/bin/env python3
"""PreToolUse hook for Write. Dispatches to the active workflow's check_write."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "workflow" / "agent-workflows" / "src"))
from dispatch import get_workflow


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    try:
        workflow = get_workflow(Path.cwd())
    except FileNotFoundError:
        return  # project doesn't use this workflow — allow through
    except Exception as e:
        print(f"Workflow construction failed: {e}", file=sys.stderr)
        sys.exit(2)  # fail closed

    allowed, message = workflow.check_write(file_path)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
