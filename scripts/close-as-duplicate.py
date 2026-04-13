#!/usr/bin/env python3
"""Close an issue as duplicate of another. Developer-only.

Adds a comment explaining why, then closes with GitHub's duplicate reason.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_dev.workflow import WorkflowDev

if len(sys.argv) < 3:
    print("Usage: close-as-duplicate.py <issue-number> <duplicate-of>", file=sys.stderr)
    raise SystemExit(1)

issue_number = sys.argv[1]
duplicate_of = sys.argv[2]

wd = WorkflowDev(Path("."))
repo = wd.get_repo()
issue_url = f"https://github.com/{repo}/issues/{issue_number}"

# Comment before closing
env = wd._gh_env()
subprocess.run(
    ["gh", "issue", "comment", issue_number, "--repo", repo,
     "--body", f"Duplicate of #{duplicate_of}."],
    capture_output=True, text=True, env=env,
)

# Close as duplicate
subprocess.run(
    ["gh", "issue", "close", issue_number, "--repo", repo,
     "--reason", "duplicate", "--duplicate-of", duplicate_of],
    capture_output=True, text=True, env=env,
)

# Update project status
try:
    wd.set_issue_status(issue_url, "Rejected")
    wd.clear_issue_labels(issue_url)
except Exception as e:
    print(f"Warning: could not update project status: {e}", file=sys.stderr)

print(f"Issue #{issue_number} closed as duplicate of #{duplicate_of}.")
