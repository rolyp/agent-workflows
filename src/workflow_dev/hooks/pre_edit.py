#!/usr/bin/env python3
"""PreToolUse hook for Edit. Gates edits via WorkflowDev state machine."""

import json
import sys
from pathlib import Path


def _is_protocol_suspended():
    for sp in [Path("state.json"), Path.cwd() / "state.json"]:
        if sp.exists():
            try:
                sf = json.loads(sp.read_text())
                if isinstance(sf, dict): return sf.get("protocol_suspended", False)
            except: pass
    return False

# Add agent-workflows root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from workflow_dev.workflow import WorkflowDev


def main() -> None:
    tool_input = json.load(sys.stdin)
    inputs = tool_input.get("tool_input", {})
    file_path = inputs.get("file_path", "")
    old_string = inputs.get("old_string")
    new_string = inputs.get("new_string")
    if not file_path:
        return

    if _is_protocol_suspended():
        return

    if Path(file_path).name == "state.json":
        print("Cannot edit state.json directly. Use workflow.py commands.", file=sys.stderr)
        sys.exit(2)

    wd = WorkflowDev(Path.cwd())

    allowed, message = wd.check_edit(file_path, old_string, new_string)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
