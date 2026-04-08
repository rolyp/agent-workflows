#!/usr/bin/env python3
"""Approve current task without running the review cycle. Developer-only — run via ! prefix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_dev.workflow import WorkflowDev

wd = WorkflowDev(Path("."))
wd._approve_task()
print("Task approved.")
