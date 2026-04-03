#!/usr/bin/env python3
"""Tests for WorkflowDev."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from workflow_dev.workflow import WorkflowDev, Phase, RefactoringMode, _is_test_file


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = Path(tempfile.mkdtemp())
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _make_wd(self) -> WorkflowDev:
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
    def test_start_task_enters_refactoring(self):
        wd = self._make_wd()
        wd.start_task("extract-base")
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "extract-base")
        self.assertNotIn("mode", state)

    def test_start_task_rejects_non_idle(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        with self.assertRaises(ValueError):
            wd.start_task("task-2")

    def test_expand_coverage(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        self.assertEqual(wd.read_state()["mode"], "expand-coverage")

    def test_refactor_code(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        self.assertEqual(wd.read_state()["mode"], "refactor-code")

    def test_toggle_modes(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        wd.refactor_code()
        self.assertEqual(wd.read_state()["mode"], "refactor-code")
        wd.expand_coverage()
        self.assertEqual(wd.read_state()["mode"], "expand-coverage")

    def test_review_of_refactoring_approves_to_refactoring(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        wd.request_review()
        self.assertEqual(wd.read_state()["review_of"], "refactoring")
        wd.approve()
        self.assertEqual(wd.read_state()["phase"], "refactoring")

    def test_begin_modify_enters_modifying(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("add feature X")
        state = wd.read_state()
        self.assertEqual(state["phase"], "modifying")
        self.assertEqual(state["modify_description"], "add feature X")

    def test_begin_modify_only_from_refactoring(self):
        wd = self._make_wd()
        with self.assertRaises(ValueError):
            wd.begin_modify("nope")  # not in refactoring

    def test_back_to_refactor(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        wd.back_to_refactor()
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertNotIn("mode", state)  # locked again

    def test_review_of_modifying_approves_to_idle(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        wd.request_review()
        self.assertEqual(wd.read_state()["review_of"], "modifying")
        wd.approve()
        self.assertEqual(wd.read_state()["phase"], "idle")

    def test_feedback_on_refactoring_review_returns_to_refactoring(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        wd.request_review()
        wd.feedback()
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "task-1")

    def test_feedback_on_modifying_review_returns_to_refactoring(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        wd.request_review()
        wd.feedback()
        state = wd.read_state()
        self.assertEqual(state["phase"], "refactoring")
        self.assertEqual(state["task"], "task-1")

    def test_begin_step_pushes_frame(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        wd.begin_step("fix-import")
        state = wd.read_state()
        self.assertEqual(state["step"], "fix-import")
        self.assertEqual(state["phase"], "refactoring")

    def test_end_step_pops_frame(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        wd.begin_step("fix-import")
        wd.end_step()
        state = wd.read_state()
        self.assertNotIn("step", state)
        self.assertEqual(state["phase"], "refactoring")

    def test_cannot_nest_steps(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        wd.begin_step("step-1")
        with self.assertRaises(ValueError):
            wd.begin_step("step-2")

    def test_cannot_request_review_during_step(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        wd.begin_step("step-1")
        with self.assertRaises(ValueError):
            wd.request_review()

    def test_end_step_without_begin_raises(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        with self.assertRaises(ValueError):
            wd.end_step()

    def test_step_preserves_mode(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        wd.begin_step("add-tests")
        self.assertEqual(wd.read_state()["mode"], "expand-coverage")

    def test_invalid_transitions(self):
        wd = self._make_wd()
        with self.assertRaises(ValueError):
            wd.expand_coverage()  # not in refactoring
        with self.assertRaises(ValueError):
            wd.request_review()  # not in refactoring or modifying
        with self.assertRaises(ValueError):
            wd.approve()  # not in review


class CheckEditTest(TestFixture):
    def test_blocked_in_idle(self):
        wd = self._make_wd()
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)
        self.assertIn("start-task", msg)

    def test_blocked_in_refactoring_no_mode(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)
        self.assertIn("expand-coverage", msg)

    def test_expand_coverage_allows_test_edit(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        allowed, msg = wd.check_edit("test.py")
        self.assertTrue(allowed)

    def test_expand_coverage_blocks_code_edit(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)
        self.assertIn("refactor-code", msg)

    def test_refactor_code_allows_code_edit(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        allowed, msg = wd.check_edit("workflow.py")
        self.assertTrue(allowed)

    def test_refactor_code_blocks_test_edit(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.refactor_code()
        allowed, msg = wd.check_edit("test.py")
        self.assertFalse(allowed)
        self.assertIn("expand-coverage", msg)

    def test_modifying_allows_all(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        allowed_code, _ = wd.check_edit("workflow.py")
        allowed_test, _ = wd.check_edit("test.py")
        self.assertTrue(allowed_code)
        self.assertTrue(allowed_test)

    def test_review_blocks_all(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        wd.request_review()
        allowed, msg = wd.check_edit("workflow.py")
        self.assertFalse(allowed)
        self.assertIn("review", msg)

    def test_file_outside_project_allowed(self):
        wd = self._make_wd()
        allowed, msg = wd.check_edit("/Users/someone/.claude/memory/test.md")
        self.assertTrue(allowed)


class CheckWriteTest(TestFixture):
    def test_blocked_in_idle(self):
        wd = self._make_wd()
        allowed, msg = wd.check_write("new_file.py")
        self.assertFalse(allowed)

    def test_expand_coverage_allows_new_test(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        allowed, msg = wd.check_write("test_new.py")
        self.assertTrue(allowed)

    def test_expand_coverage_blocks_new_code(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.expand_coverage()
        allowed, msg = wd.check_write("new_module.py")
        self.assertFalse(allowed)

    def test_modifying_allows_all(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        allowed, msg = wd.check_write("new_module.py")
        self.assertTrue(allowed)

    def test_review_blocks_all(self):
        wd = self._make_wd()
        wd.start_task("task-1")
        wd.begin_modify("feature X")
        wd.request_review()
        allowed, msg = wd.check_write("new_file.py")
        self.assertFalse(allowed)

    def test_file_outside_project_allowed(self):
        wd = self._make_wd()
        allowed, msg = wd.check_write("/tmp/scratch.txt")
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
