#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
: "${RLDC_BACKEND_URL:=http://127.0.0.1:8000}"
: "${RLDC_OVERLAY_PORT:=8099}"
pkill -f "serve_live_overlay.py" 2>/dev/null || true
echo "Start RLdC LIVE overlay sync"
echo "Backend: ${RLDC_BACKEND_URL}"
echo "OBS URL: http://127.0.0.1:${RLDC_OVERLAY_PORT}/index.html"
python3 serve_live_overlay.py
