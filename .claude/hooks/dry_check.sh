#!/usr/bin/env bash
# Stop hook.
#
# Runs the DRY (copy/paste) detector across the package once Claude finishes a
# turn and surfaces any duplication as a non-blocking warning. It never blocks
# (exit 0 always) to avoid stop-hook loops; it only informs.
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
command -v uv >/dev/null 2>&1 || exit 0
[ -d src/bot ] || exit 0

report="$(uv run pylint --disable=all --enable=duplicate-code src/bot 2>/dev/null)" || true

if printf '%s' "$report" | grep -q 'R0801'; then
  summary="$(printf '%s' "$report" | grep -vE '^\*+ Module|^-+$|^Your code|^$' | head -c 1800)"
  jq -n --arg s "DRY check: duplicate code detected (pylint R0801). Consider extracting shared logic.

$summary" '{"systemMessage": $s, "suppressOutput": true}'
fi

exit 0
