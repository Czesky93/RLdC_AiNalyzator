#!/usr/bin/env bash
# stop_tunnel.sh — Zatrzymuje aktywny tunel Cloudflare

PID_FILE="/tmp/cloudflared_tunnel.pid"
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    kill "$PID" 2>/dev/null && echo "✅ Tunel (PID $PID) zatrzymany." || echo "❌ Nie można zabić PID $PID."
    rm -f "$PID_FILE"
else
    # Spróbuj znaleźć po nazwie
    pkill -f "cloudflared tunnel" 2>/dev/null && echo "✅ Tunel zatrzymany." || echo "Tunel nie był uruchomiony."
fi
