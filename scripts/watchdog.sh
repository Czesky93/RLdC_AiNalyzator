#!/usr/bin/env bash
# =============================================================
# RLdC Trading Bot — Watchdog
# Uruchamia się co 60s (via systemd timer lub cron)
# Sprawdza stan 4 serwisów i restartuje je jeśli nie działają
# =============================================================
set -euo pipefail

SERVICES=(rldc-backend rldc-frontend rldc-telegram rldc-cloudflared)
BACKEND_URL="http://127.0.0.1:8000/health"
FRONTEND_URL="http://127.0.0.1:3000"
LOG_FILE="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/watchdog.log"
MAX_RESTARTS=3
WINDOW_SEC=300

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

restart_service() {
    local svc="$1"
    log "RESTART: $svc"
    systemctl --user restart "$svc" 2>&1 | tee -a "$LOG_FILE" || true
}

check_service() {
    local svc="$1"
    if ! systemctl --user is-active --quiet "$svc" 2>/dev/null; then
        log "DOWN: $svc — próba restartu"
        restart_service "$svc"
        sleep 5
        if ! systemctl --user is-active --quiet "$svc" 2>/dev/null; then
            log "FAILED: $svc — nie udało się uruchomić"
            return 1
        else
            log "OK: $svc — wznowiony"
        fi
    fi
    return 0
}

check_http() {
    local url="$1"
    local svc="$2"
    if ! curl -sf --max-time 5 "$url" > /dev/null 2>&1; then
        log "HTTP_FAIL: $url ($svc) — restart"
        restart_service "$svc"
    fi
}

# Upewnij się że katalog logów istnieje
mkdir -p "$(dirname "$LOG_FILE")"

log "=== Watchdog check start ==="

for svc in "${SERVICES[@]}"; do
    # Cloudflared może być wyłączony celowo (brak tunnel config)
    if [[ "$svc" == "rldc-cloudflared" ]]; then
        # Pomiń jeśli config ma placeholder lub serwis disabled
        if grep -q "TUNNEL_ID" /home/rldc/.cloudflared/config.yml 2>/dev/null; then
            log "SKIP: rldc-cloudflared — config.yml ma placeholder, tunnel nie skonfigurowany"
            continue
        fi
        if systemctl --user is-enabled --quiet "rldc-cloudflared" 2>/dev/null; then
            check_service "$svc" || true
        else
            log "SKIP: rldc-cloudflared — disabled"
        fi
        continue
    fi
    check_service "$svc" || true
done

# HTTP health checks (jeśli serwisy działają)
check_http "$BACKEND_URL" "rldc-backend"
check_http "$FRONTEND_URL" "rldc-frontend"

log "=== Watchdog check done ==="
