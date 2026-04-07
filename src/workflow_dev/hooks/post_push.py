#!/usr/bin/env python3
"""PostToolUse hook for Bash. Records pending CI run after git push."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Add agent-workflows root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from workflow_dev.workflow import WorkflowDev


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")

    if "git push" not in command:
        return

    wd = WorkflowDev(Path.cwd())
    env = wd._gh_env()

    # Brief wait for run to register
    time.sleep(3)

    result = subprocess.run(
        ["gh", "run", "list", "--limit", "1",
         "--json", "databaseId,status",
         "-q", ".[0].databaseId"],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"CI: could not determine run ID: {result.stderr}", file=sys.stderr)
        sys.exit(2)

    run_id = result.stdout.strip()

    # Record pending run in state
    stack = wd._read_stack()
    stack[-1]["pending_ci_run"] = run_id
    wd._save_stack(stack)
    print(f"CI: run {run_id} recorded; request-review will verify it passed", file=sys.stderr)


if __name__ == "__main__":
    main()
