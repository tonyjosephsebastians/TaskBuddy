#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_VENV_DIR="$REPO_ROOT/.venv"
REVIEW_VENV_DIR="$REPO_ROOT/.review-pack-venv"
APP_REQUIREMENTS_FILE="$REPO_ROOT/requirements.txt"
REVIEW_REQUIREMENTS_FILE="$REPO_ROOT/requirements-review-pack.txt"
APP_REQUIREMENTS_HASH_FILE="$APP_VENV_DIR/.requirements.sha256"
REVIEW_REQUIREMENTS_HASH_FILE="$REVIEW_VENV_DIR/.requirements.sha256"
DEFAULT_APP_URL="http://localhost:8000"
ISOLATED_APP_URL="http://127.0.0.1:8010"

START_APP=0
SKIP_VIDEO=0
APP_URL=""
STARTED_PID=""
REVIEW_DB_PATH="$REPO_ROOT/docs/review-pack/taskbuddy-runtime.db"

usage() {
  cat <<'EOF'
Usage: ./scripts/build-review-pack.sh [--app-url URL | --start-app] [--skip-video]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-url)
      APP_URL="${2:-}"
      shift 2
      ;;
    --start-app)
      START_APP=1
      shift
      ;;
    --skip-video)
      SKIP_VIDEO=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ $START_APP -eq 1 && -n "$APP_URL" ]]; then
  echo "Use either --start-app or --app-url, not both." >&2
  exit 1
fi

find_python() {
  local candidate
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done

  echo "Python 3.12 or a compatible Python interpreter was not found on PATH." >&2
  return 1
}

ensure_venv() {
  local python_cmd="$1"
  local venv_dir="$2"
  if [[ -d "$venv_dir" ]]; then
    return 0
  fi

  echo "Creating virtual environment in $venv_dir"
  "$python_cmd" -m venv "$venv_dir"
}

resolve_venv_python() {
  local venv_dir="$1"
  if [[ -x "$venv_dir/bin/python" ]]; then
    echo "$venv_dir/bin/python"
    return 0
  fi
  if [[ -x "$venv_dir/Scripts/python.exe" ]]; then
    echo "$venv_dir/Scripts/python.exe"
    return 0
  fi

  echo "Virtual environment python executable was not found in $venv_dir" >&2
  return 1
}

requirements_hash() {
  "$1" - "$@" <<'PY'
import hashlib
import pathlib
import sys

paths = [pathlib.Path(arg) for arg in sys.argv[2:]]
digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
print(hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest())
PY
}

ensure_requirements() {
  local venv_python="$1"
  local hash_file="$2"
  local label="$3"
  shift 3
  local requirement_files=("$@")
  local current_hash stored_hash
  local install_args=("-m" "pip" "install")

  current_hash="$(requirements_hash "$venv_python" "${requirement_files[@]}")"
  stored_hash=""
  if [[ -f "$hash_file" ]]; then
    stored_hash="$(tr -d '[:space:]' < "$hash_file")"
  fi

  if [[ "$current_hash" == "$stored_hash" ]]; then
    return 0
  fi

  echo "Installing $label Python dependencies"
  for file in "${requirement_files[@]}"; do
    install_args+=("-r" "$file")
  done
  "$venv_python" "${install_args[@]}"
  printf '%s\n' "$current_hash" > "$hash_file"
}

wait_for_health() {
  local health_url="$1"
  local timeout_seconds="${2:-40}"
  local deadline=$((SECONDS + timeout_seconds))

  while (( SECONDS < deadline )); do
    if [[ -n "$STARTED_PID" ]] && ! kill -0 "$STARTED_PID" 2>/dev/null; then
      echo "The temporary TaskBuddy app exited before becoming healthy." >&2
      return 1
    fi

    if "$PYTHON_CMD" - "$health_url" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=2) as response:
    if response.status == 200:
        print("ok")
PY
    then
      return 0
    fi
    sleep 1
  done

  echo "TaskBuddy did not become ready at $health_url within the timeout window." >&2
  return 1
}

start_isolated_app() {
  local app_python="$1"
  rm -f "$REVIEW_DB_PATH"

  TASKBUDDY_DEMO_PACING=0 \
  TASKBUDDY_STREAM_STEP_DELAY_MS=0 \
  TASKBUDDY_RETRY_BACKOFF_MS=0 \
  TASKBUDDY_DATABASE_PATH="$REVIEW_DB_PATH" \
  TASKBUDDY_PORT=8010 \
  TASKBUDDY_HOST=127.0.0.1 \
  "$app_python" app.py >/dev/null 2>&1 &
  STARTED_PID=$!

  wait_for_health "$ISOLATED_APP_URL/health"
}

cleanup() {
  if [[ -n "$STARTED_PID" ]] && kill -0 "$STARTED_PID" 2>/dev/null; then
    kill "$STARTED_PID" 2>/dev/null || true
    wait "$STARTED_PID" 2>/dev/null || true
  fi
  rm -f "$REVIEW_DB_PATH"
}

trap cleanup EXIT

cd "$REPO_ROOT"

PYTHON_CMD="$(find_python)"

if [[ $START_APP -eq 1 ]]; then
  ensure_venv "$PYTHON_CMD" "$APP_VENV_DIR"
  APP_VENV_PYTHON="$(resolve_venv_python "$APP_VENV_DIR")"
  ensure_requirements "$APP_VENV_PYTHON" "$APP_REQUIREMENTS_HASH_FILE" "app runtime" "$APP_REQUIREMENTS_FILE"
  start_isolated_app "$APP_VENV_PYTHON"
  RESOLVED_APP_URL="$ISOLATED_APP_URL"
elif [[ -n "$APP_URL" ]]; then
  RESOLVED_APP_URL="${APP_URL%/}"
else
  RESOLVED_APP_URL="$DEFAULT_APP_URL"
fi

ensure_venv "$PYTHON_CMD" "$REVIEW_VENV_DIR"
REVIEW_VENV_PYTHON="$(resolve_venv_python "$REVIEW_VENV_DIR")"
ensure_requirements "$REVIEW_VENV_PYTHON" "$REVIEW_REQUIREMENTS_HASH_FILE" "documentation pack" "$REVIEW_REQUIREMENTS_FILE"

echo "Ensuring Playwright Chromium is installed in .review-pack-venv"
"$REVIEW_VENV_PYTHON" -m playwright install chromium

echo "Generating TaskBuddy documentation pack from $RESOLVED_APP_URL"
GENERATOR_ARGS=("scripts/generate_review_pack.py" "--app-url" "$RESOLVED_APP_URL")
if [[ $SKIP_VIDEO -eq 1 ]]; then
  GENERATOR_ARGS+=("--skip-video")
fi
"$REVIEW_VENV_PYTHON" "${GENERATOR_ARGS[@]}"
