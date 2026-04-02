#!/bin/bash
# Build and test all workflow implementations.
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Type checking ==="
python3 -m mypy base.py dispatch.py paper_authoring/workflow.py workflow_dev/workflow.py

echo "=== Tests ==="
python3 -m pytest paper_authoring/test.py workflow_dev/test.py -v

echo "=== All passed ==="
