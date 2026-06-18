#!/usr/bin/env bash
# Launch Perplexity Council.
# Prefers an isolated .venv; falls back to a user-level install if the
# python3-venv package is unavailable.
set -euo pipefail
cd "$(dirname "$0")"

PY=python3

# 1) If deps already import under system python, just run.
if $PY -c "import PySide6, requests" >/dev/null 2>&1; then
  exec $PY app.py
fi

# 2) Try an isolated virtual environment.
if [ ! -d .venv ]; then
  if $PY -m venv .venv >/dev/null 2>&1; then
    echo "Created virtual environment, installing dependencies…"
    ./.venv/bin/pip install --upgrade pip >/dev/null
    ./.venv/bin/pip install -r requirements.txt
  else
    echo "python3-venv unavailable; installing dependencies to your user site…"
    echo "(Tip: 'sudo apt install python3-venv' enables an isolated install.)"
    $PY -m pip install --user --break-system-packages -r requirements.txt
  fi
fi

if [ -x ./.venv/bin/python ]; then
  exec ./.venv/bin/python app.py
else
  exec $PY app.py
fi
