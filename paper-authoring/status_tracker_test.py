#!/usr/bin/env python3
"""Tests for StatusTracker."""

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from status_tracker import Phase, StatusTracker, ValidationError

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

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _write_workflow_files(self, dashboard: str | None = None):
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

    def _make_tracker(self, dashboard: str | None = None) -> StatusTracker:
        self._write_workflow_files(dashboard)
        return StatusTracker(self.test_dir)


class ConstructorTest(TestFixture):
    def test_missing_workflow_files(self):
        with self.assertRaises(FileNotFoundError):
            StatusTracker(self.test_dir)

    def test_creates_state_file(self):
        tracker = self._make_tracker()
        self.assertTrue(tracker.state_path.exists())
        state = tracker.read_state()
        self.assertEqual(state["phase"], "idle")
        self.assertIsNone(state["task"])

    def test_writes_state_to_dashboard(self):
        tracker = self._make_tracker()
        dashboard = tracker._read_dashboard()
        self.assertIn("**State:** idle", dashboard)

    def test_preserves_existing_state(self):
        self._write_workflow_files()
        state_path = self.test_dir / "workflow" / "state.json"
        state_path.write_text('{"phase": "edit", "task": "My task"}\n')
        # Need select bars for edit phase to be valid
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart text \\selectend\n"
        )
        # Need an in-progress task in dashboard
        (self.test_dir / "workflow" / "dashboard.md").write_text(
            _make_dashboard(
                structural_tasks=["Task one", "Task two"],
                in_progress=["🔵 My task"],
            )
        )
        tracker = StatusTracker(self.test_dir)
        state = tracker.read_state()
        self.assertEqual(state["phase"], "edit")
        self.assertEqual(state["task"], "My task")


