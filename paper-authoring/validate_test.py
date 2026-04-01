#!/usr/bin/env python3
"""Tests for validate.py."""

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from validate import validate

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.md"


def _make_dashboard(
    structural_tasks: list[str] | None = None,
    minor_tasks: list[str] | None = None,
    in_progress: list[str] | None = None,
) -> str:
    """Build a dashboard from the template, injecting tasks."""
    dashboard = TEMPLATE_PATH.read_text()
    structural = structural_tasks or []
    minor = minor_tasks or []
    ip = in_progress or []

    # Update counts
    dashboard = dashboard.replace(
        f"minor issues](todo/completed.md#minor) (0 of 0)",
        f"minor issues](todo/completed.md#minor) (0 of {len(minor)})",
    )
    dashboard = dashboard.replace(
        f"structural tasks](todo/completed.md#structural) (0 of 0)",
        f"structural tasks](todo/completed.md#structural) (0 of {len(structural)})",
    )

    # Inject in-progress
    if ip:
        dashboard = dashboard.replace(
            "## In progress\n\n(none)",
            "## In progress\n\n" + "\n".join(ip),
        )

    # Inject structural to-do items
    if structural:
        dashboard = re.sub(
            r"(### Structural\n\n)(.*?)$",
            "\\1" + "\n".join(f"- {t}" for t in structural) + "\n",
            dashboard,
            flags=re.DOTALL,
        )

    # Inject minor to-do items
    if minor:
        dashboard = re.sub(
            r"(### Minor\n\n)\(none\)",
            "\\1" + "\n".join(f"- {t}" for t in minor),
            dashboard,
        )

    return dashboard


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _setup_project(self, dashboard: str | None = None):
        os.makedirs("workflow/todo", exist_ok=True)
        os.makedirs("sec", exist_ok=True)
        with open("workflow/dashboard.md", "w") as f:
            f.write(dashboard or _make_dashboard(structural_tasks=["Task one", "Task two"]))
        with open("workflow/todo/structural.md", "w") as f:
            f.write("# Structural Review Notes\n")
        with open("workflow/todo/completed.md", "w") as f:
            f.write("# Completed\n\n## Minor\n\n## Structural\n")

    def test_no_workflow_files(self):
        errors = validate()
        self.assertIn("Missing: workflow/dashboard.md", errors)
        self.assertIn("Missing: workflow/todo/structural.md", errors)
        self.assertIn("Missing: workflow/todo/completed.md", errors)

    def test_clean_state(self):
        self._setup_project()
        self.assertEqual(validate(), [])

    def test_orphaned_select_markers(self):
        self._setup_project()
        with open("sec/test.tex", "w") as f:
            f.write("\\selectstart some text \\selectend\n")
        errors = validate()
        self.assertTrue(any("Orphaned \\selectstart" in e for e in errors))

    def test_orphaned_review_markers(self):
        self._setup_project()
        with open("sec/test.tex", "w") as f:
            f.write("\\reviewstart some text \\reviewend\n")
        errors = validate()
        self.assertTrue(any("Orphaned \\reviewstart" in e for e in errors))

    def test_in_progress_without_markers(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        errors = validate()
        self.assertTrue(any("no select/review markers" in e for e in errors))

    def test_multiple_in_progress(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Task A", "🔵 Task B"],
        ))
        errors = validate()
        self.assertTrue(any("Multiple in-progress" in e for e in errors))

    def test_coexisting_markers(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        with open("sec/a.tex", "w") as f:
            f.write("\\selectstart text \\selectend\n")
        with open("sec/b.tex", "w") as f:
            f.write("\\reviewstart text \\reviewend\n")
        errors = validate()
        self.assertTrue(any("should not coexist" in e for e in errors))

    def test_count_mismatch(self):
        dashboard = _make_dashboard(structural_tasks=["Task one", "Task two"])
        dashboard = dashboard.replace("0 of 2", "0 of 5")
        self._setup_project(dashboard)
        errors = validate()
        self.assertTrue(any("count mismatch" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
