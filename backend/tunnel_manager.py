"""
tunnel_manager.py — Self-healing quick tunnel manager dla RLdC Trading Bot.

Odpowiada za:
- Sprawdzanie stanu lokalnych serwisów (port 3000/8000)
- Weryfikację działającego publicznego URL (GET probe + content check)
- Automatyczny restart cloudflared quick tunnel gdy URL nieosiągalny
- Odczyt nowego URL z logów/runtime pliku
- Zaktualizowanie .env (APP_DOMAIN, CLOUDFLARE_TUNNEL_URL)
- Statusowy endpoint /api/account/system-health/tunnel

Logi: [tunnel] ...
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests as _req

# ---------------------------------------------------------------------------
# Stałe
# ---------------------------------------------------------------------------
_RUNTIME_FILE = Path("/tmp/rldc_tunnel_runtime.json")
_LOG_FILE = Path(
    "/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/quicktunnel.log"
)
_ENV_FILE = Path(
    os.getenv("ENV_FILE", "/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/.env")
)
_SYSTEMD_SERVICE = "rldc-quicktunnel"

_FRONTEND_PORT = int(os.getenv("PORT", "3000"))
_BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

_PROBE_TIMEOUT = 6
_PROBE_CONTENT_MIN = 100
_URL_READ_RETRIES = 10
_URL_READ_INTERVAL = 3.0  # s — czas między próbami odczytu URL
_MAX_RECOVERY_ATTEMPTS = 3  # max restartów pod rząd przed poddaniem się
_RECOVERY_COOLDOWN = 120  # s — min przerwa między kolejnymi recovery

_CF_ERROR_PATTERNS = [
    r"error\s+1\d{3}",
    r'"cf-error-details"',
    r"<title>[^<]{0,60}1\d{3}[^<]{0,60}</title>",
    r"cloudflare ray id",
    r"host not found",
    r"this page can.t be reached",
]

# ---------------------------------------------------------------------------
# Singleton state (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()

_state: dict = {
    "active_url": None,
    "source": None,  # "runtime" | "env" | "freshly_generated"
    "probe_ok": False,
    "probe_ts": None,
    "local_frontend_ok": False,
    "local_backend_ok": False,
    "tunnel_pid": None,
    "recovery_count": 0,
    "last_recovery_at": None,
    "last_recovery_result": None,
    "last_error": None,
    "env_url": None,
    "runtime_url": None,
    "startup_done": False,
}


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    line = f"[tunnel] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _probe_local(port: int, path: str = "/") -> bool:
    """Sprawdź czy lokalny port odpowiada HTTP 200."""
    try:
        r = _req.get(f"http://localhost:{port}{path}", timeout=3, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def _probe_url(url: str) -> dict:
    """
    Realny test dostępności URL (GET + analiza treści).
    Zwraca dict z reachable, status, debug, status_code, content_len.
    """
    result = {
        "reachable": False,
        "status": "unreachable",
        "status_code": None,
        "final_url": url,
        "content_len": 0,
        "cf_error": False,
        "cf_error_code": None,
        "debug": None,
    }
    try:
        r = _req.get(
            url,
            timeout=_PROBE_TIMEOUT,
            allow_redirects=True,
            verify=False,
            headers={"User-Agent": "RLdC-TunnelProbe/1.0"},
        )
        result["status_code"] = r.status_code
        result["final_url"] = str(r.url)
        body = (r.text or "")[:5000]
        result["content_len"] = len(r.content)

        if r.status_code >= 400:
            result["status"] = f"http_{r.status_code}"
            result["debug"] = f"HTTP {r.status_code}"
            return result

        body_lower = body.lower()
        for pat in _CF_ERROR_PATTERNS:
            m = re.search(pat, body_lower)
            if m:
                result["cf_error"] = True
                result["cf_error_code"] = m.group(0)[:60]
                result["status"] = "cf_error_page"
                result["debug"] = f"CF error page: {m.group(0)[:60]}"
                return result

        if len(r.content) < _PROBE_CONTENT_MIN:
            result["status"] = "empty_response"
            result["debug"] = (
                f"HTTP {r.status_code}, pusta odpowiedź ({len(r.content)} B)"
            )
            return result

        result["reachable"] = True
        result["status"] = "reachable"
        result["debug"] = f"HTTP {r.status_code}, {len(r.content)} B"
        return result

    except _req.exceptions.Timeout:
        result["status"] = "timeout"
        result["debug"] = f"Timeout ({_PROBE_TIMEOUT}s)"
    except _req.exceptions.ConnectionError as e:
        result["status"] = "error"
        result["debug"] = str(e)[:100]
    except Exception as e:
        result["status"] = "error"
        result["debug"] = str(e)[:100]
    return result


def _read_runtime_url() -> Optional[str]:
    """Odczytaj URL z /tmp/rldc_tunnel_runtime.json."""
    try:
        if _RUNTIME_FILE.exists():
            data = json.loads(_RUNTIME_FILE.read_text())
            url = data.get("frontend_url") or data.get("api_url")
            if url and data.get("running"):
                return url
    except Exception as e:
        _log(f"runtime file read error: {e}")
    return None


def _read_cf_log_url() -> Optional[str]:
    """Odczytaj najnowszy URL z logu quicktunnel lub cloudflared (fallback gdy runtime file nie działa)."""
    # Preferuj quicktunnel.log (pisany przez run_quicktunnel.sh)
    _QT_LOG = Path(
        "/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/quicktunnel.log"
    )
    _CF_LOG = Path(
        "/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator/logs/runtime/cloudflared.log"
    )
    for log_path in (_QT_LOG, _CF_LOG):
        try:
            if not log_path.exists():
                continue
            # Czytaj od końca — szukaj ostatniego trycloudflare URL
            lines = log_path.read_text(errors="replace").splitlines()
            for line in reversed(lines):
                m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
                if m:
                    return m.group(0)
        except Exception:
            pass
    return None


def _read_env_url() -> Optional[str]:
    """Odczytaj CLOUDFLARE_TUNNEL_URL z .env."""
    try:
        if _ENV_FILE.exists():
            for line in _ENV_FILE.read_text().splitlines():
                line = line.strip()
                if line.startswith("CLOUDFLARE_TUNNEL_URL="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and not line.startswith("#"):
                        return val
    except Exception:
        pass
    return None


def _get_tunnel_pid() -> Optional[int]:
    """Znajdź PID procesu cloudflared."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "cloudflared tunnel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _kill_cloudflared() -> None:
    """Zatrzymaj wszystkie procesy cloudflared."""
    try:
        subprocess.run(["pkill", "-f", "cloudflared tunnel"], timeout=5)
        time.sleep(1)
        # Wymuś jeśli nadal działa
        subprocess.run(["pkill", "-9", "-f", "cloudflared tunnel"], timeout=3)
        time.sleep(1)
        _log("stare procesy cloudflared zatrzymane")
    except Exception as e:
        _log(f"kill cloudflared error: {e}")


