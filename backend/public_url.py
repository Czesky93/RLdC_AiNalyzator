"""
Public URL — centralna logika wykrywania aktywnego publicznego adresu panelu.

Hierarchia priorytetów:
  1. PUBLIC_BASE_URL       (env — skonfigurowany przez operatora)
  2. CLOUDFLARE_TUNNEL_URL (env — tunel CF/ngrok)
  3. NGROK_URL             (env — tunel ngrok)
  4. Zewnętrzne IP przez api.ipify.org + port z env
  5. LAN IP (fallback lokalny)

DS-Lite / IPv6: Jeśli router ma DS-Lite (brak publicznego IPv4), wykryte zewnętrzne
IP może być adresem CGNAT i nie będzie dostępne z zewnątrz.
W takim przypadku należy ustawić CLOUDFLARE_TUNNEL_URL lub PUBLIC_BASE_URL.
"""
from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Optional

_EXTERNAL_IP_SERVICES = [
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://icanhazip.com",
]


def _get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _fetch_external_ip(timeout: float = 3.0) -> Optional[str]:
    """Pobiera zewnętrzne IP z publicznych serwisów (z timeoutem)."""
    try:
        import requests  # lazy — nie ma w środowisku testowym
    except ImportError:
        return None
    for url in _EXTERNAL_IP_SERVICES:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip:
                    return ip
        except Exception:
            continue
    return None


def get_public_url_info() -> dict:
    """
    Zwraca słownik z informacjami o aktywnym publicznym adresie panelu:

    Klucze:
      public_url   — pełny URL do panelu WWW (None jeśli tylko local)
      api_url      — URL backendu API
      source       — skąd pochodzi adres
      mode         — "configured" | "tunnel" | "direct_ip" | "local"
      lan_url      — adres LAN (zawsze dostępny)
      lan_ip       — IP w sieci lokalnej
      status       — "configured" | "tunnel_active" | "detected" | "local_only"
      warning      — opcjonalne ostrzeżenie (np. DS-Lite)
      updated_at   — ISO timestamp
    """
    frontend_port = int(os.getenv("FRONTEND_PORT", "3000"))
    api_port = int(os.getenv("API_PORT", "8000"))
    lan_ip = _get_lan_ip()
    lan_url = f"http://{lan_ip}:{frontend_port}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. PUBLIC_BASE_URL — skonfigurowany przez operatora (najwyższy priorytet)
    public_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public_base:
        public_api = os.getenv("PUBLIC_API_URL", "").strip().rstrip("/")
        return {
            "public_url": public_base,
            "api_url": public_api or public_base,
            "source": "PUBLIC_BASE_URL",
            "mode": os.getenv("PUBLIC_MODE", "configured"),
            "lan_url": lan_url,
            "lan_ip": lan_ip,
            "status": "configured",
            "updated_at": now_iso,
        }

    # 2. Tunel Cloudflare lub ngrok
    tunnel_url = (
        os.getenv("CLOUDFLARE_TUNNEL_URL", "")
        or os.getenv("NGROK_URL", "")
    ).strip().rstrip("/")
    if tunnel_url:
        return {
            "public_url": tunnel_url,
            "api_url": tunnel_url,
            "source": "TUNNEL_URL",
            "mode": "tunnel",
            "lan_url": lan_url,
            "lan_ip": lan_ip,
            "status": "tunnel_active",
            "updated_at": now_iso,
        }

    # 3. Autodetekcja zewnętrznego IP
    external_ip = _fetch_external_ip()
    if external_ip:
        public_url = f"http://{external_ip}:{frontend_port}"
        return {
            "public_url": public_url,
            "api_url": f"http://{external_ip}:{api_port}",
            "source": "auto_detected_ip",
            "mode": "direct_ip",
            "lan_url": lan_url,
            "lan_ip": lan_ip,
            "external_ip": external_ip,
            "status": "detected",
            "warning": (
                "DS-Lite/CGNAT może blokować dostęp z zewnątrz przez IPv4. "
                "Zalecane: ustaw PUBLIC_BASE_URL lub CLOUDFLARE_TUNNEL_URL w .env."
            ),
            "updated_at": now_iso,
        }

    # 4. Fallback — tylko LAN
    return {
        "public_url": None,
        "api_url": f"http://{lan_ip}:{api_port}",
        "source": "local_only",
        "mode": "local",
        "lan_url": lan_url,
        "lan_ip": lan_ip,
        "status": "local_only",
        "warning": (
            "Brak publicznego adresu. "
            "Ustaw PUBLIC_BASE_URL lub CLOUDFLARE_TUNNEL_URL w .env."
        ),
        "updated_at": now_iso,
    }
