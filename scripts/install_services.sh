#!/usr/bin/env bash
# =============================================================
# RLdC Trading Bot — Instalacja serwisów produkcyjnych
# Uruchamia 4 systemd user services, konfiguruje linger
# i opcjonalnie buduje frontend.
#
# Użycie:
#   bash scripts/install_services.sh           # instaluj i uruchom
#   bash scripts/install_services.sh --rebuild # + przebuduj frontend
#   bash scripts/install_services.sh --stop    # zatrzymaj i wyłącz
# =============================================================
set -euo pipefail

MODE="${1:-install}"
PROJECT_DIR="/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator"
SYSTEMD_DIR="$HOME/.config/systemd/user"
LOG_DIR="$PROJECT_DIR/logs/runtime"
NODE_BIN="/home/rldc/.nvm/versions/node/v20.11.1/bin"
SERVICES=(rldc-backend rldc-telegram rldc-frontend)
# cloudflared osobno — tylko jeśli tunnel skonfigurowany

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERR]${NC} $*"; }
log_info() { echo -e "${CYAN}[INFO]${NC} $*"; }

echo ""
echo "======================================================"
echo "  RLdC Trading Bot — Konfiguracja serwisów produkcja"
echo "======================================================"
echo ""

# --- STOP MODE ---
if [[ "$MODE" == "--stop" ]]; then
    log_info "Zatrzymywanie serwisów..."
    for svc in rldc-cloudflared rldc-frontend rldc-telegram rldc-backend; do
        systemctl --user stop "$svc" 2>/dev/null && log_ok "Stopped: $svc" || log_warn "Nie działa: $svc"
        systemctl --user disable "$svc" 2>/dev/null || true
    done
    log_ok "Wszystkie serwisy zatrzymane i wyłączone"
    exit 0
fi

# --- REBUILD FRONTEND ---
if [[ "$MODE" == "--rebuild" ]]; then
    log_info "Przebudowuję frontend Next.js..."
    export PATH="$NODE_BIN:$PATH"
    cd "$PROJECT_DIR/web_portal"
    npm ci --silent 2>&1 | tail -5
    npm run build 2>&1 | tail -10
    log_ok "Frontend przebudowany"
    cd "$PROJECT_DIR"
fi

# KROK 1: Katalogi logów
log_info "Tworzę katalogi logów..."
mkdir -p "$LOG_DIR"
log_ok "Logdir: $LOG_DIR"

# KROK 2: Sprawdź zależności
log_info "Sprawdzam zależności..."
[[ -f "$PROJECT_DIR/.venv/bin/uvicorn" ]] || { log_err "Brak uvicorn w .venv — aktywuj środowisko i pip install -r requirements.txt"; exit 1; }
[[ -f "$NODE_BIN/node" ]] || { log_err "Brak node w $NODE_BIN — sprawdź nvm"; exit 1; }
[[ -d "$PROJECT_DIR/web_portal/.next" ]] || { log_err "Brak buildu frontendu. Uruchom z --rebuild"; exit 1; }
[[ -f "$PROJECT_DIR/.env" ]] || { log_err "Brak .env w $PROJECT_DIR"; exit 1; }
log_ok "Zależności OK"

# KROK 3: Sprawdź next binary path
NEXT_BIN="$NODE_BIN/next"
if [[ ! -f "$NEXT_BIN" ]]; then
    # next może być lokalnie w web_portal/node_modules/.bin/
    NEXT_BIN="$PROJECT_DIR/web_portal/node_modules/.bin/next"
    if [[ ! -f "$NEXT_BIN" ]]; then
        log_err "Brak binarki next. Uruchom: cd web_portal && npm install"
        exit 1
    fi
    log_warn "next binary: $NEXT_BIN (lokalny)"
    # Zaktualizuj service ExecStart żeby wskazywał na lokalny next
    sed -i "s|%NODE_BIN%/next|$NEXT_BIN|g" "$SYSTEMD_DIR/rldc-frontend.service" 2>/dev/null || true
fi
log_ok "next binary: $NEXT_BIN"

# KROK 4: loginctl linger (kluczowe dla boot bez logowania)
log_info "Włączam loginctl linger (auto-start po restarcie)..."
CURRENT_USER=$(whoami)
if loginctl show-user "$CURRENT_USER" 2>/dev/null | grep -q "Linger=yes"; then
    log_ok "Linger już włączony"
else
    loginctl enable-linger "$CURRENT_USER" && log_ok "Linger włączony" || {
        log_warn "Nie udało się enable-linger. Możliwe że wymaga 'sudo loginctl enable-linger $CURRENT_USER'"
        log_warn "Wpisz ręcznie: sudo loginctl enable-linger $CURRENT_USER"
    }
