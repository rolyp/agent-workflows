#!/usr/bin/env python3
"""Tests for PaperAuthoring."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_authoring.workflow import (
    CHANGE_MARKUP, EDIT_END, EDIT_START, Phase, REVIEW_END, REVIEW_START,
    PaperAuthoring, ValidationError,
)

class TestFixture(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = Path(tempfile.mkdtemp())
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _write_workflow_files(self):
        (self.test_dir / "workflow" / "todo").mkdir(parents=True, exist_ok=True)
        (self.test_dir / "sec").mkdir(exist_ok=True)
        (self.test_dir / "workflow" / "todo" / "structural.md").write_text(
            "# Structural Review Notes\n"
        )

    def _make_workflow(self) -> PaperAuthoring:
        self._write_workflow_files()
        return PaperAuthoring(self.test_dir)


class ConstructorTest(TestFixture):
    def test_missing_workflow_files(self):
        with self.assertRaises(FileNotFoundError):
            PaperAuthoring(self.test_dir)

    def test_creates_state_file(self):
        workflow = self._make_workflow()
        self.assertTrue(workflow.state_path.exists())
        state = workflow.read_state()
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
        workflow = PaperAuthoring(self.test_dir)
        state = workflow.read_state()
        self.assertEqual(state["phase"], "edit")
        self.assertEqual(state["task"], "My task")


class InvariantTest(TestFixture):
    def test_clean_state(self):
        workflow = self._make_workflow()
        workflow.assert_valid()  # should not raise

    def test_orphaned_edit_markers(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} some text {EDIT_END}\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            workflow.assert_valid()
        self.assertTrue(any("idle" in e and "markers" in e for e in ctx.exception.errors))

    def test_orphaned_review_markers(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} some text {REVIEW_END}\n"
        )
        with self.assertRaises(ValidationError) as ctx:
            workflow.assert_valid()
        self.assertTrue(any("idle" in e and "markers" in e for e in ctx.exception.errors))

    def test_coexisting_markers(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "a.tex").write_text(f"{EDIT_START} text {EDIT_END}\n")
        (self.test_dir / "sec" / "b.tex").write_text(f"{REVIEW_START} text {REVIEW_END}\n")
        with self.assertRaises(ValidationError) as ctx:
            workflow.assert_valid()
        self.assertTrue(any("should not coexist" in e for e in ctx.exception.errors))


class StateTest(TestFixture):
    def test_edit_to_review_sets_review_phase(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} text {EDIT_END}\n"
        )
        workflow._write_state(Phase.EDIT, "Active task")
        workflow.edit_to_review()
        state = workflow.read_state()
        self.assertEqual(state["phase"], "author-review")

    def test_review_to_edit_sets_edit_phase(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        workflow._write_state(Phase.AUTHOR_REVIEW, "Active task")
        workflow.review_to_edit()
        state = workflow.read_state()
        self.assertEqual(state["phase"], "edit")

class EditToReviewTest(TestFixture):
    def test_swaps_edit_to_review(self):
        workflow = self._make_workflow()
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text(f"before {EDIT_START} middle {EDIT_END} after\n")
        workflow._write_state(Phase.EDIT, "Active task")
        workflow.edit_to_review()
        result = tex.read_text()
        self.assertIn(f"{REVIEW_START}", result)
        self.assertNotIn(f"{EDIT_START}", result)


class ReviewToEditTest(TestFixture):
    def test_swaps_review_to_edit(self):
        workflow = self._make_workflow()
        tex = self.test_dir / "sec" / "test.tex"
        tex.write_text(f"before {REVIEW_START} middle {REVIEW_END} after\n")
        workflow._write_state(Phase.AUTHOR_REVIEW, "Active task")
        workflow.review_to_edit()
        result = tex.read_text()
        self.assertIn(f"{EDIT_START}", result)
        self.assertNotIn(f"{REVIEW_START}", result)


class CheckEditTest(TestFixture):
    def test_non_tex_non_protected_allowed(self):
        workflow = self._make_workflow()
        allowed, msg = workflow.check_edit("comp-sci.bib")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_tex_edit_blocked_in_idle(self):
        workflow = self._make_workflow()
        allowed, msg = workflow.check_edit("sec/test.tex", None, "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("begin-task", msg)

    def test_tex_edit_blocked_without_change_markup(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{EDIT_START} old text {EDIT_END}\n"
        )
        workflow.state_path.write_text(json.dumps([{"phase": "edit", "task": "Active task"}]) + "\n")
        allowed, msg = workflow.check_edit("sec/test.tex", "old text", "new text")
        self.assertFalse(allowed)
        self.assertIn("change markup", msg)

    def test_tex_edit_blocked_outside_any_bars(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text("bare text\n")
        workflow.state_path.write_text(json.dumps([{"phase": "edit", "task": "Active task"}]) + "\n")
        allowed, msg = workflow.check_edit("sec/test.tex", "bare text", "\\deleted{bare text}")
        self.assertFalse(allowed)
        self.assertIn("outside change bars", msg)

    def test_tex_edit_allowed_within_review_bars_ad_hoc(self):
        """Ad hoc edit: review bars + change markup, author-review phase."""
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"before {REVIEW_START} old text {REVIEW_END} after\n"
        )
        workflow.state_path.write_text(json.dumps([{"phase": "author-review", "task": "Ad hoc"}]) + "\n")
        # author-review blocks edits
        allowed, msg = workflow.check_edit("sec/test.tex", "old text", "\\deleted{old text}")
        self.assertFalse(allowed)

    def test_tex_edit_allowed_within_edit_bars(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"before {EDIT_START} editable text {EDIT_END} after\n"
        )
        workflow._write_state(Phase.EDIT, "Some task")
        allowed, msg = workflow.check_edit("sec/test.tex", "editable text", "\\replaced{new}{editable text}")
        self.assertTrue(allowed)

    def test_tex_edit_blocked_in_review_bars_during_edit_phase(self):
        """During edit phase, must be in edit bars, not review bars."""
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        workflow.state_path.write_text(json.dumps([{"phase": "edit", "task": "Some task"}]) + "\n")
        allowed, msg = workflow.check_edit("sec/test.tex", "text", "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("review bars but phase is 'edit'", msg)

    def test_tex_edit_blocked_during_author_review(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "test.tex").write_text(
            f"{REVIEW_START} text {REVIEW_END}\n"
        )
        workflow._write_state(Phase.AUTHOR_REVIEW, "Some task")
        allowed, msg = workflow.check_edit("sec/test.tex", "text", "\\deleted{text}")
        self.assertFalse(allowed)
        self.assertIn("review-to-edit", msg)

    def test_tex_edit_blocked_during_triage(self):
        workflow = self._make_workflow()
        workflow.begin_triage()
        allowed, msg = workflow.check_edit("sec/test.tex", None, "\\added{text}")
        self.assertFalse(allowed)
        self.assertIn("approve-triage", msg)


class TriageTest(TestFixture):
    def test_begin_triage_sets_phase(self):
        workflow = self._make_workflow()
        workflow.begin_triage()
        state = workflow.read_state()
        self.assertEqual(state["phase"], "triage")

    @patch("paper_authoring.workflow.PaperAuthoring.close_issue")
    @patch("paper_authoring.workflow.PaperAuthoring._read_issue_body")
    @patch("paper_authoring.workflow.PaperAuthoring.get_repo")
    def test_approve_triage_returns_to_idle(self, mock_repo, mock_read, mock_close):
        mock_repo.return_value = "owner/repo"
        mock_read.return_value = ""
        workflow = self._make_workflow()
        workflow.begin_triage()
        workflow.approve_triage("1")
        state = workflow.read_state()
        self.assertEqual(state["phase"], "idle")

    def test_reclassify_structural_to_minor(self):
        workflow = self._make_workflow()
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
        workflow.reclassify("structural-1", "minor")
        structural = (self.test_dir / "workflow" / "todo" / "structural.md").read_text()
        minor = (self.test_dir / "workflow" / "todo" / "minor-issues.md").read_text()
        self.assertNotIn("structural-1", structural)
        self.assertIn("structural-1", minor)
        self.assertIn("Fix it.", minor)

    def test_reclassify_nonexistent_note_raises(self):
        workflow = self._make_workflow()
        with self.assertRaises(ValueError):
            workflow.reclassify("structural-99", "minor")


class CheckWriteTest(TestFixture):
    def test_write_allowed_for_new_file(self):
        workflow = self._make_workflow()
        allowed, msg = workflow.check_write("sec/new-file.tex")
        self.assertTrue(allowed)

    def test_write_blocked_for_existing_file(self):
        workflow = self._make_workflow()
        (self.test_dir / "sec" / "existing.tex").write_text("content\n")
        allowed, msg = workflow.check_write("sec/existing.tex")
        self.assertFalse(allowed)
        self.assertIn("Edit tool", msg)


class GitHubIssuesTest(TestFixture):
    """Tests for issue-based triage: approve_triage reads review issue, promotes findings."""

    def _make_workflow_in_triage(self):
        workflow = self._make_workflow()
        workflow.begin_triage()
        return workflow

    @patch("paper_authoring.workflow.PaperAuthoring.close_issue")
    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    @patch("paper_authoring.workflow.PaperAuthoring._read_issue_body")
    @patch("paper_authoring.workflow.PaperAuthoring.get_repo")
    def test_approve_triage_creates_issues_from_review(self, mock_repo, mock_read, mock_create, mock_close):
        mock_repo.return_value = "owner/repo"
        mock_read.return_value = (
            "## Structure Review\n\n"
            "- [ ] Fix introduction argument\n"
            "- [x] Already addressed point\n"
            "- [ ] Restructure related work\n"
        )
        mock_create.side_effect = [
            "https://github.com/owner/repo/issues/10",
            "https://github.com/owner/repo/issues/11",
        ]
        workflow = self._make_workflow_in_triage()
        workflow.approve_triage("5")

        # Two unchecked items promoted, one checked item skipped
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(mock_create.call_args_list[0][0][0], "Fix introduction argument")
        self.assertEqual(mock_create.call_args_list[1][0][0], "Restructure related work")

    @patch("paper_authoring.workflow.PaperAuthoring.close_issue")
    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    @patch("paper_authoring.workflow.PaperAuthoring._read_issue_body")
    @patch("paper_authoring.workflow.PaperAuthoring.get_repo")
    def test_approve_triage_closes_review_issue(self, mock_repo, mock_read, mock_create, mock_close):
        mock_repo.return_value = "owner/repo"
        mock_read.return_value = "- [ ] Some finding\n"
        mock_create.return_value = "https://github.com/owner/repo/issues/10"
        workflow = self._make_workflow_in_triage()
        workflow.approve_triage("5")
        mock_close.assert_called_once_with("https://github.com/owner/repo/issues/5")

    @patch("paper_authoring.workflow.PaperAuthoring.close_issue")
    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    @patch("paper_authoring.workflow.PaperAuthoring._read_issue_body")
    @patch("paper_authoring.workflow.PaperAuthoring.get_repo")
    def test_approve_triage_transitions_to_idle(self, mock_repo, mock_read, mock_create, mock_close):
        mock_repo.return_value = "owner/repo"
        mock_read.return_value = ""
        workflow = self._make_workflow_in_triage()
        workflow.approve_triage("5")
        self.assertEqual(workflow.read_state()["phase"], "idle")

    @patch("paper_authoring.workflow.PaperAuthoring.close_issue")
    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    @patch("paper_authoring.workflow.PaperAuthoring._read_issue_body")
    @patch("paper_authoring.workflow.PaperAuthoring.get_repo")
    def test_approve_triage_empty_review_creates_no_issues(self, mock_repo, mock_read, mock_create, mock_close):
        mock_repo.return_value = "owner/repo"
        mock_read.return_value = "All items addressed.\n"
        workflow = self._make_workflow_in_triage()
        workflow.approve_triage("5")
        mock_create.assert_not_called()

    @patch("paper_authoring.workflow.PaperAuthoring.close_issue")
    @patch("paper_authoring.workflow.PaperAuthoring.create_issue")
    @patch("paper_authoring.workflow.PaperAuthoring._read_issue_body")
    @patch("paper_authoring.workflow.PaperAuthoring.get_repo")
    def test_approve_triage_skips_checked_items(self, mock_repo, mock_read, mock_create, mock_close):
        mock_repo.return_value = "owner/repo"
        mock_read.return_value = (
            "- [ ] Accepted finding\n"
            "- [x] Rejected finding\n"
            "- [ ] Another accepted\n"
        )
        mock_create.side_effect = ["url1", "url2"]
        workflow = self._make_workflow_in_triage()
        workflow.approve_triage("5")
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(mock_create.call_args_list[0][0][0], "Accepted finding")
        self.assertEqual(mock_create.call_args_list[1][0][0], "Another accepted")


if __name__ == "__main__":
    unittest.main()
