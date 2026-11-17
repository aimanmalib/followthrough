#!/usr/bin/env bash
# Offline test gate: locked install + full pytest. No network in tests, no secrets needed.
set -euo pipefail
cd "$(dirname "$0")/.."
# Git hooks export GIT_DIR and friends; tests that run git in temp dirs must not inherit them.
while IFS= read -r v; do unset "$v"; done < <(env | sed -n 's/^\(GIT_[A-Z_]*\)=.*/\1/p')
uv sync --frozen
uv run --frozen pytest -q
