#!/bin/bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  echo "python3 was not found; install the project environment before scheduling imports." >&2
  exit 127
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$PROJECT_ROOT"

if "$PYTHON" -m nse_strategy_lab.ingestion.cli refresh-actions \
  --data-dir "$PROJECT_ROOT/data"; then
  exit 0
else
  result=$?
  /usr/bin/osascript -e 'display notification "Corporate-actions refresh needs attention. Check the NSE Strategy Lab log and inbox." with title "NSE Strategy Lab"' >/dev/null 2>&1 || true
  exit "$result"
fi