class InvariantTest(TestFixture):
    def test_clean_state(self):
        tracker = self._make_tracker()
        tracker.assert_valid()  # should not raise

    def test_orphaned_select_markers(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart some text \\selectend\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            tracker.assert_valid()
        self.assertTrue(any("idle" in e and "markers" in e for e in ctx.exception.errors))

    def test_orphaned_review_markers(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\reviewstart some text \\reviewend\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            tracker.assert_valid()
        self.assertTrue(any("idle" in e and "markers" in e for e in ctx.exception.errors))

    def test_multiple_in_progress(self):
        tracker = self._make_tracker()
        # Break invariant after construction
        (self.test_dir / "workflow" / "dashboard.md").write_text(
            _make_dashboard(
                structural_tasks=["Task one", "Task two"],
                in_progress=["🔵 Task A", "🔵 Task B"],
            )
        )
        with self.assertRaises(ValidationError) as ctx:
            tracker.assert_valid()
        self.assertTrue(any("Multiple in-progress" in e for e in ctx.exception.errors))

    def test_coexisting_markers(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "a.tex").write_text("\\selectstart text \\selectend\n")
        (self.test_dir / "sec" / "b.tex").write_text("\\reviewstart text \\reviewend\n")
        with self.assertRaises(ValidationError) as ctx:
            tracker.assert_valid()
        self.assertTrue(any("should not coexist" in e for e in ctx.exception.errors))

    def test_count_mismatch(self):
        tracker = self._make_tracker()
        # Break invariant after construction
        dashboard = _make_dashboard(structural_tasks=["Task one", "Task two"])
        dashboard = dashboard.replace("0 of 2", "0 of 5")
        (self.test_dir / "workflow" / "dashboard.md").write_text(dashboard)
        with self.assertRaises(ValidationError) as ctx:
            tracker.assert_valid()
        self.assertTrue(any("count mismatch" in e for e in ctx.exception.errors))


class StateTest(TestFixture):
    def test_begin_review_sets_review_phase(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart text \\selectend\n"
        )
        tracker._write_state(Phase.EDIT, "Active task")
        tracker.begin_review()
        state = tracker.read_state()
        self.assertEqual(state["phase"], "author-review")

    def test_return_to_edit_sets_edit_phase(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\reviewstart text \\reviewend\n"
        )
        tracker._write_state(Phase.AUTHOR_REVIEW, "Active task")
        tracker.return_to_edit()
        state = tracker.read_state()
        self.assertEqual(state["phase"], "edit")

    def test_state_reported_in_dashboard(self):
        tracker = self._make_tracker()
        dashboard = tracker._read_dashboard()
        self.assertIn("**State:** idle", dashboard)

    def test_state_line_updated_not_duplicated(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart text \\selectend\n"
        )
        tracker._write_state(Phase.EDIT, "Task A")
        tracker.begin_review()
        dashboard = tracker._read_dashboard()
        self.assertEqual(dashboard.count("**State:**"), 1)
        self.assertIn("**State:** author-review — Task A", dashboard)


class BeginReviewTest(TestFixture):
    def test_swaps_select_to_review(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text("before \\selectstart middle \\selectend after\n")
        tracker._write_state(Phase.EDIT, "Active task")
        tracker.begin_review()
        result = tex.read_text()
        self.assertIn("\\reviewstart", result)
        self.assertNotIn("\\selectstart", result)


class ReturnToEditTest(TestFixture):
    def test_swaps_review_to_select(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text("before \\reviewstart middle \\reviewend after\n")
        tracker._write_state(Phase.AUTHOR_REVIEW, "Active task")
        tracker.return_to_edit()
        result = tex.read_text()
        self.assertIn("\\selectstart", result)
        self.assertNotIn("\\reviewstart", result)


class CheckEditTest(TestFixture):
    def test_non_tex_always_allowed(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_edit("workflow/dashboard.md")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_tex_edit_blocked_during_review(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\reviewstart text \\reviewend\n"
        )
        tracker._write_state(Phase.AUTHOR_REVIEW, "Some task")
        allowed, msg = tracker.check_edit("sec/intro.tex")
        self.assertFalse(allowed)
        self.assertIn("return-to-edit", msg)

    def test_tex_edit_warned_during_idle(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_edit("sec/intro.tex")
        self.assertTrue(allowed)
        self.assertIn("ad hoc", msg)

    def test_tex_edit_allowed_during_edit_phase(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            "\\selectstart text \\selectend\n"
        )
        tracker._write_state(Phase.EDIT, "Some task")
        allowed, msg = tracker.check_edit("sec/intro.tex")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")


class TriageTest(TestFixture):
    def test_begin_triage_sets_phase(self):
        tracker = self._make_tracker()
        tracker.begin_triage()
        state = tracker.read_state()
        self.assertEqual(state["phase"], "triage")

    def test_approve_triage_returns_to_idle(self):
        tracker = self._make_tracker()
        tracker.begin_triage()
        tracker.approve_triage()
        state = tracker.read_state()
        self.assertEqual(state["phase"], "idle")

    def test_tex_edit_blocked_during_triage(self):
        tracker = self._make_tracker()
        tracker.begin_triage()
        allowed, msg = tracker.check_edit("sec/intro.tex")
        self.assertFalse(allowed)
        self.assertIn("approve-triage", msg)

    def test_reclassify_structural_to_minor(self):
        tracker = self._make_tracker()
        # Add a structural note
        (self.test_dir / "workflow" / "todo" / "structural.md").write_text(
            "# Structural Review Notes\n\n"
            "### Note structural-1\n\n"
            "Some issue\n\n"
            "**Diagnosis:** Problem here.\n\n"
            "**Proposed action:** Fix it.\n"
        )
        (self.test_dir / "workflow" / "todo" / "minor-issues.md").write_text(
            "# Minor Issues\n"
        )
        tracker.reclassify("structural-1", "minor")
        structural = (self.test_dir / "workflow" / "todo" / "structural.md").read_text()
        minor = (self.test_dir / "workflow" / "todo" / "minor-issues.md").read_text()
        self.assertNotIn("structural-1", structural)
        self.assertIn("structural-1", minor)
        self.assertIn("Fix it.", minor)

    def test_reclassify_nonexistent_note_raises(self):
        tracker = self._make_tracker()
        with self.assertRaises(ValueError):
            tracker.reclassify("structural-99", "minor")


if __name__ == "__main__":
    unittest.main()
