import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis import _build_ai_input_payload  # noqa: E402
from backend.collector import DataCollector  # noqa: E402
from backend.database import MarketData, Signal, utc_now_naive  # noqa: E402
from backend.routers import control as control_router  # noqa: E402


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, market_rows, signal_rows):
        self.market_rows = market_rows
        self.signal_rows = signal_rows

    def query(self, model):
        if model is MarketData:
            return _FakeQuery(self.market_rows)
        if model is Signal:
            return _FakeQuery(self.signal_rows)
        return _FakeQuery([])


def test_indicator_confidence_fallback_is_never_zero():
    collector = object.__new__(DataCollector)
    conf = collector._calculate_confidence_from_indicators(
        signal_type="BUY",
        rsi=42.0,
        ema20=101.0,
        ema50=99.0,
        volume_ratio=1.3,
        momentum_hist=0.8,
    )
    assert conf > 0.0
    assert 0.35 <= conf <= 0.95


def test_dynamic_min_confidence_ai_state():
    collector = object.__new__(DataCollector)
    assert collector._dynamic_min_confidence(ai_failed=True) == 0.4
    assert collector._dynamic_min_confidence(ai_failed=False) == 0.6


def test_ai_payload_contains_required_market_fields():
    insights = [
        {
            "symbol": "BTCEUR",
            "timeframe": "1h",
            "signal_type": "BUY",
            "confidence": 0.72,
            "price": 100000.0,
            "candles": [99000.0, 99500.0, 100000.0],
            "trend": "UP",
            "reason": "test",
            "indicators": {
                "rsi_14": 51.0,
                "ema_20": 99900.0,
                "ema_50": 99500.0,
                "volume": 1234.0,
                "volume_ratio": 1.1,
            },
        }
    ]
    payload = _build_ai_input_payload(insights)
    assert len(payload) == 1
    row = payload[0]
    assert row["price"] == 100000.0
    assert row["candles"] == [99000.0, 99500.0, 100000.0]
    assert row["rsi"] == 51.0
    assert row["ema20"] == 99900.0
    assert row["ema50"] == 99500.0
    assert row["volume"] == 1234.0
    assert row["trend"] == "UP"


def test_chat_context_uses_live_market_and_opportunities(monkeypatch):
    monkeypatch.setattr(
        control_router,
        "get_ai_orchestrator_status",
        lambda force=False: {"primary": "heuristic", "fallback_active": True},
    )

    now = utc_now_naive()
    md = MarketData(symbol="BTCEUR", price=101000.0, volume=2500.0, timestamp=now)
    sig = Signal(
        symbol="BTCEUR",
        signal_type="BUY",
        confidence=0.81,
        price=101000.0,
        indicators=json.dumps({"rsi_14": 48.0, "ema_20": 100900.0, "ema_50": 100500.0}),
        reason="test",
        timestamp=now,
    )

    db = _FakeDb([md], [sig])
    context_json = control_router._build_ai_chat_context(db, source="telegram")
    data = json.loads(context_json)

    assert data["market_scan_snapshot"]
    assert data["top_opportunities"]
    market = data["market_scan_snapshot"][0]
    opp = data["top_opportunities"][0]
    assert market["symbol"] == "BTCEUR"
    assert market["price"] == pytest.approx(101000.0)
    assert opp["symbol"] == "BTCEUR"
    assert opp["confidence"] == pytest.approx(0.81)
