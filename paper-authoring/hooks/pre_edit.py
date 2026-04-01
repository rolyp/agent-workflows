#!/usr/bin/env python3
"""PreToolUse hook for Edit. Reads tool input from stdin, checks with StatusTracker."""

import json
import sys
from pathlib import Path

# Import from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from status_tracker import StatusTracker


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    tracker = StatusTracker(Path.cwd())
    allowed, message = tracker.check_edit(file_path)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
