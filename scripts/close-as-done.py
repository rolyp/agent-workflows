#!/usr/bin/env python3
"""Close an issue whose work was already completed elsewhere. Developer-only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_dev.workflow import WorkflowDev

if len(sys.argv) < 2:
    print("Usage: close-as-done.py <issue-number>", file=sys.stderr)
    raise SystemExit(1)

wd = WorkflowDev(Path("."))
issue_number = sys.argv[1]
wd.begin_task(issue_number)
wd._approve_task()
wd.end_task()
print(f"Issue #{issue_number} closed as done.")
