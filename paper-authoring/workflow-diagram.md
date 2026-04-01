# Paper Authoring Workflow

## Overview

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef phase fill:#eceff1,stroke:#546e7a,stroke-width:3px,color:#263238
    classDef entry fill:#fce4ec,stroke:#c62828,stroke-width:2px,color:#b71c1c

    CS["Cold Start"]:::entry
    RFT["Reviewer Feedback<br/>Triage"]:::entry

    P1["Task Selection"]:::phase
    P2["Edit / Dismiss"]:::phase
    P3["Author Review"]:::phase
    P4["Structural Close-out"]:::phase

    CS -- "/ populate dashboard" --> P1
    RFT -- "/ populate dashboard" --> P1
    P1 -- "[approve]" --> P2
    P1 -- "[reject] / select another" --> P1
    P1 -- "[bump] / move to structural" --> P1
    P2 -- "[edit complete]" --> P3
    P2 -- "[dismissed] / remove todo" --> P1
    P3 -- "[approve]" --> P4
    P3 -- "[approve, minor issue]" --> P1
    P3 -- "[reject] / revert" --> P1
    P3 -- "[further changes] / 🟥→🟦" --> P2
    P4 -- "[confirmed]" --> P1
    P4 -- "[new issues] / add tasks" --> P1
    P4 -- "[copy-edit failed] / return to author" --> P3
```

Legend: 🟦 Author-assistant 🟢 Human author 🟥 Entry point. See [entry points](#entry-points) and [phase details](#phase-details) below.

---

## Entry points

### Cold Start

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef structure fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c
    classDef copyeditor fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c

    SR["Full-paper<br/>structural review"]:::structure
    TRIAGE_S{"Triage"}:::author
    POLISHED{"Paper polished<br/>enough?"}:::author
    CE["Full-paper<br/>copy-edit review"]:::copyeditor
    COLLECT["Collect todos into<br/>minor-issues.md"]:::assistant

    SR -- "/ produce structural.md" --> TRIAGE_S
    TRIAGE_S -- "[approve] / add to dashboard" --> POLISHED
    TRIAGE_S -- "[dismiss]" --> POLISHED
    POLISHED -- "[yes]" --> CE
    CE -- "/ insert \todo annotations" --> COLLECT
    COLLECT -- "/ add to dashboard" --> EXIT(("→ Phase 1"))
    POLISHED -- "[no]" --> EXIT
```

### Reviewer Feedback Triage

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1

    READ["Read reviews;<br/>extract actionable items;<br/>classify structural / minor"]:::assistant
    TRIAGE{"Triage"}:::author

    READ -- "/ present summary" --> TRIAGE
    TRIAGE -- "[approve] / add to dashboard" --> EXIT(("→ Phase 1"))
    TRIAGE -- "[reclassify]" --> TRIAGE
    TRIAGE -- "[dismiss]" --> TRIAGE
    TRIAGE -- "[merge items]" --> TRIAGE
```

---

## Phase details

### Phase 1 — Task Selection

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1

    SELECT["Select candidate<br/>from todos / minor-issues"]:::assistant
    D1{"Approve?"}:::author

    SELECT -- "/ add 🟦 bar" --> D1
    D1 -- "[approve]" --> EXIT(("→ Phase 2"))
    D1 -- "[reject]" --> SELECT
    D1 -- "[bump]" --> SELECT
```

### Phase 2 — Edit / Dismiss

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef copyeditor fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c
    classDef structure fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c

    DISMISS{"Dismiss?"}:::assistant

    subgraph EDIT_PATH [Edit path]
        direction TB
        NOTE["All edits within 🟦 bars"]:::assistant
        EDIT["Apply markup"]:::assistant
        CE["Review passage"]:::copyeditor
        CEOK{"Approve?"}:::copyeditor
        MAXCK{"n ≥ 3?"}:::copyeditor
        NOTE -.-> EDIT
        EDIT --> CE
        CE -- "/ send sentence + context" --> CEOK
        CEOK -- "[flag] / n++" --> MAXCK
        MAXCK -- "[no] / revise" --> CE
    end

    subgraph DISMISS_PATH [Dismiss path]
        SRCHECK["Check proposal"]:::structure
        DAUTH{"Approve<br/>dismissal?"}:::author
        SRCHECK -- "/ present rationale +<br/>feedback" --> DAUTH
    end

    DISMISS -- "[no]" --> EDIT
    DISMISS -- "[yes]" --> SRCHECK

    CEOK -- "[approve]" --> EXIT_EDIT(("→ Phase 3"))
    MAXCK -- "[yes]" --> EXIT_EDIT
    DAUTH -- "[approve] / remove todo" --> EXIT_DISMISS(("→ Phase 1"))
    DAUTH -- "[reject]" --> EXIT_DISMISS
```

### Phase 3 — Author Review

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1

    PRESENT["Replace 🟦 bar<br/>with 🟥 bar"]:::assistant
    D3{"Approve?"}:::author

    PRESENT --> D3
    D3 -- "[approve, structural]" --> EXIT_S(("→ Phase 4"))
    D3 -- "[approve, minor]" --> EXIT_M(("→ Phase 1"))
    D3 -- "[reject] / revert" --> EXIT_R(("→ Phase 1"))
    D3 -- "[further changes]<br/>/ 🟥→🟦" --> EXIT_E(("→ Phase 2"))
```

### Phase 4 — Structural Close-out

```mermaid
flowchart TD
    classDef author fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef assistant fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef copyeditor fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c
    classDef structure fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c

    CE["Copy-edit affected<br/>paragraphs"]:::copyeditor
    CEOK{"Approve?"}:::copyeditor
    MAXCK{"n ≥ 3?"}:::copyeditor
    REVISE["Revise"]:::assistant
    SR["Re-read full paper;<br/>update review notes +<br/>task list"]:::structure
    SROK{"Confirmed?"}:::structure

    CE --> CEOK
    CEOK -- "[approve]" --> SR
    CEOK -- "[flag] / n++" --> MAXCK
    MAXCK -- "[no]" --> REVISE --> CE
    MAXCK -- "[yes]" --> EXIT_AUTHOR(("→ Author"))
    SR --> SROK
    SROK -- "[confirmed] / move to Done" --> EXIT_DONE(("→ Phase 1"))
    SROK -- "[new issues] / add tasks" --> EXIT_NEW(("→ Phase 1"))
```

---

**Edge notation:** `[guard] / action`. Build implicit after any document change.

**Status Tracker operations** (all marker/state changes go through Status Tracker):
- **select**: add 🔵 + 🟦 bars
- **expand-scope**: add 🟦 bars around additional passage
- **begin-review**: 🟦→🟥 (Phase 2→3 gate)
- **return-to-edit**: 🟥→🟦 (Phase 3→2 return)
- **complete** / **complete-collaborative**: remove bars, move to Done
- **validate**: check dashboard ↔ `.tex` consistency (session resume)

**Markers:** 🟦 bar = `\selectstart`/`\selectend` (editing precondition). 🟥 bar = `\reviewstart`/`\reviewend` (awaiting approval). Approved markup outside bars is expected.

**Colours:** 🟦 Author-assistant 🟢 Human author 🟧 Copy-editor 🟪 Structure reviewer
