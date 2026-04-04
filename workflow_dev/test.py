#!/usr/bin/env python3
"""Tests for WorkflowDev."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from workflow_dev.workflow import WorkflowDev, Phase, StepMode, _is_test_file


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = Path(tempfile.mkdtemp())
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _make_wd(self) -> WorkflowDev:
        # Create minimal test.sh so _run_tests succeeds in temp dir
        test_sh = self.test_dir / "test.sh"
        test_sh.write_text("#!/bin/bash\nexit 0\n")
        test_sh.chmod(0o755)
        # Init git repo so git rev-parse HEAD works (for reviewed_sha)
        import subprocess
        subprocess.run(["git", "init"], capture_output=True, cwd=self.test_dir)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       capture_output=True, cwd=self.test_dir)
        return WorkflowDev(self.test_dir)


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
        wd.begin_task("extract-base")
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "extract-base")
        self.assertNotIn("mode", state)

    def test_begin_task_rejects_non_idle(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        with self.assertRaises(ValueError):
            wd.begin_task("task-2")

    def test_begin_step_pushes_frame(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Fix imports", "code")
        state = wd.read_state()
        self.assertEqual(state["step"], "[refactor/code] Fix imports")
        self.assertEqual(state["mode"], "code")

    def test_end_step_pops_to_idle(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Fix imports", "code")
        wd.end_step()
        state = wd.read_state()
        self.assertNotIn("step", state)
        self.assertNotIn("mode", state)

    def test_nested_steps(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Outer", "code")
        wd.begin_step("Inner", "code")
        self.assertEqual(wd.read_state()["step"], "[refactor/code] Inner")
        wd.end_step()
        self.assertEqual(wd.read_state()["step"], "[refactor/code] Outer")
        wd.end_step()
        self.assertNotIn("step", wd.read_state())

    def test_modify_step(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Add feature", "modify")
        state = wd.read_state()
        self.assertEqual(state["mode"], "modify")
        self.assertEqual(state["phase"], "modifying")

    def test_request_review_only_from_idle(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        with self.assertRaises(ValueError):
            wd.request_review()

    def test_review_approve_returns_to_idle(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "test")
        wd.end_step()
        wd.request_review()
        self.assertEqual(wd.read_state()["phase"], "review")
        wd.approve()
        self.assertEqual(wd.read_state()["phase"], "refactoring")
        self.assertNotIn("mode", wd.read_state())

    def test_feedback_returns_to_idle(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        wd.end_step()
        wd.request_review()
        wd.feedback()
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "task-1")

    def test_end_task_after_review(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        wd.end_step()
        wd.request_review()
        wd.approve()
        wd.end_task()
        self.assertEqual(wd.read_state()["phase"], "idle")

    def test_end_task_without_review_fails(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        with self.assertRaises(ValueError):
            wd.end_task()

    def test_end_step_at_root_raises(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        with self.assertRaises(ValueError):
            wd.end_step()

    def test_end_step_failure_blocks_begin_step(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        # Make test.sh fail
        (self.test_dir / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        with self.assertRaises(RuntimeError):
            wd.end_step()
        # Now begin-step should be blocked
        # Restore test.sh first so it doesn't interfere
        (self.test_dir / "test.sh").write_text("#!/bin/bash\nexit 0\n")
        with self.assertRaises(ValueError) as ctx:
            wd.begin_step("Dodge", "test")
        self.assertIn("end-step failed", str(ctx.exception))

    def test_end_step_retry_after_fix(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        # Fail first
        (self.test_dir / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        with self.assertRaises(RuntimeError):
            wd.end_step()
        # Fix and retry
        (self.test_dir / "test.sh").write_text("#!/bin/bash\nexit 0\n")
        wd.end_step()  # should succeed now
        self.assertNotIn("step", wd.read_state())

    def test_abort_step_pops_without_tests(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        # Make test.sh fail — abort should still work
        (self.test_dir / "test.sh").write_text("#!/bin/bash\nexit 1\n")
        wd.abort_step()  # no tests run
        self.assertNotIn("step", wd.read_state())

    def test_invalid_transitions(self):
        wd = self._make_wd()
        with self.assertRaises(ValueError):
            wd.begin_step("Work", "code")  # no task
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
        wd.begin_task("task-1")
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)

    def test_code_step_allows_code(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        allowed, _ = wd.check_edit("workflow.py")
        self.assertTrue(allowed)

    def test_code_step_blocks_test(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        allowed, _ = wd.check_edit("test.py")
        self.assertFalse(allowed)

    def test_test_step_allows_test(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "test")
        allowed, _ = wd.check_edit("test.py")
        self.assertTrue(allowed)

    def test_test_step_blocks_code(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "test")
        allowed, _ = wd.check_edit("workflow.py")
        self.assertFalse(allowed)

    def test_modify_step_allows_all(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Feature", "modify")
        allowed_code, _ = wd.check_edit("workflow.py")
        allowed_test, _ = wd.check_edit("test.py")
        self.assertTrue(allowed_code)
        self.assertTrue(allowed_test)

    def test_review_blocks_all(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        wd.end_step()
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
        wd.begin_task("task-1")
        wd.begin_step("Work", "test")
        allowed, _ = wd.check_write("test_new.py")
        self.assertTrue(allowed)

    def test_test_step_blocks_new_code(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "test")
        allowed, _ = wd.check_write("new_module.py")
        self.assertFalse(allowed)

    def test_modify_step_allows_all(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Feature", "modify")
        allowed, _ = wd.check_write("new_module.py")
        self.assertTrue(allowed)

    def test_review_blocks_all(self):
        wd = self._make_wd()
        wd.begin_task("task-1")
        wd.begin_step("Work", "code")
        wd.end_step()
        wd.request_review()
        allowed, _ = wd.check_write("new_file.py")
        self.assertFalse(allowed)

    def test_file_outside_project_allowed(self):
        wd = self._make_wd()
        allowed, _ = wd.check_write("/tmp/scratch.txt")
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
