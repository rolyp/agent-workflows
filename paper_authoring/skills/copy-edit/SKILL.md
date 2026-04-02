---
name: copy-edit
description: Review prose quality, flow, and change markup in LaTeX paper edits. Invoke after each edit during the Edit phase, or as a full-paper review pass.
model: sonnet
---

# Copy Editor

Two modes:

## Inline review (default, after each edit)

Performed by Author Assistant directly — no subagent spawned.

**Validate markup:**
- Change markup should be minimal — e.g. "Yet X" → "While Y, X" should be `\replaced{While Y,}{Yet} X`, not `\replaced{While Y, X}{Yet X}`
- Exception: sometimes useful to include unchanged words to avoid markup becoming too fragmentary (and thus hard to read)
- Prefer `\deleted` or `\added` over `\replaced` when only inserting or removing; prefer `\replaced` over separate `\added`/`\deleted` when one piece of text substitutes for another
- For each `\replaced`, check whether unchanged text could be factored out
- Markup should align to word boundaries — e.g. `\replaced{T}{So t}he` is wrong; prefer `\replaced{The}{So the}`
- Preserve formatting (e.g. `\emph`)

**Review prose:**
- Check flow, redundancy, unclear antecedents, tone shifts

## Full-paper review (on demand)

- Read the full paper; review for low-level textual issues throughout
- Insert `\todo` annotations directly into `.tex` files at each issue found
