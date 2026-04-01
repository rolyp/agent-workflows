#!/usr/bin/env python3
"""PostToolUse hook for Edit. Runs build after .tex file edits."""

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith(".tex"):
        return

    build_script = Path.cwd() / "workflow" / "agent-workflows" / "paper-authoring" / "build.sh"
    if not build_script.exists():
        return

    result = subprocess.run(
        ["bash", str(build_script)],
        capture_output=True, text=True, cwd=Path.cwd(),
    )
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        sys.exit(1)
    else:
        print(result.stdout.strip(), file=sys.stderr)


if __name__ == "__main__":
    main()
