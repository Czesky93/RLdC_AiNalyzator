#!/usr/bin/env bash
# ============================================================
# stop_dev.sh — zatrzymuje backend i frontend
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs/dev"

echo "============================================"
echo "  RLdC AiNalyzator — zatrzymywanie procesów"
echo "============================================"

stop_pid_file() {
    local pidfile="$1"
    local label="$2"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "[STOP] $label PID $pid — zatrzymany."
        else
            echo "[INFO] $label PID $pid — już nie działał."
        fi
        rm -f "$pidfile"
    else
        echo "[INFO] $label — brak pliku PID ($pidfile)."
    fi
}

stop_pid_file "$LOG_DIR/backend.pid"  "Backend"
stop_pid_file "$LOG_DIR/frontend.pid" "Frontend"
stop_pid_file "$LOG_DIR/telegram.pid" "Telegram"

# Fallback: zabij po nazwie procesu gdyby PID file nie istniał
echo ""
echo "[FALLBACK] Sprawdzam procesy po porcie..."

if ss -tlnp | grep -q ':8000'; then
    fuser -k 8000/tcp 2>/dev/null && echo "[STOP] Port 8000 zwolniony." || true
else
    echo "[OK] Port 8000 już wolny."
fi

if ss -tlnp | grep -q ':3000'; then
    fuser -k 3000/tcp 2>/dev/null && echo "[STOP] Port 3000 zwolniony." || true
else
    echo "[OK] Port 3000 już wolny."
fi

if pgrep -f "telegram_bot.bot" >/dev/null 2>&1; then
    pkill -f "telegram_bot.bot" 2>/dev/null || true
    echo "[STOP] Telegram bot zatrzymany."
else
    echo "[OK] Telegram bot już zatrzymany."
fi

echo ""
echo "[DONE] Środowisko zatrzymane."
echo "       Uruchom ponownie: ./scripts/start_dev.sh"
echo "============================================"
