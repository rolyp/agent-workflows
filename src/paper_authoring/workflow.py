#!/usr/bin/env python3
"""PaperAuthoring: paper_authoring workflow automaton.

Each method reads current state from disk, performs its operation, and writes
back. No in-memory state is cached between calls.

State is externalised to workflow/state.json.
"""

import glob
import subprocess
import json
import re
import sys
from enum import Enum
from pathlib import Path

# Ensure parent directory is on path when run as script
if __name__ == "__main__" or "workflow" not in sys.modules:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from workflow import Workflow, ValidationError



# LaTeX marker commands (must match change-tracking.tex)
EDIT_START = "\\editstart"
EDIT_END = "\\editend"
REVIEW_START = "\\reviewstart"
REVIEW_END = "\\reviewend"

# Change markup commands
CHANGE_MARKUP = ("\\added", "\\deleted", "\\replaced")

# Files managed exclusively by PaperAuthoring (block direct Edit)
PROTECTED_FILES = ("workflow/state.json",)

# CLI command names
CMD_STARTUP = "startup"
CMD_BEGIN_TRIAGE = "begin-triage"
CMD_RECLASSIFY = "reclassify"
CMD_APPROVE_TRIAGE = "approve-triage"
CMD_BEGIN_TASK = "begin-task"
CMD_BEGIN_AD_HOC = "begin-ad-hoc"
CMD_END_TASK = "end-task"
CMD_OPEN_REVIEW = "open-review"
CMD_CLOSE_REVIEW = "close-review"
CMD_EDIT_TO_REVIEW = "edit-to-review"
CMD_REVIEW_TO_EDIT = "review-to-edit"
CMD_CREATE_PLAN = "create-plan"
CMD_APPROVE_PLAN = "approve-plan"
CMD_ADD_SUBTASK = "add-subtask"
CMD_BEGIN_SUBTASK = "begin-subtask"
CMD_CHECK_EDIT = "check-edit"


class Phase(Enum):
    IDLE = "idle"                        # No active task
    TRIAGE = "triage"                    # Reviewing structural/minor notes before editing cycle
    SELECTING = "selecting"              # Phase 1: choosing next task
    EDIT = "edit"                        # Phase 2: editing within edit bars
    PLANNING = "planning"                  # Substate of edit: working on a plan
    AUTHOR_REVIEW = "author-review"      # Phase 3: awaiting author approval
    CLOSEOUT = "closeout"                # Phase 4: structural close-out


