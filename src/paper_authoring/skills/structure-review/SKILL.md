---
name: structure-review
description: Assess high-level argument structure of the paper. Read existing structural tasks and linked documents before starting. Produce diagnosis and proposed action for each issue found.
model: opus
context: fork
agent: general-purpose
---

# Structure Reviewer

- Read existing structural issues (if any) before starting
- Re-read full paper in light of existing issues and recent structural changes
- Produce findings as a single GitHub Issue via `workflow.py create-issue`

## Output

A single issue titled "Structure Review" with findings as a checklist:

```markdown
- [ ] **One-line summary.** Diagnosis: what the problem is. Proposed action: the concrete change proposed.
- [ ] **Another finding.** Diagnosis: ... Proposed action: ...
```

During triage, the author promotes accepted items to standalone Planned issues.
