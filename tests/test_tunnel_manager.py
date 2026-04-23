"""
tests/test_tunnel_manager.py — testy self-healing tunnel managera.

Scenariusze:
1. `.env` ma stary URL, runtime nie ma URL → generuje nowy i zapisuje.
2. runtime ma martwy URL → restart tunelu i podmiana URL.
3. lokalny port nie działa → brak prób publikacji, czytelny error_step.
4. cloudflared startuje, ale nie oddaje URL w czasie → url_parse_failed.
5. nowy URL działa → zwracany jako active_url.
6. reset_state usuwa recovery_count po sukcesie.
7. cooldown między recovery działa poprawnie.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Patch env przed importem tunnel_manager (inaczej próbuje pisać do /home/rldc/.env)
os.environ.setdefault("DISABLE_COLLECTOR", "true")


@pytest.fixture(autouse=True)
def reset_tunnel_state():
    """Czyść globalny stan tunelu przed każdym testem."""
    import backend.tunnel_manager as tm

    with tm._lock:
        tm._state.update(
            {
                "active_url": None,
                "source": None,
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
        )
    yield


# ---------------------------------------------------------------------------
# Test 1: lokalny port DOWN → error_step=local_port_down, brak recovery
# ---------------------------------------------------------------------------
def test_local_port_down():
    """Scenariusz 3: lokalny frontend nie działa → natychmiastowy błąd, bez recovery."""
    import backend.tunnel_manager as tm

    with patch.object(tm, "_probe_local", return_value=False):
        result = tm.ensure_public_url()

    assert result["success"] is False
    assert result["error_step"] == "local_port_down"
    assert result["local_frontend_ok"] is False
    assert result["recovery_attempted"] is False


# ---------------------------------------------------------------------------
# Test 2: runtime URL działa → zwraca natychmiast OK
# ---------------------------------------------------------------------------
def test_runtime_url_ok():
    """Runtime URL jest osiągalny → success True, source=runtime."""
    import backend.tunnel_manager as tm

    good_url = "https://good-url.trycloudflare.com"

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(tm, "_read_runtime_url", return_value=good_url),
        patch.object(
            tm,
            "_probe_url",
            return_value={
                "reachable": True,
                "status": "reachable",
                "status_code": 200,
                "final_url": good_url,
                "content_len": 500,
                "cf_error": False,
                "cf_error_code": None,
                "debug": "HTTP 200, 500 B",
            },
        ),
        patch.object(tm, "_get_tunnel_pid", return_value=12345),
    ):
        result = tm.ensure_public_url()

    assert result["success"] is True
    assert result["source"] == "runtime"
    assert result["active_url"] == good_url
    assert result["probe_ok"] is True
    assert result["recovery_attempted"] is False


# ---------------------------------------------------------------------------
# Test 3: env URL działa, runtime nie → success z env
# ---------------------------------------------------------------------------
def test_env_url_fallback_ok():
    """Runtime URL dead, env URL alive → success, source=env."""
    import backend.tunnel_manager as tm

    dead_url = "https://dead.trycloudflare.com"
    env_url = "https://env-url.trycloudflare.com"

    _probe_responses = {
        dead_url: {
            "reachable": False,
            "status": "http_404",
            "status_code": 404,
            "final_url": dead_url,
            "content_len": 0,
            "cf_error": False,
            "cf_error_code": None,
            "debug": "HTTP 404",
        },
        env_url: {
            "reachable": True,
            "status": "reachable",
            "status_code": 200,
            "final_url": env_url,
            "content_len": 1000,
            "cf_error": False,
            "cf_error_code": None,
            "debug": "HTTP 200, 1000 B",
        },
    }

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(tm, "_read_runtime_url", return_value=dead_url),
        patch.object(tm, "_read_env_url", return_value=env_url),
        patch.object(tm, "_probe_url", side_effect=lambda url: _probe_responses[url]),
        patch.object(tm, "_get_tunnel_pid", return_value=None),
    ):
        result = tm.ensure_public_url()

    assert result["success"] is True
    assert result["source"] == "env"
    assert result["active_url"] == env_url


# ---------------------------------------------------------------------------
# Test 4: runtime + env dead → self-healing, nowy URL działa
# ---------------------------------------------------------------------------
def test_self_healing_success():
    """Scenariusz 5: oba URL dead → restart → nowy URL probe OK → zwraca active_url."""
    import backend.tunnel_manager as tm

    dead_url = "https://dead.trycloudflare.com"
    new_url = "https://new-fresh.trycloudflare.com"

    _dead_probe = {
        "reachable": False,
        "status": "error",
        "status_code": None,
        "final_url": dead_url,
        "content_len": 0,
        "cf_error": False,
        "cf_error_code": None,
        "debug": "Connection refused",
    }
    _new_probe = {
        "reachable": True,
        "status": "reachable",
        "status_code": 200,
        "final_url": new_url,
        "content_len": 800,
        "cf_error": False,
        "cf_error_code": None,
        "debug": "HTTP 200, 800 B",
    }

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(tm, "_read_runtime_url", return_value=dead_url),
        patch.object(tm, "_read_env_url", return_value=dead_url),
        patch.object(
            tm,
            "_probe_url",
            side_effect=lambda url: _dead_probe if "dead" in url else _new_probe,
        ),
        patch.object(tm, "_restart_via_systemd", return_value=True),
        patch.object(tm, "_wait_for_new_url", return_value=new_url),
        patch.object(tm, "_update_env_url", return_value=True),
        patch.object(tm, "_get_tunnel_pid", return_value=99999),
        patch("time.sleep"),
    ):
        result = tm.ensure_public_url()

    assert result["success"] is True
    assert result["source"] == "freshly_generated"
    assert result["active_url"] == new_url
    assert result["recovery_attempted"] is True
    assert result["recovery_success"] is True
    assert result.get("env_updated") is True


# ---------------------------------------------------------------------------
# Test 5: cloudflared startuje ale URL nie przychodzi → url_parse_failed
# ---------------------------------------------------------------------------
def test_url_parse_failed():
    """Scenariusz 4: cloudflared restart OK ale nie zwraca URL → url_parse_failed."""
    import backend.tunnel_manager as tm

    dead_url = "https://dead.trycloudflare.com"
    _dead_probe = {
        "reachable": False,
        "status": "error",
        "status_code": None,
        "final_url": dead_url,
        "content_len": 0,
        "cf_error": False,
        "cf_error_code": None,
        "debug": "error",
    }

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(tm, "_read_runtime_url", return_value=dead_url),
        patch.object(tm, "_read_env_url", return_value=None),
        patch.object(tm, "_probe_url", return_value=_dead_probe),
        patch.object(tm, "_restart_via_systemd", return_value=True),
        patch.object(tm, "_wait_for_new_url", return_value=None),  # timeout — brak URL
        patch.object(tm, "_get_tunnel_pid", return_value=None),
        patch("time.sleep"),
    ):
        result = tm.ensure_public_url()

    assert result["success"] is False
    assert result["error_step"] == "url_parse_failed"
    assert result["recovery_attempted"] is True
    assert result["recovery_success"] is False


# ---------------------------------------------------------------------------
# Test 6: recovery cooldown — zbyt szybka kolejna próba
# ---------------------------------------------------------------------------
def test_recovery_cooldown():
    """Scenariusz 7: cooldown między recovery ─ druga próba w ciągu <120s zablokowana."""
    import backend.tunnel_manager as tm

    dead_probe = {
        "reachable": False,
        "status": "error",
        "status_code": None,
        "final_url": "x",
        "content_len": 0,
        "cf_error": False,
        "cf_error_code": None,
        "debug": "error",
    }

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(tm, "_read_runtime_url", return_value=None),
        patch.object(tm, "_read_env_url", return_value=None),
        patch.object(tm, "_probe_url", return_value=dead_probe),
        patch.object(tm, "_restart_via_systemd", return_value=True),
        patch.object(tm, "_wait_for_new_url", return_value=None),
        patch.object(tm, "_get_tunnel_pid", return_value=None),
        patch("time.sleep"),
    ):
        # Pierwsza recovery → url_parse_failed (no url returned)
        r1 = tm.ensure_public_url()
        assert r1["error_step"] == "url_parse_failed"

        # Od razu kolejna próba → cooldown
        r2 = tm.ensure_public_url()
        assert r2["error_step"] == "recovery_cooldown"
        assert r2["recovery_attempted"] is False


# ---------------------------------------------------------------------------
# Test 7: force=True omija cooldown
# ---------------------------------------------------------------------------
def test_force_bypasses_cooldown():
    """force=True omija cooldown między recovery."""
    import backend.tunnel_manager as tm

    new_url = "https://fresh-forced.trycloudflare.com"
    dead_probe = {
        "reachable": False,
        "status": "error",
        "status_code": None,
        "final_url": "x",
        "content_len": 0,
        "cf_error": False,
        "cf_error_code": None,
        "debug": "error",
    }
    good_probe = {
        "reachable": True,
        "status": "reachable",
        "status_code": 200,
        "final_url": new_url,
        "content_len": 800,
        "cf_error": False,
        "cf_error_code": None,
        "debug": "OK",
    }

    # Ręcznie ustaw że recovery był niedawno (cooldown aktywny)
    with tm._lock:
        tm._state["last_recovery_at"] = time.time() - 10  # 10s temu

    def _probe_side(url):
        return good_probe if url == new_url else dead_probe

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(tm, "_read_runtime_url", return_value=None),
        patch.object(tm, "_read_env_url", return_value=None),
        patch.object(tm, "_probe_url", side_effect=_probe_side),
        patch.object(tm, "_restart_via_systemd", return_value=True),
        patch.object(tm, "_wait_for_new_url", return_value=new_url),
        patch.object(tm, "_update_env_url", return_value=True),
        patch.object(tm, "_get_tunnel_pid", return_value=111),
        patch("time.sleep"),
    ):
        result = tm.ensure_public_url(force_recovery=True)

    assert result["success"] is True
    assert result["active_url"] == new_url


# ---------------------------------------------------------------------------
# Test 8: _read_runtime_url parsuje pliki poprawnie
# ---------------------------------------------------------------------------
def test_read_runtime_url_ok(tmp_path):
    """_read_runtime_url czyta URL z pliku runtime gdy running=true."""
    import backend.tunnel_manager as tm

    runtime = tmp_path / "tunnel_runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "running": True,
                "frontend_url": "https://some-url.trycloudflare.com",
                "api_url": None,
                "started_at": "2026-04-18T10:00:00Z",
            }
        )
    )

    with patch.object(tm, "_RUNTIME_FILE", runtime):
        url = tm._read_runtime_url()

    assert url == "https://some-url.trycloudflare.com"


def test_read_runtime_url_running_false(tmp_path):
    """_read_runtime_url zwraca None gdy running=false."""
    import backend.tunnel_manager as tm

    runtime = tmp_path / "tunnel_runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "running": False,
                "frontend_url": "https://old.trycloudflare.com",
            }
        )
    )

    with patch.object(tm, "_RUNTIME_FILE", runtime):
        url = tm._read_runtime_url()

    assert url is None


# ---------------------------------------------------------------------------
# Test 9: _update_env_url idempotentna aktualizacja
# ---------------------------------------------------------------------------
def test_update_env_url(tmp_path):
    """_update_env_url aktualizuje APP_DOMAIN i CLOUDFLARE_TUNNEL_URL."""
    import backend.tunnel_manager as tm

    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOME_VAR=abc\n"
        "CLOUDFLARE_TUNNEL_URL=https://old.trycloudflare.com\n"
        "APP_DOMAIN=old.trycloudflare.com\n"
        "ANOTHER=xyz\n"
    )

    new_url = "https://new-fresh.trycloudflare.com"
    with patch.object(tm, "_ENV_FILE", env_file):
        ok = tm._update_env_url(new_url)

    assert ok is True
    content = env_file.read_text()
    assert f"CLOUDFLARE_TUNNEL_URL={new_url}" in content
    assert "APP_DOMAIN=new-fresh.trycloudflare.com" in content
    assert "SOME_VAR=abc" in content
    assert "ANOTHER=xyz" in content
    assert "old.trycloudflare.com" not in content


def test_update_env_url_adds_missing_vars(tmp_path):
    """_update_env_url dodaje brakujące wpisy APP_DOMAIN i CLOUDFLARE_TUNNEL_URL."""
    import backend.tunnel_manager as tm

    env_file = tmp_path / ".env"
    env_file.write_text("SOME_VAR=value\n")

    new_url = "https://brand-new.trycloudflare.com"
    with patch.object(tm, "_ENV_FILE", env_file):
        ok = tm._update_env_url(new_url)

    assert ok is True
    content = env_file.read_text()
    assert f"CLOUDFLARE_TUNNEL_URL={new_url}" in content
    assert "APP_DOMAIN=brand-new.trycloudflare.com" in content


# ---------------------------------------------------------------------------
# Test 10: get_tunnel_status — zwraca właściwe pola
# ---------------------------------------------------------------------------
def test_get_tunnel_status():
    """get_tunnel_status zwraca snapshot ze wszystkimi wymaganymi polami."""
    import backend.tunnel_manager as tm

    with (
        patch.object(tm, "_probe_local", return_value=True),
        patch.object(
            tm, "_read_runtime_url", return_value="https://rt.trycloudflare.com"
        ),
        patch.object(tm, "_read_env_url", return_value="https://env.trycloudflare.com"),
        patch.object(tm, "_get_tunnel_pid", return_value=42),
    ):
        status = tm.get_tunnel_status()

    required_keys = [
        "local_frontend_ok",
        "local_backend_ok",
        "runtime_url",
        "env_url",
        "active_url",
        "source",
        "probe_ok",
        "probe_ts",
        "tunnel_pid",
        "recovery_count",
        "last_recovery_at",
        "last_recovery_result",
        "last_error",
        "startup_done",
    ]
    for key in required_keys:
        assert key in status, f"Brakuje klucza: {key}"

    assert status["local_frontend_ok"] is True
    assert status["tunnel_pid"] == 42
    assert status["runtime_url"] == "https://rt.trycloudflare.com"
