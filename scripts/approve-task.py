#!/usr/bin/env python3
"""Approve current task without running the review cycle. Developer-only — run via ! prefix."""

import json
from pathlib import Path

state_path = Path("state.json")
if not state_path.exists():
    print("No state.json found")
    raise SystemExit(1)

sf = json.loads(state_path.read_text())
stack = sf.get("stack", [])
if not stack:
    print("No task on the stack")
    raise SystemExit(1)

phase = stack[-1].get("phase")
if phase not in ("refactoring", "approved"):
    print(f"Cannot approve: current phase is '{phase}', expected 'refactoring'")
    raise SystemExit(1)

stack[-1]["phase"] = "approved"
state_path.write_text(json.dumps(sf, indent=2) + "\n")
print("Task approved. Run: python3 src/workflow_dev/workflow.py end-task")
