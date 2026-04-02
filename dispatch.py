"""Dispatch to the appropriate workflow based on the state stack."""

from pathlib import Path

from base import Workflow
from paper_authoring.workflow import PaperAuthoring


def get_workflow(project_root: Path) -> Workflow:
    """Return the workflow instance for the project.

    Currently always returns PaperAuthoring. WorkflowDev is a standalone
    workflow, not dispatched from here.
    """
    return PaperAuthoring(project_root)
