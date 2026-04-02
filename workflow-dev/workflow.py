#!/usr/bin/env python3
"""WorkflowDev: manages workflow development activity within the submodule.

Enforces that edits are scoped to the agent-workflows submodule directory.
"""

import sys
from pathlib import Path

# Submodule path relative to project root
SUBMODULE_DIR = "workflow/agent-workflows"


class WorkflowDev:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.submodule_path = project_root / SUBMODULE_DIR

    def check_edit(self, file_path: str) -> tuple[bool, str]:
        """Check whether an edit is allowed during workflow development.

        Only files within the agent-workflows submodule are editable.
        """
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""  # outside project root
        if rel_path.startswith(SUBMODULE_DIR):
            return True, ""
        return False, (
            f"During workflow development, only files in {SUBMODULE_DIR}/ are editable. "
            f"Attempted: {rel_path}"
        )

    def check_write(self, file_path: str) -> tuple[bool, str]:
        """Check whether a write is allowed during workflow development.

        Only new files within the agent-workflows submodule can be created.
        """
        rel_path = self._resolve(file_path)
        if rel_path is None:
            return True, ""  # outside project root
        if not rel_path.startswith(SUBMODULE_DIR):
            return False, (
                f"During workflow development, only files in {SUBMODULE_DIR}/ can be created. "
                f"Attempted: {rel_path}"
            )
        full_path = self.root / rel_path
        if full_path.exists():
            return False, (
                f"Cannot overwrite existing file {rel_path} with Write tool. "
                f"Use Edit tool for modifications."
            )
        return True, ""

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


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: workflow_dev.py check-edit|check-write <file_path>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    file_path = sys.argv[2]
    wd = WorkflowDev(Path.cwd())

    if command == "check-edit":
        allowed, message = wd.check_edit(file_path)
    elif command == "check-write":
        allowed, message = wd.check_write(file_path)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    elif message:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
