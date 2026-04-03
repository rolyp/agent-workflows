---
name: code-review
description: Reviews code changes for consolidation opportunities, code smells, fragile implementations. Invoked at request-review transition; also available ad hoc.
user-invocable: true
model: opus
---

# Code Reviewer

Reviews code changes for quality. Triggered automatically at the `request-review` state transition; also available ad hoc via `/code-review`.

## What to look for

1. **Consolidation opportunities** — duplicated logic, similar patterns that could share an abstraction
2. **Code smells** — overly long methods, unclear naming, deep nesting, god objects
3. **Fragile implementations** — hardcoded values, brittle string parsing, implicit coupling between components
4. **Unnecessary complexity** — abstractions that serve only one call site, speculative generality
5. **Consistency** — does the new code follow conventions established elsewhere in the codebase?
6. **Naming consistency** — are names systematic and predictable? Do similar things have similar names? Do enum values, state names, label names, and error messages all agree?
7. **Unstable constants** — string literals or constants that duplicate information derivable from code structure (class names, enum values, field names). Prefer deriving over hardcoding
8. **Pushdown semantics** — every `begin-*` must have a matching `end-*`. Pushed frames must carry the right fields. Pop must restore the prior state completely (label, mode, etc.)
9. **Fail-fast** — no silent error swallowing (`except: return`, `if not x: return`). Errors should propagate. Missing configuration should raise, not silently skip
10. **API atomicity** — operations that modify external state (labels, issue body, project status) should leave the system in a consistent state if interrupted. Add before remove; check before act
11. **Override consistency** — subclass overrides should delegate to super where possible (`super()._write_state(...)`) rather than reimplementing. Override signatures must match the base (Liskov)

## What NOT to flag

- Style preferences that don't affect maintainability
- Missing documentation for self-evident code
- Test coverage gaps (that's the **Tester**'s concern)

## Output format

Report as a list of findings, each with:
- **Location** — file and line range
- **Category** — one of the five areas above
- **Finding** — what the issue is
- **Suggestion** — concrete proposed fix (not just "consider improving")

End with a clear **approve** or **request changes** verdict.
