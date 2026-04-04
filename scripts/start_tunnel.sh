#!/usr/bin/env bash
# start_tunnel.sh — Uruchamia Cloudflare Quick Tunnel dla panelu RLdC
# Nie wymaga logowania ani konta Cloudflare.
# URL jest losowy przy każdym uruchomieniu (trycloudflare.com).
# Użycie: bash scripts/start_tunnel.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/.."
ENV_FILE="$ROOT/.env"

CLOUDFLARED="${HOME}/.local/bin/cloudflared"
if ! command -v cloudflared &>/dev/null; then
    if [[ -x "$CLOUDFLARED" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "❌ cloudflared nie znaleziony. Pobierz: https://github.com/cloudflare/cloudflared/releases"
        exit 1
    fi
fi

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
LOG_FILE="/tmp/cloudflared_tunnel.log"

echo "🌐 Uruchamianie tunelu Cloudflare → http://localhost:${FRONTEND_PORT}"
echo "   Log: $LOG_FILE"

# Uruchom tunel w tle
cloudflared tunnel --url "http://localhost:${FRONTEND_PORT}" --no-autoupdate > "$LOG_FILE" 2>&1 &
TUNNEL_PID=$!
echo "$TUNNEL_PID" > /tmp/cloudflared_tunnel.pid

# Czekaj na URL w logu (max 15 sekund)
TUNNEL_URL=""
for i in $(seq 1 30); do
    sleep 0.5
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -1)
    if [[ -n "$TUNNEL_URL" ]]; then
        break
    fi
done

if [[ -z "$TUNNEL_URL" ]]; then
    echo "❌ Nie udało się uzyskać URL tunelu. Sprawdź log: $LOG_FILE"
    kill "$TUNNEL_PID" 2>/dev/null
    exit 1
fi

echo ""
echo "✅ Tunel aktywny!"
echo "   Publiczny URL panelu: $TUNNEL_URL"
echo "   PID tunelu:           $TUNNEL_PID"
echo ""
echo "📱 Wpisz ten adres na iPhonie lub udostępnij komukolwiek:"
echo "   $TUNNEL_URL"
echo ""

# Zaktualizuj .env
if [[ -f "$ENV_FILE" ]]; then
    # Zamień lub dodaj CLOUDFLARE_TUNNEL_URL
    if grep -q "^CLOUDFLARE_TUNNEL_URL=" "$ENV_FILE"; then
        sed -i "s|^CLOUDFLARE_TUNNEL_URL=.*|CLOUDFLARE_TUNNEL_URL=$TUNNEL_URL|" "$ENV_FILE"
    else
        echo "CLOUDFLARE_TUNNEL_URL=$TUNNEL_URL" >> "$ENV_FILE"
    fi
    echo "   (.env zaktualizowany)"
fi

echo "   Aby zatrzymać tunel: kill $TUNNEL_PID"
echo "   lub: bash scripts/stop_tunnel.sh"
