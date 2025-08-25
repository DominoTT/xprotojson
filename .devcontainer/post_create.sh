#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/workspaces/xprotojson"
cd "$PROJECT_ROOT"

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip

if [ -f "app/requirements.txt" ]; then
  pip install -r app/requirements.txt
fi

if [ -f "python/requirements.txt" ]; then
  pip install -r python/requirements.txt
fi

if [ -f "sample/requirements.txt" ]; then
  pip install -r sample/requirements.txt
fi

echo "postCreate completed: dependencies installed."


