#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export RLDC_BACKEND_URL="http://127.0.0.1:8000"
export RLDC_OVERLAY_PORT="8099"
exec python3 serve_live.py
