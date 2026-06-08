#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit).
#
# Formats the edited Python file and runs the lint + type gate. On any
# violation it prints a concise report to stderr and exits 2, which feeds the
# output back to Claude so it self-corrects before continuing. A clean run
# exits 0 silently.
set -uo pipefail

input="$(cat)"
file="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')"

# Only act on Python files inside this project's source/test trees.
case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Auto-format first (idempotent; never fails the gate on its own).
uv run ruff format -- "$file" >/dev/null 2>&1

problems=""

if ! lint="$(uv run ruff check --fix -- "$file" 2>&1)"; then
  problems+="── ruff check ──"$'\n'"$lint"$'\n\n'
fi

# ty analyses the whole project so cross-file type errors are caught.
if ! types="$(uv run ty check 2>&1)"; then
  problems+="── ty ──"$'\n'"$types"$'\n'
fi

if [ -n "$problems" ]; then
  printf '%s\n' "Quality gate failed for ${file}. Fix these before moving on:" >&2
  printf '%s\n' "$problems" >&2
  exit 2
fi

exit 0
