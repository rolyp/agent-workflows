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
from enum import Enum
from pathlib import Path


class Phase(Enum):
    IDLE = "idle"                        # No active task
    TRIAGE = "triage"                    # Reviewing structural/minor notes before editing cycle
    SELECTING = "selecting"              # Phase 1: choosing next task
    EDIT = "edit"                        # Phase 2: editing within select bars
    AUTHOR_REVIEW = "author-review"      # Phase 3: awaiting author approval
    CLOSEOUT = "closeout"                # Phase 4: structural close-out


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} invariant(s) violated")


class StatusTracker:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.dashboard_path = project_root / "workflow" / "dashboard.md"
        self.structural_path = project_root / "workflow" / "todo" / "structural.md"
        self.completed_path = project_root / "workflow" / "todo" / "completed.md"
        self.state_path = project_root / "workflow" / "state.json"

        # Preconditions: workflow files must exist
        missing = []
        for path in (self.dashboard_path, self.structural_path, self.completed_path):
            if not path.exists():
                missing.append(str(path.relative_to(self.root)))
        if missing:
            raise FileNotFoundError(f"Missing workflow files: {', '.join(missing)}")

        # Initialise state file if absent
        if not self.state_path.exists():
            self._write_state(Phase.IDLE)

        self.assert_valid()

    # --- Invariants ---

    def assert_valid(self) -> None:
        errors = []
        dashboard = self._read_dashboard()
        errors += self._state_file_exists()
        errors += self._at_most_one_in_progress(dashboard)
        errors += self._no_orphaned_markers(dashboard)
        errors += self._markers_do_not_coexist()
        errors += self._progress_counts_consistent(dashboard)
        errors += self._state_consistent_with_markers()
        if errors:
            raise ValidationError(errors)

    def _state_file_exists(self) -> list[str]:
        if not self.state_path.exists():
            return ["workflow/state.json does not exist"]
        return []

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

    def _state_consistent_with_markers(self) -> list[str]:
        phase = self._read_phase()
        has_select = bool(self._tex_files_containing("\\selectstart"))
        has_review = bool(self._tex_files_containing("\\reviewstart"))
        errors = []
        if phase is Phase.EDIT and not has_select:
            errors.append("State is 'edit' but no select bars found in .tex files")
        if phase is Phase.AUTHOR_REVIEW and not has_review:
            errors.append("State is 'author-review' but no review bars found in .tex files")
        if phase is Phase.IDLE and (has_select or has_review):
            errors.append("State is 'idle' but markers found in .tex files")
        return errors

    # --- State ---

    def read_state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def _read_phase(self) -> Phase:
        return Phase(self.read_state()["phase"])

    def _write_state(self, phase: Phase, task: str | None = None) -> None:
        state = {"phase": phase.value, "task": task}
        self.state_path.write_text(json.dumps(state, indent=2) + "\n")
        self._update_dashboard_state(phase, task)

    def _update_dashboard_state(self, phase: Phase, task: str | None) -> None:
        if not self.dashboard_path.exists():
            return
        dashboard = self._read_dashboard()
        state_line = f"**State:** {phase.value}" + (f" — {task}" if task else "")
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

    # --- Triage commands ---

    def begin_triage(self) -> None:
        """Enter triage phase."""
        self._write_state(Phase.TRIAGE)
        self.assert_valid()

    def reclassify(self, note_id: str, target: str) -> None:
        """Move a note between structural.md and minor-issues.md.

        target must be 'structural' or 'minor'.
        """
        assert target in ("structural", "minor"), f"Invalid target: {target}"
        source_path = self.structural_path if target == "minor" else self._minor_issues_path()
        target_path = self._minor_issues_path() if target == "minor" else self.structural_path
        source_text = source_path.read_text()
        # Extract the note block (### Note <id> through next ### or end)
        pattern = rf"(### Note {re.escape(note_id)}\n.*?)(?=\n### |\Z)"
        match = re.search(pattern, source_text, re.DOTALL)
        if not match:
            raise ValueError(f"Note '{note_id}' not found in {source_path.relative_to(self.root)}")
        note_block = match.group(1).strip()
        # Remove from source
        source_text = re.sub(pattern + r"\n?", "", source_text, flags=re.DOTALL)
        source_path.write_text(source_text)
        # Append to target
        target_text = target_path.read_text().rstrip()
        target_path.write_text(target_text + "\n\n" + note_block + "\n")

    def approve_triage(self) -> None:
        """Exit triage, enter idle (ready for Phase 1–4 cycle)."""
        self._write_state(Phase.IDLE)
        self.assert_valid()

    # --- Phase transition commands ---

    def begin_review(self) -> None:
        """Replace select bars with review bars in .tex files."""
        for path in self._tex_files_containing("\\selectstart"):
            text = Path(path).read_text()
            text = text.replace("\\selectstart", "\\reviewstart")
            text = text.replace("\\selectend", "\\reviewend")
            Path(path).write_text(text)
        task = self.read_state().get("task")
        self._write_state(Phase.AUTHOR_REVIEW, task)
        self.assert_valid()

    def return_to_edit(self) -> None:
        """Replace review bars with select bars in .tex files."""
        for path in self._tex_files_containing("\\reviewstart"):
            text = Path(path).read_text()
            text = text.replace("\\reviewstart", "\\selectstart")
            text = text.replace("\\reviewend", "\\selectend")
            Path(path).write_text(text)
        task = self.read_state().get("task")
        self._write_state(Phase.EDIT, task)
        self.assert_valid()

    # --- PreToolUse gate ---

    def check_edit(self, file_path: str) -> tuple[bool, str]:
        """Check whether an edit to file_path is allowed.

        Returns (allowed, message). If not allowed, message explains
        what state transition is needed.
        """
        if not file_path.endswith(".tex"):
            return True, ""
        phase = self._read_phase()
        task = self.read_state().get("task") or "unknown"
        if phase is Phase.TRIAGE:
            return False, (
                "Cannot edit .tex files during triage phase. "
                "Run `status_tracker.py approve-triage` to enter editing cycle first."
            )
        if phase is Phase.AUTHOR_REVIEW:
            return False, (
                f"Cannot edit .tex files during author-review phase (task: {task}). "
                f"Run `status_tracker.py return-to-edit` first."
            )
        if phase is Phase.IDLE:
            return True, "Note: no active task. Is this an ad hoc edit?"
        return True, ""

    # --- Helpers ---

    def _minor_issues_path(self) -> Path:
        return self.root / "workflow" / "todo" / "minor-issues.md"

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
        command = "startup"
    else:
        command = sys.argv[1]

    try:
        tracker = StatusTracker(Path.cwd())
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(0)  # non-fatal for hooks — project may not use workflow
    except ValidationError as e:
        print(f"Workflow validation: {len(e.errors)} issue(s)")
        for err in e.errors:
            print(f"  - {err}")
        if command == "startup":
            sys.exit(0)  # report to Claude's context, don't block
        else:
            sys.exit(1)

    if command == "startup":
        state = tracker.read_state()
        phase = state["phase"]
        task = state.get("task")
        summary = f"Workflow state: {phase}"
        if task:
            summary += f" — {task}"
        print(summary)
    elif command == "begin-triage":
        tracker.begin_triage()
        print("Entered triage phase")
    elif command == "reclassify":
        if len(sys.argv) < 4:
            print("Usage: status_tracker.py reclassify <note-id> <structural|minor>", file=sys.stderr)
            sys.exit(1)
        tracker.reclassify(sys.argv[2], sys.argv[3])
        print(f"Reclassified {sys.argv[2]} → {sys.argv[3]}")
    elif command == "approve-triage":
        tracker.approve_triage()
        print("Triage complete; entering idle")
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
