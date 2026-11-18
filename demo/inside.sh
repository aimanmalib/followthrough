#!/bin/sh
# Runs inside the demo image. With arguments: `followthrough <arguments>`. Without: the replayed fixture sweep
# (model reader + drafter), then every draft it saved (nothing is posted: a draft waits for approval).
set -u
if [ "$#" -gt 0 ]; then exec /app/.venv/bin/followthrough "$@"; fi
/app/.venv/bin/followthrough replay --serve -- sweep --fixture --reader model --draft
rc=$?
for draft in /app/out/*/drafts/*.md; do
  [ -f "$draft" ] || continue
  printf '\n--- drafts/%s ---\n\n' "$(basename "$draft")"
  cat "$draft"
  printf '\n'
done
exit "$rc"
