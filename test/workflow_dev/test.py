#!/usr/bin/env python3
"""Tests for WorkflowDev."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_dev.workflow import WorkflowDev, Phase, StepMode, _is_test_file
from workflow import Workflow


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = Path(tempfile.mkdtemp())
        os.chdir(self.test_dir)
        # Mock GitHub operations so tests don't hit the API
        self._patches = [
            patch.object(WorkflowDev, "get_repo", return_value="test/repo"),
            patch.object(WorkflowDev, "set_issue_status"),
            patch.object(WorkflowDev, "set_issue_label"),
            patch.object(WorkflowDev, "clear_issue_labels"),
            patch.object(WorkflowDev, "close_issue"),
            patch.object(WorkflowDev, "open_blockers", return_value=[]),
            patch.object(WorkflowDev, "add_blocker"),
            patch.object(WorkflowDev, "create_issue", return_value="https://github.com/test/repo/issues/99"),
            patch.object(WorkflowDev, "add_label"),
            patch.object(WorkflowDev, "_render_issue_todos"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _make_wd(self) -> WorkflowDev:
        # Create minimal test/test.sh so _run_tests succeeds in temp dir
        (self.test_dir / "test").mkdir(exist_ok=True)
        test_sh = self.test_dir / "test" / "test.sh"
        test_sh.write_text("#!/bin/bash\nexit 0\n")
        test_sh.chmod(0o755)
        # Init git repo (with user config for CI environments)
        import subprocess
        subprocess.run(["git", "init", "-b", "main"], capture_output=True, cwd=self.test_dir)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       capture_output=True, cwd=self.test_dir)
        subprocess.run(["git", "config", "user.name", "Test"],
                       capture_output=True, cwd=self.test_dir)
        # Create WorkflowDev (writes state.json)
        wd = WorkflowDev(self.test_dir)
        # Commit everything (test.sh + state.json) for clean-tree check
        subprocess.run(["git", "add", "-A"], capture_output=True, cwd=self.test_dir)
        subprocess.run(["git", "commit", "-m", "init"],
                       capture_output=True, cwd=self.test_dir)
        return wd


class TestIsTestFile(unittest.TestCase):
    def test_test_prefix(self):
        self.assertTrue(_is_test_file("test.py"))
        self.assertTrue(_is_test_file("test_workflow.py"))

    def test_test_suffix(self):
        self.assertTrue(_is_test_file("workflow_test.py"))

    def test_code_file(self):
        self.assertFalse(_is_test_file("workflow.py"))
        self.assertFalse(_is_test_file("base.py"))

    def test_nested_path(self):
        self.assertTrue(_is_test_file("paper_authoring/test.py"))
        self.assertFalse(_is_test_file("paper_authoring/workflow.py"))


class ConstructorTest(TestFixture):
    def test_creates_state_file(self):
        wd = self._make_wd()
        self.assertTrue(wd.state_path.exists())
        state = wd.read_state()
        self.assertEqual(state["phase"], "idle")

    def test_preserves_existing_state(self):
        state_path = self.test_dir / "state.json"
        state_path.write_text(json.dumps([{"phase": "refactoring", "task": "my-task"}]))
        wd = self._make_wd()
        self.assertEqual(wd.read_state()["phase"], "refactoring")
        self.assertEqual(wd.read_state()["task"], "my-task")


class StateTransitionTest(TestFixture):
    def test_begin_task_enters_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "1")
        self.assertNotIn("mode", state)

    def test_begin_task_rejects_non_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        with self.assertRaises(ValueError):
            wd.begin_task("2")

    def test_begin_refactor_pushes_frame(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Fix imports", "code")
        state = wd.read_state()
        self.assertEqual(state["step"], "[refactor/code] Fix imports")
        self.assertEqual(state["mode"], "code")

    def test_end_step_pops_to_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Fix imports", "code")
        wd.end_step("test commit")
        state = wd.read_state()
        self.assertNotIn("step", state)
        self.assertNotIn("mode", state)

    def test_nested_steps(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Outer", "code")
        wd.begin_refactor("Inner", "code")
        self.assertEqual(wd.read_state()["step"], "[refactor/code] Inner")
        wd.end_step("test commit")
        self.assertEqual(wd.read_state()["step"], "[refactor/code] Outer")
        wd.end_step("test commit")
        self.assertNotIn("step", wd.read_state())

    def test_modify_step(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_modify("Add feature",
                        rationale=["test_x: no feature → feature exists"])
        state = wd.read_state()
        self.assertEqual(state["mode"], "modify")
        self.assertEqual(state["phase"], "modifying")
        self.assertEqual(state["rationale"], ["test_x: no feature → feature exists"])

    def test_modify_step_requires_rationale(self):
        wd = self._make_wd()
        wd.begin_task("1")
        with self.assertRaises(ValueError) as ctx:
            wd.begin_modify("Add feature", rationale=[])
        self.assertIn("rationale", str(ctx.exception))

    def test_request_review_only_from_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        with self.assertRaises(ValueError):
            wd.request_review()

    def _submit_mock_reviews(self, wd):
        """Mark both reviews as submitted in state (without GitHub calls)."""
        sf = wd._read_state_file()
        sf["stack"][-1]["reviews_submitted"] = list(wd.REVIEW_ROLES)
        wd._save_stack(sf["stack"], history=sf["history"])

    def test_review_approve_returns_to_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "test")
        wd.end_step("test commit")
        wd.request_review()
        self.assertEqual(wd.read_state()["phase"], "review")
        self._submit_mock_reviews(wd)
        wd.approve()
        self.assertEqual(wd.read_state()["phase"], "approved")
        self.assertNotIn("mode", wd.read_state())

    def test_feedback_returns_to_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        self._submit_mock_reviews(wd)
        wd.feedback()
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "1")

    @patch.object(WorkflowDev, "_write_issue_body")
    @patch.object(WorkflowDev, "_read_issue_body")
    def test_feedback_inserts_todos_above_steps(self, mock_read, mock_write):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        self._submit_mock_reviews(wd)
        mock_read.return_value = "Some text\n\n## Steps\n\n- [x] step one"
        wd.feedback(items=["Fix this", "Fix that"])
        mock_write.assert_called_once()
        body = mock_write.call_args[0][1]
        self.assertIn("- [ ] Fix this", body)
        self.assertIn("- [ ] Fix that", body)
        steps_idx = body.index("## Steps")
        todos_idx = body.index("- [ ] Fix this")
        self.assertLess(todos_idx, steps_idx)

    @patch.object(WorkflowDev, "_write_issue_body")
    @patch.object(WorkflowDev, "_read_issue_body")
    def test_feedback_without_items_skips_body_edit(self, mock_read, mock_write):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        self._submit_mock_reviews(wd)
        wd.feedback()
        mock_write.assert_not_called()

    def test_feedback_without_reviews_fails(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        with self.assertRaises(ValueError) as ctx:
            wd.feedback()
        self.assertIn("missing reviews", str(ctx.exception))

    def test_approve_without_reviews_fails(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        with self.assertRaises(ValueError) as ctx:
            wd.approve()
        self.assertIn("missing reviews", str(ctx.exception))

    @patch.object(WorkflowDev, "close_issue")
    @patch.object(WorkflowDev, "_review_status")
    def test_finish_review_approve_transitions_to_approved_when_all_done(self, mock_status, mock_close):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        mock_status.return_value = {"user": "done", "architect": "done"}
        wd.finish_review_approve("https://github.com/test/repo/issues/99")
        self.assertEqual(wd.read_state()["phase"], "approved")
        mock_close.assert_called_once_with("https://github.com/test/repo/issues/99")

    @patch.object(WorkflowDev, "_write_issue_body")
    @patch.object(WorkflowDev, "_review_status")
    def test_finish_review_feedback_transitions_to_refactoring_when_no_missing(self, mock_status, mock_write):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        mock_status.return_value = {"user": "pending", "architect": "done"}
        wd.finish_review_feedback("https://github.com/test/repo/issues/99", "Findings here")
        self.assertEqual(wd.read_state()["phase"], "refactoring")
        mock_write.assert_called_once()

    @patch.object(WorkflowDev, "close_issue")
    @patch.object(WorkflowDev, "_review_status")
    def test_finish_review_does_not_transition_when_role_missing(self, mock_status, mock_close):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        mock_status.return_value = {"user": "done", "architect": "missing"}
        wd.finish_review_approve("https://github.com/test/repo/issues/99")
        self.assertEqual(wd.read_state()["phase"], "review")

    @patch.object(WorkflowDev, "close_issue")
    @patch.object(WorkflowDev, "_review_status")
    def test_finish_review_does_not_transition_when_not_in_review(self, mock_status, mock_close):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        # Parent stays in refactoring (no request-review)
        mock_status.return_value = {"user": "done", "architect": "done"}
        wd.finish_review_approve("https://github.com/test/repo/issues/99")
        self.assertEqual(wd.read_state()["phase"], "refactoring")

    def test_finish_review_feedback_rejects_empty_findings(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        with self.assertRaises(ValueError):
            wd.finish_review_feedback("https://github.com/test/repo/issues/99", "  ")

    def test_end_task_after_review(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        self._submit_mock_reviews(wd)
        wd.approve()
        wd.end_task()
        self.assertEqual(wd.read_state()["phase"], "idle")

    def test_end_task_without_review_fails(self):
        wd = self._make_wd()
        wd.begin_task("1")
        with self.assertRaises(ValueError):
            wd.end_task()

    def test_end_step_at_root_raises(self):
        wd = self._make_wd()
        wd.begin_task("1")
        with self.assertRaises(ValueError):
            wd.end_step("test commit")

    def test_end_step_failure_keeps_step_on_stack(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        # Make test.sh fail
        (self.test_dir / "test" / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        with self.assertRaises(RuntimeError):
            wd.end_step("test commit")
        # Step should still be on stack
        self.assertEqual(wd.read_state().get("step"), "[refactor/code] Work")

    def test_end_step_retry_after_fix(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        # Fail first
        (self.test_dir / "test" / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        with self.assertRaises(RuntimeError):
            wd.end_step("test commit")
        # Fix and retry
        (self.test_dir / "test" / "test.sh").write_text("#!/bin/bash\nexit 0\n")
        wd.end_step("test commit")  # should succeed now
        self.assertNotIn("step", wd.read_state())

    def test_abort_step_pops_without_tests(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        # Make test.sh fail — abort should still work
        (self.test_dir / "test" / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        wd.abort_step()  # no tests run
        self.assertNotIn("step", wd.read_state())

    def test_completed_step_in_history(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Fix imports", "code")
        wd.end_step("test commit")
        history = wd._read_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["step"], "[refactor/code] Fix imports")
        self.assertEqual(history[0]["status"], "completed")
        self.assertIn("commit", history[0])

    def test_failed_end_step_no_history_entry(self):
        """Failed end-step doesn't record in history (step stays on stack)."""
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Bad change", "code")
        (self.test_dir / "test" / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        with self.assertRaises(RuntimeError):
            wd.end_step("test commit")
        history = wd._read_history()
        self.assertEqual(len(history), 0)

    def test_aborted_step_in_history(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Wrong approach", "code")
        wd.abort_step()
        history = wd._read_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "aborted")

    def test_history_accumulates(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Step 1", "code")
        wd.end_step("test commit")
        wd.begin_refactor("Step 2", "test")
        wd.end_step("test commit")
        history = wd._read_history()
        self.assertEqual(len(history), 2)

    def test_legacy_format_auto_migrates(self):
        """Old flat-list state.json should be readable."""
        state_path = self.test_dir / "state.json"
        state_path.write_text(json.dumps([{"phase": "refactoring", "task": "old-task"}]))
        wd = self._make_wd()
        self.assertEqual(wd.read_state()["task"], "old-task")
        self.assertEqual(wd._read_history(), [])

    def test_invalid_transitions(self):
        wd = self._make_wd()
        with self.assertRaises(ValueError):
            wd.begin_refactor("Work", "code")  # no task
        with self.assertRaises(ValueError):
            wd.request_review()  # no task
        with self.assertRaises(ValueError):
            wd.approve()  # not in review


class CheckEditTest(TestFixture):
    def test_blocked_no_task(self):
        wd = self._make_wd()
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)

    def test_blocked_in_idle(self):
        wd = self._make_wd()
        wd.begin_task("1")
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)

    def test_code_step_allows_code(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        allowed, _ = wd.check_edit("workflow.py")
        self.assertTrue(allowed)

    def test_code_step_blocks_test(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        allowed, _ = wd.check_edit("test.py")
        self.assertFalse(allowed)

    def test_test_step_allows_test(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "test")
        allowed, _ = wd.check_edit("test.py")
        self.assertTrue(allowed)

    def test_test_step_blocks_code(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "test")
        allowed, _ = wd.check_edit("workflow.py")
        self.assertFalse(allowed)

    def test_modify_step_allows_all(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_modify("Feature", rationale=["test: change"])
        allowed_code, _ = wd.check_edit("workflow.py")
        allowed_test, _ = wd.check_edit("test.py")
        self.assertTrue(allowed_code)
        self.assertTrue(allowed_test)

    def test_review_blocks_all(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)

    def test_file_outside_project_allowed(self):
        wd = self._make_wd()
        allowed, _ = wd.check_edit("/Users/someone/.claude/memory/test.md")
        self.assertTrue(allowed)


class CheckWriteTest(TestFixture):
    def test_blocked_no_task(self):
        wd = self._make_wd()
        allowed, _ = wd.check_write("new_file.py")
        self.assertFalse(allowed)

    def test_test_step_allows_new_test(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "test")
        allowed, _ = wd.check_write("test_new.py")
        self.assertTrue(allowed)

    def test_test_step_blocks_new_code(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "test")
        allowed, _ = wd.check_write("new_module.py")
        self.assertFalse(allowed)

    def test_modify_step_allows_all(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_modify("Feature", rationale=["test: change"])
        allowed, _ = wd.check_write("new_module.py")
        self.assertTrue(allowed)

    def test_review_blocks_all(self):
        wd = self._make_wd()
        wd.begin_task("1")
        wd.begin_refactor("Work", "code")
        wd.end_step("test commit")
        wd.request_review()
        allowed, _ = wd.check_write("new_file.py")
        self.assertFalse(allowed)

    def test_file_outside_project_allowed(self):
        wd = self._make_wd()
        allowed, _ = wd.check_write("/tmp/scratch.txt")
        self.assertTrue(allowed)


class TodoMarkingTest(unittest.TestCase):
    """Tests for issue body todo marking (fail/abort/complete)."""

    def setUp(self):
        self.body = ""

    def _mock_read(self, url):
        return self.body

    def _mock_write(self, url, body):
        self.body = body

    def _make_workflow(self):
        """Create a WorkflowDev with mocked issue body read/write."""
        orig_dir = os.getcwd()
        test_dir = Path(tempfile.mkdtemp())
        os.chdir(test_dir)
        (test_dir / "test").mkdir(exist_ok=True)
        (test_dir / "test" / "test.sh").write_text("#!/bin/bash\nexit 0\n")
        (test_dir / "test" / "test.sh").chmod(0o755)
        import subprocess
        subprocess.run(["git", "init", "-b", "main"], capture_output=True, cwd=test_dir)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       capture_output=True, cwd=test_dir)
        wd = WorkflowDev(test_dir)
        wd._read_issue_body = self._mock_read
        wd._write_issue_body = self._mock_write
        self._test_dir = test_dir
        self._orig_dir = orig_dir
        return wd

    def tearDown(self):
        os.chdir(self._orig_dir)
        shutil.rmtree(self._test_dir)

    def test_activate_adds_mode_emoji(self):
        wd = self._make_workflow()
        wd.activate_issue_todo("url", "[refactor/code] Fix thing", "code")
        self.assertIn("🟢 [refactor/code] Fix thing", self.body)
        self.assertIn("- [ ]", self.body)

    def test_complete_replaces_with_commit_link(self):
        wd = self._make_workflow()
        self.body = "- [ ] 🟢 [refactor/code] Fix thing"
        wd._get_issue_number = lambda url: "1"
        wd.get_repo = lambda: "owner/repo"
        wd.complete_issue_todo("url", "[refactor/code] Fix thing", "abc1234def")
        self.assertIn("- [x]", self.body)
        self.assertIn("abc1234", self.body)
        self.assertNotIn("- [ ]", self.body)

    def test_abort_marks_with_stop(self):
        wd = self._make_workflow()
        self.body = "- [ ] 🟠 [modify] Add feature"
        wd.abort_issue_todo("url", "[modify] Add feature")
        self.assertIn("⛔", self.body)
        self.assertIn("(aborted)", self.body)
        self.assertNotIn("- [ ]", self.body)

if __name__ == "__main__":
    unittest.main()
