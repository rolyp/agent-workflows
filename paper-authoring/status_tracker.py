#!/usr/bin/env python3
"""Status Tracker: owns all task state and marker coherence.

Each method reads current state from disk, performs its operation, and writes
back. No in-memory state is cached between calls.
"""

import glob
import re
import sys
from pathlib import Path


class StatusTracker:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.dashboard_path = project_root / "workflow" / "dashboard.md"
        self.structural_path = project_root / "workflow" / "todo" / "structural.md"
        self.completed_path = project_root / "workflow" / "todo" / "completed.md"

    # --- Validation ---

    def validate(self) -> list[str]:
        missing = self._files_exist()
        if missing:
            return missing
        dashboard = self._read_dashboard()
        errors = []
        errors += self._at_most_one_in_progress(dashboard)
        errors += self._no_orphaned_markers(dashboard)
        errors += self._in_progress_has_markers(dashboard)
        errors += self._markers_do_not_coexist()
        errors += self._progress_counts_consistent(dashboard)
        return errors

    def _files_exist(self) -> list[str]:
        errors = []
        for path in (self.dashboard_path, self.structural_path, self.completed_path):
            if not path.exists():
                errors.append(f"Missing: {path.relative_to(self.root)}")
        return errors

    def _at_most_one_in_progress(self, dashboard: str) -> list[str]:
        n = self._count_in_progress(dashboard)
        if n > 1:
            return [f"Multiple in-progress tasks ({n}) — expected at most 1"]
        return []

    def _no_orphaned_markers(self, dashboard: str) -> list[str]:
        if self._count_in_progress(dashboard) > 0:
            return []
        errors = []
        if self._tex_files_containing("\\selectstart"):
            errors.append("Orphaned \\selectstart markers but no in-progress task")
        if self._tex_files_containing("\\reviewstart"):
            errors.append("Orphaned \\reviewstart markers but no in-progress task")
        return errors

    def _in_progress_has_markers(self, dashboard: str) -> list[str]:
        if self._count_in_progress(dashboard) == 0:
            return []
        if not self._tex_files_containing("\\selectstart") and not self._tex_files_containing("\\reviewstart"):
            return ["In-progress task but no select/review markers in .tex files"]
        return []

    def _markers_do_not_coexist(self) -> list[str]:
        if self._tex_files_containing("\\selectstart") and self._tex_files_containing("\\reviewstart"):
            return ["Both \\selectstart and \\reviewstart markers present — should not coexist"]
        return []

    def _progress_counts_consistent(self, dashboard: str) -> list[str]:
        errors = []
        for kind in ("minor", "structural"):
            match = re.search(
                rf"Completed {kind}.*?\((\d+) of (\d+)\)", dashboard, re.IGNORECASE
            )
            if not match:
                continue
            done = int(match.group(1))
            total = int(match.group(2))
            todo = self._count_section_items(dashboard, kind.capitalize())
            expected = done + todo
            if total != expected:
                errors.append(
                    f"{kind} count mismatch: header says {done} of {total}, "
                    f"but {done} done + {todo} to-do = {expected}"
                )
        return errors

    # --- Commands (to be added incrementally) ---

    def begin_review(self) -> None:
        """Replace select bars with review bars in .tex files."""
        for path in self._tex_files_containing("\\selectstart"):
            text = Path(path).read_text()
            text = text.replace("\\selectstart", "\\reviewstart")
            text = text.replace("\\selectend", "\\reviewend")
            Path(path).write_text(text)

    def return_to_edit(self) -> None:
        """Replace review bars with select bars in .tex files."""
        for path in self._tex_files_containing("\\reviewstart"):
            text = Path(path).read_text()
            text = text.replace("\\reviewstart", "\\selectstart")
            text = text.replace("\\reviewend", "\\selectend")
            Path(path).write_text(text)

    # --- Helpers ---

    def _read_dashboard(self) -> str:
        return self.dashboard_path.read_text()

    def _count_in_progress(self, dashboard: str) -> int:
        return len(re.findall("🔵", dashboard))

    def _tex_files_containing(self, pattern: str) -> list[str]:
        return [
            f for f in glob.glob(str(self.root / "**" / "*.tex"), recursive=True)
            if pattern in Path(f).read_text()
        ]

    def _count_section_items(self, dashboard: str, section: str) -> int:
        match = re.search(
            rf"^### {section}$\n(.*?)(?=^### |\Z)",
            dashboard, re.MULTILINE | re.DOTALL,
        )
        if not match:
            return 0
        return len(re.findall(r"^- ", match.group(1), re.MULTILINE))


# --- CLI entry point ---

def main() -> None:
    if len(sys.argv) < 2:
        command = "validate"
    else:
        command = sys.argv[1]

    tracker = StatusTracker(Path.cwd())

    if command == "validate":
        errors = tracker.validate()
        if not errors:
            print("Workflow validation: OK")
        else:
            print(f"Workflow validation: {len(errors)} issue(s)")
            for e in errors:
                print(f"  - {e}")
    elif command == "begin-review":
        tracker.begin_review()
        print("Markers: select → review")
    elif command == "return-to-edit":
        tracker.return_to_edit()
        print("Markers: review → select")
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
