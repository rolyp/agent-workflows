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
| **Status Tracker** | `status_tracker.py` + hooks | Blocks team lead | Owns all task state: dashboard, `.tex` markers, phase coherence |

Foreground subagents and **Status Tracker** block **Author Assistant** until they return — no concurrent edits to avoid race conditions. **Librarian** can run inline for simple searches (1–2 entries) or as a background teammate for larger batches.

---

## Conventions

### This document
- Sparse English — avoid articles ("the", "a") unless necessary for clarity
- Bullet lists for processes
- Capture every workflow suggestion from author here
- Bold for agent names and formal statuses (e.g. **In progress**, **Done**)

### Model usage
- Default to **Sonnet** for routine work; prompt **Author** to switch (`/model sonnet`) when transitioning from structural to routine work, and vice versa (`/model opus`)
- **Opus**: **Structure Reviewer** assessments; collaborative work with **Author** on structural issues (drafting new paragraphs, rethinking argument)
- **Sonnet**: everything else (edits, commits, file ops, inline copy-editing)
- Subagents/teammates must always set `model` explicitly:
  - `model: "sonnet"` — **Librarian**, **Status Tracker**, **Copy Editor** (full-paper review)
  - `model: "opus"` — **Structure Reviewer**

### Branching and commits
- Always work on a branch, never directly on `main`; related tasks can share a working branch
- Commit after every change
- Open PR when branch is ready; get **Author** approval; **Author** or **Author Assistant** merges into `main`
- After merge: strip all `\added`/`\deleted`/`\replaced` markup from affected files (keep new text, remove old)
- Commit messages: imperative mood, with `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

### Build and references
- `workflow/build.sh` must pass after every committed change. Never pipe `make` through `grep` or `head` (SIGPIPE kills pdflatex)
- No unresolved references (`??`). After every build: `grep "LaTeX Warning: Reference\|LaTeX Warning: Citation" main.log` — any output is a blocker

---

## Status Tracker

Implemented in `status_tracker.py`. Sole owner of all task state and marker coherence. **Author Assistant** invokes via CLI commands — never place or remove markers directly.

### State and phases

State is externalised to `workflow/state.json` and reported in the dashboard. See `Phase` enum in `status_tracker.py` for legal phases: `idle`, `selecting`, `edit`, `author-review`, `closeout`.

### Automation

- **Session start**: constructor runs, initialises `state.json` if absent, calls `assert_valid()`; output injected into Claude's context
- **PreToolUse on Edit**: `check_edit()` blocks `.tex` edits during `author-review` (with actionable feedback), warns during `idle`
- **After every mutation**: `assert_valid()` runs automatically

### Mechanical invariants (enforced by `assert_valid`)

- At most one in-progress task
- Markers must match task state
- Select and review bars do not coexist
- Progress counts consistent
- State phase consistent with markers on disk

### Editorial invariants (not mechanically enforceable)

1. **Author Assistant** must not edit `.tex` content outside select bars for the current task
2. **Approved markup outside bars is expected.** Previously approved `\added`/`\deleted`/`\replaced` markup sits outside any bars until the branch is merged — not an inconsistency
3. **Editing outside bars means new work.** Wanting to edit a passage outside bars requires task selection (Phase 1) first

### Task dependencies

- Structural tasks can form a tree: precursors become indented children
- Work on children before parents
- Keep completed subtasks under parent (strikethrough) until entire parent is **Done**; move whole tree to **Done** together
- **Author** may identify new subtasks at any time
- Task status lives in the dashboard only. Plans describe strategy, not status

### Commands

| Command | When | Effect |
|---------|------|--------|
| `select` | Phase 1 approval | Move task to **In progress** with 🔵; add `\selectstart`/`\selectend` around passage; rebuild |
| `expand-scope` | Scope grows during Phase 2 | Add `\selectstart`/`\selectend` around additional passage; rebuild |
| `begin-review` | Phase 2→3 gate | Swap `\selectstart`→`\reviewstart`, `\selectend`→`\reviewend`; update state |
| `return-to-edit` | Phase 3→2 return | Swap `\reviewstart`→`\selectstart`, `\reviewend`→`\selectend`; update state |
| `complete` | Phase 3 approval or Phase 2 dismissal | Remove markers; move task to **Done**; update counts; rebuild |
| `complete-collaborative` | Author actively directed edits | As `complete`, without Phase 3 ceremony |
| `complete-tree` | Phase 4 confirmed | As `complete`, for task + subtree |
| `add` | New task identified | Add task to **To do**; update counts |

---

## Entry points

Two independent entry points can populate the dashboard before the Phase 1–4 cycle begins. When both apply, run reviewer feedback triage first — external feedback may reshape direction, making some structural/copy-edit findings moot.

### Cold start

For a pre-existing paper not yet using this workflow.

- Invoke **Structure Reviewer** for full-paper initial pass → augments `workflow/todo/structural.md`
- **Author** triages each item: approve, dismiss, or defer
- Approved items added to dashboard via **Status Tracker** → `add`
- Optionally invoke **Copy Editor** in full-paper review mode (skip if paper is a rough draft)
- **Author Assistant** collects `\todo` annotations into `workflow/todo/minor-issues.md`
- Minor items added to dashboard via **Status Tracker** → `add`

### Reviewer feedback triage

For a paper (pre-existing or authored using this workflow) that has received external reviews.

- **Author Assistant** reads reviews (e.g. `reviews/*.md`), extracts actionable items
- Classify each as structural or minor
- Present summary to **Author** for triage: approve, reclassify, dismiss, or merge items
- Approved items added to dashboard via **Status Tracker** → `add`; structural items also recorded in `workflow/todo/structural.md` with links to source review files

---

## Author Assistant

Drives the editing process. Owns paper content (`\added`/`\deleted`/`\replaced` markup and prose) but delegates all marker and task-state changes to **Status Tracker**.

### Ad hoc edits

**Author** may direct a specific, bounded change to any passage at any time, outside the phase system. **Author Assistant** applies `\added`/`\deleted`/`\replaced` markup but no select/review bars and no **Status Tracker** involvement. The **Author**'s explicit direction constitutes approval; commit directly. If the edit turns out to need broader investigation or touches multiple passages, escalate to a task.

### Phases

Works in four phases:

**Phase 1 — Task selection:**
- Either **Author** names a task directly (constitutes both identification and approval), or **Author Assistant** identifies a candidate from dashboard **To do** (prioritising low-risk/small-scope edits) and presents to **Author** for approval
- On approval: invoke **Status Tracker** → `select`; proceed to Phase 2
- If **Author** redirects: select another candidate, repeat
- **Author** may also bump a minor issue to structural

**Phase 2 — Edit (or dismiss):**
- If proposing to dismiss: invoke **Structure Reviewer** for alternative proposal; present rationale + feedback to author. On **Author** approval: invoke **Status Tracker** → `complete`
- Otherwise, read proposed resolution (if one exists)
- Mark up changes using `\added`/`\deleted`/`\replaced`, taking care not to include unchanged text unless helpful for readability
- If scope expands to new passage: invoke **Status Tracker** → `expand-scope` before editing
- Rebuild and perform **Copy Editor** review inline (markup validation + prose). Reserve subagent invocation for full-paper review passes only

**Phase 3 — Author review:**
- Once **Copy Editor** approves, or after 3 iterations:
  - Invoke **Status Tracker** → `begin-review`; present to **Author**
  - If max iterations exceeded: note **Copy Editor** concerns remain
- Do NOT commit until **Author** explicitly approves
- On approval: commit; invoke **Status Tracker** → `complete`
  - Minor issues: return to Phase 1
  - Structural issues: proceed to Phase 4
- On rejection: revert; return to Phase 1
- On **Author** requesting further changes: invoke **Status Tracker** → `return-to-edit`; return to Phase 2
- Keep `\added`/`\deleted`/`\replaced` markup until branch is merged

**Collaborative shortcut:** when **Author** has been actively directing edits in the current session, they may approve and complete a subtask directly without Phase 3 ceremony. Invoke **Status Tracker** → `complete-collaborative`. Parent task still requires full Phase 3.

**Invariant:** every edit to `.tex` files must pass through Phase 2 (markup + **Copy Editor**) and Phase 3 (review bars + **Author** approval), unless the collaborative shortcut applies. No exceptions, even for edits arising during review.

**Phase 4 — Structural close-out** (structural issues only):
- Invoke **Copy Editor** on affected paragraphs (max 3 iterations)
- If **Copy Editor** fails to approve: return to **Author**
- If **Copy Editor** approves: invoke **Structure Reviewer** to confirm resolution and update `workflow/todo/structural.md`
- If **Structure Reviewer** confirms: invoke **Status Tracker** → `complete-tree`; return to Phase 1
- If **Structure Reviewer** flags new issues: invoke **Status Tracker** → `add`; return to Phase 1

Maintains: `.tex` files (paper content only — markers managed by **Status Tracker**).

---

## Copy Editor

Two modes:

**Inline review** (default, after each edit):
- Performed by **Author Assistant** directly — no subagent spawned
- **Validate markup:**
  - Change markup should be minimal — e.g. "Yet X" → "While Y, X" should be `\replaced{While Y,}{Yet} X`, not `\replaced{While Y, X}{Yet X}`
  - Exception: sometimes useful to include unchanged words to avoid markup becoming too fragmentary (and thus hard to read)
  - Prefer `\deleted` or `\added` over `\replaced` when only inserting or removing; prefer `\replaced` over separate `\added`/`\deleted` when one piece of text substitutes for another
  - For each `\replaced`, check whether unchanged text could be factored out
  - Markup should align to word boundaries — e.g. `\replaced{T}{So t}he` is wrong; prefer `\replaced{The}{So the}`
  - Preserve formatting (e.g. `\emph`)
- Review prose: check flow, redundancy, unclear antecedents, tone shifts

**Full-paper review** (on demand, subagent):
- Spawned as subagent; reads full paper; reviews for low-level textual issues throughout
- Insert `\todo` annotations directly into `.tex` files at each issue found

Maintains: inline `\todo` annotations in `.tex` files.

---

## Structure Reviewer

- Read existing structural tasks in `workflow/todo/structural.md` and any linked documents (reviews, plans) before starting
- Re-read full paper in light of existing tasks and recent structural changes
- Update or remove criticisms that have been addressed
- Add new items if structural changes have introduced new issues; each item should include a **Proposed action** (the concrete change proposed) alongside the diagnosis

Maintains: `workflow/todo/structural.md` (authoritative source for both diagnosis and proposed action).

---

## Librarian

- Search existing `.bib` files for entries
- When not found: search online, verify DOI is genuine (not hallucinated)
- Add verified entries to a staging `.bib` file in standard BibTeX format
- Commit alongside edit that first cites entry
- After author imports into Zotero and re-exports primary `.bib`, clear staging file (leave comment header)
- Never fabricate citations — if paper cannot be found, report back rather than guessing

Maintains: staging `.bib` file.
