#!/usr/bin/env python3
"""
tunnel_doctor.py — Diagnostyka E2E tunelu Cloudflare dla RLdC Trading Bot.

Sprawdza w kolejności:
  1. Proces cloudflared (PID, uptime, komenda)
  2. Lokalny frontend (port 3000) — HTTP 200
  3. Lokalny backend (port 8000) — HTTP 200
  4. Runtime file (/tmp/rldc_tunnel_runtime.json) — URL + running
  5. Cloudflared.log — ostatni URL
  6. Publiczny URL — HTTP probe na / i /api/health
  7. Backend status endpoint — tunnel_manager state

Uruchomienie:
  python3 scripts/tunnel_doctor.py
  python3 scripts/tunnel_doctor.py --json
  python3 scripts/tunnel_doctor.py --fix   (próba auto-naprawy)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

_BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BASE_DIR / ".env"
_RUNTIME_FILE = Path("/tmp/rldc_tunnel_runtime.json")
_CF_LOG = _BASE_DIR / "logs/runtime/cloudflared.log"
_QT_LOG = _BASE_DIR / "logs/runtime/quicktunnel.log"
_BACKEND_PORT = 8000
_FRONTEND_PORT = 3000
_PROBE_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    try:
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.getenv(key, default)


def _probe(url: str, path: str = "/", timeout: int = _PROBE_TIMEOUT) -> dict:
    full = f"{url.rstrip('/')}{path}"
    try:
        r = requests.get(
            full,
            timeout=timeout,
            allow_redirects=True,
            verify=False,
            headers={"User-Agent": "RLdC-TunnelDoctor/1.0"},
        )
        return {
            "ok": r.status_code < 400,
            "status_code": r.status_code,
            "content_len": len(r.content),
            "url": full,
            "error": None,
        }
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "status_code": None,
            "url": full,
            "error": f"Timeout ({timeout}s)",
            "content_len": 0,
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "url": full,
            "error": str(e)[:80],
            "content_len": 0,
        }


def _get_cf_processes() -> list[dict]:
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        procs = []
        for line in result.stdout.splitlines():
            if "cloudflared tunnel" in line and "grep" not in line:
                parts = line.split()
                procs.append(
                    {
                        "pid": int(parts[1]) if len(parts) > 1 else None,
                        "cpu": parts[2] if len(parts) > 2 else "?",
                        "mem": parts[3] if len(parts) > 3 else "?",
                        "cmd": (
                            " ".join(parts[10:])[:100] if len(parts) > 10 else line[:80]
                        ),
                    }
                )
        return procs
    except Exception as e:
        return [{"error": str(e)}]


def _read_runtime_url() -> dict:
    try:
        if _RUNTIME_FILE.exists():
            data = json.loads(_RUNTIME_FILE.read_text())
            age_s = None
            if data.get("started_at"):
                try:
                    from datetime import timezone

                    started = datetime.fromisoformat(
                        data["started_at"].replace("Z", "+00:00")
                    )
                    age_s = int((datetime.now(timezone.utc) - started).total_seconds())
                except Exception:
                    pass
            return {
                "running": data.get("running", False),
                "frontend_url": data.get("frontend_url"),
                "api_url": data.get("api_url"),
                "started_at": data.get("started_at"),
                "age_s": age_s,
                "tunnel_type": data.get("tunnel_type"),
            }
    except Exception as e:
        return {"error": str(e)}
    return {"running": False}


def _read_cf_log_url() -> str | None:
    try:
        if _CF_LOG.exists():
            lines = _CF_LOG.read_text(errors="replace").splitlines()
            for line in reversed(lines):
                m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
                if m:
                    return m.group(0)
    except Exception:
        pass
    return None


def _get_backend_tunnel_status() -> dict | None:
    token = _env("ADMIN_TOKEN")
    if not token:
        return {"error": "ADMIN_TOKEN nie skonfigurowany w .env"}
    try:
        r = requests.get(
            f"http://localhost:{_BACKEND_PORT}/api/account/tunnel-status",
            headers={"X-Admin-Token": token},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}", "body": r.text[:200]}
    except Exception as e:
        return {"error": str(e)[:80]}


# ---------------------------------------------------------------------------
# Główna diagnostyka
# ---------------------------------------------------------------------------


def run_diagnostics() -> dict:
    results = {}
    issues = []

    print("\n=== RLdC Tunnel Doctor ===\n")

    # 1. Procesy cloudflared
    procs = _get_cf_processes()
    results["cloudflared_processes"] = procs
    if not procs:
        issues.append("KRYTYCZNY: Brak procesu cloudflared!")
        print("❌ [1] cloudflared: BRAK PROCESU")
    elif len(procs) > 1:
        issues.append(
            f"OSTRZEŻENIE: Aktywnych procesów cloudflared: {len(procs)} (powinien być 1)"
        )
        print(f"⚠️  [1] cloudflared: {len(procs)} procesów (za dużo!)")
        for p in procs:
            print(f"     PID={p.get('pid')} cmd={p.get('cmd','?')[:60]}")
    else:
        print(f"✅ [1] cloudflared: PID={procs[0].get('pid')} działa")

    # 2. Lokalny frontend
    local_fe = _probe(f"http://localhost:{_FRONTEND_PORT}")
    results["local_frontend"] = local_fe
    if local_fe["ok"]:
        print(
            f"✅ [2] Lokalny frontend (port {_FRONTEND_PORT}): HTTP {local_fe['status_code']}"
        )
    else:
        issues.append(f"KRYTYCZNY: Lokalny frontend DOWN — {local_fe['error']}")
        print(f"❌ [2] Lokalny frontend: {local_fe['error']}")

    # 3. Lokalny backend
    local_be = _probe(f"http://localhost:{_BACKEND_PORT}", "/health")
    results["local_backend"] = local_be
    if local_be["ok"]:
        print(
            f"✅ [3] Lokalny backend (port {_BACKEND_PORT}): HTTP {local_be['status_code']}"
        )
    else:
        issues.append(f"KRYTYCZNY: Lokalny backend DOWN — {local_be['error']}")
        print(f"❌ [3] Lokalny backend: {local_be['error']}")

    # 4. Runtime file
    rt = _read_runtime_url()
    results["runtime_file"] = rt
    rt_url = rt.get("frontend_url")
    if rt.get("running") and rt_url:
        age_str = (
            f", uruchomiony {rt.get('age_s', '?')}s temu" if rt.get("age_s") else ""
        )
        print(f"✅ [4] Runtime file: {rt_url}{age_str}")
    else:
        issues.append("OSTRZEŻENIE: Runtime file nie zawiera aktywnego URL")
        print(f"⚠️  [4] Runtime file: running={rt.get('running')}, url={rt_url}")

    # 5. Cloudflared log
    log_url = _read_cf_log_url()
    results["cf_log_url"] = log_url
    if log_url:
        same_as_rt = "(= runtime)" if log_url == rt_url else "(różny od runtime!)"
        print(f"ℹ️  [5] cloudflared.log URL: {log_url} {same_as_rt}")
    else:
        print(f"⚠️  [5] cloudflared.log: brak URL")

    # 6. Publiczny probe
    active_url = rt_url or log_url
    results["public_probe"] = {}
    if active_url:
        print(f"\n--- Probe publicznego URL: {active_url} ---")
        for path in ["/", "/api/health"]:
            p = _probe(active_url, path)
            results["public_probe"][path] = p
            if p["ok"]:
                print(f"  ✅ {path}: HTTP {p['status_code']} ({p['content_len']} B)")
            else:
                issues.append(
                    f"Publiczny probe FAIL: {path} → {p.get('status_code') or p.get('error')}"
                )
                print(f"  ❌ {path}: {p.get('status_code') or p.get('error')}")
    else:
        issues.append("KRYTYCZNY: Brak publicznego URL do sprawdzenia")
        print("❌ [6] Publiczny probe: brak URL do sprawdzenia")

    # 7. Backend tunnel_manager status
    print("\n--- Backend tunnel_manager status ---")
    be_status = _get_backend_tunnel_status()
    results["backend_tunnel_status"] = be_status
    if be_status and "data" in be_status:
        d = be_status["data"]
        probe_ok = d.get("probe_ok", False)
        rec_count = d.get("recovery_count", "?")
        last_err = d.get("last_error")
        act_url = d.get("active_url")
        if probe_ok:
            print(f"  ✅ probe_ok=True, active_url={act_url}")
            print(f"     source={d.get('source')}, recovery_count={rec_count}")
        else:
            issues.append(f"tunnel_manager: probe_ok=False, last_error={last_err}")
            print(f"  ❌ probe_ok=False")
            print(f"     last_error={last_err}")
            print(f"     recovery_count={rec_count}")
            if rec_count >= 3:
                issues.append(
                    "tunnel_manager: recovery_count >= 3 — self-healing ZABLOKOWANY"
                )
                print("  ❌ recovery_count >= 3 — self-healing zablokowany!")
    elif be_status:
        print(f"  ⚠️  Backend: {be_status.get('error', be_status)}")

    # Podsumowanie
    print("\n=== PODSUMOWANIE ===")
    results["issues"] = issues
    results["active_url"] = active_url
    results["overall_ok"] = len(issues) == 0

    if not issues:
        print(f"✅ Tunel sprawny. Publiczny URL: {active_url}")
    else:
        print(f"❌ Znaleziono {len(issues)} problem(ów):")
        for i in issues:
            print(f"   • {i}")

    return results


def run_fix() -> None:
    """Próba auto-naprawy: wymuś tunnel-heal przez API."""
    token = _env("ADMIN_TOKEN")
    if not token:
        print("❌ Brak ADMIN_TOKEN — nie mogę uruchomić tunnel-heal")
        return

    print("\n=== AUTO-FIX: wywołuję /api/account/tunnel-heal?force=true ===")
    try:
        r = requests.post(
            f"http://localhost:{_BACKEND_PORT}/api/account/tunnel-heal",
            headers={"X-Admin-Token": token},
            params={"force": "true"},
            timeout=90,
        )
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:300]}

        if r.status_code == 200 and data.get("success"):
            print(f"✅ Tunnel heal OK: {data.get('active_url') or data}")
        else:
            print(f"❌ Tunnel heal FAIL: HTTP {r.status_code}: {data}")
    except Exception as e:
        print(f"❌ Błąd połączenia: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RLdC Tunnel Doctor")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--fix", action="store_true", help="Attempt auto-fix via tunnel-heal API"
    )
    args = parser.parse_args()

    # Suppress SSL warning
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    results = run_diagnostics()

    if args.fix and not results["overall_ok"]:
        run_fix()
        print("\n--- Po naprawie ---")
        time.sleep(5)
        run_diagnostics()

    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(results, indent=2, default=str))

    sys.exit(0 if results["overall_ok"] else 1)