fi

# KROK 5: Reload daemon i enable + start serwisów
log_info "Przeładowuję systemd daemon i startuję serwisy..."
systemctl --user daemon-reload

for svc in "${SERVICES[@]}"; do
    log_info "Włączam: $svc"
    systemctl --user enable "$svc"
    systemctl --user restart "$svc" 2>&1 | head -3 || true
done

# KROK 6: Cloudflared — tylko jeśli tunnel skonfigurowany
if grep -q "TUNNEL_ID" /home/rldc/.cloudflared/config.yml 2>/dev/null; then
    log_warn "Cloudflared POMINIĘTY — config.yml ma placeholder."
    log_warn "  Skonfiguruj: bash scripts/setup_tunnel.sh TWOJA_DOMENA.PL"
else
    log_info "Włączam: rldc-cloudflared"
    systemctl --user enable rldc-cloudflared
    systemctl --user restart rldc-cloudflared 2>&1 | head -3 || true
    SERVICES+=(rldc-cloudflared)
fi

# KROK 7: Status check
echo ""
echo "======================================================"
echo "  Status serwisów"
echo "======================================================"
sleep 5

ALL_OK=true
for svc in "${SERVICES[@]}"; do
    if systemctl --user is-active --quiet "$svc" 2>/dev/null; then
        echo -e "  ${GREEN}●${NC} $svc — DZIAŁA"
    else
        echo -e "  ${RED}●${NC} $svc — NIE DZIAŁA"
        ALL_OK=false
    fi
done

echo ""
# KROK 8: HTTP healthchecks
HEALTH_OK=false
for i in 1 2 3; do
    if curl -sf --max-time 5 http://127.0.0.1:8000/health > /dev/null 2>&1; then
        HEALTH_OK=true; break
    fi
    sleep 3
done
$HEALTH_OK && log_ok "Backend HTTP: OK" || log_warn "Backend HTTP nie odpowiada — sprawdź logi: $LOG_DIR/backend.log"

FRONT_OK=false
for i in 1 2 3; do
    if curl -sf --max-time 5 http://127.0.0.1:3000 > /dev/null 2>&1; then
        FRONT_OK=true; break
    fi
    sleep 3
done
$FRONT_OK && log_ok "Frontend HTTP: OK" || log_warn "Frontend HTTP nie odpowiada — sprawdź logi: $LOG_DIR/frontend.log"

# KROK 9: Konfiguracja logrotate (user)
log_info "Konfiguruję logrotate..."
LOGROTATE_CONF="$HOME/.config/logrotate/rldc.conf"
mkdir -p "$HOME/.config/logrotate"
cp "$PROJECT_DIR/ops/logrotate.conf" "$LOGROTATE_CONF"
# Sprawdź czy cronjob już istnieje
if ! crontab -l 2>/dev/null | grep -q "logrotate.*rldc"; then
    (crontab -l 2>/dev/null; echo "0 3 * * * /usr/sbin/logrotate --state $HOME/.config/logrotate/state $LOGROTATE_CONF") | crontab -
    log_ok "Logrotate cron: 3:00 daily"
else
    log_ok "Logrotate cron już istnieje"
fi

# KROK 10: Konfiguracja watchdog via cron
if ! crontab -l 2>/dev/null | grep -q "watchdog.sh"; then
    (crontab -l 2>/dev/null; echo "* * * * * bash $PROJECT_DIR/scripts/watchdog.sh >> $LOG_DIR/watchdog.log 2>&1") | crontab -
    log_ok "Watchdog cron: co minutę"
else
    log_ok "Watchdog cron już istnieje"
fi

echo ""
echo "======================================================"
echo "  Komunikaty diagnostyczne"
echo "======================================================"
echo ""
echo "  Logi:          tail -f $LOG_DIR/backend.log"
echo "  Health:        curl http://127.0.0.1:8000/api/health"
echo "  Status:        systemctl --user status rldc-backend"
echo "  Wszystkie:     systemctl --user list-units 'rldc-*'"
echo ""
echo "  Setup tunnel:  bash scripts/setup_tunnel.sh TWOJA_DOMENA.PL"
echo "  Przebuduj FE:  bash scripts/install_services.sh --rebuild"
echo "  Zatrzymaj:     bash scripts/install_services.sh --stop"
echo ""

$ALL_OK && log_ok "Instalacja zakończona SUKCESEM" || log_warn "Instalacja z ostrzeżeniami — sprawdź powyższe logi"
echo ""
