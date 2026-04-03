"""Base class for workflow implementations."""

import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} invariant(s) violated")


class Workflow(ABC):
    """Base workflow with pushdown automaton state management.

    Subclasses must set `root`, `state_path`, and their own Phase enum.
    """

    root: Path
    state_path: Path

    # --- State (pushdown automaton: stack of {phase, task, ...} frames) ---

    def read_state(self) -> dict:
        """Read the top frame of the state stack."""
        return self._read_stack()[-1]

    def _read_stack(self) -> list[dict]:
        return json.loads(self.state_path.read_text())

    def _read_phase(self) -> Enum:
        """Read the current phase. Subclasses should narrow the return type."""
        return self._phase_enum()(self.read_state()["phase"])

    def _write_state(self, phase: Enum, task: str | None = None,
                     **extra: object) -> None:
        """Replace the top frame of the state stack."""
        stack = self._read_stack()
        frame: dict[str, object] = {"phase": phase.value, "task": task}
        frame.update(extra)
        stack[-1] = frame
        self._save_stack(stack)

    def _push_state(self, phase: Enum, task: str | None = None,
                    **extra: object) -> None:
        """Push a new frame onto the state stack."""
        stack = self._read_stack()
        frame: dict[str, object] = {"phase": phase.value, "task": task}
        frame.update(extra)
        stack.append(frame)
        self._save_stack(stack)

    def _pop_state(self, validate: bool = True) -> dict[str, object]:
        """Pop the top frame and return it."""
        stack = self._read_stack()
        if len(stack) <= 1:
            raise ValueError("Cannot pop the last state frame")
        popped = stack.pop()
        self._save_stack(stack, validate=validate)
        return popped

    def _save_stack(self, stack: list[dict], validate: bool = True) -> None:
        """Write the stack to disk. Subclasses may override to add side effects.

        validate: no-op in base; subclasses (e.g. PaperAuthoring) use it to
        skip validation when the caller will validate after further changes.
        """
        self.state_path.write_text(json.dumps(stack, indent=2) + "\n")

    def _init_state(self, idle_phase: Enum) -> None:
        """Initialise state file if absent, with a single idle frame."""
        if not self.state_path.exists():
            stack = [{"phase": idle_phase.value, "task": None}]
            self.state_path.write_text(json.dumps(stack, indent=2) + "\n")

    # --- Path resolution ---

    def _resolve(self, file_path: str) -> str | None:
        """Resolve file_path to a path relative to project root.

        Returns None if the file is outside the project root.
        """
        if Path(file_path).is_absolute():
            try:
                return str(Path(file_path).relative_to(self.root))
            except ValueError:
                return None
        return file_path

    # --- GitHub integration ---

    def get_repo(self) -> str:
        """Detect owner/repo from git remote."""
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=self.root,
        )
        if result.returncode != 0:
            raise ValueError(f"Cannot get git remote: {result.stderr}")
        url = result.stdout.strip()
        match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if not match:
            raise ValueError(f"Cannot parse repo from remote URL: {url}")
        return match.group(1)

    def get_active_milestone(self) -> str:
        """Return the title of the single open milestone for the repo.

        Raises if there isn't exactly one.
        """
        gh_token = os.environ.get("GH_TOKEN", "")
        if not gh_token:
            raise RuntimeError("GH_TOKEN not set")
        repo = self.get_repo()
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/milestones", "--jq", ".[].title"],
            capture_output=True, text=True,
            env={**os.environ, "GH_TOKEN": gh_token},
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to list milestones: {result.stderr}")
        titles = [t for t in result.stdout.strip().split("\n") if t]
        if len(titles) != 1:
            raise RuntimeError(
                f"Expected exactly 1 open milestone, found {len(titles)}: {titles}"
            )
        return titles[0]

    def create_issue(self, title: str, body: str) -> str:
        """Create a GitHub issue, assign to active milestone and project with status Planned.

        Uses GH_TOKEN, GH_PROJECT_ORG, GH_PROJECT_NUMBER from environment.
        """
        gh_token = os.environ.get("GH_TOKEN", "")
        if not gh_token:
            raise RuntimeError("GH_TOKEN not set")

        repo = self.get_repo()
        milestone = self.get_active_milestone()
        env = {**os.environ, "GH_TOKEN": gh_token}

        # Create the issue
        cmd = ["gh", "issue", "create", "--repo", repo,
               "--title", title, "--body", body,
               "--milestone", milestone]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"gh issue create failed: {result.stderr}")
        issue_url = result.stdout.strip()

        # Add to project if configured
        project_org = os.environ.get("GH_PROJECT_ORG", "")
        project_number = os.environ.get("GH_PROJECT_NUMBER", "")
        if project_org and project_number:
            self._add_issue_to_project(issue_url, project_org, project_number, env)

        return issue_url

    def _add_issue_to_project(self, issue_url: str, org: str,
                              project_number: str, env: dict) -> None:
        """Add issue to project and set status to Planned."""
        # Add item
        result = subprocess.run(
            ["gh", "project", "item-add", project_number,
             "--owner", org, "--url", issue_url, "--format", "json"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh project item-add failed: {result.stderr}")

        item_data = json.loads(result.stdout)
        item_id = item_data.get("id")
        if not item_id:
            raise RuntimeError(f"No item ID returned from project item-add")

        # Get project ID and Status field info
        gql_result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"""query={{
                organization(login: "{org}") {{
                    projectV2(number: {project_number}) {{
                        id
                        field(name: "Status") {{
                            ... on ProjectV2SingleSelectField {{
                                id
                                options {{ id name }}
                            }}
                        }}
                    }}
                }}
            }}"""],
            capture_output=True, text=True, env=env,
        )
        if gql_result.returncode != 0:
            raise RuntimeError(f"Failed to query project fields: {gql_result.stderr}")

        project_data = json.loads(gql_result.stdout)
        project = project_data["data"]["organization"]["projectV2"]
        project_id = project["id"]
        status_field = project["field"]
        field_id = status_field["id"]

        # Find "Planned" option
        planned_id = None
        for opt in status_field["options"]:
            if opt["name"] == "Planned":
                planned_id = opt["id"]
                break
        if not planned_id:
            raise RuntimeError("No 'Planned' status option found in project")

        # Set status to Planned
        result = subprocess.run(
            ["gh", "project", "item-edit",
             "--id", item_id,
             "--project-id", project_id,
             "--field-id", field_id,
             "--single-select-option-id", planned_id],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh project item-edit failed: {result.stderr}")

    # --- Abstract interface ---

    @abstractmethod
    def _phase_enum(self) -> type[Enum]:
        """Return the Phase enum class for this workflow."""

    @abstractmethod
    def check_edit(self, file_path: str, old_string: str | None = None,
                   new_string: str | None = None) -> tuple[bool, str]:
        """Check whether an edit to file_path is allowed.

        Returns (allowed, message). If not allowed, message explains
        what state transition is needed.
        """

    @abstractmethod
    def check_write(self, file_path: str) -> tuple[bool, str]:
        """Check whether a Write to file_path is allowed."""
