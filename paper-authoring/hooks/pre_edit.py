#!/usr/bin/env python3
"""PreToolUse hook for Edit. Reads tool input from stdin, checks with StatusTracker."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from status_tracker import StatusTracker


def main() -> None:
    tool_input = json.load(sys.stdin)
    inputs = tool_input.get("tool_input", {})
    file_path = inputs.get("file_path", "")
    old_string = inputs.get("old_string")
    new_string = inputs.get("new_string")
    if not file_path:
        return

    tracker = StatusTracker(Path.cwd())
    allowed, message = tracker.check_edit(file_path, old_string, new_string)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
