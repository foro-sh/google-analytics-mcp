#!/usr/bin/env sh
# The upstream sync's smoke test: relock after the bump, serve, list the tools.
set -eu
uv lock
uv sync --frozen
uv run python scripts/write_manifest.py
uv run python scripts/smoke.py
