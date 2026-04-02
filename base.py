"""Base class for workflow implementations."""

import json
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

    def _pop_state(self) -> dict[str, object]:
        """Pop the top frame and return it."""
        stack = self._read_stack()
        if len(stack) <= 1:
            raise ValueError("Cannot pop the last state frame")
        popped = stack.pop()
        self._save_stack(stack)
        return popped

    def _save_stack(self, stack: list[dict]) -> None:
        """Write the stack to disk. Subclasses may override to add side effects."""
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
