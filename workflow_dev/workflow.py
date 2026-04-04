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


class StepMode(Enum):
    CODE = "code"
    TEST = "test"
    MODIFY = "modify"


# CLI command names
CMD_STARTUP = "startup"
CMD_BEGIN_TASK = "begin-task"
CMD_END_TASK = "end-task"
CMD_BEGIN_STEP = "begin-step"
CMD_END_STEP = "end-step"
CMD_REQUEST_REVIEW = "request-review"
CMD_RESPOND_APPROVE = "respond-review/approve"
CMD_RESPOND_FEEDBACK = "respond-review/feedback"


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
    _CARRY_FORWARD = ("issue_url", "reviewed_sha")

    def _write_state(self, phase: Enum, task: str | None = None,
                     **extra: object) -> None:
        """Replace top frame, carrying forward issue_url."""
        prev = self.read_state()
        for key in self._CARRY_FORWARD:
            if key not in extra and key in prev:
                extra[key] = prev[key]
        super()._write_state(phase, task, **extra)

    def _label_for_state(self, state: dict) -> str:
        """Derive the appropriate label from a state frame."""
        phase = state.get("phase")
        mode = state.get("mode")
        if phase == Phase.REVIEW.value:
            return self.LABEL_REVIEW
        if mode == StepMode.CODE.value:
            return self.LABEL_REFACTOR_CODE
        if mode == StepMode.TEST.value:
            return self.LABEL_REFACTOR_TEST
        if mode == StepMode.MODIFY.value:
            return self.LABEL_MODIFY
        return self.LABEL_IDLE

    def _pop_state(self, validate: bool = True) -> dict:
        """Pop state frame and restore the label for the frame below."""
        result = super()._pop_state(validate=validate)
        self._set_label(self._label_for_state(self.read_state()))
        return result

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

    def _is_idle(self) -> bool:
        """True if at root frame with no mode (idle within a task)."""
        stack = self._read_stack()
        return len(stack) == 1 and self._read_phase() is Phase.REFACTORING

    def begin_task(self, task: str, issue_number: str | None = None) -> None:
        """Start a task. Sets root frame to idle (refactoring, no mode)."""
        phase = self._read_phase()
        if phase is not Phase.IDLE:
            raise ValueError(f"Cannot begin task: current phase is {phase.value}, expected idle")
        issue_url = None
        if issue_number:
            repo = self.get_repo()
            issue_url = f"https://github.com/{repo}/issues/{issue_number}"
            self.set_issue_status(issue_url, "In Progress")
        self._write_state(Phase.REFACTORING, task, issue_url=issue_url)
        self._set_label(self.LABEL_IDLE)

    def begin_step(self, description: str, mode: str) -> None:
        """Push a step frame. Mode is 'code', 'test', or 'modify'."""
        if mode not in (m.value for m in StepMode):
            raise ValueError(f"Unknown mode: {mode} (use code, test, or modify)")
        phase = self._read_phase()
        if phase not in (Phase.REFACTORING, Phase.MODIFYING):
            raise ValueError(f"begin-step not available in {phase.value}")
        state = self.read_state()
        step_mode = StepMode(mode)
        # Map mode to Phase for the pushed frame
        frame_phase = Phase.MODIFYING if step_mode is StepMode.MODIFY else Phase.REFACTORING
        # Map mode to label
        label_map = {
            StepMode.CODE: self.LABEL_REFACTOR_CODE,
            StepMode.TEST: self.LABEL_REFACTOR_TEST,
            StepMode.MODIFY: self.LABEL_MODIFY,
        }
        # Tag the description with the mode
        tag = f"[refactor/{mode}]" if step_mode is not StepMode.MODIFY else "[modify]"
        tagged = f"{tag} {description}"
        self._push_state(frame_phase, state.get("task"),
                         step=tagged, mode=mode)
        self._set_label(label_map[step_mode])
        issue_url = self._issue_url_from_state()
        if issue_url:
            self.activate_issue_todo(issue_url, tagged)

    def end_step(self) -> None:
        """Pop the current step. Runs tests first. Checks off todo with commit link."""
        state = self.read_state()
        step_name = state.get("step")
        if not step_name:
            raise ValueError("No step in progress.")
        stack = self._read_stack()
        if len(stack) <= 1:
            raise ValueError("Cannot pop root frame.")
        self._run_tests()
        self._pop_state()
        issue_url = self._issue_url_from_state()
        if issue_url and step_name:
            head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=self.root,
            ).stdout.strip()
            self.complete_issue_todo(issue_url, step_name, commit_sha=head_sha)

    def request_review(self) -> None:
        """Request code review. Only from idle (root frame, no mode)."""
        if not self._is_idle():
            raise ValueError("request-review only available from idle. Run end-step first.")
        self._run_tests()
        self._check_ci()
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=self.root,
        ).stdout.strip()
        state = self.read_state()
        self._write_state(Phase.REVIEW, state.get("task"), reviewed_sha=head_sha)
        self._set_label(self.LABEL_REVIEW)

    def approve(self) -> None:
        """Approve review; return to idle."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"approve only available during review (current: {phase.value})")
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))
        self._set_label(self.LABEL_IDLE)

    def feedback(self, items: list[str] | None = None) -> None:
        """Review feedback; return to idle. Optionally add todo items."""
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

    def end_task(self) -> None:
        """Complete the current task. Requires review since last code change."""
        if not self._is_idle():
            raise ValueError("end-task only available from idle. Run end-step first.")

        state = self.read_state()
        reviewed_sha = state.get("reviewed_sha")
        if not reviewed_sha:
            raise ValueError("No review on record. Run request-review first.")

        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=self.root,
        ).stdout.strip()
        if head_sha != reviewed_sha:
            raise ValueError(
                f"Code changed since last review (reviewed: {reviewed_sha[:8]}, "
                f"HEAD: {head_sha[:8]}). Run request-review again."
            )

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

    # --- Hook gates ---

    def _check_file_access(self, rel_path: str) -> tuple[bool, str]:
        """Shared gate logic for check_edit and check_write."""
        phase = self._read_phase()
        state = self.read_state()
        mode = state.get("mode")

        if phase is Phase.IDLE:
            return False, f"No active task. Use `workflow.py {CMD_BEGIN_TASK} <task>` first."

        if phase is Phase.REVIEW:
            return False, "Edits blocked during review."

        if phase is Phase.REFACTORING and not mode:
            return False, f"Idle — no step active. Use `workflow.py {CMD_BEGIN_STEP} <desc> <code|test|modify>` first."

        if mode == StepMode.CODE.value:
            if _is_test_file(rel_path):
                return False, "In code mode: only code files are editable."
        elif mode == StepMode.TEST.value:
            if not _is_test_file(rel_path):
                return False, "In test mode: only test files are editable."
        # StepMode.MODIFY: all files allowed

        return True, ""

    def check_edit(self, file_path: str, old_string: str | None = None,
                   new_string: str | None = None) -> tuple[bool, str]:
        """Gate edits based on current step mode."""
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""
        return self._check_file_access(rel_path)

    def check_write(self, file_path: str) -> tuple[bool, str]:
        """Gate file creation based on current step mode."""
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""
        return self._check_file_access(rel_path)

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

    CI_TIMEOUT = 30 * 60  # 30 minutes

    def _check_ci(self) -> None:
        """Check pending CI run if recorded by post-push hook. Blocks until complete."""
        state = self.read_state()
        run_id = state.get("pending_ci_run")
        if not run_id:
            return

        env = self._gh_env()
        deadline = time.time() + self.CI_TIMEOUT

        # Poll until run completes or timeout
        while time.time() < deadline:
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

        raise RuntimeError(
            f"CI run {run_id} timed out after {self.CI_TIMEOUT // 60} minutes. "
            f"Check manually: gh run view {run_id}"
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
        milestone = wd.get_active_milestone()
        state = wd.read_state()
        phase = state["phase"]
        task = state.get("task")
        step = state.get("step")
        mode = state.get("mode")
        summary = f"Workflow state: {phase} · milestone: {milestone}"
        if task:
            summary += f" — {task}"
        if step:
            summary += f" · step: {step}"
        elif mode:
            summary += f" ({mode})"
        print(summary)
    elif command == CMD_BEGIN_TASK:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_BEGIN_TASK} <task-name> [issue-number]", file=sys.stderr)
            sys.exit(1)
        issue_number = sys.argv[3] if len(sys.argv) > 3 else None
        wd.begin_task(sys.argv[2], issue_number)
        msg = f"Task started: {sys.argv[2]} (idle)"
        if issue_number:
            msg += f" · issue #{issue_number} → In Progress"
        print(msg)
    elif command == CMD_BEGIN_STEP:
        if len(sys.argv) < 4 or sys.argv[3] not in ("code", "test", "modify"):
            print(f"Usage: workflow.py {CMD_BEGIN_STEP} <description> <code|test|modify>", file=sys.stderr)
            sys.exit(1)
        wd.begin_step(sys.argv[2], sys.argv[3])
        print(f"Step: [{sys.argv[3]}] {sys.argv[2]}")
    elif command == CMD_END_STEP:
        wd.end_step()
        print("Step complete; back to idle")
    elif command == CMD_REQUEST_REVIEW:
        wd.request_review()
        print("Review requested; edits blocked. Invoke /code-review now.")
    elif command == CMD_RESPOND_APPROVE:
        wd.approve()
        print("Review approved; back to idle")
    elif command == CMD_RESPOND_FEEDBACK:
        items = sys.argv[2:] if len(sys.argv) > 2 else None
        wd.feedback(items)
        msg = "Review feedback; back to idle"
        if items:
            msg += f" · {len(items)} todo(s) added to issue"
        print(msg)
    elif command == CMD_END_TASK:
        wd.end_task()
        print("Task complete; issue closed")
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
