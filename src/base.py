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

    # --- State (pushdown automaton with history) ---
    #
    # State file format:
    #   {"stack": [...frames...], "history": [...entries...]}
    # Legacy format (list of frames) is auto-migrated on read.

    def _read_state_file(self) -> dict:
        """Read the full state file, auto-migrating legacy format."""
        raw = json.loads(self.state_path.read_text())
        if isinstance(raw, list):
            # Legacy format: bare stack list → migrate
            return {"stack": raw, "history": []}
        return raw

    def _write_state_file(self, state_file: dict) -> None:
        """Write the full state file."""
        self.state_path.write_text(json.dumps(state_file, indent=2) + "\n")

    def read_state(self) -> dict:
        """Read the top frame of the state stack."""
        return self._read_stack()[-1]

    def _read_stack(self) -> list[dict]:
        return self._read_state_file()["stack"]

    def _read_history(self) -> list[dict]:
        return self._read_state_file()["history"]

    def _read_phase(self) -> Enum:
        """Read the current phase. Subclasses should narrow the return type."""
        return self._phase_enum()(self.read_state()["phase"])

    def _write_state(self, phase: Enum, task: str | None = None,
                     **extra: object) -> None:
        """Replace the top frame of the state stack."""
        sf = self._read_state_file()
        frame: dict[str, object] = {"phase": phase.value, "task": task}
        frame.update(extra)
        sf["stack"][-1] = frame
        self._save_stack(sf["stack"], history=sf["history"])

    def _push_state(self, phase: Enum, task: str | None = None,
                    **extra: object) -> None:
        """Push a new frame onto the state stack."""
        sf = self._read_state_file()
        frame: dict[str, object] = {"phase": phase.value, "task": task}
        frame.update(extra)
        sf["stack"].append(frame)
        self._save_stack(sf["stack"], history=sf["history"])

    def _pop_state(self, validate: bool = True) -> dict[str, object]:
        """Pop the top frame and return it."""
        sf = self._read_state_file()
        if len(sf["stack"]) <= 1:
            raise ValueError("Cannot pop the last state frame")
        popped = sf["stack"].pop()
        self._save_stack(sf["stack"], history=sf["history"], validate=validate)
        return popped

    def _append_history(self, entry: dict) -> None:
        """Append an entry to the history log."""
        sf = self._read_state_file()
        sf["history"].append(entry)
        self._save_stack(sf["stack"], history=sf["history"])

    def _save_stack(self, stack: list[dict], history: list[dict] | None = None,
                    validate: bool = True) -> None:
        """Write the state file. Subclasses may override to add side effects.

        validate: no-op in base; subclasses (e.g. PaperAuthoring) use it to
        skip validation when the caller will validate after further changes.
        """
        sf = {"stack": stack, "history": history if history is not None else []}
        self._write_state_file(sf)

    def _init_state(self, idle_phase: Enum) -> None:
        """Initialise state file if absent."""
        if not self.state_path.exists():
            sf = {"stack": [{"phase": idle_phase.value, "task": None}], "history": []}
            self._write_state_file(sf)

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

    def _get_env_optional(self, key: str) -> str | None:
        """Get env var, falling back to .claude/settings.local.json. Returns None if not set."""
        value = os.environ.get(key, "")
        if value:
            return value
        settings_path = self.root / ".claude" / "settings.local.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            value = settings.get("env", {}).get(key, "")
        return value or None

    def _gh_env(self, token_key: str = "GH_TOKEN") -> dict:
        """Build env dict for subprocess calls with the given token.

        Falls back to GH_TOKEN if the requested key isn't set.
        """
        token = self._get_env_optional(token_key)
        if not token and token_key != "GH_TOKEN":
            token = self._get_env_optional("GH_TOKEN")
        if not token:
            raise RuntimeError(f"Neither {token_key} nor GH_TOKEN is set")
        return {**os.environ, "GH_TOKEN": token}

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

    def create_issue(self, title: str, body: str,
                     status: str = "Proposed") -> str:
        """Create a GitHub issue, assign to active milestone and project.

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

        # Add to project and set status
        project_env = self._ensure_project_info()
        item_id = self._add_issue_to_project(
            issue_url, self._get_env("GH_PROJECT_ORG"),
            self._get_env("GH_PROJECT_NUMBER"), project_env)
        self._set_item_status(item_id, status, project_env)

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

    def close_issue(self, issue_url: str) -> None:
        """Set issue to Done, clear workflow labels, close on GitHub."""
        self.set_issue_status(issue_url, "Done")
        self.clear_issue_labels(issue_url)
        env = self._gh_env()
        number = self._get_issue_number(issue_url)
        result = subprocess.run(
            ["gh", "issue", "close", number, "--repo", self.get_repo()],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to close issue: {result.stderr}")

    def reopen_issue(self, issue_url: str) -> None:
        """Reopen a closed issue and set project status to In Progress."""
        env = self._gh_env()
        number = self._get_issue_number(issue_url)
        result = subprocess.run(
            ["gh", "issue", "reopen", number, "--repo", self.get_repo()],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to reopen issue: {result.stderr}")
        self.set_issue_status(issue_url, "In Progress")

    # --- Issue label management ---

    # Subclasses must define their own labels and WORKFLOW_LABELS tuple.
    WORKFLOW_LABELS: tuple[str, ...] = ()

    def set_issue_label(self, issue_url: str, label: str) -> None:
        """Set exactly one workflow label on an issue, removing any others.

        Adds the new label first, then removes old ones — ensures the issue
        always has at least one workflow label (no gap between remove and add).
        """
        if label not in self.WORKFLOW_LABELS:
            raise ValueError(f"Unknown workflow label: {label} (expected one of {self.WORKFLOW_LABELS})")
        repo = self.get_repo()
        env = self._gh_env()
        number = self._get_issue_number(issue_url)

        # Add the new label first
        result = subprocess.run(
            ["gh", "issue", "edit", number, "--repo", repo,
             "--add-label", label],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to add label '{label}': {result.stderr}")

        # Then remove any other workflow labels
        result = subprocess.run(
            ["gh", "issue", "view", number, "--repo", repo,
             "--json", "labels", "--jq", ".labels[].name"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode == 0:
            for existing in result.stdout.strip().split("\n"):
                if existing in self.WORKFLOW_LABELS and existing != label:
                    subprocess.run(
                        ["gh", "issue", "edit", number, "--repo", repo,
                         "--remove-label", existing],
                        capture_output=True, text=True, env=env,
                    )

    def clear_issue_labels(self, issue_url: str) -> None:
        """Remove all workflow labels from an issue."""
        repo = self.get_repo()
        env = self._gh_env()
        number = self._get_issue_number(issue_url)

        result = subprocess.run(
            ["gh", "issue", "view", number, "--repo", repo,
             "--json", "labels", "--jq", ".labels[].name"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode == 0:
            for existing in result.stdout.strip().split("\n"):
                if existing in self.WORKFLOW_LABELS:
                    subprocess.run(
                        ["gh", "issue", "edit", number, "--repo", repo,
                         "--remove-label", existing],
                        capture_output=True, text=True, env=env,
                    )

    # --- Issue body management ---

    # Mode emoji for active step markers (matches label colours)
    MODE_EMOJI = {
        "code": "\U0001f7e2",   # 🟢
        "test": "\U0001f7e2",   # 🟢
        "modify": "\U0001f7e0", # 🟠
    }

    def _get_issue_number(self, issue_url: str) -> str:
        """Extract issue number from URL."""
        _, _, number = self._parse_issue_url(issue_url)
        return number

    def _read_issue_body(self, issue_url: str) -> str:
        """Read an issue's body text."""
        repo = self.get_repo()
        env = self._gh_env()
        number = self._get_issue_number(issue_url)
        result = subprocess.run(
            ["gh", "issue", "view", number, "--repo", repo,
             "--json", "body", "--jq", ".body"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to read issue body: {result.stderr}")
        return result.stdout.rstrip()

    def _write_issue_body(self, issue_url: str, body: str) -> None:
        """Write an issue's body text."""
        repo = self.get_repo()
        env = self._gh_env()
        number = self._get_issue_number(issue_url)
        result = subprocess.run(
            ["gh", "issue", "edit", number, "--repo", repo, "--body", body],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to update issue body: {result.stderr}")

    def add_issue_todos(self, issue_url: str, items: list[str]) -> None:
        """Append unchecked todo items to an issue body."""
        body = self._read_issue_body(issue_url)
        new_items = "\n".join(f"- [ ] {item}" for item in items)
        body = f"{body}\n{new_items}" if body else new_items
        self._write_issue_body(issue_url, body)

    def activate_issue_todo(self, issue_url: str, item: str, mode: str) -> None:
        """Add an unchecked todo with mode-coloured emoji. At most one unchecked todo at a time."""
        emoji = self.MODE_EMOJI.get(mode, "\u26aa")  # fallback: ⚪
        body = self._read_issue_body(issue_url)
        entry = f"- [ ] {emoji} {item}"
        body = f"{body}\n{entry}" if body else entry
        self._write_issue_body(issue_url, body)

    def complete_issue_todo(self, issue_url: str, item: str,
                            commit_sha: str) -> None:
        """Check off a todo item, linking to the commit that completed it.

        Matches unchecked items or previously failed items containing the item text.
        """
        body = self._read_issue_body(issue_url)
        repo = self.get_repo()
        checked = f"- [x] {item} ([{commit_sha[:7]}](https://github.com/{repo}/commit/{commit_sha}))"
        # Find the line containing this item (unchecked, or previously failed)
        for line in body.split("\n"):
            if item in line and ("- [ ] " in line or "\u274c" in line):
                body = body.replace(line, checked, 1)
                self._write_issue_body(issue_url, body)
                return
        raise RuntimeError(f"Todo item not found in issue: {item}")

    def abort_issue_todo(self, issue_url: str, item: str) -> None:
        """Mark a todo as aborted. Leaves it visible in the issue body as history."""
        body = self._read_issue_body(issue_url)
        aborted = f"- [x] \u26d4 {item} (aborted)"  # ⛔
        for line in body.split("\n"):
            if line.startswith("- [ ] ") and item in line:
                body = body.replace(line, aborted, 1)
                self._write_issue_body(issue_url, body)
                return
        raise RuntimeError(f"Todo item not found in issue: {item}")

    def get_active_todo(self, issue_url: str) -> str | None:
        """Return the name of the active (unchecked) todo, or None."""
        body = self._read_issue_body(issue_url)
        for line in body.split("\n"):
            if line.startswith("- [ ] "):
                # Strip emoji prefix if present
                text = line[6:]  # after "- [ ] "
                for emoji in self.MODE_EMOJI.values():
                    if text.startswith(emoji + " "):
                        text = text[len(emoji) + 1:]
                        break
                return text.strip()
        return None

    # --- Sub-issue management ---

    def create_sub_issue(self, parent_url: str, title: str, body: str = "") -> str:
        """Create a sub-issue under a parent issue. Returns the new issue URL."""
        issue_url = self.create_issue(title, body)
        # Link as sub-issue via GitHub's sub-issue API
        parent_number = self._get_issue_number(parent_url)
        child_number = self._get_issue_number(issue_url)
        repo = self.get_repo()
        env = self._gh_env()
        # Use the REST API to add sub-issue relationship
        owner, repo_name, _ = self._parse_issue_url(parent_url)
        result = subprocess.run(
            ["gh", "api", "--method", "POST",
             f"repos/{owner}/{repo_name}/issues/{parent_number}/sub_issues",
             "-f", f"sub_issue_id={child_number}"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            # Sub-issues API may not be available; fall back to mentioning in body
            child_body = self._read_issue_body(issue_url)
            child_body = f"Parent: #{parent_number}\n\n{child_body}" if child_body else f"Parent: #{parent_number}"
            self._write_issue_body(issue_url, child_body)
        return issue_url

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