def _restart_via_systemd() -> bool:
    """Restartuj serwis rldc-quicktunnel przez systemctl."""
    try:
        # Reload daemon units (plik serwisu mógł się zmienić)
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            timeout=10,
            capture_output=True,
        )
        r = subprocess.run(
            ["systemctl", "--user", "restart", _SYSTEMD_SERVICE],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            _log(f"systemctl restart {_SYSTEMD_SERVICE} — OK")
            return True
        else:
            _log(f"systemctl restart {_SYSTEMD_SERVICE} FAILED: {r.stderr[:200]}")
            return False
    except Exception as e:
        _log(f"systemctl restart error: {e}")
        return False


def _wait_for_new_url(timeout: float = 30.0) -> Optional[str]:
    """
    Po restarcie serwisu czekaj na pojawienie się nowego URL w runtime file.
    Fallback: czyta z cloudflared.log jeśli runtime file nie zawiera nowego URL.
    Próbuje co _URL_READ_INTERVAL sekund, max timeout sekund.
    """
    deadline = time.monotonic() + timeout
    known_old = _state.get("runtime_url")
    known_old_log = _read_cf_log_url()  # baseline z logu przed startem
    _log(f"czekam na nowy URL (stary: {known_old}, timeout: {timeout}s)")

    while time.monotonic() < deadline:
        time.sleep(_URL_READ_INTERVAL)
        # Źródło 1: runtime file (zarządzany przez run_quicktunnel.sh)
        new_url = _read_runtime_url()
        if new_url and new_url != known_old:
            _log(f"nowy URL wykryty (runtime): {new_url}")
            return new_url
        if new_url:
            _log(f"URL bez zmian w runtime ({new_url}), czekam...")
        # Źródło 2: cloudflared.log (fallback gdy run_quicktunnel.sh nie działa)
        log_url = _read_cf_log_url()
        if log_url and log_url != known_old_log:
            _log(f"nowy URL wykryty (cloudflared.log): {log_url}")
            return log_url

    _log("timeout — nowy URL nie pojawił się (ani runtime, ani cloudflared.log)")
    return None


def _update_env_url(new_url: str) -> bool:
    """
    Zaktualizuj APP_DOMAIN i CLOUDFLARE_TUNNEL_URL w .env.
    Idempotentna operacja — nie psuje innych wpisów.
    """
    try:
        domain = new_url.replace("https://", "").replace("http://", "").rstrip("/")
        text = _ENV_FILE.read_text()
        lines = text.splitlines()
        updated = []
        found_url = False
        found_domain = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(
                "CLOUDFLARE_TUNNEL_URL="
            ) and not stripped.startswith("#"):
                updated.append(f"CLOUDFLARE_TUNNEL_URL={new_url}")
                found_url = True
            elif stripped.startswith("APP_DOMAIN=") and not stripped.startswith("#"):
                updated.append(f"APP_DOMAIN={domain}")
                found_domain = True
            else:
                updated.append(line)

        if not found_url:
            updated.append(f"CLOUDFLARE_TUNNEL_URL={new_url}")
        if not found_domain:
            updated.append(f"APP_DOMAIN={domain}")

        _ENV_FILE.write_text("\n".join(updated) + "\n")
        _log(
            f"env zaktualizowane: APP_DOMAIN={domain}, CLOUDFLARE_TUNNEL_URL={new_url}"
        )
        return True
    except Exception as e:
        _log(f"env update failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Główna logika self-healing
# ---------------------------------------------------------------------------


def ensure_public_url(force_recovery: bool = False) -> dict:
    """
    Sprawdź i ewentualnie napraw publiczny URL tunelu.

    Kroki:
    1. Sprawdź lokalny port 3000 (frontend).
    2. Sprawdź aktualny runtime URL — jeśli OK, gotowe.
    3. Sprawdź URL z .env — jeśli OK, gotowe.
    4. Self-healing: restart cloudflared → czekaj na nowy URL → probe.
    5. Jeśli udane: zapisz do runtime + .env.

    Zwraca:
    {
        "success": bool,
        "active_url": str | None,
        "source": "runtime" | "env" | "freshly_generated" | None,
        "local_frontend_ok": bool,
        "probe_ok": bool,
        "recovery_attempted": bool,
        "recovery_success": bool | None,
        "error_step": str | None,  # "local_port_down" | "cloudflared_failed_to_start" | ...
        "tunnel_pid": int | None,
        "ts": str,
    }
    """
    ts = datetime.now(timezone.utc).isoformat()

    with _lock:
        # ── Cooldown między recovery ───────────────────────────────────────
        last_rec = _state.get("last_recovery_at")
        cooldown_ok = (
            force_recovery
            or last_rec is None
            or (time.time() - last_rec) > _RECOVERY_COOLDOWN
        )

        # ── 1. Sprawdź lokalny frontend ────────────────────────────────────
        local_ok = _probe_local(_FRONTEND_PORT)
        _state["local_frontend_ok"] = local_ok
        _state["local_backend_ok"] = _probe_local(_BACKEND_PORT)

        if not local_ok:
            _log(f"local probe failed — port {_FRONTEND_PORT} DOWN")
            _state["last_error"] = "local_port_down"
            return {
                "success": False,
                "active_url": None,
                "source": None,
                "local_frontend_ok": False,
                "probe_ok": False,
                "recovery_attempted": False,
                "recovery_success": None,
                "error_step": "local_port_down",
                "tunnel_pid": None,
                "ts": ts,
            }

        _log(f"local probe ok (port {_FRONTEND_PORT})")

        env_url = _read_env_url()
        _state["env_url"] = env_url

        # ── 2. Sprawdź runtime URL ────────────────────────────────────────
        if not force_recovery:
            rt_url = _read_runtime_url()
            _state["runtime_url"] = rt_url
            if rt_url:
                p = _probe_url(rt_url)
                if p["reachable"]:
                    _log(f"runtime URL ok: {rt_url}")
                    _state.update(
                        {
                            "active_url": rt_url,
                            "source": "runtime",
                            "probe_ok": True,
                            "probe_ts": ts,
                            "last_error": None,
                            "recovery_count": 0,  # reset po sukcesie
                            "tunnel_pid": _get_tunnel_pid(),
                        }
                    )
                    return {
                        "success": True,
                        "active_url": rt_url,
                        "source": "runtime",
                        "local_frontend_ok": True,
                        "probe_ok": True,
                        "recovery_attempted": False,
                        "recovery_success": None,
                        "error_step": None,
                        "tunnel_pid": _state["tunnel_pid"],
                        "ts": ts,
                    }
                else:
                    _log(f"runtime URL probe failed ({p['status']}): {rt_url}")

            # ── 3. Sprawdź URL z .env ─────────────────────────────────────
            if env_url:
                p = _probe_url(env_url)
                if p["reachable"]:
                    _log(f"env URL ok: {env_url}")
                    _state.update(
                        {
                            "active_url": env_url,
                            "source": "env",
                            "probe_ok": True,
                            "probe_ts": ts,
                            "last_error": None,
                            "recovery_count": 0,  # reset po sukcesie
                            "tunnel_pid": _get_tunnel_pid(),
                        }
                    )
                    return {
                        "success": True,
                        "active_url": env_url,
                        "source": "env",
                        "local_frontend_ok": True,
                        "probe_ok": True,
                        "recovery_attempted": False,
                        "recovery_success": None,
                        "error_step": None,
                        "tunnel_pid": _state["tunnel_pid"],
                        "ts": ts,
                    }
                else:
                    _log(f"env URL probe failed ({p['status']}): {env_url}")

        # ── 4. Self-healing: restart tunelu ────────────────────────────────
        if not cooldown_ok:
            wait_s = int(_RECOVERY_COOLDOWN - (time.time() - last_rec))
            _log(f"recovery cooldown — czekaj {wait_s}s")
            _state["last_error"] = f"recovery_cooldown ({wait_s}s)"
            return {
                "success": False,
                "active_url": None,
                "source": None,
                "local_frontend_ok": True,
                "probe_ok": False,
                "recovery_attempted": False,
                "recovery_success": None,
                "error_step": f"recovery_cooldown",
                "tunnel_pid": _get_tunnel_pid(),
                "ts": ts,
            }

        if _state["recovery_count"] >= _MAX_RECOVERY_ATTEMPTS:
            _log(
                f"max recovery attempts ({_MAX_RECOVERY_ATTEMPTS}) reached — rezygnuję"
            )
            _state["last_error"] = "max_recovery_attempts_reached"
            return {
                "success": False,
                "active_url": None,
                "source": None,
                "local_frontend_ok": True,
                "probe_ok": False,
                "recovery_attempted": True,
                "recovery_success": False,
                "error_step": "max_recovery_attempts_reached",
                "tunnel_pid": _get_tunnel_pid(),
                "ts": ts,
            }

        _log("restarting cloudflared (self-healing)...")
        _state["recovery_count"] += 1
        _state["last_recovery_at"] = time.time()

        # Restart przez systemd
        restarted = _restart_via_systemd()
        if not restarted:
            # Fallback: kill + próba bezpośrednio
            _kill_cloudflared()
            restarted = True  # zakładamy sukces kill

        if not restarted:
            _log("cloudflared restart FAILED")
            _state["last_error"] = "cloudflared_failed_to_start"
            _state["last_recovery_result"] = "failed"
            return {
                "success": False,
                "active_url": None,
                "source": None,
                "local_frontend_ok": True,
                "probe_ok": False,
                "recovery_attempted": True,
                "recovery_success": False,
                "error_step": "cloudflared_failed_to_start",
                "tunnel_pid": None,
                "ts": ts,
            }

        # ── 5. Czekaj na nowy URL ─────────────────────────────────────────
        new_url = _wait_for_new_url(timeout=35.0)
        if not new_url:
            _log("url_parse_failed — cloudflared nie zwrócił URL w czasie")
            _state["last_error"] = "url_parse_failed"
            _state["last_recovery_result"] = "failed"
            return {
                "success": False,
                "active_url": None,
                "source": None,
                "local_frontend_ok": True,
                "probe_ok": False,
                "recovery_attempted": True,
                "recovery_success": False,
                "error_step": "url_parse_failed",
                "tunnel_pid": _get_tunnel_pid(),
                "ts": ts,
            }

        # ── 6. Probe nowego URL ───────────────────────────────────────────
        _log(f"probing new URL: {new_url}")
        # Tunel potrzebuje do 15s na pełną propagację
        time.sleep(5)
        probe = _probe_url(new_url)
        if not probe["reachable"]:
            _log(f"probe failed ({probe['status']}): {new_url}")
            _state["last_error"] = f"probe_failed: {probe['debug']}"
            _state["last_recovery_result"] = "failed"
            return {
                "success": False,
                "active_url": None,
                "source": None,
                "local_frontend_ok": True,
                "probe_ok": False,
                "recovery_attempted": True,
                "recovery_success": False,
                "error_step": "probe_failed",
                "tunnel_pid": _get_tunnel_pid(),
                "ts": ts,
            }

        # ── 7. Sukces — zapisz URL ────────────────────────────────────────
        _log(f"recovery success! URL: {new_url}")
        env_updated = _update_env_url(new_url)
        _state.update(
            {
                "active_url": new_url,
                "source": "freshly_generated",
                "probe_ok": True,
                "probe_ts": ts,
                "runtime_url": new_url,
                "last_error": None,
                "last_recovery_result": "success",
                "recovery_count": 0,  # reset po sukcesie
                "tunnel_pid": _get_tunnel_pid(),
            }
        )

        return {
            "success": True,
            "active_url": new_url,
            "source": "freshly_generated",
            "local_frontend_ok": True,
            "probe_ok": True,
            "recovery_attempted": True,
            "recovery_success": True,
            "env_updated": env_updated,
            "error_step": None,
            "tunnel_pid": _state["tunnel_pid"],
            "ts": ts,
        }


def get_tunnel_status() -> dict:
    """
    Zwraca aktualny snapshot stanu tunelu (bez triggerowania healing).
    """
    with _lock:
        env_url = _read_env_url()
        rt_url = _read_runtime_url()
        pid = _get_tunnel_pid()

        return {
            "local_frontend_ok": _probe_local(_FRONTEND_PORT),
            "local_backend_ok": _probe_local(_BACKEND_PORT),
            "local_frontend_port": _FRONTEND_PORT,
            "local_backend_port": _BACKEND_PORT,
            "runtime_url": rt_url,
            "env_url": env_url,
            "active_url": _state.get("active_url"),
            "source": _state.get("source"),
            "probe_ok": _state.get("probe_ok", False),
            "probe_ts": _state.get("probe_ts"),
            "tunnel_pid": pid,
            "recovery_count": _state.get("recovery_count", 0),
            "last_recovery_at": (
                datetime.fromtimestamp(
                    _state["last_recovery_at"], tz=timezone.utc
                ).isoformat()
                if _state.get("last_recovery_at")
                else None
            ),
            "last_recovery_result": _state.get("last_recovery_result"),
            "last_error": _state.get("last_error"),
            "startup_done": _state.get("startup_done", False),
        }


def startup_ensure(timeout: float = 60.0) -> None:
    """
    Wywoływana przy starcie aplikacji (w osobnym wątku).
    Nie blokuje startu — zapewnia URL w tle.
    """
    _log("startup check — local port scan + tunnel probe")
    try:
        # Poczekaj chwilę, aż lokalny frontend zdąży wstać
        deadline = time.monotonic() + timeout
        while not _probe_local(_FRONTEND_PORT) and time.monotonic() < deadline:
            time.sleep(3)

        result = ensure_public_url()
        if result["success"]:
            _log(
                f"startup OK — active_url={result['active_url']} source={result['source']}"
            )
        else:
            _log(f"startup: brak publicznego URL — {result.get('error_step')}")
    except Exception as e:
        _log(f"startup_ensure error: {e}")
    finally:
        with _lock:
            _state["startup_done"] = True
