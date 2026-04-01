#!/usr/bin/env python3
"""Tests for validate.py."""

import os
import shutil
import tempfile
import unittest

from validate import validate


DASHBOARD_TEMPLATE = """\
# Task Dashboard

- [Completed minor issues](todo/completed.md#minor) (0 of 0)
- [Completed structural tasks](todo/completed.md#structural) (0 of 2)

## In progress

(none)

## To do

### Minor

(none)

### Structural

- Task one
- Task two
"""


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.orig_dir = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.test_dir)

    def _setup_project(self, dashboard=DASHBOARD_TEMPLATE):
        os.makedirs("workflow/todo", exist_ok=True)
        os.makedirs("sec", exist_ok=True)
        with open("workflow/dashboard.md", "w") as f:
            f.write(dashboard)
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
        dashboard = DASHBOARD_TEMPLATE.replace("(none)", "🔵 Active task", 1)
        self._setup_project(dashboard)
        errors = validate()
        self.assertTrue(any("no select/review markers" in e for e in errors))

    def test_multiple_in_progress(self):
        dashboard = DASHBOARD_TEMPLATE.replace(
            "(none)\n\n## To do",
            "🔵 Task A\n🔵 Task B\n\n## To do",
        )
        self._setup_project(dashboard)
        errors = validate()
        self.assertTrue(any("Multiple in-progress" in e for e in errors))

    def test_coexisting_markers(self):
        dashboard = DASHBOARD_TEMPLATE.replace("(none)", "🔵 Active task", 1)
        self._setup_project(dashboard)
        with open("sec/a.tex", "w") as f:
            f.write("\\selectstart text \\selectend\n")
        with open("sec/b.tex", "w") as f:
            f.write("\\reviewstart text \\reviewend\n")
        errors = validate()
        self.assertTrue(any("should not coexist" in e for e in errors))

    def test_count_mismatch(self):
        dashboard = DASHBOARD_TEMPLATE.replace("0 of 2", "0 of 5")
        self._setup_project(dashboard)
        errors = validate()
        self.assertTrue(any("count mismatch" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
