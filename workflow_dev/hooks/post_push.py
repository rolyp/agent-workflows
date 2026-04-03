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

    gh_token = os.environ.get("GH_TOKEN", "")
    if not gh_token:
        print("CI: GH_TOKEN not set, cannot track CI run", file=sys.stderr)
        sys.exit(2)

    # Brief wait for run to register
    time.sleep(3)

    result = subprocess.run(
        ["gh", "run", "list", "--limit", "1",
         "--json", "databaseId,status",
         "-q", ".[0].databaseId"],
        capture_output=True, text=True,
        env={**os.environ, "GH_TOKEN": gh_token},
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"CI: could not determine run ID: {result.stderr}", file=sys.stderr)
        sys.exit(2)

    run_id = result.stdout.strip()

    # Record pending run in state
    try:
        wd = WorkflowDev(Path.cwd())
        stack = wd._read_stack()
        stack[-1]["pending_ci_run"] = run_id
        wd._save_stack(stack)
        print(f"CI: run {run_id} recorded; request-review will verify it passed", file=sys.stderr)
    except Exception as e:
        print(f"CI: could not record run: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
