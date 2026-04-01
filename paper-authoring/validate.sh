#!/bin/bash
# Validate dashboard ↔ .tex marker consistency.
# Runs from project root. Exits 0 with findings on stdout (for hook context).
set -euo pipefail

DASHBOARD="workflow/dashboard.md"
STRUCTURAL="workflow/todo/structural.md"
COMPLETED="workflow/todo/completed.md"
errors=()

# --- Check files exist ---
for f in "$DASHBOARD" "$STRUCTURAL" "$COMPLETED"; do
    if [ ! -f "$f" ]; then
        errors+=("Missing: $f")
    fi
done
if [ ${#errors[@]} -gt 0 ]; then
    printf '%s\n' "${errors[@]}"
    exit 0
fi

# --- Count in-progress tasks (lines with 🔵) ---
in_progress=$(grep -c '🔵' "$DASHBOARD" || true)
if [ "$in_progress" -gt 1 ]; then
    errors+=("Multiple in-progress tasks ($in_progress) — expected at most 1")
fi

# --- Check select/review markers in .tex files ---
select_count=$(grep -rl '\\selectstart' --include='*.tex' . 2>/dev/null | wc -l | tr -d ' ' || true)
review_count=$(grep -rl '\\reviewstart' --include='*.tex' . 2>/dev/null | wc -l | tr -d ' ' || true)

# Markers without in-progress task
if [ "$in_progress" -eq 0 ]; then
    if [ "$select_count" -gt 0 ]; then
        errors+=("Orphaned \\selectstart markers but no in-progress task")
    fi
    if [ "$review_count" -gt 0 ]; then
        errors+=("Orphaned \\reviewstart markers but no in-progress task")
    fi
fi

# In-progress task without markers
if [ "$in_progress" -gt 0 ] && [ "$select_count" -eq 0 ] && [ "$review_count" -eq 0 ]; then
    errors+=("In-progress task but no select/review markers in .tex files")
fi

# Both select and review markers (should not coexist)
if [ "$select_count" -gt 0 ] && [ "$review_count" -gt 0 ]; then
    errors+=("Both \\selectstart and \\reviewstart markers present — should not coexist")
fi

# --- Check progress counts ---
# Count to-do items per section (between ### heading and next ### or end of file)
minor_todo=$(sed -n '/^### Minor$/,/^### /p' "$DASHBOARD" | grep -c '^- ' || true)
structural_todo=$(sed -n '/^### Structural$/,$ p' "$DASHBOARD" | grep -c '^- ' || true)

for kind in minor structural; do
    line=$(grep -i "Completed ${kind}" "$DASHBOARD" || true)
    if [ -n "$line" ]; then
        done_count=$(echo "$line" | sed 's/.*(\([0-9]*\) of .*/\1/')
        total_count=$(echo "$line" | sed 's/.* of \([0-9]*\)).*/\1/')
        if [ "$kind" = "minor" ]; then
            todo_count=$minor_todo
        else
            todo_count=$structural_todo
        fi
        expected_total=$((done_count + todo_count))
        if [ "$total_count" -ne "$expected_total" ] 2>/dev/null; then
            errors+=("${kind} count mismatch: header says $done_count of $total_count, but $done_count done + $todo_count to-do = $expected_total")
        fi
    fi
done

# --- Report ---
if [ ${#errors[@]} -eq 0 ]; then
    echo "Workflow validation: OK"
else
    echo "Workflow validation: ${#errors[@]} issue(s)"
    for e in "${errors[@]}"; do
        echo "  - $e"
    done
fi
exit 0
