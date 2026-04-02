"""Base class for workflow implementations."""

from abc import ABC, abstractmethod

# Phase value for workflow development (shared across implementations)
class Workflow(ABC):
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
