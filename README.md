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

Set up a GitHub fine-grained PAT for your repo's org in `.claude/settings.local.json` (gitignored):

```json
{
  "env": {
    "GH_TOKEN": "github_pat_..."
  }
}
```

Required PAT permissions (repository scope):
- **Administration**: Read and write (repo creation)
- **Contents**: Read and write (push code)
- **Issues**: Read and write (task tracking via GitHub Issues)
- **Workflows**: Read and write (if pushing GitHub Actions files)
