#!/usr/bin/env python3
"""Status Tracker: owns all task state and marker coherence.

Each method reads current state from disk, performs its operation, and writes
back. No in-memory state is cached between calls.

State is externalised to workflow/state.json and reported in the dashboard.
"""

import glob
import json
import re
import sys
from pathlib import Path

PHASES = ("idle", "selecting", "edit", "review", "closeout")


class StatusTracker:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.dashboard_path = project_root / "workflow" / "dashboard.md"
        self.structural_path = project_root / "workflow" / "todo" / "structural.md"
        self.completed_path = project_root / "workflow" / "todo" / "completed.md"
        self.state_path = project_root / "workflow" / "state.json"

    # --- State ---

    def read_state(self) -> dict:
        if not self.state_path.exists():
            return {"phase": "idle", "task": None}
        return json.loads(self.state_path.read_text())

    def _write_state(self, phase: str, task: str | None = None) -> None:
        assert phase in PHASES, f"Invalid phase: {phase}"
        state = {"phase": phase, "task": task}
        self.state_path.write_text(json.dumps(state, indent=2) + "\n")
        self._update_dashboard_state(phase, task)

    def _update_dashboard_state(self, phase: str, task: str | None) -> None:
        if not self.dashboard_path.exists():
            return
        dashboard = self._read_dashboard()
        state_line = f"**State:** {phase}" + (f" — {task}" if task else "")
        # Replace existing state line or insert after header
        if re.search(r"^\*\*State:\*\*", dashboard, re.MULTILINE):
            dashboard = re.sub(
                r"^\*\*State:\*\*.*$", state_line, dashboard, flags=re.MULTILINE
            )
        else:
            dashboard = dashboard.replace(
                "# Task Dashboard\n",
                f"# Task Dashboard\n\n{state_line}\n",
            )
        self.dashboard_path.write_text(dashboard)

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
        errors += self._state_consistent_with_markers(dashboard)
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

    def _state_consistent_with_markers(self, dashboard: str) -> list[str]:
        state = self.read_state()
        phase = state["phase"]
        has_select = bool(self._tex_files_containing("\\selectstart"))
        has_review = bool(self._tex_files_containing("\\reviewstart"))
        errors = []
        if phase == "edit" and not has_select:
            errors.append("State is 'edit' but no select bars found in .tex files")
        if phase == "review" and not has_review:
            errors.append("State is 'review' but no review bars found in .tex files")
        if phase == "idle" and (has_select or has_review):
            errors.append("State is 'idle' but markers found in .tex files")
        return errors

    # --- Commands ---

    def begin_review(self) -> None:
        """Replace select bars with review bars in .tex files."""
        for path in self._tex_files_containing("\\selectstart"):
            text = Path(path).read_text()
            text = text.replace("\\selectstart", "\\reviewstart")
            text = text.replace("\\selectend", "\\reviewend")
            Path(path).write_text(text)
        state = self.read_state()
        self._write_state("review", state.get("task"))

    def return_to_edit(self) -> None:
        """Replace review bars with select bars in .tex files."""
        for path in self._tex_files_containing("\\reviewstart"):
            text = Path(path).read_text()
            text = text.replace("\\reviewstart", "\\selectstart")
            text = text.replace("\\reviewend", "\\selectend")
            Path(path).write_text(text)
        state = self.read_state()
        self._write_state("edit", state.get("task"))

    # --- PreToolUse hook ---

    def check_edit(self, file_path: str) -> tuple[bool, str]:
        """Check whether an edit to file_path is allowed.

        Returns (allowed, message). If not allowed, message explains
        what state transition is needed.
        """
        if not file_path.endswith(".tex"):
            return True, ""
        state = self.read_state()
        phase = state["phase"]
        task = state.get("task") or "unknown"
        if phase == "review":
            return False, (
                f"Cannot edit .tex files during review phase (task: {task}). "
                f"Run `status_tracker.py return-to-edit` first."
            )
        if phase == "idle":
            return True, "Note: no active task. Is this an ad hoc edit?"
        return True, ""

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
    elif command == "check-edit":
        if len(sys.argv) < 3:
            print("Usage: status_tracker.py check-edit <file_path>", file=sys.stderr)
            sys.exit(1)
        allowed, message = tracker.check_edit(sys.argv[2])
        if not allowed:
            print(message, file=sys.stderr)
            sys.exit(2)
        elif message:
            print(message, file=sys.stderr)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
