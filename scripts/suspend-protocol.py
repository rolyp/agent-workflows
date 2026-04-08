#!/usr/bin/env python3
"""Suspend protocol mode. Developer-only — run via ! prefix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_dev.workflow import WorkflowDev

wd = WorkflowDev(Path("."))
wd._suspend_protocol()
print("Protocol suspended. Resume with: python3 src/workflow_dev/workflow.py resume-protocol")
