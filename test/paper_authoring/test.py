#!/usr/bin/env python3
"""Tests for PaperAuthoring."""

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_authoring.workflow import (
    CHANGE_MARKUP, EDIT_END, EDIT_START, Phase, REVIEW_END, REVIEW_START,
    PaperAuthoring, ValidationError,
)

TEMPLATE_PATH = Path(__file__).parent.parent.parent / "src" / "paper_authoring" / "templates" / "dashboard.md"


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

    def _make_tracker(self, dashboard: str | None = None) -> PaperAuthoring:
        self._write_workflow_files(dashboard)
        return PaperAuthoring(self.test_dir)


class ConstructorTest(TestFixture):
    def test_missing_workflow_files(self):
        with self.assertRaises(FileNotFoundError):
            PaperAuthoring(self.test_dir)

    def test_creates_state_file(self):
        tracker = self._make_tracker()
        self.assertTrue(tracker.state_path.exists())
        state = tracker.read_state()
        self.assertEqual(state["phase"], "idle")
        self.assertIsNone(state["task"])

    def test_preserves_existing_state(self):
        self._write_workflow_files()
        state_path = self.test_dir / "workflow" / "state.json"
        state_path.write_text('[{"phase": "edit", "task": "My task"}]\n')
        # Need edit bars for edit phase to be valid
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} text {EDIT_END}\n"
        )
        # Need an in-progress task in dashboard
        (self.test_dir / "workflow" / "dashboard.md").write_text(
            _make_dashboard(
                structural_tasks=["Task one", "Task two"],
                in_progress=["- 🔵 My task"],
            )
        )
        tracker = PaperAuthoring(self.test_dir)
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

    def test_coexisting_markers(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["- 🔵 Active task"],
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
            in_progress=["- 🔵 Active task"],
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
            in_progress=["- 🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        tracker._write_state(Phase.AUTHOR_REVIEW, "Active task")
        tracker.review_to_edit()
        state = tracker.read_state()
        self.assertEqual(state["phase"], "edit")

class EditToReviewTest(TestFixture):
    def test_swaps_edit_to_review(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["- 🔵 Active task"],
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
            in_progress=["- 🔵 Active task"],
        ))
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text(f"before {REVIEW_START} middle {REVIEW_END} after\n")
        tracker._write_state(Phase.AUTHOR_REVIEW, "Active task")
        tracker.review_to_edit()
        result = tex.read_text()
        self.assertIn(f"{EDIT_START}", result)
        self.assertNotIn(f"{REVIEW_START}", result)


class CheckEditTest(TestFixture):
    def test_non_tex_non_protected_allowed(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_edit("comp-sci.bib")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_dashboard_edit_blocked(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_edit("workflow/dashboard.md")
        self.assertFalse(allowed)
        self.assertIn("PaperAuthoring", msg)

    def test_tex_edit_blocked_in_idle(self):
        tracker = self._make_tracker()
        allowed, msg = tracker.check_edit("sec/test.tex", None, "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("begin-task", msg)

    def test_tex_edit_blocked_without_change_markup(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["\U0001f535 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} old text {EDIT_END}\n"
        )
        tracker.state_path.write_text(json.dumps([{"phase": "edit", "task": "Active task"}]) + "\n")
        allowed, msg = tracker.check_edit("sec/test.tex", "old text", "new text")
        self.assertFalse(allowed)
        self.assertIn("change markup", msg)

    def test_tex_edit_blocked_outside_any_bars(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["\U0001f535 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text("bare text\n")
        tracker.state_path.write_text(json.dumps([{"phase": "edit", "task": "Active task"}]) + "\n")
        allowed, msg = tracker.check_edit("sec/test.tex", "bare text", "\\deleted{bare text}")
        self.assertFalse(allowed)
        self.assertIn("outside change bars", msg)

    def test_tex_edit_allowed_within_review_bars_ad_hoc(self):
        """Ad hoc edit: review bars + change markup, author-review phase."""
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["\U0001f535 Ad hoc"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"before {REVIEW_START} old text {REVIEW_END} after\n"
        )
        tracker.state_path.write_text(json.dumps([{"phase": "author-review", "task": "Ad hoc"}]) + "\n")
        # author-review blocks edits
        allowed, msg = tracker.check_edit("sec/test.tex", "old text", "\\deleted{old text}")
        self.assertFalse(allowed)

    def test_tex_edit_allowed_within_edit_bars(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["- 🔵 Active task"],
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
            in_progress=["- 🔵 Active task"],
        ))
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        tracker.state_path.write_text(json.dumps([{"phase": "edit", "task": "Some task"}]) + "\n")
        allowed, msg = tracker.check_edit("sec/test.tex", "text", "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("review bars but phase is 'edit'", msg)

    def test_tex_edit_blocked_during_author_review(self):
        tracker = self._make_tracker(_make_dashboard(
            structural_tasks=["Task one", "Task two"],
            in_progress=["- 🔵 Active task"],
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


class CompleteTaskTest(TestFixture):
    def _make_tracker_with_task(self):
        """Create a tracker with a properly linked task, select it."""
        tracker = self._make_tracker()
        # Add a task with proper note link
        tracker.add_task("test-1", "Fix something", "structural")
        (self.test_dir / "sec" / "test.tex").write_text("some passage\n")
        tracker.begin_task("test-1", [("sec/test.tex", "some passage")])
        return tracker

    def test_complete_updates_done_count(self):
        tracker = self._make_tracker_with_task()
        tracker.end_task()
        dashboard = tracker._read_dashboard()
        # structural: was "0 of 3" (2 original + 1 added), now 1 done
        self.assertIn("1 of 3", dashboard)

    def test_complete_validates(self):
        """end_task should call assert_valid; a broken state should raise."""
        tracker = self._make_tracker_with_task()
        # Corrupt the count before completing
        dashboard = tracker._read_dashboard()
        dashboard = dashboard.replace("0 of 3", "0 of 99")
        tracker.dashboard_path.write_text(dashboard)
        with self.assertRaises(ValidationError):
            tracker.end_task()


class SubtaskTest(TestFixture):
    def _make_tracker_with_selected_task(self):
        tracker = self._make_tracker()
        tracker.add_task("test-1", "Big task", "structural")
        (self.test_dir / "sec" / "intro.tex").write_text("intro passage\n")
        (self.test_dir / "sec" / "related.tex").write_text("related passage\n")
        tracker.begin_task("test-1", [
            ("sec/intro.tex", "intro passage"),
            ("sec/related.tex", "related passage"),
        ])
        return tracker

    def test_add_subtask_appears_in_dashboard(self):
        tracker = self._make_tracker_with_selected_task()
        tracker.add_subtask("test-1a", "Fix introduction")
        dashboard = tracker._read_dashboard()
        self.assertIn("[ ] Fix introduction (subtask: test-1a)", dashboard)

    def test_begin_subtask_pushes_state(self):
        tracker = self._make_tracker_with_selected_task()
        tracker.add_subtask("test-1a", "Fix introduction")
        tracker.begin_subtask("test-1a", [("sec/intro.tex", "intro passage")])
        stack = tracker._read_stack()
        self.assertEqual(len(stack), 2)
        self.assertEqual(stack[-1]["task"], "test-1a")

    def test_begin_subtask_replaces_bars(self):
        tracker = self._make_tracker_with_selected_task()
        tracker.add_subtask("test-1a", "Fix introduction")
        tracker.begin_subtask("test-1a", [("sec/intro.tex", "intro passage")])
        # Parent bars removed from related.tex
        related = (self.test_dir / "sec" / "related.tex").read_text()
        self.assertNotIn(EDIT_START, related)
        # Subtask bars placed in intro.tex
        intro = (self.test_dir / "sec" / "intro.tex").read_text()
        self.assertIn(EDIT_START, intro)

    def test_complete_subtask_pops_state(self):
        tracker = self._make_tracker_with_selected_task()
        tracker.add_subtask("test-1a", "Fix introduction")
        tracker.begin_subtask("test-1a", [("sec/intro.tex", "intro passage")])
        tracker.end_task()
        stack = tracker._read_stack()
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[-1]["task"], "test-1")

    def test_complete_subtask_shows_checked_in_dashboard(self):
        tracker = self._make_tracker_with_selected_task()
        tracker.add_subtask("test-1a", "Fix introduction")
        tracker.begin_subtask("test-1a", [("sec/intro.tex", "intro passage")])
        tracker.end_task()
        dashboard = tracker._read_dashboard()
        self.assertIn("[x] Fix introduction", dashboard)
        self.assertNotIn("🔵 Fix introduction", dashboard)


class GitHubIssuesTest(TestFixture):
    """Tests for GitHub Issues integration in approve_triage."""

    def _make_tracker_with_tasks(self):
        """Set up tracker with structural and minor tasks in To Do."""
        tracker = self._make_tracker()
        # Add structural notes
        (self.test_dir / "workflow" / "todo" / "structural.md").write_text(
            "# Structural Review Notes\n\n"
            "### Note s-1\n\n"
            "Diagnosis of first issue.\n\n"
            "**Proposed action:** Fix the first thing.\n\n"
            "### Note s-2\n\n"
            "Second issue diagnosis.\n"
        )
        (self.test_dir / "workflow" / "todo" / "minor-issues.md").write_text(
            "# Minor Issues\n\n"
            "### Note m-1\n\nTypo on page 3.\n\n"
            "### Note m-2\n\nMissing citation.\n"
        )
        tracker.add_task("s-1", "Fix introduction argument", "structural")
        tracker.add_task("s-2", "Restructure related work", "structural")
        tracker.add_task("m-1", "Fix typo on page 3", "minor")
        tracker.add_task("m-2", "Add missing citation", "minor")
        tracker.begin_triage()
        return tracker

    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    def test_approve_triage_creates_structural_issues(self, mock_create):
        mock_create.side_effect = [
            "https://github.com/owner/repo/issues/1",
            "https://github.com/owner/repo/issues/2",
            "https://github.com/owner/repo/issues/3",  # minor batch
        ]
        tracker = self._make_tracker_with_tasks()
        tracker.approve_triage()

        # Two structural issues + one minor batch
        self.assertEqual(mock_create.call_count, 3)

        # First structural issue
        args1 = mock_create.call_args_list[0]
        self.assertEqual(args1[0][0], "Fix introduction argument")
        self.assertIn("first issue", args1[0][1])

        # Second structural issue
        args2 = mock_create.call_args_list[1]
        self.assertEqual(args2[0][0], "Restructure related work")

        # Minor batch issue
        args3 = mock_create.call_args_list[2]
        self.assertEqual(args3[0][0], "Minor issues")
        self.assertIn("- [ ] Fix typo on page 3", args3[0][1])
        self.assertIn("- [ ] Add missing citation", args3[0][1])

    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    def test_approve_triage_stores_urls_in_dashboard(self, mock_create):
        mock_create.side_effect = [
            "https://github.com/owner/repo/issues/1",
            "https://github.com/owner/repo/issues/2",
            "https://github.com/owner/repo/issues/3",
        ]
        tracker = self._make_tracker_with_tasks()
        tracker.approve_triage()
        dashboard = tracker._read_dashboard()

        self.assertIn("[issue](https://github.com/owner/repo/issues/1)", dashboard)
        self.assertIn("[issue](https://github.com/owner/repo/issues/2)", dashboard)
        self.assertIn("[issue](https://github.com/owner/repo/issues/3)", dashboard)

    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    def test_approve_triage_transitions_to_idle(self, mock_create):
        mock_create.return_value = "https://github.com/owner/repo/issues/1"
        tracker = self._make_tracker_with_tasks()
        tracker.approve_triage()
        self.assertEqual(tracker.read_state()["phase"], "idle")

    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    def test_approve_triage_no_tasks_creates_no_issues(self, mock_create):
        """If no tasks in To Do, no issues created but triage completes."""
        tracker = self._make_tracker()
        tracker.begin_triage()
        tracker.approve_triage()
        mock_create.assert_not_called()
        self.assertEqual(tracker.read_state()["phase"], "idle")

    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    def test_structural_entries_get_only_their_own_issue_url(self, mock_create):
        """Each structural entry should have exactly one [issue] link."""
        mock_create.side_effect = [
            "https://github.com/owner/repo/issues/1",  # structural s-1
            "https://github.com/owner/repo/issues/2",  # structural s-2
            "https://github.com/owner/repo/issues/3",  # minor batch
        ]
        tracker = self._make_tracker_with_tasks()
        tracker.approve_triage()
        dashboard = tracker._read_dashboard()

        # Each structural entry should have exactly one [issue] link
        structural_lines = [
            l for l in dashboard.split("\n")
            if "Fix introduction argument" in l or "Restructure related work" in l
        ]
        for line in structural_lines:
            count = line.count("[issue]")
            self.assertEqual(count, 1, f"Expected exactly 1 [issue] link: {line}")

        # Structural entries should have their own URLs, not the minor batch URL
        self.assertIn("issues/1", structural_lines[0])
        self.assertIn("issues/2", structural_lines[1])
        self.assertNotIn("issues/3", structural_lines[0])
        self.assertNotIn("issues/3", structural_lines[1])

