#!/usr/bin/env python3
"""PostToolUse hook for Bash. Checks GitHub Actions status after git push."""

import json
import os
import subprocess
import sys
import time


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")

    if "git push" not in command:
        return

    # Wait briefly for the run to register
    time.sleep(3)

    gh_token = os.environ.get("GH_TOKEN", "")
    if not gh_token:
        return

    # Get the most recent run
    result = subprocess.run(
        ["gh", "run", "list", "--limit", "1", "--json", "databaseId,status,conclusion,headBranch,name"],
        capture_output=True, text=True,
        env={**os.environ, "GH_TOKEN": gh_token},
    )
    if result.returncode != 0:
        return  # fail open

    runs = json.loads(result.stdout)
    if not runs:
        return

    run = runs[0]
    run_id = run["databaseId"]
    status = run["status"]
    name = run.get("name", "CI")
    branch = run.get("headBranch", "")

    if status == "completed":
        conclusion = run.get("conclusion", "unknown")
        if conclusion == "success":
            print(f"✓ {name} ({branch}): passed", file=sys.stderr)
        else:
            print(f"✗ {name} ({branch}): {conclusion}", file=sys.stderr)
            print(f"  Run: gh run view {run_id}", file=sys.stderr)
    else:
        print(f"⋯ {name} ({branch}): {status}", file=sys.stderr)
        print(f"  Check: gh run view {run_id}", file=sys.stderr)


if __name__ == "__main__":
    main()
