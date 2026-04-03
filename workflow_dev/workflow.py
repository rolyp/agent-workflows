#!/usr/bin/env python3
"""WorkflowDev: workflow development automaton.

Enforces refactor-first discipline via a state machine:
  idle → refactoring → review → modifying → review → idle

Review is mandatory at both transitions: refactoring→modifying and modifying→idle.
State is externalised to state.json. Hooks consult phase to gate edits/writes.
"""

import os
import re
import subprocess
import sys
import time
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
CMD_BEGIN_STEP = "begin-step"
CMD_END_STEP = "end-step"
CMD_BEGIN_SUBTASK = "begin-subtask"
CMD_END_SUBTASK = "end-subtask"
CMD_BEGIN_MODIFY = "begin-modify"
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

    # Fields carried forward from previous frame unless overridden
    _CARRY_FORWARD = ("issue_url",)

    def _write_state(self, phase: Enum, task: str | None = None,
                     **extra: object) -> None:
        """Replace top frame, carrying forward issue_url."""
        prev = self.read_state()
        for key in self._CARRY_FORWARD:
            if key not in extra and key in prev:
                extra[key] = prev[key]
        super()._write_state(phase, task, **extra)

    # --- Dashboard ---

    def _render_state(self) -> str:
        """Render current state as a human-readable string."""
        state = self.read_state()
        phase = state["phase"]
        task = state.get("task")
        mode = state.get("mode")
        step = state.get("step")
        review_of = state.get("review_of")
        modify_desc = state.get("modify_description")
        if phase == Phase.IDLE.value:
            return "(idle)"
        parts = [f"**{phase}**"]
        if task:
            parts.append(f"task: {task}")
        if mode:
            parts.append(f"mode: {mode}")
        if step:
            parts.append(f"step: {step}")
        if modify_desc:
            parts.append(f"scope: {modify_desc}")
        if review_of:
            parts.append(f"reviewing: {review_of}")
        return " · ".join(parts)

    def _update_dashboard(self) -> None:
        """Regenerate the Current state section of the dashboard."""
        if not self.dashboard_path.exists():
            return
        dashboard = self.dashboard_path.read_text()
        rendered = self._render_state()
        dashboard = re.sub(
            r"(## Current state\n\n<!-- .* -->\n\n).*?(?=\n## |\Z)",
            f"\\1{rendered}\n",
            dashboard, flags=re.DOTALL,
        )
        self.dashboard_path.write_text(dashboard)

    def _save_stack(self, stack: list[dict], validate: bool = True) -> None:
        """Write stack and update dashboard."""
        super()._save_stack(stack, validate=validate)
        self._update_dashboard()

    # --- Commands ---

    def start_task(self, task: str, issue_number: str | None = None) -> None:
        """Start a task; enter refactoring phase (locked until sub-mode chosen).

        If issue_number is provided, stores the issue URL in state and
        sets project status to In Progress.
        """
        phase = self._read_phase()
        if phase is not Phase.IDLE:
            raise ValueError(f"Cannot start task: current phase is {phase.value}, expected idle")
        issue_url = None
        if issue_number:
            repo = self.get_repo()
            issue_url = f"https://github.com/{repo}/issues/{issue_number}"
            self.set_issue_status(issue_url, "In Progress")
        self._write_state(Phase.REFACTORING, task, issue_url=issue_url)
        self._set_label(self.LABEL_IDLE)

    def expand_coverage(self) -> None:
        """Switch to expand-coverage mode: only test files editable."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"expand-coverage only available during refactoring (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"), mode=RefactoringMode.EXPAND_COVERAGE.value)
        self._set_label(self.LABEL_REFACTOR_TEST)

    def refactor_code(self) -> None:
        """Switch to refactor-code mode: only code files editable."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"refactor-code only available during refactoring (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"), mode=RefactoringMode.REFACTOR_CODE.value)
        self._set_label(self.LABEL_REFACTOR_CODE)

    def _issue_url_from_state(self) -> str | None:
        """Get issue URL from the bottom of the state stack (root task)."""
        stack = self._read_stack()
        return stack[0].get("issue_url")

    def _set_label(self, label: str) -> None:
        """Set workflow label on the active issue, if one is tracked."""
        issue_url = self._issue_url_from_state()
        if issue_url:
            self.set_issue_label(issue_url, label)

    def _clear_labels(self) -> None:
        """Remove all workflow labels from the active issue."""
        issue_url = self._issue_url_from_state()
        if issue_url:
            self.clear_issue_labels(issue_url)

    def begin_step(self, name: str) -> None:
        """Begin a named refactoring step. Pushes a frame; marks todo as active."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"begin-step only available during refactoring (current: {phase.value})")
        stack = self._read_stack()
        if len(stack) > 1:
            current_step = stack[-1].get("step")
            raise ValueError(f"Already in step '{current_step}'. Run `end-step` first.")
        state = self.read_state()
        self._push_state(Phase.REFACTORING, state.get("task"), step=name,
                         mode=state.get("mode"))
        issue_url = self._issue_url_from_state()
        if issue_url:
            self.activate_issue_todo(issue_url, name)

    def end_step(self) -> None:
        """End the current refactoring step. Runs tests, checks off todo."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"end-step only available during refactoring (current: {phase.value})")
        stack = self._read_stack()
        if len(stack) <= 1:
            raise ValueError("No step in progress. Use `begin-step <name>` first.")
        step_name = stack[-1].get("step")
        self._run_tests()
        self._pop_state()
        issue_url = self._issue_url_from_state()
        if issue_url and step_name:
            self.complete_issue_todo(issue_url, step_name)

    def begin_subtask(self, title: str) -> str:
        """Create a sub-issue for a substantial subtask. Returns the sub-issue URL."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"begin-subtask only available during refactoring (current: {phase.value})")
        issue_url = self._issue_url_from_state()
        if not issue_url:
            raise ValueError("No issue URL in state; use start-task with an issue number first")
        sub_url = self.create_sub_issue(issue_url, title)
        state = self.read_state()
        self._push_state(Phase.REFACTORING, state.get("task"),
                         issue_url=sub_url, mode=state.get("mode"))
        self.set_issue_label(sub_url, self.LABEL_IDLE)
        self.set_issue_status(sub_url, "In Progress")
        return sub_url

    def end_subtask(self) -> None:
        """Complete the current subtask. Closes the sub-issue."""
        stack = self._read_stack()
        if len(stack) <= 1:
            raise ValueError("No subtask in progress.")
        self._run_tests()
        issue_url = self._issue_url_from_state()
        self._pop_state()
        if issue_url:
            self.set_issue_status(issue_url, "Done")
            self.clear_issue_labels(issue_url)
            env = self._gh_env()
            number = self._get_issue_number(issue_url)
            subprocess.run(
                ["gh", "issue", "close", number, "--repo", self.get_repo()],
                capture_output=True, text=True, env=env,
            )

    def begin_modify(self, description: str) -> None:
        """Enter modifying phase with explicit scope."""
        phase = self._read_phase()
        if phase is not Phase.REFACTORING:
            raise ValueError(f"begin-modify only available during refactoring (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.MODIFYING, state.get("task"), modify_description=description)
        self._set_label(self.LABEL_MODIFY)

    def back_to_refactor(self) -> None:
        """Return from modifying to refactoring (locked)."""
        phase = self._read_phase()
        if phase is not Phase.MODIFYING:
            raise ValueError(f"back-to-refactor only available during modifying (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))
        self._set_label(self.LABEL_IDLE)

    def request_review(self) -> None:
        """Request code review from refactoring or modifying. Runs tests and checks CI first."""
        phase = self._read_phase()
        if phase not in (Phase.REFACTORING, Phase.MODIFYING):
            raise ValueError(f"request-review only available during refactoring or modifying (current: {phase.value})")
        stack = self._read_stack()
        if len(stack) > 1:
            current_step = stack[-1].get("step")
            raise ValueError(f"Step '{current_step}' still in progress. Run `end-step` first.")
        self._run_tests()
        self._check_ci()
        state = self.read_state()
        self._write_state(Phase.REVIEW, state.get("task"), review_of=phase.value)
        self._set_label(self.LABEL_REVIEW)

    def approve(self) -> None:
        """Approve review; return to refactoring or idle depending on review type."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"approve only available during review (current: {phase.value})")
        state = self.read_state()
        if state.get("review_of") == Phase.MODIFYING.value:
            # Task complete — set issue to Done and close
            issue_url = self._issue_url_from_state()
            if issue_url:
                self.set_issue_status(issue_url, "Done")
                self.clear_issue_labels(issue_url)
                env = self._gh_env()
                number = self._get_issue_number(issue_url)
                subprocess.run(
                    ["gh", "issue", "close", number, "--repo", self.get_repo()],
                    capture_output=True, text=True, env=env,
                )
            self._write_state(Phase.IDLE)
        else:
            self._write_state(Phase.REFACTORING, state.get("task"))
            self._set_label(self.LABEL_IDLE)

    def feedback(self, items: list[str] | None = None) -> None:
        """Review feedback; return to refactoring. Optionally add todo items for fixes."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"feedback only available during review (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))
        self._set_label(self.LABEL_IDLE)
        if items:
            issue_url = self._issue_url_from_state()
            if issue_url:
                self.add_issue_todos(issue_url, items)

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
        """Run test.sh (mypy + pytest); raise if anything fails."""
        test_script = self.root / "test.sh"
        if not test_script.exists():
            raise FileNotFoundError(f"test.sh not found at {test_script}")
        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True, text=True, cwd=self.root,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Build check failed.\n"
                f"{result.stdout}{result.stderr}"
            )

    def _check_ci(self) -> None:
        """Check pending CI run if recorded by post-push hook. Blocks until complete."""
        state = self.read_state()
        run_id = state.get("pending_ci_run")
        if not run_id:
            return

        env = self._gh_env()

        # Poll until run completes
        while True:
            result = subprocess.run(
                ["gh", "run", "view", str(run_id),
                 "--json", "status,conclusion",
                 "-q", ".status + \" \" + .conclusion"],
                capture_output=True, text=True, env=env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Failed to check CI run {run_id}: {result.stderr}"
                )

            parts = result.stdout.strip().split()
            status = parts[0] if parts else "unknown"
            conclusion = parts[1] if len(parts) > 1 else ""

            if status == "completed":
                # Clear pending run
                stack = self._read_stack()
                stack[-1].pop("pending_ci_run", None)
                self._save_stack(stack)

                if conclusion != "success":
                    raise RuntimeError(
                        f"CI run {run_id} failed ({conclusion}). "
                        f"Fix before requesting review: gh run view {run_id}"
                    )
                return

            time.sleep(10)


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
        milestone = wd.get_active_milestone()
        state = wd.read_state()
        phase = state["phase"]
        task = state.get("task")
        mode = state.get("mode")
        summary = f"Workflow state: {phase} · milestone: {milestone}"
        if task:
            summary += f" — {task}"
        if mode:
            summary += f" ({mode})"
        print(summary)
    elif command == CMD_START_TASK:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_START_TASK} <task-name> [issue-number]", file=sys.stderr)
            sys.exit(1)
        issue_number = sys.argv[3] if len(sys.argv) > 3 else None
        wd.start_task(sys.argv[2], issue_number)
        msg = f"Started task: {sys.argv[2]} (refactoring, locked)"
        if issue_number:
            msg += f" · issue #{issue_number} → In Progress"
        print(msg)
    elif command == CMD_EXPAND_COVERAGE:
        wd.expand_coverage()
        print("Mode: expand-coverage (test files only)")
    elif command == CMD_REFACTOR_CODE:
        wd.refactor_code()
        print("Mode: refactor-code (code files only)")
    elif command == CMD_BEGIN_STEP:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_BEGIN_STEP} <step-name>", file=sys.stderr)
            sys.exit(1)
        wd.begin_step(sys.argv[2])
        print(f"Started step: {sys.argv[2]}")
    elif command == CMD_END_STEP:
        wd.end_step()
        print("Step complete; tests passed")
    elif command == CMD_BEGIN_SUBTASK:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_BEGIN_SUBTASK} <title>", file=sys.stderr)
            sys.exit(1)
        url = wd.begin_subtask(sys.argv[2])
        print(f"Started subtask: {sys.argv[2]} → {url}")
    elif command == CMD_END_SUBTASK:
        wd.end_subtask()
        print("Subtask complete; sub-issue closed")
    elif command == CMD_BEGIN_MODIFY:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_BEGIN_MODIFY} <description>", file=sys.stderr)
            sys.exit(1)
        wd.begin_modify(sys.argv[2])
        print(f"Entering modifying: {sys.argv[2]}")
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
        items = sys.argv[2:] if len(sys.argv) > 2 else None
        wd.feedback(items)
        msg = "Review feedback; returning to refactoring (locked)"
        if items:
            msg += f" · {len(items)} todo(s) added to issue"
        print(msg)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
