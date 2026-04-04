# agent-workflows

Shared workflow definitions for Claude Code agent teams, designed to be consumed as a Git submodule.

## Workflows

- **[paper_authoring](paper_authoring/)** — 4-phase editing workflow for academic papers with human-in-the-loop review. Roles: Author (human), Author Assistant (team lead), Copy Editor, Structure Reviewer, Librarian, Status Tracker.

## Usage

Add as a submodule in your project repo:

```bash
git submodule add https://github.com/rolyp/agent-workflows.git workflow/agent-workflows
```

Copy starter templates into your project's `workflow/` directory:

```bash
cp workflow/agent-workflows/paper_authoring/templates/dashboard.md workflow/
cp -r workflow/agent-workflows/paper_authoring/templates/todo workflow/
```

Point your `CLAUDE.md` at the workflow:

```
Follow `workflow/agent-workflows/paper_authoring/workflow.md` for all paper editing.
```

Configure Claude Code hooks in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 workflow/agent-workflows/paper_authoring/workflow.py startup"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 workflow/agent-workflows/paper_authoring/hooks/pre_edit.py"
          }
        ]
      },
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 workflow/agent-workflows/paper_authoring/hooks/pre_write.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 workflow/agent-workflows/paper_authoring/hooks/post_edit.py"
          }
        ]
      }
    ]
  }
}
```

Set up environment in `.claude/settings.local.json` (gitignored):

```json
{
  "env": {
    "GH_TOKEN": "github_pat_...",
    "GH_PROJECT_ORG": "your-org",
    "GH_PROJECT_NUMBER": "1"
  }
}
```

- `GH_TOKEN`: Fine-grained PAT for the repo's org
- `GH_PROJECT_ORG`: GitHub org that owns the project board
- `GH_PROJECT_NUMBER`: Project number within that org (visible in project URL)

If the project is in a different org from the repo, add `GH_PROJECT_TOKEN` with a PAT that has project access on that org. If omitted, `GH_TOKEN` is used for both.

### Required PAT permissions

Repository scope:
- **Contents**: Read and write (push code)
- **Issues**: Read and write (task tracking via GitHub Issues)
- **Pull requests**: Read and write (PRs)

Organization scope (on `GH_PROJECT_ORG`):
- **Projects**: Read and write (project board status and labels)

### GitHub labels

The workflow tracks state via issue labels. Create them on your repo:

For **paper_authoring**: ⚪ idle, 🟢 edit, 🟣 triage, 🔵 planning, 🟡 author-review, 🟠 closeout

For **workflow_dev**: ⚪ idle, 🟢 refactor/code, 🟢 refactor/test, 🟠 modify, 🟡 review

All labels should use colour `ededed` (light grey) — the emoji provides the visual distinction.

### Git hooks

Install the `prepare-commit-msg` and `post-commit` hooks from `workflow_dev/hooks/` into your `.git/hooks/` directory (or `.git/modules/<submodule>/hooks/` for submodules). These auto-tag commit messages with the current workflow state and record commit SHAs for step tracking.