class PaperAuthoring(Workflow):
    # Paper-authoring-specific labels
    LABEL_IDLE = "\u26aa idle"                     # ⚪ idle
    LABEL_TRIAGE = "\U0001f7e3 triage"             # 🟣 triage
    LABEL_EDIT = "\U0001f7e2 edit"                 # 🟢 edit
    LABEL_PLANNING = "\U0001f535 planning"          # 🔵 planning
    LABEL_REVIEW = "\U0001f7e1 author-review"      # 🟡 author-review
    LABEL_CLOSEOUT = "\U0001f7e0 closeout"         # 🟠 closeout

    WORKFLOW_LABELS = (
        LABEL_IDLE, LABEL_TRIAGE, LABEL_EDIT,
        LABEL_PLANNING, LABEL_REVIEW, LABEL_CLOSEOUT,
    )

    def __init__(self, project_root: Path):
        self.root = project_root
        self.structural_path = project_root / "workflow" / "todo" / "structural.md"
        self.state_path = project_root / "workflow" / "state.json"

        # Preconditions: workflow files must exist
        missing = []
        for path in (self.structural_path,):
            if not path.exists():
                missing.append(str(path.relative_to(self.root)))
        if missing:
            raise FileNotFoundError(f"Missing workflow files: {', '.join(missing)}")

        self._init_state(Phase.IDLE)
    

        self.assert_valid()

    # --- Invariants ---

    def assert_valid(self) -> None:
        errors = []
        errors += self._state_file_exists()
        # Compute marker census once
        edit_files = self._tex_files_containing(EDIT_START)
        review_files = self._tex_files_containing(REVIEW_START)
        errors += self._no_orphaned_markers(edit_files, review_files)
        errors += self._markers_do_not_coexist(edit_files, review_files)
        errors += self._state_consistent_with_markers(edit_files, review_files)
        if errors:
            raise ValidationError(errors)

    def _state_file_exists(self) -> list[str]:
        if not self.state_path.exists():
            return ["workflow/state.json does not exist"]
        return []

    def _no_orphaned_markers(self, edit_files: list[str],
                             review_files: list[str]) -> list[str]:
        phase = self._read_phase()
        if phase not in (Phase.IDLE, Phase.TRIAGE):
            return []
        errors = []
        if edit_files:
            errors.append(f"State is '{phase.value}' but {EDIT_START} markers found in .tex files")
        if review_files:
            errors.append(f"State is '{phase.value}' but {REVIEW_START} markers found in .tex files")
        return errors

    def _markers_do_not_coexist(self, edit_files: list[str],
                                review_files: list[str]) -> list[str]:
        if edit_files and review_files:
            return [f"Both {EDIT_START} and {REVIEW_START} markers present — should not coexist"]
        return []

    def _state_consistent_with_markers(self, edit_files: list[str],
                                       review_files: list[str]) -> list[str]:
        phase = self._read_phase()
        has_edit = bool(edit_files)
        has_review = bool(review_files)
        errors = []
        if phase is Phase.EDIT and not has_edit:
            errors.append("State is 'edit' but no edit bars found in .tex files")
        if phase is Phase.AUTHOR_REVIEW and not has_review:
            errors.append("State is 'author-review' but no review bars found in .tex files")
        if phase is Phase.IDLE and (has_edit or has_review):
            errors.append("State is 'idle' but markers found in .tex files")
        return errors

    # --- State overrides (paper-authoring enriches frames) ---

    def _phase_enum(self) -> type[Phase]:
        return Phase

    # Fields carried forward from the previous frame unless overridden
    _CARRY_FORWARD = ("regions", "description", "note_link", "plan_link", "subtasks", "issue_url")

    @staticmethod
    def _normalize_regions(regions: object) -> list[list[str]]:
        """Convert regions to list-of-lists format for JSON serialization."""
        return [[f, p] for f, p in regions]  # type: ignore[attr-defined]

    def _write_state(self, phase: Enum, task: str | None = None,
                     **extra: object) -> None:
        """Replace top frame, carrying forward paper-authoring-specific fields."""
        prev = self.read_state()
        if "regions" in extra and extra["regions"] is not None:
            extra["regions"] = self._normalize_regions(extra["regions"])
        for key in self._CARRY_FORWARD:
            if key not in extra and key in prev:
                extra[key] = prev[key]
        super()._write_state(phase, task, **extra)

    def _push_state(self, phase: Enum, task: str | None = None,
                    **extra: object) -> None:
        """Push a new frame, normalizing regions if provided."""
        if "regions" in extra and extra["regions"] is not None:
            extra["regions"] = self._normalize_regions(extra["regions"])
        super()._push_state(phase, task, **extra)

    def _save_stack(self, stack: list[dict], history: list[dict] | None = None,
                    validate: bool = True) -> None:
        """Write stack, optionally validate."""
        super()._save_stack(stack, history=history, validate=validate)
        if validate:
            self.assert_valid()

    # --- Triage commands ---

    def begin_triage(self) -> None:
        """Enter triage phase."""
        self._write_state(Phase.TRIAGE)

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

    def approve_triage(self, review_issue_number: str) -> None:
        """Exit triage. Promotes accepted findings from review issue to standalone issues.

        Closes the review issue after promotion.
        """
        findings = self.parse_review_issue(review_issue_number)
        self.promote_findings(findings)
        repo = self.get_repo()
        review_url = f"https://github.com/{repo}/issues/{review_issue_number}"
        self.close_issue(review_url)
        self._write_state(Phase.IDLE)

    # --- Task selection ---

    AD_HOC = "Ad hoc"

    def begin_task(self, issue_number: str, regions: list[tuple[str, str]]) -> None:
        """Select a task by issue number; move to In Progress; place edit bars.

        issue_number: GitHub issue number.
        regions: list of (file_path, passage) pairs to place edit bars around.
        """
        if not regions:
            raise ValueError("At least one edit region required")

        repo = self.get_repo()
        issue_url = f"https://github.com/{repo}/issues/{issue_number}"
        env = self._gh_env()
        result = subprocess.run(
            ["gh", "issue", "view", issue_number, "--repo", repo,
             "--json", "title", "--jq", ".title"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise ValueError(f"Issue #{issue_number} not found: {result.stderr}")
        description = result.stdout.strip()

        # Place edit bars
        for file_path, passage in regions:
            self._place_bars(file_path, passage, EDIT_START, EDIT_END)
        # Update state
        self._write_state(Phase.EDIT, issue_number, regions=regions,
                          description=description, issue_url=issue_url)
        # Update GitHub
        self.set_issue_status(issue_url, "In Progress")
        self.set_issue_label(issue_url, self.LABEL_EDIT)

    def begin_ad_hoc(self, regions: list[tuple[str, str]]) -> None:
        """Start an ad hoc edit; place review bars (skips Edit, goes to review)."""
        if not regions:
            raise ValueError("At least one edit region required")
        for file_path, passage in regions:
            self._place_bars(file_path, passage, REVIEW_START, REVIEW_END)
        self._write_state(Phase.AUTHOR_REVIEW, self.AD_HOC, regions=regions,
                          description=self.AD_HOC)

    # --- Planning ---

    def create_plan(self, plan_name: str) -> Path:
        """Create a plan file and transition to planning phase.

        Returns the path to the created plan file.
        """
        phase = self._read_phase()
        if phase is not Phase.EDIT:
            raise ValueError(f"Can only create plans during edit phase (current: {phase.value})")
        plans_dir = self.root / "workflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{plan_name}.md"
        if plan_path.exists():
            raise ValueError(f"Plan already exists: {plan_path.relative_to(self.root)}")
        state = self.read_state()
        task = state.get("task")
        plan_path.write_text(
            f"# Plan: {plan_name}\n\n"
            f"Task: [{task}](../todo/structural.md#note-{task})\n\n"
            f"## Problem\n\n## Proposed approach\n\n## Open questions\n"
        )
        plan_link_rel = f"plans/{plan_name}.md"
        stack = self._read_stack()
        stack[-1]["plan_link"] = plan_link_rel
        self._save_stack(stack)
        self._push_state(Phase.PLANNING, task)
        return plan_path

    def approve_plan(self) -> None:
        """Approve the plan and pop back to the previous phase."""
        phase = self._read_phase()
        if phase is not Phase.PLANNING:
            raise ValueError(f"Can only approve plans during planning phase (current: {phase.value})")
        self._pop_state(validate=False)
        self.assert_valid()

    def end_task(self) -> None:
        """Complete the current task or subtask."""
        stack = self._read_stack()

        for path in (self._tex_files_containing(EDIT_START)
                     + self._tex_files_containing(REVIEW_START)):
            self._remove_bars(path, EDIT_START, EDIT_END)
            self._remove_bars(path, REVIEW_START, REVIEW_END)
        self._build()

        if len(stack) > 1:
            completed_task = self.read_state().get("task")
            subtask_url = self.read_state().get("issue_url")
            self._pop_state(validate=False)
            # Close sub-issue if linked
            if subtask_url:
                self.close_issue(subtask_url)
            # Mark subtask as completed in parent's list
            parent_stack = self._read_stack()
            for st in parent_stack[-1].get("subtasks", []):
                if st.get("id") == completed_task:
                    st["completed"] = True
            self._save_stack(parent_stack, validate=False)
            parent = self.read_state()
            parent_regions = parent.get("regions", [])
            for file_path, passage in parent_regions:
                full_path = self.root / file_path
                if full_path.exists() and passage in full_path.read_text():
                    self._place_bars(file_path, passage, EDIT_START, EDIT_END)
            self.assert_valid()
        else:
            # Close GitHub issue if linked
            state = self.read_state()
            issue_url = state.get("issue_url")
            if issue_url:
                self.close_issue(issue_url)
            self._write_state(Phase.IDLE)

    # --- Subtasks ---

    def add_subtask(self, subtask_id: str, description: str,
                    issue_number: str | None = None) -> None:
        """Add a subtask under the current in-progress task.

        If issue_number is provided, links that existing issue as a sub-issue.
        Otherwise creates a new sub-issue if the parent task has an issue URL.
        """
        state = self.read_state()
        parent_url = state.get("issue_url")
        sf = self._read_state_file()
        frame = sf["stack"][-1]
        subtask_entry: dict[str, object] = {"id": subtask_id, "description": description}
        if issue_number:
            # Link existing issue
            repo = self.get_repo()
            sub_url = f"https://github.com/{repo}/issues/{issue_number}"
            if parent_url:
                self.link_sub_issue(parent_url, sub_url)
            subtask_entry["issue_url"] = sub_url
        elif parent_url:
            # Create new sub-issue
            sub_url = self.create_sub_issue(parent_url, description)
            subtask_entry["issue_url"] = sub_url
        subtasks = list(frame.get("subtasks", []))
        subtasks.append(subtask_entry)
        frame["subtasks"] = subtasks
        self._save_stack(sf["stack"], history=sf["history"])

    def begin_subtask(self, subtask_id: str, regions: list[tuple[str, str]]) -> None:
        """Select a subtask; remove parent bars, place subtask bars, push state."""
        if not regions:
            raise ValueError("At least one edit region required")
        # Find subtask entry to get issue_url
        state = self.read_state()
        subtask_url = None
        for st in state.get("subtasks", []):
            if st.get("id") == subtask_id:
                subtask_url = st.get("issue_url")
                break
        for path in (self._tex_files_containing(EDIT_START)
                     + self._tex_files_containing(REVIEW_START)):
            self._remove_bars(path, EDIT_START, EDIT_END)
            self._remove_bars(path, REVIEW_START, REVIEW_END)
        for file_path, passage in regions:
            self._place_bars(file_path, passage, EDIT_START, EDIT_END)
        self._push_state(Phase.EDIT, subtask_id, regions=regions,
                         issue_url=subtask_url)
        # Set sub-issue to In Progress
        if subtask_url:
            self.set_issue_status(subtask_url, "In Progress")
            self.set_issue_label(subtask_url, self.LABEL_EDIT)


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
        self._build()
        state = self.read_state()
        task = state.get("task")
        self._write_state(Phase.AUTHOR_REVIEW, task)
        issue_url = state.get("issue_url")
        if issue_url:
            self.set_issue_label(issue_url, self.LABEL_REVIEW)

    def review_to_edit(self) -> None:
        """Swap all review bars to edit bars; transition to edit phase."""
        for path in self._tex_files_containing(REVIEW_START):
            text = Path(path).read_text()
            text = text.replace(REVIEW_START, EDIT_START)
            text = text.replace(REVIEW_END, EDIT_END)
            Path(path).write_text(text)
        self._build()
        state = self.read_state()
        task = state.get("task")
        self._write_state(Phase.EDIT, task)
        issue_url = state.get("issue_url")
        if issue_url:
            self.set_issue_label(issue_url, self.LABEL_EDIT)

    def _build(self) -> None:
        """Run the build script if it exists."""
        build_script = self.root / "workflow" / "agent-workflows" / "src" / "paper_authoring" / "build.sh"
        if build_script.exists():
            result = subprocess.run(
                ["bash", str(build_script)],
                capture_output=True, text=True, cwd=self.root,
            )
            if result.returncode != 0:
                print(result.stdout + result.stderr, file=sys.stderr)

    def _require_active_task(self) -> None:
        phase = self._read_phase()
        if phase is Phase.IDLE:
            raise ValueError(f"No active task. Use {CMD_BEGIN_TASK} or {CMD_BEGIN_AD_HOC} first.")


    def _place_bars(self, file_path: str, passage: str,
                    start: str, end: str) -> None:
        full_path = self.root / file_path if not Path(file_path).is_absolute() else Path(file_path)
        content = full_path.read_text()
        if passage not in content:
            raise ValueError(f"Passage not found in {file_path}")
        content = content.replace(passage, f"{start} {passage}{end}", 1)
        full_path.write_text(content)
        self._build()

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
        phase = self._read_phase()
        state = self.read_state()
        task = state.get("task") or "unknown"

        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""  # outside project root

        # Protected files: never editable directly
        for protected in PROTECTED_FILES:
            if rel_path == protected or rel_path.endswith(protected):
                return False, (
                    f"Cannot edit {protected} directly. "
                    f"Use PaperAuthoring commands to modify workflow state."
                )

        # .md files in workflow/plans: only during planning, only the active plan
        if "workflow/plans/" in rel_path and rel_path.endswith(".md"):
            if phase is not Phase.PLANNING:
                return False, (
                    f"Cannot edit plan files outside planning phase. "
                    f"Use `workflow.py {CMD_CREATE_PLAN}` first."
                )
            return True, ""

        # Non-.tex files: allow (e.g. .bib, structural.md, minor-issues.md)
        if not file_path.endswith(".tex"):
            return True, ""

        # --- .tex-specific checks below ---

        # Phase-based blocks
        if phase is Phase.IDLE:
            return False, (
                f"No active task. Use `workflow.py {CMD_BEGIN_TASK}` or "
                f"`workflow.py {CMD_BEGIN_AD_HOC}` first."
            )
        if phase is Phase.TRIAGE:
            return False, (
                "Cannot edit .tex files during triage phase. "
                f"Run `workflow.py {CMD_APPROVE_TRIAGE}` to enter editing cycle first."
            )
        if phase is Phase.PLANNING:
            return False, (
                "Cannot edit .tex files during planning phase. "
                f"Run `workflow.py {CMD_APPROVE_PLAN}` to return to edit phase first."
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
                        f"Run `workflow.py {CMD_REVIEW_TO_EDIT}` first."
                    )

        return True, ""

    def check_write(self, file_path: str) -> tuple[bool, str]:
        """Check whether a Write to file_path is allowed.

        Write is only allowed if the file does not already exist.
        Plan files can only be created by PaperAuthoring.
        Only applies to files within the project root.
        """
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""  # outside project root

        # Block writing to protected files
        for protected in PROTECTED_FILES:
            if rel_path == protected or rel_path.endswith(protected):
                return False, (
                    f"Cannot write {protected} directly. "
                    f"Use PaperAuthoring commands."
                )

        # Block creating plan files directly
        if "workflow/plans/" in rel_path and rel_path.endswith(".md"):
            return False, (
                f"Cannot create plan files directly. "
                f"Use `workflow.py {CMD_CREATE_PLAN}` instead."
            )

        full_path = self.root / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if full_path.exists():
            return False, (
                f"Cannot overwrite existing file {file_path} with Write tool. "
                f"Use Edit tool for modifications to existing files."
            )
        return True, ""

    def check_bash(self, command: str, agent_type: str | None = None) -> tuple[bool, str]:
        """Gate shell commands: block writes to protected files via shell."""
        cmd = command.strip()
        # Detect common shell write patterns targeting protected files
        for protected in PROTECTED_FILES:
            if protected in cmd:
                return False, (
                    f"Cannot modify {protected} via shell. "
                    "Use PaperAuthoring commands."
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


    def _minor_issues_path(self) -> Path:
        return self.root / "workflow" / "todo" / "minor-issues.md"

    def _tex_files_containing(self, pattern: str) -> list[str]:
        return [
            f for f in glob.glob(str(self.root / "**" / "*.tex"), recursive=True)
            if not f.startswith(str(self.root / "workflow"))
            if pattern in Path(f).read_text()
        ]

    # --- GitHub Issues integration ---

    def parse_review_issue(self, issue_number: str) -> list[tuple[str, str]]:
        """Parse accepted findings from a review issue's checklist.

        Returns list of (title, body) pairs for unchecked items.
        Checked/strikethrough items are treated as rejected.
        """
        repo = self.get_repo()
        issue_url = f"https://github.com/{repo}/issues/{issue_number}"
        body = self._read_issue_body(issue_url)
        findings = []
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("- [ ] "):
                description = line[6:].strip()
                findings.append((description, f"From review issue #{issue_number}"))
        return findings

    def promote_findings(self, findings: list[tuple[str, str]]) -> list[str]:
        """Create a standalone issue for each finding.

        findings: list of (title, body) pairs.
        Returns list of created issue URLs.
        """
        urls = []
        for title, body in findings:
            url = self.create_issue(title, body)
            urls.append(url)
        return urls



# --- CLI entry point ---

def main() -> None:
    if len(sys.argv) < 2:
        command = CMD_STARTUP
    else:
        command = sys.argv[1]

    try:
        workflow = PaperAuthoring(Path.cwd())
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
        state = workflow.read_state()
        phase = state["phase"]
        task = state.get("task")
        summary = f"Workflow state: {phase}"
        if task:
            summary += f" — {task}"
        print(summary)
    elif command == CMD_BEGIN_TRIAGE:
        workflow.begin_triage()
        print("Entered triage phase")
    elif command == CMD_RECLASSIFY:
        if len(sys.argv) < 4:
            print(f"Usage: workflow.py {CMD_RECLASSIFY} <note-id> <structural|minor>", file=sys.stderr)
            sys.exit(1)
        workflow.reclassify(sys.argv[2], sys.argv[3])
        print(f"Reclassified {sys.argv[2]} → {sys.argv[3]}")
    elif command == CMD_APPROVE_TRIAGE:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_APPROVE_TRIAGE} <review-issue-number>", file=sys.stderr)
            sys.exit(1)
        workflow.approve_triage(sys.argv[2])
        print(f"Triage complete; review issue #{sys.argv[2]} closed")
    elif command == CMD_BEGIN_TASK:
        if len(sys.argv) < 4:
            print(f"Usage: workflow.py {CMD_BEGIN_TASK} <note-id> <regions-json>", file=sys.stderr)
            print(f"  regions-json: [[\"file\", \"passage\"], ...]", file=sys.stderr)
            sys.exit(1)
        regions = json.loads(sys.argv[3])
        workflow.begin_task(sys.argv[2], [(r[0], r[1]) for r in regions])
        print(f"Selected task: {sys.argv[2]} ({len(regions)} region(s))")
    elif command == CMD_BEGIN_AD_HOC:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_BEGIN_AD_HOC} <regions-json>", file=sys.stderr)
            sys.exit(1)
        regions = json.loads(sys.argv[2])
        workflow.begin_ad_hoc([(r[0], r[1]) for r in regions])
        print(f"Ad hoc edit started ({len(regions)} region(s))")
    elif command == CMD_CREATE_PLAN:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_CREATE_PLAN} <plan-name>", file=sys.stderr)
            sys.exit(1)
        plan_path = workflow.create_plan(sys.argv[2])
        print(f"Plan created: {plan_path}")
    elif command == CMD_APPROVE_PLAN:
        workflow.approve_plan()
        print("Plan approved; returning to edit phase")
    elif command == CMD_ADD_SUBTASK:
        if len(sys.argv) < 4:
            print(f"Usage: workflow.py {CMD_ADD_SUBTASK} <subtask-id> <description> [issue-number]", file=sys.stderr)
            sys.exit(1)
        issue_num = sys.argv[4] if len(sys.argv) > 4 else None
        workflow.add_subtask(sys.argv[2], sys.argv[3], issue_number=issue_num)
        print(f"Added subtask: {sys.argv[2]}")
    elif command == CMD_BEGIN_SUBTASK:
        if len(sys.argv) < 4:
            print(f"Usage: workflow.py {CMD_BEGIN_SUBTASK} <subtask-id> <regions-json>", file=sys.stderr)
            sys.exit(1)
        regions = json.loads(sys.argv[3])
        workflow.begin_subtask(sys.argv[2], [(r[0], r[1]) for r in regions])
        print(f"Selected subtask: {sys.argv[2]} ({len(regions)} region(s))")
    elif command == CMD_END_TASK:
        workflow.end_task()
        print("Task completed")
    elif command == CMD_OPEN_REVIEW:
        if len(sys.argv) < 4:
            print(f"Usage: workflow.py {CMD_OPEN_REVIEW} <file_path> <passage>", file=sys.stderr)
            sys.exit(1)
        workflow.open_review(sys.argv[2], sys.argv[3])
        print(f"Review bars placed in {sys.argv[2]}")
    elif command == CMD_CLOSE_REVIEW:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_CLOSE_REVIEW} <file_path>", file=sys.stderr)
            sys.exit(1)
        workflow.close_review(sys.argv[2])
        print(f"Review bars removed from {sys.argv[2]}")
    elif command == CMD_EDIT_TO_REVIEW:
        workflow.edit_to_review()
        print("Bars: edit → review")
    elif command == CMD_REVIEW_TO_EDIT:
        workflow.review_to_edit()
        print("Bars: review → edit")
    elif command == CMD_CHECK_EDIT:
        if len(sys.argv) < 3:
            print(f"Usage: workflow.py {CMD_CHECK_EDIT} <file_path>", file=sys.stderr)
            sys.exit(1)
        allowed, message = workflow.check_edit(sys.argv[2])
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
