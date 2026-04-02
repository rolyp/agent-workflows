#!/usr/bin/env python3
"""WorkflowDev: workflow development automaton.

Enforces refactor-first discipline via a state machine:
  idle → refactoring → review → modifying → review → idle

Review is mandatory at both transitions: refactoring→modifying and modifying→idle.
State is externalised to state.json. Hooks consult phase to gate edits/writes.
"""

import subprocess
import sys
from enum import Enum
from pathlib import Path

# Ensure parent directory is on path when run as script
if __name__ == "__main__" or "base" not in sys.modules:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from base import Workflow


class Phase(Enum):
    IDLE = "idle"
    REFACTORING = "refactoring"
    MODIFYING = "modifying"
    REVIEW = "review"


class RefactoringMode(Enum):
    EXPAND_COVERAGE = "expand-coverage"
    REFACTOR_CODE = "refactor-code"


# CLI command names
CMD_STARTUP = "startup"
CMD_START_TASK = "start-task"
CMD_EXPAND_COVERAGE = "expand-coverage"
CMD_REFACTOR_CODE = "refactor-code"
CMD_BACK_TO_REFACTOR = "back-to-refactor"
CMD_REQUEST_REVIEW = "request-review"
CMD_APPROVE = "approve"
CMD_FEEDBACK = "feedback"


def _is_test_file(path: str) -> bool:
    """Heuristic: file is a test file if its name starts with 'test' or contains '_test'."""
    name = Path(path).name
    stem = Path(path).stem
    return name.startswith("test") or stem.endswith("_test")


