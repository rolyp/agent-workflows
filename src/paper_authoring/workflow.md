# Paper Authoring Workflow

Follow whenever agent team is started on paper. See [GitHub Issues](https://github.com/explorable-viz/literate-execution/issues) for task tracking and [workflow diagram](workflow-diagram.md) for visual overview.

## Roles

| Role | Skill | Invocation | Responsibility |
|------|-------|------------|----------------|
| **Author** | — | — | Human; reviews and approves changes |
| **Author Assistant** | [`author-assistant`](skills/author-assistant/SKILL.md) (background) | Always active | Drives editing process; orchestrates other skills |
| **Copy Editor** | [`/copy-edit`](skills/copy-edit/SKILL.md) | Inline or subagent | Reviews prose quality and change markup |
| **Structure Reviewer** | [`/structure-review`](skills/structure-review/SKILL.md) | Foreground subagent | Assesses high-level argument |
| **Librarian** | [`/librarian`](skills/librarian/SKILL.md) | Inline or background | Searches, verifies, adds bibliography entries |

Foreground subagents block **Author Assistant** until they return. Workflow state and invariants are enforced by `PaperAuthoring` (`workflow.py`) via hooks.

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

**Note:** previously approved `\added`/`\deleted`/`\replaced` markup may appear outside edit/review bars — this is expected until the branch is merged.

### Task dependencies

- Structural tasks can form a tree: precursors become indented children
- Work on children before parents
- Keep completed subtasks under parent (strikethrough) until entire parent is **Done**; move whole tree to **Done** together
- **Author** may identify new subtasks at any time
- Task status lives in GitHub Issues. Plans describe strategy, not status

---

## Entry points

Two independent entry points can create review issues before the editing cycle begins. When both apply, run reviewer feedback triage first — external feedback may reshape direction, making some structural/copy-edit findings moot.

### Cold start

For a pre-existing paper not yet using this workflow.

- Invoke **Structure Reviewer** for full-paper initial pass → creates a review issue with findings as checklist
- Optionally invoke **Copy Editor** in full-paper review mode (skip if paper is a rough draft) → creates a review issue with findings as checklist
- Enter triage (`begin-triage`); **Author** iterates through the review issue:
  - **Approve item** → keep in checklist
  - **Merge/split** → edit the checklist
  - **Reject** → strikethrough with reason
- When satisfied: `approve-triage` → promotes accepted items to standalone issues (Planned); closes review issue; enters idle

### Reviewer feedback triage

For a paper (pre-existing or authored using this workflow) that has received external reviews.

- **Author Assistant** reads reviews (e.g. `reviews/*.md`), extracts actionable items
- Creates a review issue with findings as checklist
- Enter triage; **Author** iterates (same loop as cold start above)
- When satisfied: `approve-triage`

---

## Phases

The editing cycle has four phases:

**Task selection:**
- Either **Author** names a task directly (constitutes both identification and approval), or **Author Assistant** identifies a candidate from open issues (prioritising low-risk/small-scope edits) and presents to **Author** for approval
- On approval: run `select`; proceed to Edit
- If **Author** redirects: select another candidate, repeat
- **Author** may also bump a minor issue to structural

**Edit (or dismiss):**
- If proposing to dismiss: invoke **Structure Reviewer** for alternative proposal; present rationale + feedback to author. On **Author** approval: run `complete`
- Otherwise, read proposed resolution (if one exists)
- Apply changes with `\added`/`\deleted`/`\replaced` markup within edit bars
- If scope expands to new passage: run `expand-scope` before editing

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

**Collaborative shortcut:** when **Author** has been actively directing edits in the current session, they may approve and complete a subtask directly without Author review ceremony. Run `complete-collaborative`. Parent task still requires full Author review.


**Structural close-out** (structural issues only):
- Invoke **Copy Editor** on affected paragraphs (max 3 iterations)
- If **Copy Editor** fails to approve: return to **Author**
- If **Copy Editor** approves: invoke **Structure Reviewer** to confirm resolution
- If **Structure Reviewer** confirms: close the task issue; return to Task selection
- If **Structure Reviewer** flags new issues: create new review issue; enter triage
