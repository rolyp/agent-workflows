#!/usr/bin/env python3
"""Tests for WorkflowDev."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from workflow import WorkflowDev, SUBMODULE_DIR


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = Path(tempfile.mkdtemp())
        os.chdir(self.test_dir)
        # Create submodule directory structure
        (self.test_dir / SUBMODULE_DIR / "paper-authoring").mkdir(parents=True)
        self.wd = WorkflowDev(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)


class CheckEditTest(TestFixture):
    def test_submodule_file_allowed(self):
        allowed, msg = self.wd.check_edit(f"{SUBMODULE_DIR}/paper-authoring/status_tracker.py")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_tex_file_blocked(self):
        allowed, msg = self.wd.check_edit("sec/introduction.tex")
        self.assertFalse(allowed)
        self.assertIn(SUBMODULE_DIR, msg)

    def test_dashboard_blocked(self):
        allowed, msg = self.wd.check_edit("workflow/dashboard.md")
        self.assertFalse(allowed)
        self.assertIn(SUBMODULE_DIR, msg)

    def test_file_outside_project_allowed(self):
        allowed, msg = self.wd.check_edit("/Users/someone/.claude/memory/test.md")
        self.assertTrue(allowed)

    def test_absolute_submodule_path_allowed(self):
        abs_path = str(self.test_dir / SUBMODULE_DIR / "paper-authoring" / "test.py")
        allowed, msg = self.wd.check_edit(abs_path)
        self.assertTrue(allowed)


class CheckWriteTest(TestFixture):
    def test_new_submodule_file_allowed(self):
        allowed, msg = self.wd.check_write(f"{SUBMODULE_DIR}/paper-authoring/new_file.py")
        self.assertTrue(allowed)

    def test_existing_submodule_file_blocked(self):
        existing = self.test_dir / SUBMODULE_DIR / "paper-authoring" / "existing.py"
        existing.write_text("content\n")
        allowed, msg = self.wd.check_write(f"{SUBMODULE_DIR}/paper-authoring/existing.py")
        self.assertFalse(allowed)
        self.assertIn("Edit tool", msg)

    def test_non_submodule_file_blocked(self):
        allowed, msg = self.wd.check_write("sec/new_section.tex")
        self.assertFalse(allowed)
        self.assertIn(SUBMODULE_DIR, msg)

    def test_file_outside_project_allowed(self):
        allowed, msg = self.wd.check_write("/tmp/scratch.txt")
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
