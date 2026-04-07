#!/usr/bin/env python3
"""PostToolUse hook for Edit. Runs appropriate build/test after edits."""

import json
import subprocess
import sys
from pathlib import Path

SUBMODULE_DIR = "workflow/agent-workflows"


def _run(script: Path, cwd: Path) -> None:
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        sys.exit(1)
    else:
        output = result.stdout.strip()
        if output:
            print(output, file=sys.stderr)


def main() -> None:
    tool_input = json.load(sys.stdin)
    file_path = tool_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    root = Path.cwd()

    # Submodule Python edits: run test.sh
    if file_path.startswith(SUBMODULE_DIR) and file_path.endswith(".py"):
        test_script = root / SUBMODULE_DIR / "test.sh"
        if test_script.exists():
            _run(test_script, root / SUBMODULE_DIR)
        return

    # .tex edits: run LaTeX build
    if file_path.endswith(".tex"):
        build_script = root / SUBMODULE_DIR / "paper_authoring" / "build.sh"
        if build_script.exists():
            _run(build_script, root)


if __name__ == "__main__":
    main()
