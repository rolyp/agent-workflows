#!/usr/bin/env python3
"""PreToolUse hook for Edit. Dispatches to the active workflow's check_edit."""

import json
import sys
from pathlib import Path

# Add agent-workflows to path for imports
sys.path.insert(0, str(Path.cwd() / "workflow" / "agent-workflows" / "src"))
from paper_authoring.workflow import PaperAuthoring


def main() -> None:
    tool_input = json.load(sys.stdin)
    inputs = tool_input.get("tool_input", {})
    file_path = inputs.get("file_path", "")
    old_string = inputs.get("old_string")
    new_string = inputs.get("new_string")
    if not file_path:
        return

    try:
        workflow = PaperAuthoring(Path.cwd())
    except FileNotFoundError:
        return  # project doesn't use this workflow — allow through
    except Exception as e:
        print(f"Workflow construction failed: {e}", file=sys.stderr)
        sys.exit(2)  # fail closed

    allowed, message = workflow.check_edit(file_path, old_string, new_string)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
