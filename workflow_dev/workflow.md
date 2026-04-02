# Workflow Development Workflow

Follow whenever working on the agent-workflows submodule. See [dashboard](../dashboard.md) for current state and [GitHub Issues](https://github.com/rolyp/agent-workflows/issues) for task tracking.

## Roles

| Role | Skill | Invocation | Responsibility |
|------|-------|------------|----------------|
| **Developer** | — | — | Human; reviews, approves, directs |
| **Dev Assistant** | [`dev-assistant`](skills/dev-assistant/SKILL.md) (background) | Always active | Drives implementation; orchestrates other skills |
| **Tester** | [`/tester`](skills/tester/SKILL.md) | Inline or subagent | Runs and writes tests for workflow code |
| **Code Reviewer** | [`/code-review`](skills/code-review/SKILL.md) | Forced at `request-review`; also ad hoc | Reviews for consolidation, code smells, fragile implementations |

---

## Conventions

### This document
- Sparse English — avoid articles unless necessary for clarity
- Bullet lists for processes
- Capture every workflow suggestion from **Developer** here

### Branching and commits
- Always work on a branch, never directly on `main`
- Commit after every change
- Open PR when branch is ready; get **Developer** approval before merge
- Commit messages: imperative mood, with `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

### Scope guard
- Edits scoped to `workflow/agent-workflows/` within the parent repo (enforced by `WorkflowDev.check_edit` / `check_write` via hooks)
- When running from the submodule directly: all files are in scope

### Testing
- Run `python3 -m pytest` from the workflow directory before committing
- When modifying a workflow class: update or add tests in the corresponding `test.py`

### Host repo integration
- This repo is a submodule of `explorable-viz/literate-execution` at `workflow/agent-workflows/`
- Workflows are *defined* here but *run* from the host project
- Test from the host repo to verify hooks and settings integration

---

## State machine

Enforced by `WorkflowDev` (`workflow.py`) via hooks. State stored in `state.json`.

```
idle ──start-task──► refactoring (locked)
                         │
              expand-coverage / refactor-code (toggle)
                         │
                    ready-to-modify (tests must pass)
                         │
                         ▼
                     modifying (code + tests unlocked)
                      │      │
          back-to-refactor   request-review
                      │              │
                      ▼              ▼
              refactoring (locked)  review (all locked)
                                     │
                              approve / feedback
                                     │
                                     ▼
                              idle / refactoring
```

### States

| State | Test files | Code files | Description |
|-------|-----------|------------|-------------|
| `idle` | Locked | Locked | No active task |
| `refactoring` (no mode) | Locked | Locked | Must choose sub-mode |
| `refactoring` (`expand-coverage`) | Editable | Locked | Writing behaviour-preservation witnesses |
| `refactoring` (`refactor-code`) | Locked | Editable | Restructuring without behaviour change |
| `modifying` | Editable | Editable | Making behaviour-changing edits |
| `review` | Locked | Locked | **Code Reviewer** examining work |

### Commands

| Command | From | To | Gate |
|---------|------|----|------|
| `start-task <name>` | idle | refactoring | — |
| `expand-coverage` | refactoring | refactoring (expand-coverage) | — |
| `refactor-code` | refactoring | refactoring (refactor-code) | — |
| `ready-to-modify` | refactoring | modifying | Tests must pass |
| `back-to-refactor` | modifying | refactoring (locked) | — |
| `request-review` | modifying | review | — |
| `approve` | review | idle | — |
| `feedback` | review | refactoring (locked) | — |

---

## Phases

### Task selection
- **Developer** names an issue directly, or **Dev Assistant** proposes one from open issues
- On approval: create a working branch; `start-task`

### Refactoring
- Iterative: decompose into small steps, commit after each
- Toggle between `expand-coverage` (tests) and `refactor-code` (code)
- Natural rhythm: write tests first, then refactor
- When code is ready for behaviour change: `ready-to-modify`

### Modifying
- Make behaviour-changing edits (code + tests together)
- May cycle back via `back-to-refactor` for further preparation
- Multiple refactor→modify cycles allowed per task
- When complete: `request-review`

### Review
- **Code Reviewer** examines work for consolidation, code smells, fragile implementations
- `approve` → idle; `feedback` → back to refactoring

---

## Design notes

- `GH_TOKEN` in `.claude/settings.local.json` provides GitHub API access (same pattern as host repo)
- `gh` CLI for all GitHub operations (issues, PRs)
- Issue body contains full specification; code is the implementation
- Hooks (`pre_edit.py`, `pre_write.py`) consult `WorkflowDev` state to gate file operations
- SessionStart hook reports current phase on startup
