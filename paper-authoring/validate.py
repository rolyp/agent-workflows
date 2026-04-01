#!/usr/bin/env python3
"""Validate dashboard / .tex marker consistency.

Runs from project root. Exits 0 with findings on stdout (for hook context).
"""

import glob
import re
import sys

PATHS = {
    "dashboard": "workflow/dashboard.md",
    "structural": "workflow/todo/structural.md",
    "completed": "workflow/todo/completed.md",
}


def files_exist() -> list[str]:
    return [f"Missing: {p}" for p in PATHS.values() if not _file_exists(p)]


def at_most_one_in_progress(dashboard: str) -> list[str]:
    n = len(re.findall("🔵", dashboard))
    if n > 1:
        return [f"Multiple in-progress tasks ({n}) — expected at most 1"]
    return []


def no_orphaned_markers(dashboard: str) -> list[str]:
    if _count_in_progress(dashboard) > 0:
        return []
    errors = []
    if _tex_files_containing("\\selectstart"):
        errors.append("Orphaned \\selectstart markers but no in-progress task")
    if _tex_files_containing("\\reviewstart"):
        errors.append("Orphaned \\reviewstart markers but no in-progress task")
    return errors


def in_progress_has_markers(dashboard: str) -> list[str]:
    if _count_in_progress(dashboard) == 0:
        return []
    if not _tex_files_containing("\\selectstart") and not _tex_files_containing("\\reviewstart"):
        return ["In-progress task but no select/review markers in .tex files"]
    return []


def markers_do_not_coexist() -> list[str]:
    if _tex_files_containing("\\selectstart") and _tex_files_containing("\\reviewstart"):
        return ["Both \\selectstart and \\reviewstart markers present — should not coexist"]
    return []


def progress_counts_consistent(dashboard: str) -> list[str]:
    errors = []
    for kind in ("minor", "structural"):
        match = re.search(
            rf"Completed {kind}.*?\((\d+) of (\d+)\)", dashboard, re.IGNORECASE
        )
        if not match:
            continue
        done = int(match.group(1))
        total = int(match.group(2))
        todo = _count_section_items(dashboard, kind.capitalize())
        expected = done + todo
        if total != expected:
            errors.append(
                f"{kind} count mismatch: header says {done} of {total}, "
                f"but {done} done + {todo} to-do = {expected}"
            )
    return errors


# --- Helpers ---

def _file_exists(path: str) -> bool:
    try:
        open(path).close()
        return True
    except FileNotFoundError:
        return False


def _count_in_progress(dashboard: str) -> int:
    return len(re.findall("🔵", dashboard))


def _tex_files_containing(pattern: str) -> list[str]:
    return [f for f in glob.glob("**/*.tex", recursive=True) if pattern in open(f).read()]


def _count_section_items(dashboard: str, section: str) -> int:
    match = re.search(rf"^### {section}$\n(.*?)(?=^### |\Z)", dashboard, re.MULTILINE | re.DOTALL)
    if not match:
        return 0
    return len(re.findall(r"^- ", match.group(1), re.MULTILINE))


# --- Entry point ---

def validate() -> list[str]:
    missing = files_exist()
    if missing:
        return missing
    dashboard = open(PATHS["dashboard"]).read()
    errors = []
    errors += at_most_one_in_progress(dashboard)
    errors += no_orphaned_markers(dashboard)
    errors += in_progress_has_markers(dashboard)
    errors += markers_do_not_coexist()
    errors += progress_counts_consistent(dashboard)
    return errors


def main() -> None:
    errors = validate()
    if not errors:
        print("Workflow validation: OK")
    else:
        print(f"Workflow validation: {len(errors)} issue(s)")
        for e in errors:
            print(f"  - {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
