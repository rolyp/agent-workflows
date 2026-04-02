#!/usr/bin/env python3
"""PreToolUse hook for Write. Gates file creation via WorkflowDev state machine."""

import json
import sys
from pathlib import Path

# Add agent-workflows root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from workflow_dev.workflow import WorkflowDev


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    try:
        wd = WorkflowDev(Path.cwd())
    except Exception:
        return  # fail open

    allowed, message = wd.check_write(file_path)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
