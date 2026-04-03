#!/usr/bin/env python3
"""PostToolUse hook for Bash. Reminds Dev Assistant to watch CI after git push."""

import json
import sys


def main() -> None:
    tool_input = json.load(sys.stdin)
    command = tool_input.get("tool_input", {}).get("command", "")

    if "git push" not in command:
        return

    print(
        "CI triggered. Spawn a background agent to watch: "
        "gh run watch --exit-status --repo rolyp/agent-workflows",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
