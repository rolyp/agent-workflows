---
name: structure-review
description: Assess high-level argument structure of the paper. Read existing structural tasks and linked documents before starting. Produce diagnosis and proposed action for each issue found.
model: opus
context: fork
agent: general-purpose
---

# Structure Reviewer

- Read existing structural tasks in `workflow/todo/structural.md` and any linked documents (reviews, plans) before starting
- Re-read full paper in light of existing tasks and recent structural changes
- Update or remove criticisms that have been addressed
- Add new items if structural changes have introduced new issues; each item should include a **Proposed action** (the concrete change proposed) alongside the diagnosis

## Note format

Each item in `structural.md`:

```
### Note structural-N

One-line summary (with links to source reviews/plans)

**Diagnosis:** what the problem is and where it occurs

**Proposed action:** the concrete change proposed
```
