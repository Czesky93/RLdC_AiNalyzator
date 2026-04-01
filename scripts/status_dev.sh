#!/usr/bin/env bash
# ============================================================
# status_dev.sh — sprawdza stan backendu i frontendu
# ============================================================

LAN_IP="192.168.0.109"

echo "============================================"
echo "  RLdC AiNalyzator — status środowiska"
echo "============================================"

# Porty
echo ""
echo "[PORTY]"
if ss -tlnp | grep -q ':8000'; then
    echo "  ✅ Backend  :8000 — DZIAŁA"
else
    echo "  ❌ Backend  :8000 — ZATRZYMANY"
fi

if ss -tlnp | grep -q ':3000'; then
    echo "  ✅ Frontend :3000 — DZIAŁA"
else
    echo "  ❌ Frontend :3000 — ZATRZYMANY"
fi

# HTTP health-check
echo ""
echo "[HTTP]"

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

check_url "http://localhost:8000/"                        "Backend  (localhost)"
check_url "http://localhost:3000/"                        "Frontend (localhost)"
check_url "http://$LAN_IP:8000/"                         "Backend  (LAN)"
check_url "http://$LAN_IP:3000/"                         "Frontend (LAN)"
check_url "http://localhost:8000/api/signals/best-opportunity" "Best-opportunity API"
check_url "http://localhost:8000/api/positions/analysis"      "Positions analysis API"

echo ""
echo "============================================"
echo "  Adresy dostępowe:"
echo "  Lokalnie:  http://localhost:3000"
echo "  Z sieci:   http://$LAN_IP:3000"
echo "============================================"
