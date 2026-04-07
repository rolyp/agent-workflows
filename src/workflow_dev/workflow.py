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
CMD_BEGIN_REFACTOR = "begin-refactor"
CMD_BEGIN_MODIFY = "begin-modify"
CMD_END_STEP = "end-step"
CMD_ABORT_STEP = "abort-step"
CMD_REQUEST_REVIEW = "request-review"
CMD_SUBMIT_REVIEW = "submit-review"
CMD_RESPOND_APPROVE = "respond-review/approve"
CMD_RESPOND_FEEDBACK = "respond-review/feedback"
CMD_CREATE_ISSUE = "create-issue"
CMD_REOPEN_ISSUE = "reopen-issue"
CMD_RESUME_PROTOCOL = "resume-protocol"


def _is_test_file(path: str) -> bool:
    """Check if a file is part of the test infrastructure."""
    p = str(path)
    # Structural: test/ directory or CI workflows
    if p.startswith("test/") or ".github/workflows/" in p:
        return True
    # Filename fallback (for relative paths without directory prefix)
    name = Path(path).name
    stem = Path(path).stem
    return name.startswith("test") or stem.endswith("_test")


class WorkflowDev(Workflow):
    def __init__(self, project_root: Path):
        self.root = project_root
        self.state_path = project_root / "state.json"
        self._init_state(Phase.IDLE)

    def _phase_enum(self) -> type[Phase]:
        return Phase

    # Workflow-dev-specific labels
    LABEL_IDLE = "\u26aa idle"                     # ⚪ idle
    LABEL_REFACTOR_TEST = "\U0001f7e2 refactor/test"  # 🟢 refactor/test
    LABEL_REFACTOR_CODE = "\U0001f7e2 refactor/code"  # 🟢 refactor/code
    LABEL_MODIFY = "\U0001f7e0 modify"                # 🟠 modify
    LABEL_REVIEW = "\U0001f7e1 review"                # 🟡 review

    WORKFLOW_LABELS: tuple[str, ...] = (
        LABEL_IDLE, LABEL_REFACTOR_TEST, LABEL_REFACTOR_CODE,
        LABEL_MODIFY, LABEL_REVIEW,
    )

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

    # --- State rendering (for startup) ---

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
        """Start a task. Creates branch, sets root frame to idle."""
        phase = self._read_phase()
        if phase is not Phase.IDLE:
            raise ValueError(f"Cannot begin task: current phase is {phase.value}, expected idle")
        # Create and checkout branch
        branch = f"task/{task}"
        result = subprocess.run(
            ["git", "checkout", "-b", branch],
            capture_output=True, text=True, cwd=self.root,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create branch {branch}: {result.stderr}")
        issue_url = None
        if issue_number:
            repo = self.get_repo()
            issue_url = f"https://github.com/{repo}/issues/{issue_number}"
            self.set_issue_status(issue_url, "In Progress")
        self._write_state(Phase.REFACTORING, task, issue_url=issue_url)
        # Clear history from previous task
        sf = self._read_state_file()
        sf["history"] = []
        self._save_stack(sf["stack"], history=sf["history"])
        self._set_label(self.LABEL_IDLE)

    def begin_refactor(self, description: str, mode: str) -> None:
        """Push a refactoring step. Mode is 'code' or 'test'."""
        if mode not in (StepMode.CODE.value, StepMode.TEST.value):
            raise ValueError(f"Unknown refactor mode: {mode} (use code or test)")
        self._begin_step(description, mode)

    def begin_modify(self, description: str, rationale: list[str]) -> None:
        """Push a modify step. Rationale required: 'test: current → expected' pairs."""
        if not rationale:
            raise ValueError(
                "begin-modify requires rationale: "
                "'test: current → expected' pairs."
            )
        self._begin_step(description, StepMode.MODIFY.value, rationale=rationale)

    def _begin_step(self, description: str, mode: str,
                    rationale: list[str] | None = None) -> None:
        """Internal: push a step frame."""
        phase = self._read_phase()
        if phase not in (Phase.REFACTORING, Phase.MODIFYING):
            raise ValueError(f"begin-step not available in {phase.value}. Use begin-task first.")
        # Require clean working tree (excluding state.json which is workflow-managed)
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", ":!state.json"],
            capture_output=True, text=True, cwd=self.root,
        )
        if status.stdout.strip():
            raise ValueError(
                "Working tree is not clean. Commit or stash changes before begin-step.\n"
                f"{status.stdout.strip()}"
            )
        state = self.read_state()
        if state.get("end_step_failed"):
            raise ValueError(
                "Previous end-step failed. Fix the code and retry end-step, "
                "or use abort-step to roll back."
            )
        step_mode = StepMode(mode)
        # Forbid nesting modify inside code/test (would undermine mode discipline)
        parent_mode = state.get("mode")
        if parent_mode in (StepMode.CODE.value, StepMode.TEST.value) and step_mode is StepMode.MODIFY:
            raise ValueError(
                f"Cannot nest modify step inside {parent_mode} step. "
                f"End the current step first, then begin-step with modify."
            )
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
        extra: dict[str, object] = {"step": tagged, "mode": mode}
        if rationale:
            extra["rationale"] = rationale
        self._push_state(frame_phase, state.get("task"), **extra)
        self._set_label(label_map[step_mode])
        self._render_issue_todos()

    def end_step(self, commit_message: str | None = None) -> None:
        """Pop the current step. Runs tests, commits, records in history.

        If commit_message is provided, stages all changes and commits.
        If not provided, requires a clean working tree.
        """
        state = self.read_state()
        step_name = state.get("step")
        if not step_name:
            raise ValueError("No step in progress. Use begin-step first.")
        sf = self._read_state_file()
        if len(sf["stack"]) <= 1:
            raise ValueError("Cannot pop root frame.")
        try:
            self._run_tests()
        except (RuntimeError, FileNotFoundError):
            sf["stack"][-1]["end_step_failed"] = True
            self._save_stack(sf["stack"], history=sf["history"])
            raise
        # Commit if message provided
        if commit_message:
            subprocess.run(
                ["git", "add", "-A"], capture_output=True, cwd=self.root,
            )
            result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True, text=True, cwd=self.root,
            )
            if result.returncode != 0 and "nothing to commit" not in result.stdout:
                raise RuntimeError(f"Commit failed: {result.stderr}")
        # Get the commit SHA (post-commit hook may have recorded it, or use HEAD)
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=self.root,
        ).stdout.strip()
        rationale = state.get("rationale")
        self._pop_state()
        entry: dict[str, object] = {"step": step_name, "status": "completed", "commit": commit_sha}
        if rationale:
            entry["rationale"] = rationale
        self._append_history(entry)
        self._render_issue_todos()

    def abort_step(self, reason: str = "") -> None:
        """Abort the current step. Reverts changes, pops without tests. Records in history."""
        state = self.read_state()
        step_name = state.get("step")
        if not step_name:
            raise ValueError("No step in progress. Use begin-step first.")
        sf = self._read_state_file()
        if len(sf["stack"]) <= 1:
            raise ValueError("Cannot pop root frame.")
        # Pop state first (before reverting files, since git checkout would revert state.json)
        self._pop_state()
        # Revert all uncommitted changes (true rollback)
        subprocess.run(
            ["git", "checkout", "--", ".", ":!state.json"],
            capture_output=True, cwd=self.root,
        )
        # Remove any untracked files added during this step
        subprocess.run(
            ["git", "clean", "-fd", "--", ".", ":!state.json"],
            capture_output=True, cwd=self.root,
        )
        entry: dict[str, str] = {"step": step_name, "status": "aborted"}
        if reason:
            entry["reason"] = reason
        self._append_history(entry)
        self._render_issue_todos()

    def _render_issue_todos(self) -> None:
        """Re-render the issue body's todo section from history + stack."""
        issue_url = self._issue_url_from_state()
        if not issue_url:
            return
        sf = self._read_state_file()
        repo = self.get_repo()
        lines = []
        # Render history
        for entry in sf["history"]:
            step = entry["step"]
            status = entry["status"]
            if status == "completed":
                sha = entry.get("commit", "")
                line = f"- [x] {step}"
                if sha:
                    line += f" ([{sha[:7]}](https://github.com/{repo}/commit/{sha}))"
                lines.append(line)
                for r in entry.get("rationale", []):
                    lines.append(f"  - {r}")
            elif status == "aborted":
                reason = entry.get("reason", "")
                if reason:
                    lines.append(f'- [x] \u26d4 {step} ([aborted](## "{reason}"))')
                else:
                    lines.append(f"- [x] \u26d4 {step} (aborted)")
        # Render active step from stack (if any)
        for frame in sf["stack"][1:]:  # skip root frame
            step = frame.get("step")
            mode = frame.get("mode", "")
            if step:
                emoji = self.MODE_EMOJI.get(mode, "\u26aa")
                lines.append(f"- [ ] {emoji} {step}")
        # Read existing body, find the steps section, replace it
        body = self._read_issue_body(issue_url)
        section_start = "## Steps"
        section_end = "---"
        rendered_section = f"{section_start}\n\n" + "\n".join(lines) + f"\n\n{section_end}"
        if section_start in body:
            # Replace existing section (from heading to next ---)
            start_idx = body.index(section_start)
            end_idx = body.find(section_end, start_idx + len(section_start))
            if end_idx != -1:
                end_idx += len(section_end)
            else:
                end_idx = len(body)
            body = body[:start_idx] + rendered_section + body[end_idx:]
        else:
            body = body.rstrip() + f"\n\n{rendered_section}\n"
        self._write_issue_body(issue_url, body)

    def request_review(self) -> None:
        """Request code review. Pushes branch, runs tests, checks CI."""
        if not self._is_idle():
            raise ValueError("request-review only available from idle. Run end-step first.")
        self._run_tests()
        # Push branch and check CI (skip if no remote)
        has_remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=self.root,
        ).returncode == 0
        if has_remote:
            result = subprocess.run(
                ["git", "push", "-u", "origin", "HEAD"],
                capture_output=True, text=True, cwd=self.root,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Push failed: {result.stderr}")
            self._check_ci()
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=self.root,
        ).stdout.strip()
        state = self.read_state()
        self._write_state(Phase.REVIEW, state.get("task"), reviewed_sha=head_sha)
        self._set_label(self.LABEL_REVIEW)

    REVIEW_ROLES = ("user", "architect")

    def submit_review(self, role: str, content: str) -> None:
        """Submit a review as a comment on the issue."""
        if role not in self.REVIEW_ROLES:
            raise ValueError(f"Unknown review role: {role} (expected one of {self.REVIEW_ROLES})")
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"submit-review only available during review (current: {phase.value})")
        issue_url = self._issue_url_from_state()
        if not issue_url:
            raise ValueError("No issue URL in state")
        repo = self.get_repo()
        number = self._get_issue_number(issue_url)
        comment = f"## {role.capitalize()} Review\n\n{content}"
        env = self._gh_env()
        result = subprocess.run(
            ["gh", "issue", "comment", number, "--repo", repo, "--body", comment],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to submit review comment: {result.stderr}")
        # Record in state
        sf = self._read_state_file()
        reviews = sf["stack"][-1].get("reviews_submitted", [])
        if role not in reviews:
            reviews.append(role)
        sf["stack"][-1]["reviews_submitted"] = reviews
        self._save_stack(sf["stack"], history=sf["history"])

    def _missing_reviews(self) -> list[str]:
        """Return list of review roles not yet submitted."""
        state = self.read_state()
        submitted = state.get("reviews_submitted", [])
        return [r for r in self.REVIEW_ROLES if r not in submitted]

    def approve(self) -> None:
        """Approve review; return to idle. Requires both reviews submitted."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"approve only available during review (current: {phase.value})")
        missing = self._missing_reviews()
        if missing:
            raise ValueError(
                f"Cannot approve: missing reviews from {', '.join(missing)}. "
                f"Use `submit-review <role> <content>` first."
            )
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))
        self._set_label(self.LABEL_IDLE)

    def feedback(self, items: list[str] | None = None) -> None:
        """Review feedback; return to idle. Requires reviews to have been submitted."""
        phase = self._read_phase()
        if phase is not Phase.REVIEW:
            raise ValueError(f"feedback only available during review (current: {phase.value})")
        missing = self._missing_reviews()
        if missing:
            raise ValueError(
                f"Cannot provide feedback: missing reviews from {', '.join(missing)}. "
                f"Use `submit-review <role> <content>` first."
            )
        state = self.read_state()
        self._write_state(Phase.REFACTORING, state.get("task"))
        self._set_label(self.LABEL_IDLE)
        if items:
            issue_url = self._issue_url_from_state()
            if issue_url:
                # Insert feedback todos ABOVE the Steps section
                body = self._read_issue_body(issue_url)
                new_items = "\n".join(f"- [ ] {item}" for item in items)
                section = "## Steps"
                if section in body:
                    idx = body.index(section)
                    body = body[:idx] + new_items + "\n\n" + body[idx:]
                else:
                    body = f"{body}\n{new_items}" if body else new_items
                self._write_issue_body(issue_url, body)

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

        # Merge branch to main (skip if already on main or no remote)
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=self.root,
        ).stdout.strip()
        if branch and branch != "main":
            subprocess.run(
                ["git", "checkout", "main"],
                capture_output=True, text=True, cwd=self.root,
            )
            result = subprocess.run(
                ["git", "merge", "--no-ff", branch, "-m", f"Merge {branch}"],
                capture_output=True, text=True, cwd=self.root,
            )
            if result.returncode != 0:
                subprocess.run(
                    ["git", "checkout", branch],
                    capture_output=True, cwd=self.root,
                )
                raise RuntimeError(f"Merge failed: {result.stderr}")
            # Push main if remote exists
            has_remote = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, cwd=self.root,
            ).returncode == 0
            if has_remote:
                subprocess.run(
                    ["git", "push", "origin", "main"],
                    capture_output=True, text=True, cwd=self.root,
                )
            # Delete branch
            subprocess.run(
                ["git", "branch", "-d", branch],
                capture_output=True, cwd=self.root,
            )

        issue_url = self._issue_url_from_state()
        if issue_url:
            self.close_issue(issue_url)
        self._write_state(Phase.IDLE)

    # --- Protocol suspension ---

    def resume_protocol(self) -> None:
        """Resume protocol mode."""
        sf = self._read_state_file()
        sf.pop("protocol_suspended", None)
        self._write_state_file(sf)

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
            return False, f"Idle — no step active. Use `{CMD_BEGIN_REFACTOR} <desc> <code|test>` or `{CMD_BEGIN_MODIFY} <desc> <rationale...>`."

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
        test_script = self.root / "test" / "test.sh"
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
        """Wait for CI on the current branch to complete. Blocks until done."""
        env = self._gh_env()

        # Get current branch
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=self.root,
        ).stdout.strip()
        if not branch:
            return  # detached HEAD, skip CI check

        # Wait for run to appear (retry up to 30s)
        run_id = None
        for _ in range(6):
            time.sleep(5)
            result = subprocess.run(
                ["gh", "run", "list", "--branch", branch, "--limit", "1",
                 "--json", "databaseId", "--jq", ".[0].databaseId"],
                capture_output=True, text=True, env=env,
            )
            if result.returncode == 0 and result.stdout.strip():
                run_id = result.stdout.strip()
                break
        if not run_id:
            raise RuntimeError(
                f"No CI run found for branch {branch} after 30s. "
                f"Check that GitHub Actions is configured to run on this branch."
            )
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
    elif command == CMD_BEGIN_REFACTOR:
        args = sys.argv[2:]
        if len(args) < 2 or args[1] not in ("code", "test"):
            print(f"Usage: workflow.py {CMD_BEGIN_REFACTOR} <description> <code|test>", file=sys.stderr)
            sys.exit(1)
        wd.begin_refactor(args[0], args[1])
        print(f"Step: [refactor/{args[1]}] {args[0]}")
    elif command == CMD_BEGIN_MODIFY:
        args = sys.argv[2:]
        if len(args) < 2:
            print(f"Usage: workflow.py {CMD_BEGIN_MODIFY} <description> <rationale...>", file=sys.stderr)
            print(f"  Rationale: 'test: current → expected' pairs", file=sys.stderr)
            sys.exit(1)
        wd.begin_modify(args[0], args[1:])
        print(f"Step: [modify] {args[0]}")
    elif command == CMD_END_STEP:
        commit_msg = sys.argv[2] if len(sys.argv) > 2 else None
        wd.end_step(commit_msg)
        print("Step complete; back to idle")
    elif command == CMD_ABORT_STEP:
        reason = sys.argv[2] if len(sys.argv) > 2 else ""
        wd.abort_step(reason)
        print(f"Step aborted; back to idle" + (f" ({reason})" if reason else ""))
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
    elif command == CMD_SUBMIT_REVIEW:
        args = sys.argv[2:]
        if len(args) < 2:
            print(f"Usage: workflow.py {CMD_SUBMIT_REVIEW} <user|architect> <content>", file=sys.stderr)
            sys.exit(1)
        wd.submit_review(args[0], args[1])
        print(f"Review submitted: {args[0]}")
    elif command == CMD_CREATE_ISSUE:
        args = sys.argv[2:]
        if len(args) < 2:
            print(f"Usage: workflow.py {CMD_CREATE_ISSUE} <title> <body>", file=sys.stderr)
            sys.exit(1)
        url = wd.create_issue(args[0], args[1])
        print(f"Created: {url}")
    elif command == CMD_REOPEN_ISSUE:
        args = sys.argv[2:]
        if len(args) < 1:
            print(f"Usage: workflow.py {CMD_REOPEN_ISSUE} <issue-number>", file=sys.stderr)
            sys.exit(1)
        repo = wd.get_repo()
        issue_url = f"https://github.com/{repo}/issues/{args[0]}"
        wd.reopen_issue(issue_url)
        print(f"Reopened: issue #{args[0]}")
    elif command == CMD_RESUME_PROTOCOL:
        wd.resume_protocol()
        print("Protocol resumed.")
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
