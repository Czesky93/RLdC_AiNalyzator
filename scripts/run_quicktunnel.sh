#!/usr/bin/env bash
# =============================================================
# RLdC — Quick Tunnel (fallback gdy brak named tunnel)
# Uruchamia cloudflared quick tunnel i zapisuje żywy URL
# do pliku /tmp/rldc_tunnel_runtime.json
# Serwis: rldc-quicktunnel.service
# =============================================================
set -euo pipefail

RUNTIME_FILE="/tmp/rldc_tunnel_runtime.json"
LOG_FILE="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/quicktunnel.log"
FRONTEND_PORT=3000
API_PORT=8000

mkdir -p "$(dirname "$LOG_FILE")"

cleanup() {
    echo "{\"running\":false,\"frontend_url\":null,\"api_url\":null,\"started_at\":null,\"stopped_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$RUNTIME_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] STOP: quicktunnel zakończony" >> "$LOG_FILE"
    # kill child cloudflared
    kill 0 2>/dev/null || true
}

trap cleanup EXIT SIGTERM SIGINT

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START: uruchamiam cloudflared quick tunnel -> localhost:$FRONTEND_PORT" >> "$LOG_FILE"

# Inicjalny stan
echo "{\"running\":false,\"frontend_url\":null,\"api_url\":null,\"started_at\":null}" > "$RUNTIME_FILE"

# Uruchom cloudflared i parsuj URL z outputu
# cloudflared wypisuje URL w formie: https://xxxxx.trycloudflare.com
cloudflared tunnel --url "http://localhost:$FRONTEND_PORT" 2>&1 | while IFS= read -r line; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $line" >> "$LOG_FILE"

    # Szukaj URL w logach
    if echo "$line" | grep -qE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com'; then
        URL=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com' | head -1)
        NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        echo "{\"running\":true,\"frontend_url\":\"$URL\",\"api_url\":null,\"started_at\":\"$NOW\",\"tunnel_type\":\"quick\"}" > "$RUNTIME_FILE"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] TUNNEL URL: $URL" >> "$LOG_FILE"
        echo "OK: Quick tunnel URL: $URL" >&2
    fi
done
