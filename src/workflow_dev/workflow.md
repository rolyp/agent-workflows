# Workflow Development Workflow

Follow whenever working on the agent-workflows submodule. See [GitHub Issues](https://github.com/rolyp/agent-workflows/issues) for task tracking.

## Roles

| Role | Skill | Invocation | Responsibility |
|------|-------|------------|----------------|
| **Developer** | — | — | Human; reviews, approves, directs |
| **Dev Assistant** | [`dev-assistant`](skills/dev-assistant/SKILL.md) (background) | Always active | Drives implementation; orchestrates other skills |
| **Tester** | [`/tester`](skills/tester/SKILL.md) | Inline or subagent | Runs and writes tests for workflow code |
| **User Reviewer** | [`user-review`](skills/user-review/SKILL.md) | Subagent at `request-review` | Expert user; reviews for workflow robustness, transparency, fitness for purpose |
| **Architect Reviewer** | [`architect-review`](skills/architect-review/SKILL.md) | Subagent at `request-review` | Expert architect; reviews for design integrity, clear responsibilities, invariant enforcement |

Both reviewers run as subagents in **separate context** (fresh perspective, no shared development biases). Invoked in parallel at `request-review`.

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

### Testing and CI
- `test.sh` runs mypy + pytest; used by `end-step` and `request-review` gates
- Post-push hook records pending CI run ID in `state.json`
- `request-review` blocks until pending CI run completes; fails if CI is red
- `settings.local.json` env vars (including `GH_TOKEN`) are available to hooks and workflow commands but not to Bash tool calls or background tasks

### Priorities
- Workflow integrity fixes have multiplicative benefit — always address them before feature work, never defer to a backlog

### Host repo integration
- This repo is a submodule of `explorable-viz/literate-execution` at `workflow/agent-workflows/`
- Workflows are *defined* here but *run* from the host project
- Test from the host repo to verify hooks and settings integration

---

## State machine

Enforced by `WorkflowDev` (`workflow.py`) via hooks. State stored in `state.json` (protected from direct manipulation by hooks).

### Pushdown automaton

The state is a stack. The root frame is the task; steps push frames. Idle = root frame only.

```
no task ──begin-task──► idle (root frame, edits locked)
                            │
               begin-refactor <desc> <code|test>
               begin-modify <desc> <rationale...>
                            │
                            ▼
                        step (edits gated by mode)
                            │       │
                        end-step   abort-step
                        (tests     (no tests,
                         must       rolls back)
                         pass)
                            │
                            ▼
                          idle
                   │
              (at root = idle)
                   │
              request-review (tests + CI must pass)
                   │
                   ▼
              review (all locked)
               │          │
       respond-review/  respond-review/
         approve        feedback [items...]
               │          │
               ▼          ▼
           approved      idle (items added as todos)
               │
          end-task
               │
               ▼
          no task (issue closed)
```

### Step modes

Each `begin-step` specifies a mode that gates file access:

| Mode | Label | Emoji | Test files | Code files |
|------|-------|-------|-----------|------------|
| `code` | 🟢 refactor/code | 🟢 | Locked | Editable |
| `test` | 🟢 refactor/test | 🟢 | Editable | Locked |
| `modify` | 🟠 modify | 🟠 | Editable | Editable |

Idle (no step active): all edits locked. Review: all edits locked.

### Editing patterns

Observed patterns and how they map to step modes. These will evolve.

| Pattern | What changes | Step mode | Constraint |
|---------|-------------|-----------|------------|
| **Additive refactoring** | New code + new tests | refactor/code then refactor/test | Nothing existing changes; additions are safe independently |
| **Subtractive refactoring** | Delete unused tests + delete unused code | refactor/test then refactor/code | Deleted tests must already have equivalents covering the new implementation; deleted code must have no remaining callers |
| **Coverage improvement** | New tests only | refactor/test | New tests must pass against existing code — they document what already works |
| **Behaviour removal** | Delete code + delete tests | modify | Removed tests must only test removed code |
| **Behaviour modification** | Change code + change existing tests | modify | Rationale links each test change to the code change |

Notes:
- Additive refactoring currently requires two steps (code then test) due to the code/test firewall. Both steps are individually safe.
- Subtractive refactoring is the exact reverse: test-first (migrate/remove test references), then code (delete unused code). Used when completing a migration to a new implementation.
- Behaviour removal is not backwards-compatible, so requires modify — even though nothing is being *changed*, only eliminated.
- Purely adding tests before a change is a valuable preparatory step: it establishes witnesses that validate subsequent refactorings.

### Commands

| Command | Effect | Gate |
|---------|--------|------|
| `begin-task <issue#>` | Set root frame; issue → In Progress | No active task; no open blockers |
| `begin-refactor <desc> <code\|test>` | Push refactor step | Idle or approved |
| `begin-modify <desc> <rationale...>` | Push modify step | Idle or approved |
| `end-step <commit-message>` | Pop frame; commit; check off todo | Tests must pass |
| `abort-step [reason]` | Pop frame without tests; todo left unchecked | — |
| `suspend-task` | Park task; switch to main | Idle; clean tree |
| `request-review` | Enter review | Idle; tests + CI pass |
| `submit-review <role> <issue#>` | Link review issue as blocker | In review |
| `respond-review/approve` | Transition to approved | In review; all reviews submitted |
| `respond-review/feedback` | Return to idle | In review; all reviews submitted |
| `end-task` | Close issue; merge to main | Phase = approved |

### Failure handling

When `end-step` fails (tests don't pass):
- Step frame stays on stack with `end_step_failed` flag
- New steps blocked until either tests pass (`end-step` retry) or step is aborted (`abort-step`)
- Prevents masking a behaviour change as a refactoring

---

## Phases

### Task selection
- **Developer** names an issue directly, or **Dev Assistant** proposes one from open issues
- On approval: `begin-task <issue-number>`

### Working
- Decompose into steps: `begin-refactor <desc> <code|test>` or `begin-modify <desc> <rationale...>`
- Adding backwards-compatible behaviour is refactoring; changing existing behaviour requires modify with rationale
- `end-step <commit-message>` runs tests, stages, commits, and pops

### Bug fixes
- A bug is existing behaviour; capturing it in a test is refactoring
- Write test asserting **correct** behaviour; decorate with `@unittest.expectedFailure`
- Tests pass (expected failure counts as OK)
- Fix with `begin-modify`; remove decorator

### Review
- `request-review` from idle; spawns **User Reviewer** and **Architect Reviewer** as parallel subagents in separate context
- Both reviewers create review issues with findings as checklists
- `submit-review <role> <issue-number>` links review issue as blocker
- `respond-review/approve` transitions to approved; `respond-review/feedback` returns to idle
- `end-task` requires approved phase

### Review-finding tasks
- Tasks that work through review findings (e.g. address a user review issue) exit via `approve-task` — no nested review needed
- Do not call `request-review`; use `approve-task` (developer approval) then `end-task`
- `approve-task` accepts both refactoring and review phase for this reason

### GitHub integration
- Issue labels track current mode: ⚪ idle, 🟢 refactor/code, 🟢 refactor/test, 🟠 modify, 🟡 review
- Issue body todos track steps: 🟢/🟠 emoji for active, checked with commit link when complete
- Project status: Planned → In Progress → Done
- Milestone: exactly one open milestone required

---

## Design notes

- `GH_TOKEN` / `GH_PROJECT_TOKEN` in `.claude/settings.local.json` (gitignored)
- Hooks gate all tool calls: `pre_edit.py`, `pre_write.py`, `pre_bash.py` (protects state.json)
- `prepare-commit-msg` git hook auto-tags commits with current mode (e.g. `[refactor/code]`)
- `post_push.py` records CI run ID; `request-review` blocks until CI passes
- `state.json` is the local pushdown automaton; GitHub labels + project status are the external view
