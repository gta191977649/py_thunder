#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-portable}"

shift || true

python "$ROOT_DIR/scripts/build_release.py" --mode "$MODE" "$@"
