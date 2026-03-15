#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
REQUIREMENTS_FILE="$REPO_ROOT/requirements.txt"
REQUIREMENTS_HASH_FILE="$VENV_DIR/.requirements.sha256"
APP_URL="http://localhost:8000"

find_python() {
  local candidate
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" --version >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done

  echo "Python 3.12 or a compatible Python interpreter was not found on PATH." >&2
  return 1
}

ensure_venv() {
  local python_cmd="$1"
  if [[ -d "$VENV_DIR" ]]; then
    return 0
  fi

  echo "Creating virtual environment in $VENV_DIR"
  "$python_cmd" -m venv "$VENV_DIR"
}

resolve_venv_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "$VENV_DIR/bin/python"
    return 0
  fi
  if [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
    echo "$VENV_DIR/Scripts/python.exe"
    return 0
  fi

  echo "Virtual environment python executable was not found." >&2
  return 1
}

resolve_activate_script() {
  if [[ -f "$VENV_DIR/bin/activate" ]]; then
    echo "$VENV_DIR/bin/activate"
    return 0
  fi
  if [[ -f "$VENV_DIR/Scripts/activate" ]]; then
    echo "$VENV_DIR/Scripts/activate"
    return 0
  fi

  echo "Virtual environment activation script was not found." >&2
  return 1
}

requirements_hash() {
  "$1" - "$REQUIREMENTS_FILE" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

cd "$REPO_ROOT"

PYTHON_CMD="$(find_python)"
ensure_venv "$PYTHON_CMD"
VENV_PYTHON="$(resolve_venv_python)"
ACTIVATE_SCRIPT="$(resolve_activate_script)"

CURRENT_HASH="$(requirements_hash "$VENV_PYTHON")"
STORED_HASH=""
if [[ -f "$REQUIREMENTS_HASH_FILE" ]]; then
  STORED_HASH="$(tr -d '[:space:]' < "$REQUIREMENTS_HASH_FILE")"
fi

if [[ "$CURRENT_HASH" != "$STORED_HASH" ]]; then
  echo "Installing Python dependencies from requirements.txt"
  "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"
  printf '%s\n' "$CURRENT_HASH" > "$REQUIREMENTS_HASH_FILE"
fi

# shellcheck source=/dev/null
source "$ACTIVATE_SCRIPT"

echo "Starting TaskBuddy at $APP_URL"
python app.py
