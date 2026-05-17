#!/usr/bin/env bash
# =============================================================
# RLdC — Quick Tunnel (frontend + osobny overlay)
# Serwis: rldc-quicktunnel.service
# =============================================================
set -euo pipefail

RUNTIME_FILE="/tmp/rldc_tunnel_runtime.json"
PUBLIC_URLS_FILE="/home/rldc/.rldc_runtime/public_urls.txt"
LOG_FILE="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/quicktunnel.log"
FRONTEND_PORT=3000
OVERLAY_PORT=8099
FRONTEND_CLOUDFLARED_PID=""
OVERLAY_CLOUDFLARED_PID=""
FRONTEND_PARSER_PID=""
OVERLAY_PARSER_PID=""
FRONTEND_URL=""
OVERLAY_URL=""
LAST_ERROR="null"

mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$PUBLIC_URLS_FILE")"

json_string_or_null() {
    local value="${1:-}"
    if [[ -z "$value" ]]; then
        printf 'null'
    else
        printf '"%s"' "$value"
    fi
}

read_saved_url() {
    local key="$1"
    if [[ ! -f "$PUBLIC_URLS_FILE" ]]; then
        return 0
    fi
    grep -E "^${key}=" "$PUBLIC_URLS_FILE" | tail -1 | cut -d'=' -f2-
}

sync_runtime_state() {
    local running="${1:-true}"
    local started_at="${2:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
    local frontend_url="${FRONTEND_URL:-$(read_saved_url frontend_url)}"
    local overlay_url="${OVERLAY_URL:-$(read_saved_url overlay_url)}"
    {
        echo "frontend_url=${frontend_url}"
        echo "overlay_url=${overlay_url}"
    } > "$PUBLIC_URLS_FILE"
    cat > "$RUNTIME_FILE" <<EOF
{"running":${running},"frontend_url":$(json_string_or_null "$frontend_url"),"overlay_url":$(json_string_or_null "$overlay_url"),"api_url":null,"started_at":$(json_string_or_null "$started_at"),"tunnel_type":"quick","last_error":${LAST_ERROR}}
EOF
}

parse_tunnel_output() {
    local kind="$1"
    local pipe="$2"
    while IFS= read -r line; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$kind] $line" >> "$LOG_FILE"

        if echo "$line" | grep -qE '429 Too Many Requests|error code: 1015|failed to unmarshal quick Tunnel'; then
            LAST_ERROR='"trycloudflare_rate_limited"'
            sync_runtime_state false "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] RATE_LIMIT: Cloudflare quick tunnel ($kind) odrzucił żądanie (1015/429)" >> "$LOG_FILE"
        fi

        if echo "$line" | grep -qE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com'; then
            local url
            url=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com' | grep -v '^https://api\.trycloudflare\.com$' | head -1 || true)
            if [[ -z "$url" ]]; then
                continue
            fi
            LAST_ERROR='null'
            if [[ "$kind" == "frontend" ]]; then
                FRONTEND_URL="$url"
            else
                OVERLAY_URL="$url"
            fi
            sync_runtime_state true "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] TUNNEL URL ($kind): $url" >> "$LOG_FILE"
            echo "OK: Quick tunnel $kind URL: $url" >&2
        fi
    done < "$pipe"
}

cleanup() {
    FRONTEND_URL=""
    OVERLAY_URL=""
    LAST_ERROR='null'
    sync_runtime_state false "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] STOP: quicktunnel zakończony" >> "$LOG_FILE"
    for pid in "$FRONTEND_PARSER_PID" "$OVERLAY_PARSER_PID" "$FRONTEND_CLOUDFLARED_PID" "$OVERLAY_CLOUDFLARED_PID"; do
        if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
}

trap cleanup EXIT SIGTERM SIGINT

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START: uruchamiam cloudflared quick tunnel -> localhost:$FRONTEND_PORT oraz overlay:$OVERLAY_PORT" >> "$LOG_FILE"
sync_runtime_state false ""

FRONTEND_PIPE="$(mktemp -u /tmp/rldc-quicktunnel.frontend.XXXXXX)"
OVERLAY_PIPE="$(mktemp -u /tmp/rldc-quicktunnel.overlay.XXXXXX)"
mkfifo "$FRONTEND_PIPE" "$OVERLAY_PIPE"

cloudflared tunnel --config /dev/null --no-autoupdate --url "http://localhost:$FRONTEND_PORT" > "$FRONTEND_PIPE" 2>&1 &
FRONTEND_CLOUDFLARED_PID=$!
cloudflared tunnel --config /dev/null --no-autoupdate --url "http://localhost:$OVERLAY_PORT" > "$OVERLAY_PIPE" 2>&1 &
OVERLAY_CLOUDFLARED_PID=$!

parse_tunnel_output frontend "$FRONTEND_PIPE" &
FRONTEND_PARSER_PID=$!
parse_tunnel_output overlay "$OVERLAY_PIPE" &
OVERLAY_PARSER_PID=$!

wait "$FRONTEND_CLOUDFLARED_PID" "$OVERLAY_CLOUDFLARED_PID"
rm -f "$FRONTEND_PIPE" "$OVERLAY_PIPE"
