#!/usr/bin/env bash
# ============================================================
# start_dev.sh — uruchamia backend i frontend RLdC AiNalyzator
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs/dev"
LAN_IP="192.168.0.109"

mkdir -p "$LOG_DIR"

echo "============================================"
echo "  RLdC AiNalyzator — start środowiska dev"
echo "============================================"

# ---- Sprawdź, czy procesy już działają ----
if ss -tlnp | grep -q ':8000'; then
    echo "[INFO] Backend już działa na :8000 — pomijam uruchomienie."
else
    echo "[START] Uruchamiam backend (uvicorn :8000)..."
    cd "$PROJECT_DIR"
    nohup .venv/bin/python -m uvicorn backend.app:app \
        --host 0.0.0.0 --port 8000 \
        > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$LOG_DIR/backend.pid"
    echo "[OK] Backend PID: $(cat "$LOG_DIR/backend.pid")"
fi

if ss -tlnp | grep -q ':3000'; then
    echo "[INFO] Frontend już działa na :3000 — pomijam uruchomienie."
else
    echo "[START] Uruchamiam frontend (Next.js :3000)..."
    cd "$PROJECT_DIR/web_portal"
    nohup npx next dev --hostname 0.0.0.0 --port 3000 \
        > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
    echo "[OK] Frontend PID: $(cat "$LOG_DIR/frontend.pid")"
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
