#!/usr/bin/env python3
"""Tests for StatusTracker."""

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from status_tracker import (
    CHANGE_MARKUP, EDIT_END, EDIT_START, Phase, REVIEW_END, REVIEW_START,
    StatusTracker, ValidationError,
)

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
        # Need edit bars for edit phase to be valid
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} text {EDIT_END}\n"
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

    def test_orphaned_edit_markers(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} some text {EDIT_END}\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            tracker.assert_valid()
        self.assertTrue(any("idle" in e and "markers" in e for e in ctx.exception.errors))

    def test_orphaned_review_markers(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} some text {REVIEW_END}\n"
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
        (self.test_dir / "sec" / "a.tex").write_text(f"{EDIT_START} text {EDIT_END}\n")
        (self.test_dir / "sec" / "b.tex").write_text(f"{REVIEW_START} text {REVIEW_END}\n")
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
    def test_edit_to_review_sets_review_phase(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} text {EDIT_END}\n"
        )
        tracker._write_state(Phase.EDIT, "Active task")
        tracker.edit_to_review()
        state = tracker.read_state()
        self.assertEqual(state["phase"], "author-review")

    def test_review_to_edit_sets_edit_phase(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        tracker._write_state(Phase.AUTHOR_REVIEW, "Active task")
        tracker.review_to_edit()
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
            f"{EDIT_START} text {EDIT_END}\n"
        )
        tracker._write_state(Phase.EDIT, "Task A")
        tracker.edit_to_review()
        dashboard = tracker._read_dashboard()
        self.assertEqual(dashboard.count("**State:**"), 1)
        self.assertIn("**State:** author-review — Task A", dashboard)


class EditToReviewTest(TestFixture):
    def test_swaps_edit_to_review(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text(f"before {EDIT_START} middle {EDIT_END} after\n")
        tracker._write_state(Phase.EDIT, "Active task")
        tracker.edit_to_review()
        result = tex.read_text()
        self.assertIn(f"{REVIEW_START}", result)
        self.assertNotIn(f"{EDIT_START}", result)


class ReviewToEditTest(TestFixture):
    def test_swaps_review_to_edit(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text(f"before {REVIEW_START} middle {REVIEW_END} after\n")
        tracker._write_state(Phase.AUTHOR_REVIEW, "Active task")
        tracker.review_to_edit()
        result = tex.read_text()
        self.assertIn(f"{EDIT_START}", result)
        self.assertNotIn(f"{REVIEW_START}", result)


class CheckEditTest(TestFixture):
    def test_non_tex_always_allowed(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_edit("workflow/dashboard.md")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_tex_edit_blocked_without_change_markup(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} old text {REVIEW_END}\n"
        )
        allowed, msg = tracker.check_edit("sec/test.tex", "old text", "new text")
        self.assertFalse(allowed)
        self.assertIn("change markup", msg)

    def test_tex_edit_blocked_outside_any_bars(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text("bare text\n")
        allowed, msg = tracker.check_edit("sec/test.tex", "bare text", "\\deleted{bare text}")
        self.assertFalse(allowed)
        self.assertIn("outside change bars", msg)

    def test_tex_edit_allowed_within_review_bars_idle(self):
        """Ad hoc edit: review bars + change markup, idle phase."""
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"before {REVIEW_START} old text {REVIEW_END} after\n"
        )
        allowed, msg = tracker.check_edit("sec/test.tex", "old text", "\\deleted{old text}")
        self.assertTrue(allowed)

    def test_tex_edit_allowed_within_edit_bars(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"before {EDIT_START} editable text {EDIT_END} after\n"
        )
        tracker._write_state(Phase.EDIT, "Some task")
        allowed, msg = tracker.check_edit("sec/test.tex", "editable text", "\\replaced{new}{editable text}")
        self.assertTrue(allowed)

    def test_tex_edit_blocked_in_review_bars_during_edit_phase(self):
        """During edit phase, must be in edit bars, not review bars."""
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        tracker._write_state(Phase.EDIT, "Some task")
        allowed, msg = tracker.check_edit("sec/test.tex", "text", "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("review bars but phase is 'edit'", msg)

    def test_tex_edit_blocked_during_author_review(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        tracker._write_state(Phase.AUTHOR_REVIEW, "Some task")
        allowed, msg = tracker.check_edit("sec/test.tex", "text", "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("review-to-edit", msg)

    def test_tex_edit_blocked_during_triage(self):
        tracker = self._make_tracker()
        tracker.begin_triage()
        allowed, msg = tracker.check_edit("sec/test.tex", None, "\\added{text}")
        self.assertFalse(allowed)
        self.assertIn("approve-triage", msg)


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


class AddTaskTest(TestFixture):
    def test_add_structural_task(self):
        tracker = self._make_tracker()
        tracker.add_task("structural-3", "New issue found", "structural")
        dashboard = tracker._read_dashboard()
        self.assertIn("- New issue found (", dashboard)
        self.assertIn("note-structural-3", dashboard)
        self.assertIn("0 of 3", dashboard)  # was 2, now 3

    def test_add_minor_task(self):
        tracker = self._make_tracker()
        tracker.add_task("minor-1", "Fix typo", "minor")
        dashboard = tracker._read_dashboard()
        self.assertIn("- Fix typo (", dashboard)
        self.assertIn("note-minor-1", dashboard)
        self.assertIn("0 of 1", dashboard)  # was 0, now 1

    def test_add_first_minor_replaces_none(self):
        tracker = self._make_tracker()
        tracker.add_task("minor-1", "Fix typo", "minor")
        dashboard = tracker._read_dashboard()
        # Should not have (none) under Minor anymore
        minor_section = re.search(
            r"^### Minor$\n(.*?)(?=^### |\Z)", dashboard, re.MULTILINE | re.DOTALL
        )
        self.assertNotIn("(none)", minor_section.group(1))

    def test_add_preserves_existing_tasks(self):
        tracker = self._make_tracker()
        tracker.add_task("structural-3", "First new", "structural")
        tracker.add_task("structural-4", "Second new", "structural")
        dashboard = tracker._read_dashboard()
        self.assertIn("Task one", dashboard)
        self.assertIn("First new", dashboard)
        self.assertIn("Second new", dashboard)
        self.assertIn("0 of 4", dashboard)

    def test_validation_passes_after_add(self):
        tracker = self._make_tracker()
        tracker.add_task("structural-3", "New task", "structural")
        tracker.assert_valid()  # should not raise

    def test_duplicate_rejected(self):
        tracker = self._make_tracker()
        tracker.add_task("structural-3", "New task", "structural")
        with self.assertRaises(ValueError) as ctx:
            tracker.add_task("structural-3", "Same task again", "structural")
        self.assertIn("already exists", str(ctx.exception))

    def test_blank_line_between_sections(self):
        tracker = self._make_tracker()
        tracker.add_task("minor-1", "Fix typo", "minor")
        dashboard = tracker._read_dashboard()
        # There should be a blank line before ### Structural
        self.assertIn("\n\n### Structural", dashboard)


class CheckWriteTest(TestFixture):
    def test_write_allowed_for_new_file(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_write("sec/new-file.tex")
        self.assertTrue(allowed)

    def test_write_blocked_for_existing_file(self):
        tracker = self._make_tracker()
        (self.test_dir / "sec" / "existing.tex").write_text("content\n")
        allowed, msg = tracker.check_write("sec/existing.tex")
        self.assertFalse(allowed)
        self.assertIn("Edit tool", msg)


if __name__ == "__main__":
    unittest.main()
