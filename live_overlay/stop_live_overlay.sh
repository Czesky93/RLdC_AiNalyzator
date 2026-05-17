#!/usr/bin/env bash
set -e
pkill -f "serve_live_overlay.py" 2>/dev/null || true
echo "Zatrzymano RLdC LIVE overlay."
