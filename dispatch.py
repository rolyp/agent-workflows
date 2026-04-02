"""Dispatch to the appropriate workflow based on the state stack."""

import json
from pathlib import Path

from base import Workflow, WORKFLOW_DEV_PHASE
from paper_authoring.workflow import PaperAuthoring
from workflow_dev.workflow import WorkflowDev



def get_workflow(project_root: Path) -> Workflow:
    """Read the state stack and return the appropriate workflow instance.

    If the top frame is workflow_dev, returns WorkflowDev.
    Otherwise returns PaperAuthoring (which handles its own state).
    Falls back to PaperAuthoring if state.json doesn't exist.
    """
    state_path = project_root / "workflow" / "state.json"
    if state_path.exists():
        stack = json.loads(state_path.read_text())
        if stack and stack[-1].get("phase") == WORKFLOW_DEV_PHASE:
            return WorkflowDev(project_root)
    return PaperAuthoring(project_root)
