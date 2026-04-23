import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""
os.environ["TRADING_MODE"] = "demo"
os.environ["ALLOW_LIVE_TRADING"] = "false"

_tmp_db = tempfile.NamedTemporaryFile(prefix="rldc_ctrl_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from backend.app import app
from backend.database import PendingOrder, SessionLocal
from backend.routers import control as control_router


class _Resp:
    def __init__(self, status_code=200, text="", json_data=None, headers=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data
        self.headers = headers or {}

    def json(self):
        return self._json_data or {}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_ip_diagnostics_cloudflare_tunnel(client, monkeypatch):
    monkeypatch.setenv("APP_DOMAIN", "bot.example.com")
    monkeypatch.setattr(
        "backend.routers.account._resolve_local_ip",
        lambda: {
            "hostname": "test-host",
            "local_ip": "10.0.0.10",
            "local_ips": ["10.0.0.10"],
        },
    )
    monkeypatch.setattr(
        "backend.routers.account._resolve_public_egress_ip",
        lambda: {"public_egress_ip": "203.0.113.55", "source": "ipify"},
    )

    def fake_dns(domain, record_type):
        if record_type == "CNAME":
            return ["abc.cfargotunnel.com"]
        if record_type == "NS":
            return ["lara.ns.cloudflare.com"]
        return []

    monkeypatch.setattr("backend.routers.account._dns_resolve_records", fake_dns)

    resp = client.get("/api/account/ip-diagnostics")
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("classification") == "tunnel"
    assert data.get("cloudflare_detected") is True
    assert data.get("tunnel_detected") is True
    assert data.get("public_egress_ip") == "203.0.113.55"


def test_ai_orchestrator_unpaid_openai_with_fallback(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key")
    monkeypatch.setenv("OPENAI_UNPAID", "true")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def fake_get(url, *args, **kwargs):
        if "/api/tags" in url:
            return _Resp(200, json_data={"models": [{"name": "qwen2.5:1.5b"}]})
        return _Resp(500, text="error")

    monkeypatch.setattr("backend.ai_orchestrator.requests.get", fake_get)

    resp = client.get("/api/account/ai-orchestrator-status?force=true")
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    providers = data.get("providers") or {}
    assert (providers.get("openai") or {}).get("status") in {
        "unpaid_or_disabled",
        "unpaid",
        "auth_failed",
        "error",
    }
    assert data.get("primary") in {"local", "heuristic"}


def test_ip_diagnostics_prefers_runtime_active_url(client, monkeypatch):
    class _ProbeResp:
        status_code = 200
        url = "https://active-runtime.trycloudflare.com"
        text = "<html>" + ("x" * 180) + "</html>"
        content = b"x" * 256

    monkeypatch.setenv("APP_DOMAIN", "stale-env.trycloudflare.com")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_URL", "https://stale-env.trycloudflare.com")
    monkeypatch.setattr(
        "backend.routers.account._resolve_local_ip",
        lambda: {
            "hostname": "test-host",
            "local_ip": "10.0.0.10",
            "local_ips": ["10.0.0.10"],
        },
    )
    monkeypatch.setattr(
        "backend.routers.account._resolve_public_egress_ip",
        lambda: {"public_egress_ip": "203.0.113.55", "source": "ipify"},
    )
    monkeypatch.setattr(
        "backend.routers.account._resolve_domain_proxy_info",
        lambda domain: {
            "configured_domain": domain,
            "dns": {},
            "classification": "tunnel",
            "cloudflare_detected": True,
            "proxied": True,
            "tunnel_detected": True,
            "notes": [],
        },
    )
    monkeypatch.setattr(
        "backend.routers.account._tunnel_mgr.get_tunnel_status",
        lambda: {"active_url": "https://active-runtime.trycloudflare.com"},
    )
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: _ProbeResp())

    resp = client.get("/api/account/ip-diagnostics")
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    url_status = data.get("url_status") or []
    assert url_status
    assert url_status[0].get("label") == "tunnel_runtime_active"
    assert url_status[0].get("url") == "https://active-runtime.trycloudflare.com"
    notes = data.get("notes") or []
    assert not any("CLOUDFLARE_TUNNEL_URL" in str(n) for n in notes)


def test_system_full_status_live_uses_binance_snapshot_count(client, monkeypatch):
    monkeypatch.setattr(
        "backend.runtime_settings.build_runtime_state",
        lambda db: {
            "trading_mode": "live",
            "allow_live_trading": True,
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "backend.portfolio_reconcile.get_reconcile_status",
        lambda db: {
            "last_live_reconcile": None,
            "currently_running": False,
            "total_manual_trades_synced": 0,
        },
    )
    monkeypatch.setattr(
        "backend.routers.positions._get_live_spot_positions",
        lambda db: [
            {"symbol": "BTCEUR", "quantity": 0.25, "source": "binance_spot"},
            {"symbol": "ETHEUR", "quantity": 0.0, "source": "binance_spot"},
            {"symbol": "SOLUSDC", "quantity": 1.0, "source": "db"},
        ],
    )

    resp = client.get("/api/system/full-status")
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("trading_mode") == "live"
    assert data.get("open_positions") == 1


def test_env_set_get_diff_and_rollback(client, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    backups_path = tmp_path / ".env_backups"
    env_path.write_text("AI_PROVIDER=auto\nTRADING_MODE=demo\n", encoding="utf-8")

    monkeypatch.setattr(control_router, "_ENV_PATH", env_path)
    monkeypatch.setattr(control_router, "_ENV_BACKUP_DIR", backups_path)

    set_resp = client.post(
        "/api/control/env/set",
        json={"key": "AI_PROVIDER", "value": "local", "actor": "pytest"},
    )
    assert set_resp.status_code == 200
    get_resp = client.get("/api/control/env/get", params={"key": "AI_PROVIDER"})
    assert get_resp.status_code == 200
    get_data = (get_resp.json() or {}).get("data") or {}
    assert get_data.get("process_value") == "local"

    diff_resp = client.get("/api/control/env/diff")
    assert diff_resp.status_code == 200

    rb_resp = client.post("/api/control/env/rollback")
    assert rb_resp.status_code == 200
    restored = env_path.read_text(encoding="utf-8")
    assert "AI_PROVIDER=auto" in restored


def test_command_router_buy_force_creates_pending(client):
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/control/command/execute",
        json={
            "text": "kup btc wymus",
            "source": "pytest",
            "execute_mode": "execute",
            "force": True,
        },
    )
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("action") == "buy_symbol"
    assert data.get("pending_order_id") is not None

    db = SessionLocal()
    try:
        po = (
            db.query(PendingOrder)
            .filter(PendingOrder.id == int(data["pending_order_id"]))
            .first()
        )
        assert po is not None
        assert po.side == "BUY"
    finally:
        db.close()


def test_command_router_buy_force_rejects_duplicate_active_pending(client):
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.commit()
    finally:
        db.close()

    first = client.post(
        "/api/control/command/execute",
        json={
            "text": "kup adausdc wymus",
            "source": "pytest",
            "execute_mode": "execute",
            "force": True,
        },
    )
    assert first.status_code == 200
    first_data = (first.json() or {}).get("data") or {}
    assert first_data.get("pending_order_id") is not None

    second = client.post(
        "/api/control/command/execute",
        json={
            "text": "kup adausdc wymus",
            "source": "pytest",
            "execute_mode": "execute",
            "force": True,
        },
    )
    assert second.status_code == 200
    second_data = (second.json() or {}).get("data") or {}
    assert second_data.get("execution") == "rejected"
    assert "istnieje już aktywne zlecenie" in str(second_data.get("summary") or "")
    assert second_data.get("pending_order_id") == first_data.get("pending_order_id")


def test_command_router_analyze_symbol(client):
    resp = client.post(
        "/api/control/command/execute",
        json={
            "text": "analizuj eth",
            "source": "pytest",
            "execute_mode": "advisory",
            "force": False,
        },
    )
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("action") == "analyze_symbol"


def test_terminal_permissions_and_guard(client):
    allow_resp = client.get("/api/control/terminal/permissions")
    assert allow_resp.status_code == 200

    blocked = client.post("/api/control/terminal/exec", json={"command": "python -V"})
    assert blocked.status_code == 403

    ok = client.post("/api/control/terminal/exec", json={"command": "echo hello"})
    assert ok.status_code == 200
    data = (ok.json() or {}).get("data") or {}
    assert "hello" in str(data.get("stdout") or "")


def test_env_secret_masking_safe_mode(client, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    backups_path = tmp_path / ".env_backups"
    env_path.write_text("OPENAI_API_KEY=sk-test-super-secret\n", encoding="utf-8")

    monkeypatch.setattr(control_router, "_ENV_PATH", env_path)
    monkeypatch.setattr(control_router, "_ENV_BACKUP_DIR", backups_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-super-secret")
    monkeypatch.setenv("SAFE_MODE_CONFIG_OUTPUT", "true")

    resp = client.get("/api/control/env/get", params={"key": "OPENAI_API_KEY"})
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("file_value") == "[REDACTED]"
    assert data.get("process_value") == "[REDACTED]"


def test_command_router_set_quote_mode_nl(client):
    resp = client.post(
        "/api/control/command/execute",
        json={
            "text": "handluj tylko na usdc",
            "source": "pytest",
            "execute_mode": "execute",
            "force": False,
        },
    )
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("action") == "set_quote_mode"
    assert data.get("execution") == "runtime_updated"
    assert "QUOTE_CURRENCY_MODE=USDC" in str(data.get("summary") or "")


# ---------------------------------------------------------------------------
# NL command pipeline tests
# ---------------------------------------------------------------------------


class TestParseSymbolFromText:
    """Testy _parse_symbol_from_text — deterministyczna rozdzielczość symboli."""

    def _mock_registry(self):
        return {
            "allowed_quotes": ["USDC", "EUR"],
            "metadata": {
                "PEPEUSDC": {"symbol": "PEPEUSDC", "base_asset": "PEPE", "quote_asset": "USDC"},
                "BTCEUR": {"symbol": "BTCEUR", "base_asset": "BTC", "quote_asset": "EUR"},
                "BTCUSDC": {"symbol": "BTCUSDC", "base_asset": "BTC", "quote_asset": "USDC"},
                "ETHUSDC": {"symbol": "ETHUSDC", "base_asset": "ETH", "quote_asset": "USDC"},
                "AVAXUSDC": {"symbol": "AVAXUSDC", "base_asset": "AVAX", "quote_asset": "USDC"},
                "SHIBUSDC": {"symbol": "SHIBUSDC", "base_asset": "SHIB", "quote_asset": "USDC"},
            },
            "quote_filtered_universe": [
                "PEPEUSDC",
                "BTCEUR",
                "BTCUSDC",
                "ETHUSDC",
                "AVAXUSDC",
                "SHIBUSDC",
            ],
            "tradable_universe": [
                "PEPEUSDC",
                "BTCEUR",
                "BTCUSDC",
                "ETHUSDC",
                "AVAXUSDC",
                "SHIBUSDC",
            ],
            "by_base_asset": {
                "PEPE": ["PEPEUSDC"],
                "BTC": ["BTCEUR", "BTCUSDC"],
                "ETH": ["ETHUSDC"],
                "AVAX": ["AVAXUSDC"],
                "SHIB": ["SHIBUSDC"],
            },
        }

    def _parse(self, text: str, monkeypatch):
        from backend.routers.control import _parse_symbol_from_text

        monkeypatch.setattr(
            "backend.routers.control.get_symbol_registry",
            lambda *args, **kwargs: self._mock_registry(),
        )
        return _parse_symbol_from_text(text)

    def test_bare_asset_resolves_via_registry(self, monkeypatch):
        """kup pepe → PEPEUSDC (PEPE jest w mapie, PRIMARY_QUOTE=USDC)"""
        result = self._parse("kup pepe", monkeypatch)
        assert result is not None
        assert result.startswith("PEPE")

    def test_explicit_full_symbol_usdc(self, monkeypatch):
        """kup PEPEUSDC → PEPEUSDC (nie PEPEUSDCEUR)"""
        assert self._parse("kup PEPEUSDC", monkeypatch) == "PEPEUSDC"

    def test_explicit_full_symbol_eur(self, monkeypatch):
        """kup btceur → BTCEUR"""
        assert self._parse("kup btceur", monkeypatch) == "BTCEUR"

    def test_explicit_za_eur_override(self, monkeypatch):
        """kup btc za eur → BTCEUR"""
        assert self._parse("kup btc za eur", monkeypatch) == "BTCEUR"

    def test_explicit_za_usdc_override(self, monkeypatch):
        """kup eth za usdc → ETHUSDC"""
        assert self._parse("kup eth za usdc", monkeypatch) == "ETHUSDC"

    def test_known_asset_eth(self, monkeypatch):
        """kup eth → ETH* (jakaś wersja z mapą)"""
        result = self._parse("kup eth", monkeypatch)
        assert result is not None
        assert "ETH" in result

    def test_inline_quote_suffix(self, monkeypatch):
        """kup eth usdc → ETHUSDC"""
        assert self._parse("kup eth usdc", monkeypatch) == "ETHUSDC"

    def test_avax_in_map(self, monkeypatch):
        """kup avax — AVAX powinno być w mapie po naszym fixie"""
        result = self._parse("kup avax", monkeypatch)
        assert result is not None
        assert result.startswith("AVAX")

    def test_shib_in_map(self, monkeypatch):
        """kup shib — powinno działać"""
        result = self._parse("kup shib", monkeypatch)
        assert result is not None
        assert result.startswith("SHIB")

    def test_sell_command_resolves_symbol(self, monkeypatch):
        """sprzedaj btc → BTCEUR lub BTCUSDC"""
        result = self._parse("sprzedaj btc", monkeypatch)
        assert result is not None
        assert result.startswith("BTC")

    def test_plain_text_does_not_create_fake_symbol(self, monkeypatch):
        assert self._parse("operator", monkeypatch) is None

    def test_system_command_does_not_create_fake_symbol(self, monkeypatch):
        assert self._parse("/logs", monkeypatch) is None


class TestCommandTraceEndpoint:
    """Testy /api/control/command-trace bez auth (publiczny endpoint)."""

    def test_command_trace_pepe(self, client):
        resp = client.post(
            "/api/control/command-trace",
            json={"text": "kup pepe", "mode": "demo"},
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        assert data.get("parsed_symbol") is not None
        assert "PEPE" in data["parsed_symbol"]
        assert data.get("asset_in_map") is True

    def test_command_trace_btceur(self, client):
        resp = client.post(
            "/api/control/command-trace",
            json={"text": "kup btceur"},
        )
        assert resp.status_code == 200


def test_parse_command_intent_distinguishes_system_commands(monkeypatch):
    from backend.routers.control import _parse_command_intent

    monkeypatch.setattr(
        "backend.routers.control.get_symbol_registry",
        lambda *args, **kwargs: {
            "allowed_quotes": ["USDC"],
            "metadata": {"BTCUSDC": {"symbol": "BTCUSDC", "base_asset": "BTC", "quote_asset": "USDC"}},
            "quote_filtered_universe": ["BTCUSDC"],
            "tradable_universe": ["BTCUSDC"],
            "by_base_asset": {"BTC": ["BTCUSDC"]},
        },
    )

    assert _parse_command_intent("/logs").get("action") == "logs_status"
    assert _parse_command_intent("/execution").get("action") == "execution_status"
    assert _parse_command_intent("/ai").get("action") == "ai_status"
    assert _parse_command_intent("/reconcile").get("action") == "reconcile_status"


def test_command_router_invalid_symbol_does_not_create_pending(client, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.control.get_symbol_registry",
        lambda *args, **kwargs: {
            "allowed_quotes": ["USDC"],
            "metadata": {"BTCUSDC": {"symbol": "BTCUSDC", "base_asset": "BTC", "quote_asset": "USDC"}},
            "quote_filtered_universe": ["BTCUSDC"],
            "tradable_universe": ["BTCUSDC"],
            "by_base_asset": {"BTC": ["BTCUSDC"]},
        },
    )
    resp = client.post(
        "/api/control/command/execute",
        json={
            "text": "kup operator",
            "source": "pytest",
            "execute_mode": "execute",
            "force": False,
        },
    )
    assert resp.status_code == 200
    data = (resp.json() or {}).get("data") or {}
    assert data.get("execution") == "invalid_symbol"
    assert data.get("pending_order_id") is None
        data = (resp.json() or {}).get("data") or {}
        assert data.get("parsed_symbol") == "BTCEUR"

    def test_command_trace_env_state(self, client):
        """Trace musi zawierać env state z QUOTE_CURRENCY_MODE i PRIMARY_QUOTE."""
        resp = client.post(
            "/api/control/command-trace",
            json={"text": "kup sol"},
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        env = data.get("env") or {}
        assert "QUOTE_CURRENCY_MODE_proc" in env
        assert "PRIMARY_QUOTE_proc" in env

    def test_command_trace_returns_buy_trace(self, client):
        """Trace musi zawierać wynik buy_trace z final_decision."""
        resp = client.post(
            "/api/control/command-trace",
            json={"text": "kup btc"},
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        bt = data.get("buy_trace") or {}
        assert "final_decision" in bt

    @pytest.mark.parametrize(
        "text,expected_type,expected_side,expected_symbol",
        [
            ("kup sol", "trade", "BUY", "SOL"),
            ("kup solusdc", "trade", "BUY", "SOLUSDC"),
            ("wymuś kup sol", "trade", "BUY", "SOL"),
            ("wymuś kup solusdc", "trade", "BUY", "SOLUSDC"),
            ("sprzedaj btc", "trade", "SELL", "BTC"),
            ("wymuś sprzedaj ethusdc", "trade", "SELL", "ETHUSDC"),
        ],
    )
    def test_command_trace_parser_schema_for_trading_commands(
        self, client, text, expected_type, expected_side, expected_symbol
    ):
        resp = client.post(
            "/api/control/command-trace",
            json={"text": text},
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        parser = data.get("parser") or {}
        assert parser.get("type") == expected_type
        assert parser.get("side") == expected_side
        assert parser.get("symbol") is not None
        assert expected_symbol in str(parser.get("symbol"))

    def test_command_trace_wymus_kup_solusdc_not_config(self, client):
        resp = client.post(
            "/api/control/command-trace",
            json={"text": "wymuś kup solusdc"},
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        parser = data.get("parser") or {}
        assert parser.get("type") == "trade"
        assert parser.get("config_key") is None
        assert parser.get("symbol") == "SOLUSDC"


class TestCommandExecuteNLPipeline:
    """Testy pełnego pipeline NL execute."""

    def test_execute_buy_symbol_rejected_no_signal(self, client):
        """Bez sygnału w DB: pipeline odrzuca z konkretnym kodem."""
        resp = client.post(
            "/api/control/command/execute",
            json={
                "text": "kup nearusdc",
                "source": "pytest",
                "execute_mode": "execute",
                "force": False,
            },
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        assert data.get("action") == "buy_symbol"
        assert data.get("symbol") is not None
        assert "NEAR" in data["symbol"]
        # Odrzucone z powodu brak sygnału lub filtry
        assert data.get("execution") in (
            "rejected",
            "rejected_by_pipeline",
        )
        # Musi być reason_code w summary
        assert data.get("summary") != ""

    def test_execute_buy_force_creates_confirmed_pending(self, client):
        """force=True zawsze tworzy PENDING_CONFIRMED PendingOrder (pomija filtry)."""
        db = SessionLocal()
        try:
            db.query(PendingOrder).delete()
            db.commit()
        finally:
            db.close()

        resp = client.post(
            "/api/control/command/execute",
            json={
                "text": "kup solusdc wymus",
                "source": "pytest",
                "execute_mode": "execute",
                "force": True,
            },
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        assert data.get("action") == "buy_symbol"
        pid = data.get("pending_order_id")
        assert pid is not None

        db = SessionLocal()
        try:
            po = db.query(PendingOrder).filter(PendingOrder.id == int(pid)).first()
            assert po is not None
            assert po.side == "BUY"
            assert po.status == "PENDING_CONFIRMED"
        finally:
            db.close()

    def test_execute_wymus_kup_solusdc_priority_trade_over_config(self, client):
        resp = client.post(
            "/api/control/command/execute",
            json={
                "text": "wymuś kup solusdc",
                "source": "pytest",
                "execute_mode": "execute",
                "force": False,
            },
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        assert data.get("action") == "buy_symbol"
        assert data.get("symbol") == "SOLUSDC"
        parser = data.get("parser") or {}
        assert parser.get("type") == "trade"
        assert parser.get("config_key") is None
        assert data.get("execution") in (
            "manual_force_pending_confirmed_queued",
            "rejected",
            "rejected_by_pipeline",
        )

    def test_execute_tryb_agresywny_runtime_updated(self, client):
        resp = client.post(
            "/api/control/command/execute",
            json={
                "text": "tryb agresywny",
                "source": "pytest",
                "execute_mode": "execute",
                "force": False,
            },
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        assert data.get("action") == "set_aggressive_mode"
        assert data.get("execution") == "runtime_updated"
        parser = data.get("parser") or {}
        assert parser.get("type") == "config"
        assert parser.get("config_key") == "trading_aggressiveness"
        assert parser.get("config_value") == "aggressive"

    def test_execute_wymus_sprzedaj_ethusdc_manual_force_path(self, client):
        resp = client.post(
            "/api/control/command/execute",
            json={
                "text": "wymuś sprzedaj ethusdc",
                "source": "pytest",
                "execute_mode": "execute",
                "force": False,
            },
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        assert data.get("action") == "sell_symbol"
        assert (data.get("parser") or {}).get("force") is True
        assert data.get("execution_flow") == "MANUAL_FORCE"

    def test_execute_buy_symbol_parsed_correctly(self, client):
        """Parsing symbolu w execute mode musi zwrócić poprawny symbol."""
        for text, expected_prefix in [
            ("kup btc wymus", "BTC"),
            ("kup ETHUSDC wymus", "ETH"),
            ("kup doge wymus", "DOGE"),
        ]:
            resp = client.post(
                "/api/control/command/execute",
                json={
                    "text": text,
                    "source": "pytest",
                    "execute_mode": "execute",
                    "force": True,
                },
            )
            assert resp.status_code == 200
            data = (resp.json() or {}).get("data") or {}
            assert data.get("symbol", "").startswith(
                expected_prefix
            ), f"Text {text!r} → got symbol {data.get('symbol')!r}, expected prefix {expected_prefix!r}"

    def test_advisory_mode_no_pending_created(self, client):
        """Tryb advisory NIE tworzy PendingOrder."""
        import time

        before = time.time()
        resp = client.post(
            "/api/control/command/execute",
            json={
                "text": "kup btc",
                "source": "pytest",
                "execute_mode": "advisory",
                "force": False,
            },
        )
        assert resp.status_code == 200
        data = (resp.json() or {}).get("data") or {}
        # W advisory mode nie powinno być pending_order_id
        assert data.get("pending_order_id") is None
