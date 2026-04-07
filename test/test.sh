#!/bin/bash
# Build and test all workflow implementations.
set -euo pipefail

# Run from repo root
cd "$(dirname "$0")/.."

echo "=== Type checking ==="
python3 -m mypy src/base.py src/dispatch.py src/paper_authoring/workflow.py src/workflow_dev/workflow.py

echo "=== Tests ==="
PYTHONPATH=src python3 -m pytest test/paper_authoring/test.py test/workflow_dev/test.py -v

echo "=== All passed ==="
