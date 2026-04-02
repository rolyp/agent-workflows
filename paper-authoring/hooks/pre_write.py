#!/usr/bin/env python3
"""PreToolUse hook for Write. Blocks overwriting existing files."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from workflow import PaperAuthoring


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    tracker = PaperAuthoring(Path.cwd())
    allowed, message = tracker.check_write(file_path)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
