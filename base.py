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

        # Add to project and set status to Planned
        project_env = self._ensure_project_info()
        item_id = self._add_issue_to_project(
            issue_url, self._get_env("GH_PROJECT_ORG"),
            self._get_env("GH_PROJECT_NUMBER"), project_env)
        self._set_item_status(item_id, "Planned", project_env)

        return issue_url

    def _parse_issue_url(self, issue_url: str) -> tuple[str, str, str]:
        """Extract (owner, repo, number) from a GitHub issue URL."""
        match = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url)
        if not match:
            raise ValueError(f"Cannot parse issue URL: {issue_url}")
        return match.group(1), match.group(2), match.group(3)

    def _gql(self, query: str, env: dict) -> dict:
        """Run a GraphQL query/mutation and return the data dict."""
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"GraphQL failed: {result.stderr}")
        return json.loads(result.stdout)["data"]

    def _get_project_status_field(self, org: str, project_number: str,
                                  env: dict) -> tuple[str, str, list[dict]]:
        """Return (project_id, field_id, options) for the Status field."""
        data = self._gql(
            f'query {{ organization(login: "{org}") {{ '
            f"projectV2(number: {project_number}) {{ id "
            f'field(name: "Status") {{ '
            f"... on ProjectV2SingleSelectField {{ id options {{ id name }} }} "
            f"}} }} }} }}",
            env,
        )
        project = data["organization"]["projectV2"]
        field = project["field"]
        return project["id"], field["id"], field["options"]

    def _find_status_option(self, options: list[dict], name: str) -> str:
        """Find a status option by name; raise if not found."""
        for opt in options:
            if opt["name"] == name:
                return opt["id"]
        available = [o["name"] for o in options]
        raise RuntimeError(f"No '{name}' status option found (available: {available})")

    def _add_issue_to_project(self, issue_url: str, org: str,
                              project_number: str, env: dict) -> str:
        """Add issue to project; return the project item ID.

        Uses GraphQL directly — gh CLI has permissions issues
        with cross-owner issues (tries to read back field values).
        """
        owner, repo_name, issue_number = self._parse_issue_url(issue_url)

        # Get issue node ID
        data = self._gql(
            f'query {{ repository(owner: "{owner}", name: "{repo_name}") {{ '
            f"issue(number: {issue_number}) {{ id }} }} }}",
            env,
        )
        issue_id = data["repository"]["issue"]["id"]

        # Add to project
        data = self._gql(
            f'mutation {{ addProjectV2ItemById(input: {{ '
            f'projectId: "{self._project_id}", contentId: "{issue_id}" }}) '
            f"{{ item {{ id }} }} }}",
            env,
        )
        return data["addProjectV2ItemById"]["item"]["id"]

    def _set_item_status(self, item_id: str, status_name: str,
                         env: dict) -> None:
        """Set a project item's status field."""
        option_id = self._find_status_option(self._status_options, status_name)
        self._gql(
            f'mutation {{ updateProjectV2ItemFieldValue(input: {{ '
            f'projectId: "{self._project_id}", itemId: "{item_id}", '
            f'fieldId: "{self._status_field_id}", '
            f'value: {{ singleSelectOptionId: "{option_id}" }} }}) '
            f"{{ projectV2Item {{ id }} }} }}",
            env,
        )

    def _ensure_project_info(self) -> dict:
        """Load and cache project info (project_id, field_id, options)."""
        if not hasattr(self, "_project_id"):
            org = self._get_env("GH_PROJECT_ORG")
            number = self._get_env("GH_PROJECT_NUMBER")
            env = self._gh_env("GH_PROJECT_TOKEN")
            self._project_id, self._status_field_id, self._status_options = \
                self._get_project_status_field(org, number, env)
        return self._gh_env("GH_PROJECT_TOKEN")

    def _find_project_item(self, issue_url: str, env: dict) -> str:
        """Find the project item ID for an issue. Searches recent project items."""
        owner, repo_name, issue_number = self._parse_issue_url(issue_url)
        target_repo = f"{owner}/{repo_name}"
        org = self._get_env("GH_PROJECT_ORG")
        number = self._get_env("GH_PROJECT_NUMBER")

        data = self._gql(
            f'query {{ organization(login: "{org}") {{ '
            f"projectV2(number: {number}) {{ "
            f"items(last: 50) {{ nodes {{ id content {{ "
            f"... on Issue {{ number repository {{ nameWithOwner }} }} "
            f"}} }} }} }} }} }}",
            env,
        )
        for item in data["organization"]["projectV2"]["items"]["nodes"]:
            content = item.get("content", {})
            if (content and
                content.get("repository", {}).get("nameWithOwner") == target_repo and
                content.get("number") == int(issue_number)):
                return item["id"]
        raise RuntimeError(f"Issue {issue_url} not found in project")

    def set_issue_status(self, issue_url: str, status: str) -> None:
        """Set the project status of an issue (e.g. 'In Progress', 'Done')."""
        env = self._ensure_project_info()
        item_id = self._find_project_item(issue_url, env)
        self._set_item_status(item_id, status, env)

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
