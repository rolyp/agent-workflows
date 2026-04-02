# Paper Authoring Workflow

Follow whenever agent team is started on paper. See [dashboard](../../dashboard.md) for task status and [workflow diagram](workflow-diagram.md) for visual overview.

## Roles

| Role | Type | Concurrency | Responsibility |
|------|------|-------------|----------------|
| **Author** | Human | — | Reviews and approves changes |
| **Author Assistant** | Team lead | Always active | Drives editing process; interacts with **Author** |
| **Copy Editor** | Inline (default) or subagent | — | Reviews prose quality and flow |
| **Structure Reviewer** | Foreground subagent | Blocks team lead | Assesses high-level argument |
| **Librarian** | Inline or background teammate | — | Searches, verifies, adds bibliography entries |

Foreground subagents block **Author Assistant** until they return — no concurrent edits to avoid race conditions. **Librarian** can run inline for simple searches (1–2 entries) or as a background teammate for larger batches.

Workflow state and invariants are enforced by `PaperAuthoring` (`workflow.py`) via hooks — not a role, but the implementation of this workflow as a pushdown automaton.

---

## Conventions

### This document
- Sparse English — avoid articles ("the", "a") unless necessary for clarity
- Bullet lists for processes
- Capture every workflow suggestion from author here
- Bold for agent names and formal statuses (e.g. **In progress**, **Done**)

### Model usage
- Default to **Sonnet** for routine work; prompt **Author** to switch (`/model sonnet`) when transitioning from structural to routine work, and vice versa (`/model opus`)
- **Opus**: collaborative work with **Author** on structural issues (drafting new paragraphs, rethinking argument)
- Per-role model settings are specified in each skill's `SKILL.md` frontmatter

### Branching and commits
- Always work on a branch, never directly on `main`; related tasks can share a working branch
- Commit after every change
- Open PR when branch is ready; get **Author** approval; **Author** or **Author Assistant** merges into `main`
- After merge: strip all `\added`/`\deleted`/`\replaced` markup from affected files (keep new text, remove old)
- Commit messages: imperative mood, with `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

---

## Automation

Implemented in `workflow.py`. Sole owner of all task state and marker coherence. Invoke via CLI commands — never place or remove markers directly.

### Editorial invariants (not mechanically enforceable)

1. **Approved markup outside bars is expected.** Previously approved `\added`/`\deleted`/`\replaced` markup sits outside any bars until the branch is merged — not an inconsistency

### Task dependencies

- Structural tasks can form a tree: precursors become indented children
- Work on children before parents
- Keep completed subtasks under parent (strikethrough) until entire parent is **Done**; move whole tree to **Done** together
- **Author** may identify new subtasks at any time
- Task status lives in the dashboard only. Plans describe strategy, not status

---

## Entry points

Two independent entry points can populate the dashboard before the editing cycle begins. When both apply, run reviewer feedback triage first — external feedback may reshape direction, making some structural/copy-edit findings moot.

### Cold start

For a pre-existing paper not yet using this workflow.

- Invoke **Structure Reviewer** for full-paper initial pass → augments `workflow/todo/structural.md`
- Optionally invoke **Copy Editor** in full-paper review mode (skip if paper is a rough draft) → augments `workflow/todo/minor-issues.md`
- Enter triage (`begin-triage`); **Author** iterates:
  - **Approve item** → add to dashboard via `add-task`
  - **Reclassify** → move between structural/minor via `reclassify`
  - **Revise** → edit the note (change description, merge, split)
- When satisfied: `approve-triage` → enter idle, ready for editing cycle

### Reviewer feedback triage

For a paper (pre-existing or authored using this workflow) that has received external reviews.

- **Author Assistant** reads reviews (e.g. `reviews/*.md`), extracts actionable items
- Classify each as structural or minor; record in `workflow/todo/structural.md` or `workflow/todo/minor-issues.md` with links to source review files
- Enter triage; **Author** iterates (same loop as cold start above)
- When satisfied: `approve-triage`

---

## Author Assistant

Drives the editing process. Owns paper content (`\added`/`\deleted`/`\replaced` markup and prose) but delegates all marker and task-state changes to `PaperAuthoring`.

### Ad hoc edits

**Author** may direct a specific, bounded change to any passage at any time, outside the phase system:
- **Author Assistant** applies `\added`/`\deleted`/`\replaced` markup
- **Author Assistant** uses `open-review` to place review bars, applies markup, **Author** reviews
- No `PaperAuthoring` task involvement
- **Author** reviews proposed change before commit
- If edit turns out to need broader investigation or touches multiple passages, escalate to a task

### Phases

Works in four phases:

**Task selection:**
- Either **Author** names a task directly (constitutes both identification and approval), or **Author Assistant** identifies a candidate from dashboard **To do** (prioritising low-risk/small-scope edits) and presents to **Author** for approval
- On approval: run `select`; proceed to Edit
- If **Author** redirects: select another candidate, repeat
- **Author** may also bump a minor issue to structural

**Edit (or dismiss):**
- If proposing to dismiss: invoke **Structure Reviewer** for alternative proposal; present rationale + feedback to author. On **Author** approval: run `complete`
- Otherwise, read proposed resolution (if one exists)
- Mark up changes using `\added`/`\deleted`/`\replaced`, taking care not to include unchanged text unless helpful for readability
- If scope expands to new passage: run `expand-scope` before editing
- Rebuild and perform **Copy Editor** review inline (markup validation + prose). Reserve subagent invocation for full-paper review passes only

**Author review:**
- Once **Copy Editor** approves, or after 3 iterations:
  - Run `edit-to-review`; present to **Author**
  - If max iterations exceeded: note **Copy Editor** concerns remain
- Do NOT commit until **Author** explicitly approves
- On approval: commit; run `complete`
  - Minor issues: return to Task selection
  - Structural issues: proceed to Structural close-out
- On rejection: revert; return to Task selection
- On **Author** requesting further changes: run `review-to-edit`; return to Edit
- Keep `\added`/`\deleted`/`\replaced` markup until branch is merged

**Collaborative shortcut:** when **Author** has been actively directing edits in the current session, they may approve and complete a subtask directly without Author review ceremony. Run `complete-collaborative`. Parent task still requires full Author review.

**Invariant:** every edit to `.tex` files must pass through Edit (markup + **Copy Editor**) and Author review (review bars + **Author** approval), unless the collaborative shortcut applies. No exceptions, even for edits arising during review.

**Structural close-out** (structural issues only):
- Invoke **Copy Editor** on affected paragraphs (max 3 iterations)
- If **Copy Editor** fails to approve: return to **Author**
- If **Copy Editor** approves: invoke **Structure Reviewer** to confirm resolution and update `workflow/todo/structural.md`
- If **Structure Reviewer** confirms: run `complete-tree`; return to Task selection
- If **Structure Reviewer** flags new issues: run `add`; return to Task selection

Maintains: `.tex` files (paper content only — markers managed by `PaperAuthoring`).

---

## Skills

Role-specific behaviour is defined as [Claude Code Skills](skills/):

| Skill | Role | Invocation |
|-------|------|------------|
| [`/copy-edit`](skills/copy-edit/SKILL.md) | Copy Editor | Inline (default) or subagent for full-paper review |
| [`/structure-review`](skills/structure-review/SKILL.md) | Structure Reviewer | Foreground subagent |
| [`/librarian`](skills/librarian/SKILL.md) | Librarian | Inline or background |

See each skill's `SKILL.md` for detailed instructions. The workflow below specifies *when* each skill is invoked.
