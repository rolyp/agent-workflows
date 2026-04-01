#!/usr/bin/env python3
"""Tests for StatusTracker."""

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from status_tracker import StatusTracker

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

    dashboard = dashboard.replace(
        "minor issues](todo/completed.md#minor) (0 of 0)",
        f"minor issues](todo/completed.md#minor) (0 of {len(minor)})",
    )
    dashboard = dashboard.replace(
        "structural tasks](todo/completed.md#structural) (0 of 0)",
        f"structural tasks](todo/completed.md#structural) (0 of {len(structural)})",
    )

    if ip:
        dashboard = dashboard.replace(
            "## In progress\n\n(none)",
            "## In progress\n\n" + "\n".join(ip),
        )

    if structural:
        dashboard = re.sub(
            r"(### Structural\n\n)(.*?)$",
            "\\1" + "\n".join(f"- {t}" for t in structural) + "\n",
            dashboard,
            flags=re.DOTALL,
        )

    if minor:
        dashboard = re.sub(
            r"(### Minor\n\n)\(none\)",
            "\\1" + "\n".join(f"- {t}" for t in minor),
            dashboard,
        )

    return dashboard


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = Path(tempfile.mkdtemp())
        os.chdir(self.test_dir)
        self.tracker = StatusTracker(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _setup_project(self, dashboard: str | None = None):
        (self.test_dir / "workflow" / "todo").mkdir(parents=True, exist_ok=True)
        (self.test_dir / "sec").mkdir(exist_ok=True)
        (self.test_dir / "workflow" / "dashboard.md").write_text(
            dashboard or _make_dashboard(structural_tasks=["Task one", "Task two"])
        )
        (self.test_dir / "workflow" / "todo" / "structural.md").write_text(
            "# Structural Review Notes\n"
        )
        (self.test_dir / "workflow" / "todo" / "completed.md").write_text(
            "# Completed\n\n## Minor\n\n## Structural\n"
        )


class ValidateTest(TestFixture):
    def test_no_workflow_files(self):
        errors = self.tracker.validate()
        self.assertIn("Missing: workflow/dashboard.md", errors)
        self.assertIn("Missing: workflow/todo/structural.md", errors)
        self.assertIn("Missing: workflow/todo/completed.md", errors)

    def test_clean_state(self):
        self._setup_project()
        self.assertEqual(self.tracker.validate(), [])

    def test_orphaned_select_markers(self):
        self._setup_project()
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart some text \\selectend\n"
        )
        errors = self.tracker.validate()
        self.assertTrue(any("Orphaned \\selectstart" in e for e in errors))

    def test_orphaned_review_markers(self):
        self._setup_project()
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\reviewstart some text \\reviewend\n"
        )
        errors = self.tracker.validate()
        self.assertTrue(any("Orphaned \\reviewstart" in e for e in errors))

    def test_in_progress_without_markers(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        errors = self.tracker.validate()
        self.assertTrue(any("no select/review markers" in e for e in errors))

    def test_multiple_in_progress(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Task A", "🔵 Task B"],
        ))
        errors = self.tracker.validate()
        self.assertTrue(any("Multiple in-progress" in e for e in errors))

    def test_coexisting_markers(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "a.tex").write_text("\\selectstart text \\selectend\n")
        (self.test_dir / "sec" / "b.tex").write_text("\\reviewstart text \\reviewend\n")
        errors = self.tracker.validate()
        self.assertTrue(any("should not coexist" in e for e in errors))

    def test_count_mismatch(self):
        dashboard = _make_dashboard(structural_tasks=["Task one", "Task two"])
        dashboard = dashboard.replace("0 of 2", "0 of 5")
        self._setup_project(dashboard)
        errors = self.tracker.validate()
        self.assertTrue(any("count mismatch" in e for e in errors))


class StateTest(TestFixture):
    def test_default_state_is_idle(self):
        state = self.tracker.read_state()
        self.assertEqual(state["phase"], "idle")
        self.assertIsNone(state["task"])

    def test_begin_review_sets_review_phase(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart text \\selectend\n"
        )
        self.tracker.begin_review()
        state = self.tracker.read_state()
        self.assertEqual(state["phase"], "review")

    def test_return_to_edit_sets_edit_phase(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\reviewstart text \\reviewend\n"
        )
        self.tracker.return_to_edit()
        state = self.tracker.read_state()
        self.assertEqual(state["phase"], "edit")

    def test_state_reported_in_dashboard(self):
        self._setup_project()
        self.tracker._write_state("edit", "Some task")
        dashboard = self.tracker._read_dashboard()
        self.assertIn("**State:** edit — Some task", dashboard)

    def test_state_line_updated_not_duplicated(self):
        self._setup_project()
        self.tracker._write_state("edit", "Task A")
        self.tracker._write_state("review", "Task A")
        dashboard = self.tracker._read_dashboard()
        self.assertEqual(dashboard.count("**State:**"), 1)
        self.assertIn("**State:** review — Task A", dashboard)


class BeginReviewTest(TestFixture):
    def test_swaps_select_to_review(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text("before \\selectstart middle \\selectend after\n")
        self.tracker.begin_review()
        result = tex.read_text()
        self.assertIn("\\reviewstart", result)
        self.assertIn("\\reviewend", result)
        self.assertNotIn("\\selectstart", result)
        self.assertNotIn("\\selectend", result)


class ReturnToEditTest(TestFixture):
    def test_swaps_review_to_select(self):
        self._setup_project(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text("before \\reviewstart middle \\reviewend after\n")
        self.tracker.return_to_edit()
        result = tex.read_text()
        self.assertIn("\\selectstart", result)
        self.assertIn("\\selectend", result)
        self.assertNotIn("\\reviewstart", result)
        self.assertNotIn("\\reviewend", result)


class CheckEditTest(TestFixture):
    def test_non_tex_always_allowed(self):
        allowed, msg = self.tracker.check_edit("workflow/dashboard.md")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_tex_edit_blocked_during_review(self):
        self._setup_project()
        self.tracker._write_state("review", "Some task")
        allowed, msg = self.tracker.check_edit("sec/intro.tex")
        self.assertFalse(allowed)
        self.assertIn("return-to-edit", msg)

    def test_tex_edit_warned_during_idle(self):
        self._setup_project()
        allowed, msg = self.tracker.check_edit("sec/intro.tex")
        self.assertTrue(allowed)
        self.assertIn("ad hoc", msg)

    def test_tex_edit_allowed_during_edit_phase(self):
        self._setup_project()
        self.tracker._write_state("edit", "Some task")
        allowed, msg = self.tracker.check_edit("sec/intro.tex")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")


if __name__ == "__main__":
    unittest.main()
