#!/usr/bin/env bash
# =============================================================
# RLdC — Konfiguracja Named Cloudflare Tunnel (jednorazowy setup)
# Uruchom: bash scripts/setup_tunnel.sh TWOJA_DOMENA.PL
# Przykład: bash scripts/setup_tunnel.sh rldc-bot.com
# =============================================================
set -euo pipefail

DOMAIN="${1:-}"
TUNNEL_NAME="rldc-tunnel"
CF_DIR="/home/rldc/.cloudflared"
CONFIG_FILE="$CF_DIR/config.yml"
PROJECT_DIR="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log_ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERR]${NC} $*"; }

if [[ -z "$DOMAIN" ]]; then
    echo ""
    echo "Użycie: bash scripts/setup_tunnel.sh TWOJA_DOMENA.PL"
    echo "  Przykład: bash scripts/setup_tunnel.sh mytrading.example.com"
    echo ""
    echo "Wymagania:"
    echo "  - Domena musi być zarządzana przez Cloudflare"
    echo "  - cloudflared zainstalowany ($(cloudflared --version 2>&1 | head -1))"
    echo ""
    exit 1
fi

echo ""
echo "=== RLdC Cloudflare Named Tunnel Setup ==="
echo "Domena: $DOMAIN"
echo "Tunnel: $TUNNEL_NAME"
echo ""

# KROK 1: Login do Cloudflare
if [[ ! -f "$CF_DIR/cert.pem" ]]; then
    log_warn "cert.pem nie znaleziono — uruchamiam cloudflared tunnel login"
    echo "    Zostanie otwarta przeglądarka. Zaloguj się do Cloudflare i autoryzuj."
    echo "    Jeśli przeglądarka się nie otworzy — skopiuj URL z terminala."
    echo ""
    cloudflared tunnel login
    if [[ ! -f "$CF_DIR/cert.pem" ]]; then
        log_err "Login nieudany — cert.pem nadal brak"
        exit 1
    fi
    log_ok "Zalogowano do Cloudflare"
else
    log_ok "cert.pem istnieje — pomijam login"
fi

# KROK 2: Utwórz tunnel (jeśli nie istnieje)
EXISTING_UUID=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
for t in data:
    if t.get('name')=='$TUNNEL_NAME':
        print(t['id'])
        break
" 2>/dev/null || echo "")

if [[ -z "$EXISTING_UUID" ]]; then
    echo "Tworzę tunnel '$TUNNEL_NAME'..."
    cloudflared tunnel create "$TUNNEL_NAME"
    TUNNEL_UUID=$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
for t in data:
    if t.get('name')=='$TUNNEL_NAME':
        print(t['id'])
        break
" 2>/dev/null || echo "")
else
    TUNNEL_UUID="$EXISTING_UUID"
    log_ok "Tunnel '$TUNNEL_NAME' już istnieje: $TUNNEL_UUID"
fi

if [[ -z "$TUNNEL_UUID" ]]; then
    log_err "Nie udało się pobrać UUID tunelu"
    exit 1
fi
log_ok "Tunnel UUID: $TUNNEL_UUID"

# KROK 3: Sprawdź czy credentials JSON istnieje
CRED_FILE="$CF_DIR/${TUNNEL_UUID}.json"
if [[ ! -f "$CRED_FILE" ]]; then
    log_err "Brak pliku credentials: $CRED_FILE"
    exit 1
fi
log_ok "Credentials: $CRED_FILE"

# KROK 4: DNS CNAME records
echo ""
echo "Tworzę DNS CNAME records..."
cloudflared tunnel route dns "$TUNNEL_NAME" "rldc.${DOMAIN}" 2>&1 || log_warn "DNS dla rldc.${DOMAIN} już istnieje lub błąd — sprawdź w Cloudflare dashboard"
cloudflared tunnel route dns "$TUNNEL_NAME" "api.rldc.${DOMAIN}" 2>&1 || log_warn "DNS dla api.rldc.${DOMAIN} już istnieje lub błąd — sprawdź w Cloudflare dashboard"
log_ok "DNS records skonfigurowane (lub już istniały)"

# KROK 5: Zaktualizuj config.yml
echo ""
echo "Aktualizuję $CONFIG_FILE..."
cat > "$CONFIG_FILE" << CFEOF
# RLdC — Cloudflare Named Tunnel
# Wygenerowano automatycznie przez setup_tunnel.sh
# Domena: ${DOMAIN}
# Data: $(date '+%Y-%m-%d %H:%M:%S')

tunnel: ${TUNNEL_UUID}
credentials-file: ${CRED_FILE}

loglevel: info
logfile: ${PROJECT_DIR}/logs/runtime/cloudflared.log

ingress:
  - hostname: rldc.${DOMAIN}
    service: http://localhost:3000
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false

  - hostname: api.rldc.${DOMAIN}
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false

  - service: http_status:404
CFEOF
log_ok "config.yml zaktualizowany"

# KROK 6: Zaktualizuj .env w projekcie
ENV_FILE="$PROJECT_DIR/.env"
echo ""
echo "Aktualizuję zmienne domenowe w .env..."
python3 - << PYEOF
import re

env_path = "$ENV_FILE"
domain = "$DOMAIN"
updates = {
    "APP_DOMAIN": f"rldc.{domain}",
    "API_DOMAIN": f"api.rldc.{domain}",
    "PUBLIC_DOMAIN": f"rldc.{domain}",
    "NEXTAUTH_URL": f"https://rldc.{domain}",
    "NEXT_PUBLIC_API_URL": f"https://api.rldc.{domain}",
    "CORS_ALLOW_ORIGINS": f"https://rldc.{domain},https://api.rldc.{domain},http://localhost:3000",
}

with open(env_path, "r") as f:
    content = f.read()

for key, value in updates.items():
    pattern = rf"^{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        print(f"  Updated: {replacement}")
    else:
        content += f"\n{replacement}"
        print(f"  Added: {replacement}")

with open(env_path, "w") as f:
    f.write(content)
print("  .env zaktualizowany")
PYEOF

# KROK 7: Aktywuj rldc-cloudflared.service
echo ""
echo "Aktywuję systemd service..."
systemctl --user daemon-reload
systemctl --user enable rldc-cloudflared.service
systemctl --user start rldc-cloudflared.service
sleep 3
if systemctl --user is-active --quiet rldc-cloudflared.service; then
    log_ok "rldc-cloudflared.service DZIAŁA"
else
    log_warn "rldc-cloudflared.service nie startuje — sprawdź: journalctl --user -u rldc-cloudflared -n 20"
fi

echo ""
echo "===== GOTOWE ====="
echo ""
echo "  Panel:    https://rldc.${DOMAIN}"
echo "  API:      https://api.rldc.${DOMAIN}"
echo "  Health:   https://api.rldc.${DOMAIN}/api/health"
echo ""
echo "Sprawdź status: systemctl --user status rldc-cloudflared"
echo "Logi:           tail -f $PROJECT_DIR/logs/runtime/cloudflared.log"
echo ""
