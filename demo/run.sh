#!/usr/bin/env bash
# One-command demo: build the image, run the synthetic fixture sweep (model reader + drafter) with every model
# answer replayed from fixtures/recorded/, print the digest. Needs Docker only: no key, no network at run time.
# Extra arguments run `followthrough <arguments>` instead, e.g. `demo/run.sh replay --serve -- sweep --fixture --reader model --lang ms`.
# The image is removed afterwards (set FOLLOWTHROUGH_DEMO_KEEP=1 to keep it for a second run).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null 2>&1 || { echo "demo: Docker is required" >&2; exit 2; }
tag="followthrough-demo:run-$$"
cleanup() { [ "${FOLLOWTHROUGH_DEMO_KEEP:-0}" = 1 ] || docker rmi -f "$tag" >/dev/null 2>&1 || true; }
trap cleanup EXIT
echo "demo: building $tag" >&2
docker build --quiet --file demo/Dockerfile --tag "$tag" . >/dev/null
echo "demo: running offline (no network, no key)" >&2
docker run --rm --network none --cpus=1 --memory=1g --read-only \
  --tmpfs /tmp:mode=1777 --tmpfs /app/state:mode=1777 --tmpfs /app/out:mode=1777 --tmpfs /app/.openminion:mode=1777 \
  "$tag" "$@"