class WorkflowDev(Workflow):
    def __init__(self, project_root: Path):
        self.root = project_root
        self.state_path = project_root / "state.json"
        self.dashboard_path = project_root / "dashboard.md"
        self._init_state(Phase.IDLE)
        self._update_dashboard()

    def _phase_enum(self) -> type[Phase]:
        return Phase

    # --- Dashboard ---

    def _render_state(self) -> str:
        """Render current state as a human-readable string."""
        state = self.read_state()
        phase = state["phase"]
        task = state.get("task")
        mode = state.get("mode")
        review_of = state.get("review_of")
        if phase == Phase.IDLE.value:
            return "(idle)"
        parts = [f"**{phase}**"]
        if task:
            parts.append(f"task: {task}")
        if mode:
            parts.append(f"mode: {mode}")
        if review_of:
            parts.append(f"reviewing: {review_of}")
        return " · ".join(parts)

    def _update_dashboard(self) -> None:
        """Regenerate the Current state section of the dashboard."""
        if not self.dashboard_path.exists():
            return
        import re
        dashboard = self.dashboard_path.read_text()
        rendered = self._render_state()
        dashboard = re.sub(
            r"(## Current state\n\n<!-- .* -->\n\n).*?(?=\n## |\Z)",
            f"\\1{rendered}\n",
            dashboard, flags=re.DOTALL,
        )
        self.dashboard_path.write_text(dashboard)

    def _save_stack(self, stack: list[dict]) -> None:
        """Write stack and update dashboard."""
        super()._save_stack(stack)
        self._update_dashboard()

    # --- Commands ---

    def start_task(self, task: str) -> None:
        """Start a task; enter refactoring phase (locked until sub-mode chosen)."""
        phase = self._read_phase()
        if phase is not Phase.IDLE:
            raise ValueError(f"Cannot start task: current phase is {phase.value}, expected idle")
        self._write_state(Phase.REFACTORING, task)

    def expand_coverage(self) -> None:
        """Switch to expand-coverage mode: only test files editable."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"expand-coverage only available during refactoring (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"), mode=RefactoringMode.EXPAND_COVERAGE.value)

    def refactor_code(self) -> None:
        """Switch to refactor-code mode: only code files editable."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"refactor-code only available during refactoring (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"), mode=RefactoringMode.REFACTOR_CODE.value)

    def back_to_refactor(self) -> None:
        """Return from modifying to refactoring (locked)."""
        phase = self._read_phase()
        if phase is not Phase.MODIFYING:
            raise ValueError(f"back-to-refactor only available during modifying (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))

    def request_review(self) -> None:
        """Request code review from refactoring or modifying. Runs tests first."""
        phase = self._read_phase()
        if phase not in (Phase.REFACTORING, Phase.MODIFYING):
            raise ValueError(f"request-review only available during refactoring or modifying (current: {phase.value})")
        self._run_tests()
        state = self.read_state()
        self._write_state(Phase.REVIEW, state.get("task"), review_of=phase.value)

    def approve(self) -> None:
        """Approve review; transition depends on what was reviewed."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"approve only available during review (current: {phase.value})")
        state = self.read_state()
        if state.get("review_of") == Phase.REFACTORING.value:
            self._write_state(Phase.MODIFYING, state.get("task"))
        else:
            self._write_state(Phase.IDLE)

    def feedback(self) -> None:
        """Review feedback; always return to refactoring (fixes are refactoring by definition)."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"feedback only available during review (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))

    # --- Hook gates ---

    def check_edit(self, file_path: str, old_string: str | None = None,
                   new_string: str | None = None) -> tuple[bool, str]:
        """Gate edits based on current phase and refactoring mode."""
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""  # outside project root

        phase = self._read_phase()
        state = self.read_state()

        if phase is Phase.IDLE:
            return False, (
                f"No active task. Use `workflow.py {CMD_START_TASK} <task>` first."
            )

        if phase is Phase.REVIEW:
            return False, (
                "Edits blocked during review. "
                f"Use `workflow.py {CMD_APPROVE}` or `workflow.py {CMD_FEEDBACK}` first."
            )

        if phase is Phase.REFACTORING:
            mode = state.get("mode")
            if mode is None:
                return False, (
                    "Refactoring phase entered but no mode selected. "
                    f"Use `workflow.py {CMD_EXPAND_COVERAGE}` or `workflow.py {CMD_REFACTOR_CODE}` first."
                )
            is_test = _is_test_file(rel_path)
            if mode == RefactoringMode.EXPAND_COVERAGE.value and not is_test:
                return False, (
                    f"In expand-coverage mode: only test files are editable. "
                    f"Use `workflow.py {CMD_REFACTOR_CODE}` to switch to code editing."
                )
            if mode == RefactoringMode.REFACTOR_CODE.value and is_test:
                return False, (
                    f"In refactor-code mode: only code files are editable. "
                    f"Use `workflow.py {CMD_EXPAND_COVERAGE}` to switch to test editing."
                )

        # Phase.MODIFYING: all edits allowed
        return True, ""

    def check_write(self, file_path: str) -> tuple[bool, str]:
        """Gate file creation based on current phase and refactoring mode."""
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""  # outside project root

        phase = self._read_phase()
        state = self.read_state()

        if phase is Phase.IDLE:
            return False, (
                f"No active task. Use `workflow.py {CMD_START_TASK} <task>` first."
            )

        if phase is Phase.REVIEW:
            return False, (
                "File creation blocked during review."
            )

        if phase is Phase.REFACTORING:
            mode = state.get("mode")
            if mode is None:
                return False, (
                    "Refactoring phase entered but no mode selected. "
                    f"Use `workflow.py {CMD_EXPAND_COVERAGE}` or `workflow.py {CMD_REFACTOR_CODE}` first."
                )
            is_test = _is_test_file(rel_path)
            if mode == RefactoringMode.EXPAND_COVERAGE.value and not is_test:
                return False, (
                    "In expand-coverage mode: only test files can be created."
                )
            if mode == RefactoringMode.REFACTOR_CODE.value and is_test:
                return False, (
                    "In refactor-code mode: only code files can be created."
                )

        # Phase.MODIFYING: all writes allowed
        return True, ""

    # --- Helpers ---

    def _run_tests(self) -> None:
        """Run pytest; raise if tests fail."""
        result = subprocess.run(
            ["python3", "-m", "pytest", "-q"],
            capture_output=True, text=True, cwd=self.root,
        )
        # Exit code 5 = no tests collected (acceptable)
        if result.returncode not in (0, 5):
            raise RuntimeError(
                f"Tests must pass before transitioning to modifying.\n"
                f"{result.stdout}{result.stderr}"
            )


# --- CLI entry point ---

def main() -> None:
    if len(sys.argv) < 2:
        command = CMD_STARTUP
    else:
        command = sys.argv[1]

    try:
        wd = WorkflowDev(Path.cwd())
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if command == CMD_STARTUP:
        state = wd.read_state()
        phase = state["phase"]
        task = state.get("task")
        mode = state.get("mode")
        summary = f"Workflow state: {phase}"
        if task:
            summary += f" — {task}"
        if mode:
            summary += f" ({mode})"
        print(summary)
    elif command == CMD_START_TASK:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_START_TASK} <task-name>", file=sys.stderr)
            sys.exit(1)
        wd.start_task(sys.argv[2])
        print(f"Started task: {sys.argv[2]} (refactoring, locked)")
    elif command == CMD_EXPAND_COVERAGE:
        wd.expand_coverage()
        print("Mode: expand-coverage (test files only)")
    elif command == CMD_REFACTOR_CODE:
        wd.refactor_code()
        print("Mode: refactor-code (code files only)")
    elif command == CMD_BACK_TO_REFACTOR:
        wd.back_to_refactor()
        print("Back to refactoring (locked)")
    elif command == CMD_REQUEST_REVIEW:
        wd.request_review()
        state = wd.read_state()
        review_of = state.get("review_of", "unknown")
        print(f"Review requested (reviewing {review_of}); edits blocked. Invoke /code-review now.")
    elif command == CMD_APPROVE:
        wd.approve()
        phase = wd.read_state()["phase"]
        print(f"Review approved; entering {phase}")
    elif command == CMD_FEEDBACK:
        wd.feedback()
        print("Review feedback; returning to refactoring (locked)")
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
