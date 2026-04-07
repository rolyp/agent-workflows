#!/usr/bin/env python3
"""Suspend protocol mode. Developer-only — run via ! prefix."""

import json
from pathlib import Path

state_path = Path("state.json")
if not state_path.exists():
    print("No state.json found")
    raise SystemExit(1)

sf = json.loads(state_path.read_text())
sf["protocol_suspended"] = True
state_path.write_text(json.dumps(sf, indent=2) + "\n")
print("Protocol suspended. Resume with: python3 src/workflow_dev/workflow.py resume-protocol")
