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


# LaTeX marker commands (must match change-tracking.tex)
EDIT_START = "\\editstart"
EDIT_END = "\\editend"
REVIEW_START = "\\reviewstart"
REVIEW_END = "\\reviewend"

# Change markup commands
CHANGE_MARKUP = ("\\added", "\\deleted", "\\replaced")

# CLI command names
CMD_STARTUP = "startup"
CMD_BEGIN_TRIAGE = "begin-triage"
CMD_RECLASSIFY = "reclassify"
CMD_ADD_TASK = "add-task"
CMD_APPROVE_TRIAGE = "approve-triage"
CMD_SELECT_TASK = "select-task"
CMD_SELECT_AD_HOC = "select-ad-hoc-edit"
CMD_COMPLETE_TASK = "complete-task"
CMD_OPEN_REVIEW = "open-review"
CMD_CLOSE_REVIEW = "close-review"
CMD_EDIT_TO_REVIEW = "edit-to-review"
CMD_REVIEW_TO_EDIT = "review-to-edit"
CMD_CHECK_EDIT = "check-edit"


class Phase(Enum):
    IDLE = "idle"                        # No active task
    TRIAGE = "triage"                    # Reviewing structural/minor notes before editing cycle
    SELECTING = "selecting"              # Phase 1: choosing next task
    EDIT = "edit"                        # Phase 2: editing within edit bars
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
        if self._tex_files_containing(EDIT_START):
            errors.append(f"Orphaned {EDIT_START} markers but no in-progress task")
        if self._tex_files_containing(REVIEW_START):
            errors.append(f"Orphaned {REVIEW_START} markers but no in-progress task")
        return errors

    def _markers_do_not_coexist(self) -> list[str]:
        if self._tex_files_containing(EDIT_START) and self._tex_files_containing(REVIEW_START):
            return [f"Both {EDIT_START} and {REVIEW_START} markers present — should not coexist"]
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
            in_prog = self._count_in_progress_for_kind(dashboard, kind)
            expected = done + in_prog + todo
            if total != expected:
                errors.append(
                    f"{kind} count mismatch: header says {done} of {total}, "
                    f"but {done} done + {in_prog} in-progress + {todo} to-do = {expected}"
                )
        return errors

    def _state_consistent_with_markers(self) -> list[str]:
        phase = self._read_phase()
        has_edit = bool(self._tex_files_containing(EDIT_START))
        has_review = bool(self._tex_files_containing(REVIEW_START))
        errors = []
        if phase is Phase.EDIT and not has_edit:
            errors.append("State is 'edit' but no edit bars found in .tex files")
        if phase is Phase.AUTHOR_REVIEW and not has_review:
            errors.append("State is 'author-review' but no review bars found in .tex files")
        if phase is Phase.IDLE and (has_edit or has_review):
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

    def add_task(self, note_id: str, description: str, kind: str) -> None:
        """Add a task to the dashboard To do section.

        kind must be 'structural' or 'minor'.
        note_id is used to generate the link to the notes file.
        """
        assert kind in ("structural", "minor"), f"Invalid kind: {kind}"
        dashboard = self._read_dashboard()

        # Reject duplicates
        anchor = f"#note-{note_id})"
        if anchor in dashboard:
            raise ValueError(f"Task '{note_id}' already exists in dashboard")

        notes_file = "structural.md" if kind == "structural" else "minor-issues.md"
        link = f"[note](todo/{notes_file}#note-{note_id})"
        entry = f"- {description} ({link})"

        # Insert under the appropriate ### heading
        section = kind.capitalize()
        pattern = rf"(^### {section}$\n\n)(.*?)(?=^### |\Z)"
        match = re.search(pattern, dashboard, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError(f"Section '### {section}' not found in dashboard")

        existing = match.group(2).strip()
        if existing == "(none)":
            new_items = entry + "\n\n"
        else:
            new_items = existing + "\n" + entry + "\n\n"

        dashboard = dashboard[:match.start(2)] + new_items + dashboard[match.end(2):]

        # Update count
        count_pattern = rf"(Completed {kind}.*?\(\d+ of )(\d+)\)"
        count_match = re.search(count_pattern, dashboard, re.IGNORECASE)
        if count_match:
            old_total = int(count_match.group(2))
            dashboard = dashboard[:count_match.start(2)] + str(old_total + 1) + ")" + dashboard[count_match.end():]

        self.dashboard_path.write_text(dashboard)

    def approve_triage(self) -> None:
        """Exit triage, enter idle (ready for Phase 1–4 cycle)."""
        self._write_state(Phase.IDLE)
        self.assert_valid()

    # --- Task selection ---

    AD_HOC = "Ad hoc"

    def select_task(self, note_id: str, file_path: str, passage: str) -> None:
        """Select a named task from To Do; move to In Progress; place edit bars."""
        dashboard = self._read_dashboard()
        # Find and remove the task line from To do
        pattern = rf"^- .+#note-{re.escape(note_id)}\).*$"
        match = re.search(pattern, dashboard, re.MULTILINE)
        if not match:
            raise ValueError(f"Task '{note_id}' not found in To do")
        task_line = match.group(0)
        dashboard = dashboard.replace(task_line + "\n", "")
        # Add to In progress with 🔵
        dashboard = dashboard.replace(
            "## In progress\n\n(none)",
            f"## In progress\n\n{task_line[:2]}🔵 {task_line[2:]}",
        )
        self.dashboard_path.write_text(dashboard)
        self._place_bars(file_path, passage, EDIT_START, EDIT_END)
        self._write_state(Phase.EDIT, note_id)
        self.assert_valid()

    def select_ad_hoc(self, file_path: str, passage: str) -> None:
        """Start an ad hoc edit; place review bars (skips Edit, goes to review)."""
        dashboard = self._read_dashboard()
        dashboard = dashboard.replace(
            "## In progress\n\n(none)",
            f"## In progress\n\n- 🔵 {self.AD_HOC}",
        )
        self.dashboard_path.write_text(dashboard)
        self._place_bars(file_path, passage, REVIEW_START, REVIEW_END)
        self._write_state(Phase.AUTHOR_REVIEW, self.AD_HOC)
        self.assert_valid()

    def complete_task(self) -> None:
        """Complete the current task; remove bars and In Progress entry."""
        state = self.read_state()
        task = state.get("task")
        dashboard = self._read_dashboard()
        # Remove 🔵 line from In progress
        dashboard = re.sub(r"^- 🔵 .*$\n?", "", dashboard, flags=re.MULTILINE)
        # If In progress is now empty, restore (none)
        dashboard = re.sub(
            r"(## In progress\n\n)\s*\n",
            r"\1(none)\n\n",
            dashboard,
        )
        self.dashboard_path.write_text(dashboard)
        # Remove all bars from .tex files
        for path in (self._tex_files_containing(EDIT_START)
                     + self._tex_files_containing(REVIEW_START)):
            self._remove_bars(path, EDIT_START, EDIT_END)
            self._remove_bars(path, REVIEW_START, REVIEW_END)
        self._write_state(Phase.IDLE)

    # --- Bar operations (require active task) ---

    def open_edit(self, file_path: str, passage: str) -> None:
        """Place edit bars around a passage in a .tex file."""
        self._require_active_task()
        self._place_bars(file_path, passage, EDIT_START, EDIT_END)

    def close_edit(self, file_path: str) -> None:
        """Remove edit bars from a .tex file."""
        self._remove_bars(file_path, EDIT_START, EDIT_END)

    def open_review(self, file_path: str, passage: str) -> None:
        """Place review bars around a passage in a .tex file."""
        self._require_active_task()
        self._place_bars(file_path, passage, REVIEW_START, REVIEW_END)

    def close_review(self, file_path: str) -> None:
        """Remove review bars from a .tex file."""
        self._remove_bars(file_path, REVIEW_START, REVIEW_END)

    def edit_to_review(self) -> None:
        """Swap all edit bars to review bars; transition to author-review phase."""
        for path in self._tex_files_containing(EDIT_START):
            text = Path(path).read_text()
            text = text.replace(EDIT_START, REVIEW_START)
            text = text.replace(EDIT_END, REVIEW_END)
            Path(path).write_text(text)
        task = self.read_state().get("task")
        self._write_state(Phase.AUTHOR_REVIEW, task)
        self.assert_valid()

    def review_to_edit(self) -> None:
        """Swap all review bars to edit bars; transition to edit phase."""
        for path in self._tex_files_containing(REVIEW_START):
            text = Path(path).read_text()
            text = text.replace(REVIEW_START, EDIT_START)
            text = text.replace(REVIEW_END, EDIT_END)
            Path(path).write_text(text)
        task = self.read_state().get("task")
        self._write_state(Phase.EDIT, task)
        self.assert_valid()

    def _require_active_task(self) -> None:
        phase = self._read_phase()
        if phase is Phase.IDLE:
            raise ValueError(f"No active task. Use {CMD_SELECT_TASK} or {CMD_SELECT_AD_HOC} first.")

    def _place_bars(self, file_path: str, passage: str,
                    start: str, end: str) -> None:
        full_path = self.root / file_path if not Path(file_path).is_absolute() else Path(file_path)
        content = full_path.read_text()
        if passage not in content:
            raise ValueError(f"Passage not found in {file_path}")
        content = content.replace(passage, f"{start} {passage}{end}", 1)
        full_path.write_text(content)

    def _remove_bars(self, file_path: str, start: str, end: str) -> None:
        full_path = self.root / file_path if not Path(file_path).is_absolute() else Path(file_path)
        content = full_path.read_text()
        content = content.replace(start, "")
        content = content.replace(end, "")
        full_path.write_text(content)

    # --- PreToolUse gate ---

    def check_edit(self, file_path: str, old_string: str | None = None,
                   new_string: str | None = None) -> tuple[bool, str]:
        """Check whether an edit to file_path is allowed.

        Returns (allowed, message). If not allowed, message explains
        what state transition is needed.
        """
        if not file_path.endswith(".tex"):
            return True, ""
        phase = self._read_phase()
        task = self.read_state().get("task") or "unknown"

        # Phase-based blocks
        if phase is Phase.IDLE:
            return False, (
                f"No active task. Use `status_tracker.py {CMD_SELECT_TASK}` or "
                f"`status_tracker.py {CMD_SELECT_AD_HOC}` first."
            )
        if phase is Phase.TRIAGE:
            return False, (
                "Cannot edit .tex files during triage phase. "
                f"Run `status_tracker.py {CMD_APPROVE_TRIAGE}` to enter editing cycle first."
            )

        # Change markup required in all .tex edits
        if new_string is not None and not any(cmd in new_string for cmd in CHANGE_MARKUP):
            return False, (
                "All .tex edits must use change markup "
                "(\\added, \\deleted, or \\replaced)."
            )

        # Edits must be within bars (edit or review)
        if old_string is not None:
            full_path = self.root / file_path if not Path(file_path).is_absolute() else Path(file_path)
            if full_path.exists():
                content = full_path.read_text()
                in_edit = self._text_within_bars(content, old_string, EDIT_START, EDIT_END)
                in_review = self._text_within_bars(content, old_string, REVIEW_START, REVIEW_END)
                if not in_edit and not in_review:
                    return False, (
                        f"Edit target is outside change bars in {file_path}. "
                        f"Use `open-review` (ad hoc) or `open-edit` (task) first."
                    )
                # During edit phase, must be in edit bars specifically
                if phase is Phase.EDIT and not in_edit:
                    return False, (
                        f"Edit target is in review bars but phase is 'edit'. "
                        f"Edits during 'edit' phase must be within {EDIT_START}/{EDIT_END}."
                    )
                # During author-review, no edits allowed
                if phase is Phase.AUTHOR_REVIEW:
                    return False, (
                        f"Cannot edit .tex files during author-review phase (task: {task}). "
                        f"Run `status_tracker.py {CMD_REVIEW_TO_EDIT}` first."
                    )

        return True, ""

    def check_write(self, file_path: str) -> tuple[bool, str]:
        """Check whether a Write to file_path is allowed.

        Write is only allowed if the file does not already exist.
        """
        full_path = self.root / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if full_path.exists():
            return False, (
                f"Cannot overwrite existing file {file_path} with Write tool. "
                f"Use Edit tool for modifications to existing files."
            )
        return True, ""

    # --- Helpers ---

    def _text_within_bars(self, content: str, text: str,
                          start_marker: str, end_marker: str) -> bool:
        """Check if text appears between the given markers in content."""
        regions = re.findall(
            rf"{re.escape(start_marker)}(.*?){re.escape(end_marker)}", content, re.DOTALL
        )
        return any(text in region for region in regions)


    def _count_in_progress_for_kind(self, dashboard: str, kind: str) -> int:
        """Count in-progress items that belong to the given kind (minor/structural)."""
        in_progress_section = re.search(
            r"^## In progress$\n(.*?)(?=^## )", dashboard, re.MULTILINE | re.DOTALL
        )
        if not in_progress_section:
            return 0
        section = in_progress_section.group(1)
        if kind == "minor":
            # Minor tasks link to minor-issues.md
            return len(re.findall(r"minor-issues\.md", section))
        else:
            # Structural tasks link to structural.md
            return len(re.findall(r"structural\.md", section))

    def _minor_issues_path(self) -> Path:
        return self.root / "workflow" / "todo" / "minor-issues.md"

    def _read_dashboard(self) -> str:
        return self.dashboard_path.read_text()

    def _count_in_progress(self, dashboard: str) -> int:
        return len(re.findall("🔵", dashboard))

    def _tex_files_containing(self, pattern: str) -> list[str]:
        return [
            f for f in glob.glob(str(self.root / "**" / "*.tex"), recursive=True)
            if not f.startswith(str(self.root / "workflow"))
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
        command = CMD_STARTUP
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
        if command == CMD_STARTUP:
            sys.exit(0)  # report to Claude's context, don't block
        else:
            sys.exit(1)

    if command == CMD_STARTUP:
        state = tracker.read_state()
        phase = state["phase"]
        task = state.get("task")
        summary = f"Workflow state: {phase}"
        if task:
            summary += f" — {task}"
        print(summary)
    elif command == CMD_BEGIN_TRIAGE:
        tracker.begin_triage()
        print("Entered triage phase")
    elif command == CMD_RECLASSIFY:
        if len(sys.argv) < 4:
            print(f"Usage: status_tracker.py {CMD_RECLASSIFY} <note-id> <structural|minor>", file=sys.stderr)
            sys.exit(1)
        tracker.reclassify(sys.argv[2], sys.argv[3])
        print(f"Reclassified {sys.argv[2]} → {sys.argv[3]}")
    elif command == CMD_ADD_TASK:
        if len(sys.argv) < 5:
            print(f"Usage: status_tracker.py {CMD_ADD_TASK} <note-id> <description> <structural|minor>", file=sys.stderr)
            sys.exit(1)
        tracker.add_task(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Added {sys.argv[4]} task: {sys.argv[3]}")
    elif command == CMD_APPROVE_TRIAGE:
        tracker.approve_triage()
        print("Triage complete; entering idle")
    elif command == CMD_SELECT_TASK:
        if len(sys.argv) < 5:
            print(f"Usage: status_tracker.py {CMD_SELECT_TASK} <note-id> <file_path> <passage>", file=sys.stderr)
            sys.exit(1)
        tracker.select_task(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Selected task: {sys.argv[2]}")
    elif command == CMD_SELECT_AD_HOC:
        if len(sys.argv) < 4:
            print(f"Usage: status_tracker.py {CMD_SELECT_AD_HOC} <file_path> <passage>", file=sys.stderr)
            sys.exit(1)
        tracker.select_ad_hoc(sys.argv[2], sys.argv[3])
        print(f"Ad hoc edit started in {sys.argv[2]}")
    elif command == CMD_COMPLETE_TASK:
        tracker.complete_task()
        print("Task completed")
    elif command == CMD_OPEN_REVIEW:
        if len(sys.argv) < 4:
            print(f"Usage: status_tracker.py {CMD_OPEN_REVIEW} <file_path> <passage>", file=sys.stderr)
            sys.exit(1)
        tracker.open_review(sys.argv[2], sys.argv[3])
        print(f"Review bars placed in {sys.argv[2]}")
    elif command == CMD_CLOSE_REVIEW:
        if len(sys.argv) < 3:
            print(f"Usage: status_tracker.py {CMD_CLOSE_REVIEW} <file_path>", file=sys.stderr)
            sys.exit(1)
        tracker.close_review(sys.argv[2])
        print(f"Review bars removed from {sys.argv[2]}")
    elif command == CMD_EDIT_TO_REVIEW:
        tracker.edit_to_review()
        print("Bars: edit → review")
    elif command == CMD_REVIEW_TO_EDIT:
        tracker.review_to_edit()
        print("Bars: review → edit")
    elif command == CMD_CHECK_EDIT:
        if len(sys.argv) < 3:
            print(f"Usage: status_tracker.py {CMD_CHECK_EDIT} <file_path>", file=sys.stderr)
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
