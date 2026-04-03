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

    # --- Environment ---

    def _get_env(self, key: str) -> str:
        """Get env var, falling back to .claude/settings.local.json."""
        value = os.environ.get(key, "")
        if value:
            return value
        settings_path = self.root / ".claude" / "settings.local.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            value = settings.get("env", {}).get(key, "")
        if not value:
            raise RuntimeError(f"{key} not set (checked env and .claude/settings.local.json)")
        return value

    def _gh_env(self, token_key: str = "GH_TOKEN") -> dict:
        """Build env dict for subprocess calls with the given token."""
        return {**os.environ, "GH_TOKEN": self._get_env(token_key)}

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
        repo = self.get_repo()
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/milestones", "--jq", ".[].title"],
            capture_output=True, text=True, env=self._gh_env(),
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

        Uses GH_TOKEN for repo operations, GH_PROJECT_TOKEN for project operations.
        Falls back to .claude/settings.local.json if env vars not set.
        """
        repo = self.get_repo()
        milestone = self.get_active_milestone()
        env = self._gh_env()

        # Create the issue
        cmd = ["gh", "issue", "create", "--repo", repo,
               "--title", title, "--body", body,
               "--milestone", milestone]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"gh issue create failed: {result.stderr}")
        issue_url = result.stdout.strip()

        # Add to project (uses separate token if configured)
        project_org = self._get_env("GH_PROJECT_ORG")
        project_number = self._get_env("GH_PROJECT_NUMBER")
        project_env = self._gh_env("GH_PROJECT_TOKEN")
        self._add_issue_to_project(issue_url, project_org, project_number, project_env)

        return issue_url

    def _add_issue_to_project(self, issue_url: str, org: str,
                              project_number: str, env: dict) -> None:
        """Add issue to project and set status to Planned.

        Uses GraphQL directly — gh project item-add has permissions issues
        when adding cross-owner issues (tries to read back field values).
        """
        # Extract owner/repo#number from URL to get the issue's node ID
        match = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url)
        if not match:
            raise ValueError(f"Cannot parse issue URL: {issue_url}")
        owner, repo_name, issue_number = match.group(1), match.group(2), match.group(3)

        # Get issue node ID and project info in one query
        query = (
            f"query {{ "
            f'repository(owner: "{owner}", name: "{repo_name}") {{ '
            f"issue(number: {issue_number}) {{ id }} }} "
            f'organization(login: "{org}") {{ '
            f"projectV2(number: {project_number}) {{ id "
            f'field(name: "Status") {{ '
            f"... on ProjectV2SingleSelectField {{ id options {{ id name }} }} "
            f"}} }} }} }}"
        )
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to query issue/project: {result.stderr}")

        data = json.loads(result.stdout)["data"]
        issue_id = data["repository"]["issue"]["id"]
        project = data["organization"]["projectV2"]
        project_id = project["id"]
        status_field = project["field"]
        field_id = status_field["id"]

        planned_id = None
        for opt in status_field["options"]:
            if opt["name"] == "Planned":
                planned_id = opt["id"]
                break
        if not planned_id:
            raise RuntimeError("No 'Planned' status option found in project")

        # Add to project
        mutation = (
            f'mutation {{ addProjectV2ItemById(input: {{ '
            f'projectId: "{project_id}", contentId: "{issue_id}" }}) '
            f"{{ item {{ id }} }} }}"
        )
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={mutation}"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to add issue to project: {result.stderr}")

        item_id = json.loads(result.stdout)["data"]["addProjectV2ItemById"]["item"]["id"]

        # Set status to Planned
        set_status = (
            f'mutation {{ updateProjectV2ItemFieldValue(input: {{ '
            f'projectId: "{project_id}", itemId: "{item_id}", '
            f'fieldId: "{field_id}", '
            f'value: {{ singleSelectOptionId: "{planned_id}" }} }}) '
            f"{{ projectV2Item {{ id }} }} }}"
        )
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={set_status}"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to set project status: {result.stderr}")

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
