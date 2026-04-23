#!/usr/bin/env bash
# ============================================================
# start_dev.sh — uruchamia backend i frontend RLdC AiNalyzator
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs/dev"
LAN_IP=$(hostname -I | awk '{print $1}')

mkdir -p "$LOG_DIR"

# Blokada równoległych uruchomień (eliminuje wyścigi i duplikaty procesów)
exec 9>"$LOG_DIR/.start_dev.lock"
if ! flock -n 9; then
    echo "[INFO] start_dev.sh już działa w innej sesji — pomijam równoległy start."
    exit 0
fi

start_detached() {
    local pidfile="$1"
    local logfile="$2"
    shift 2

    setsid "$@" > "$logfile" 2>&1 < /dev/null &
    local pid=$!
    echo "$pid" > "$pidfile"
    sleep 1

    if kill -0 "$pid" 2>/dev/null; then
        echo "[OK] PID: $pid"
    else
        echo "[ERR] Proces zakończył się tuż po starcie. Sprawdź log: $logfile"
        return 1
    fi
}

echo "============================================"
echo "  RLdC AiNalyzator — start środowiska dev"
echo "============================================"

# ---- Sprawdź, czy procesy już działają ----
if ss -tlnp | grep -q ':8000'; then
    echo "[INFO] Backend już działa na :8000 — pomijam uruchomienie."
else
    echo "[START] Uruchamiam backend (uvicorn :8000)..."
    cd "$PROJECT_DIR"
    start_detached "$LOG_DIR/backend.pid" "$LOG_DIR/backend.log" \
        .venv/bin/python -m uvicorn backend.app:app \
        --host 0.0.0.0 --port 8000
fi

if systemctl --user is-enabled --quiet rldc-telegram 2>/dev/null; then
    if ! systemctl --user is-active --quiet rldc-telegram 2>/dev/null; then
        echo "[INFO] Telegram service jest enabled, ale nieaktywny — uruchamiam rldc-telegram.service."
        systemctl --user start rldc-telegram 2>/dev/null || true
        sleep 1
    fi
    service_pid=$(systemctl --user show -p MainPID --value rldc-telegram 2>/dev/null || echo "")
    echo "[INFO] Telegram bot zarządzany przez systemd (rldc-telegram.service, PID=${service_pid:-?}) — pomijam lokalny start."

    # Usuń ewentualne lokalne duplikaty i zostaw tylko proces serwisowy.
    mapfile -t tg_pids < <(pgrep -f "telegram_bot.bot" || true)
    for pid in "${tg_pids[@]:-}"; do
        [[ -z "${pid:-}" ]] && continue
        if [[ -n "${service_pid:-}" && "$pid" != "$service_pid" ]]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 1

    if [[ -n "${service_pid:-}" ]]; then
        echo "$service_pid" > "$LOG_DIR/telegram.pid"
    fi
else
    telegram_count=$(pgrep -fc "telegram_bot.bot" || true)
    if [[ "${telegram_count:-0}" -gt 1 ]]; then
        echo "[WARN] Wykryto ${telegram_count} procesy Telegram bota — czyszczę duplikaty."
        pkill -f "telegram_bot.bot" 2>/dev/null || true
        sleep 1
        telegram_count=0
    fi

    if [[ "${telegram_count:-0}" -eq 1 ]]; then
        echo "[INFO] Telegram bot już działa — pomijam uruchomienie."
        pgrep -fo "telegram_bot.bot" > "$LOG_DIR/telegram.pid" || true
    else
        echo "[START] Uruchamiam Telegram bot..."
        cd "$PROJECT_DIR"
        start_detached "$LOG_DIR/telegram.pid" "$LOG_DIR/telegram.log" \
            .venv/bin/python -u -m telegram_bot.bot
    fi
fi

if ss -tlnp | grep -q ':3000'; then
    echo "[INFO] Frontend już działa na :3000 — pomijam uruchomienie."
else
    cd "$PROJECT_DIR/web_portal"
    if [[ -f ".next/BUILD_ID" ]]; then
        echo "[START] Uruchamiam frontend produkcyjny (next start :3000)..."
        start_detached "$LOG_DIR/frontend.pid" "$LOG_DIR/frontend.log" \
            npx next start --hostname 0.0.0.0 --port 3000
    else
        echo "[START] Brak buildu — uruchamiam frontend dev (next dev :3000)..."
        start_detached "$LOG_DIR/frontend.pid" "$LOG_DIR/frontend.log" \
            npx next dev --hostname 0.0.0.0 --port 3000
    fi
fi

# ---- Poczekaj na start ----
echo ""
echo "[CZEKAM] Daję 10 sekund na pełne uruchomienie..."
sleep 10

# ---- Weryfikacja ----
echo ""
echo "============================================"
echo "  Weryfikacja dostępności"
echo "============================================"

check_url() {
    local url="$1"
    local label="$2"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "ERR")
    if [[ "$code" == "200" ]]; then
        echo "  ✅ $label → $url [$code]"
    else
        echo "  ❌ $label → $url [$code]"
    fi
}

check_url "http://localhost:8000/"            "Backend  (localhost)"
check_url "http://localhost:3000/"            "Frontend (localhost)"
check_url "http://$LAN_IP:8000/"             "Backend  (LAN)"
check_url "http://$LAN_IP:3000/"             "Frontend (LAN)"

if pgrep -f "telegram_bot.bot" >/dev/null 2>&1; then
    echo "  ✅ Telegram bot — DZIAŁA"
else
    echo "  ❌ Telegram bot — ZATRZYMANY (sprawdź logs/dev/telegram.log)"
fi

echo ""
echo "============================================"
echo "  Adresy dostępowe"
echo "============================================"
echo "  Lokalnie:  http://localhost:3000"
echo "  Z sieci:   http://$LAN_IP:3000"
echo "  API:       http://$LAN_IP:8000"
echo ""
echo "  Logi:      $LOG_DIR/"
echo "  Stop:      ./scripts/stop_dev.sh"
echo "  Status:    ./scripts/status_dev.sh"
echo "============================================"
