#!/usr/bin/env bash
# =============================================================
# RLdC Trading Bot — Watchdog
# Uruchamia się co 60s (via systemd timer lub cron)
# Sprawdza stan serwisów i restartuje je jeśli nie działają
# =============================================================
set -euo pipefail

SERVICES=(rldc-backend rldc-frontend rldc-overlay rldc-telegram rldc-quicktunnel rldc-cloudflared)
BACKEND_URL="http://127.0.0.1:8000/health"
FRONTEND_URL="http://127.0.0.1:3000"
OVERLAY_URL="http://127.0.0.1:8099/overlay/api/live-state"
LOG_FILE="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/watchdog.log"
LOCK_FILE="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/watchdog.lock"
STATE_DIR="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/watchdog_state"
MAX_RESTARTS=3
WINDOW_SEC=300
BACKEND_GRACE_SEC=180
FRONTEND_GRACE_SEC=90
BACKEND_HTTP_TIMEOUT_SEC=12
FRONTEND_HTTP_TIMEOUT_SEC=10
OVERLAY_HTTP_TIMEOUT_SEC=15
BACKEND_HTTP_FAIL_THRESHOLD=3
FRONTEND_HTTP_FAIL_THRESHOLD=2
OVERLAY_HTTP_FAIL_THRESHOLD=2

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

restart_service() {
    local svc="$1"
    log "RESTART: $svc"
    systemctl --user restart "$svc" || true
}

reset_fail_count() {
    local key="$1"
    rm -f "$STATE_DIR/${key}.failcount"
}

increment_fail_count() {
    local key="$1"
    local file="$STATE_DIR/${key}.failcount"
    local count=0
    if [[ -f "$file" ]]; then
        read -r count < "$file" || count=0
    fi
    count=$((count + 1))
    printf '%s\n' "$count" > "$file"
    echo "$count"
}

service_started_recently() {
    local svc="$1"
    local grace_sec="$2"
    local ts
    local started_at=0
    local now

    ts="$(systemctl --user show "$svc" -p ActiveEnterTimestamp --value 2>/dev/null || true)"
    if [[ -z "$ts" || "$ts" == "n/a" ]]; then
        return 1
    fi

    started_at="$(date -d "$ts" +%s 2>/dev/null || echo 0)"
    now="$(date +%s)"
    (( started_at > 0 && now - started_at < grace_sec ))
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
    local timeout_sec="$3"
    local fail_threshold="$4"
    local grace_sec="$5"
    local fail_count=0

    if ! systemctl --user is-active --quiet "$svc" 2>/dev/null; then
        reset_fail_count "$svc"
        log "HTTP_SKIP: $url ($svc) — serwis nieaktywny"
        return 0
    fi

    if service_started_recently "$svc" "$grace_sec"; then
        reset_fail_count "$svc"
        log "HTTP_GRACE: $url ($svc) — pomijam probe w oknie rozruchowym ${grace_sec}s"
        return 0
    fi

    if curl -sf --max-time "$timeout_sec" "$url" > /dev/null 2>&1; then
        reset_fail_count "$svc"
        return 0
    fi

    fail_count="$(increment_fail_count "$svc")"
    if (( fail_count < fail_threshold )); then
        log "HTTP_FAIL: $url ($svc) — blad ${fail_count}/${fail_threshold}, bez restartu"
        return 0
    fi

    log "HTTP_FAIL: $url ($svc) — restart po ${fail_count} kolejnych bledach"
    reset_fail_count "$svc"
    restart_service "$svc"
}

# Upewnij się że katalog logów istnieje
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "SKIP: watchdog już działa"
    exit 0
fi

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
check_http "$BACKEND_URL" "rldc-backend" "$BACKEND_HTTP_TIMEOUT_SEC" "$BACKEND_HTTP_FAIL_THRESHOLD" "$BACKEND_GRACE_SEC"
check_http "$FRONTEND_URL" "rldc-frontend" "$FRONTEND_HTTP_TIMEOUT_SEC" "$FRONTEND_HTTP_FAIL_THRESHOLD" "$FRONTEND_GRACE_SEC"
check_http "$OVERLAY_URL" "rldc-overlay" "$OVERLAY_HTTP_TIMEOUT_SEC" "$OVERLAY_HTTP_FAIL_THRESHOLD" "$BACKEND_GRACE_SEC"

log "=== Watchdog check done ==="
