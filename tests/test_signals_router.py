from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database import Base, Kline, utc_now_naive
from backend.routers.signals import _build_live_signals


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _insert_kline(db_session, symbol: str, hours_ago: float) -> None:
    open_time = utc_now_naive() - timedelta(hours=hours_ago)
    db_session.add(
        Kline(
            symbol=symbol,
            timeframe="1h",
            open_time=open_time,
            close_time=open_time + timedelta(hours=1),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000.0,
        )
    )
    db_session.commit()


def _patch_live_signal_deps(monkeypatch: pytest.MonkeyPatch, get_regime_indicators_fn):
    monkeypatch.setattr("backend.runtime_settings.get_runtime_config", lambda _db: {})
    monkeypatch.setattr("backend.risk.estimate_trade_costs", lambda _cfg: {})
    monkeypatch.setattr(
        "backend.analysis.get_regime_indicators",
        get_regime_indicators_fn,
    )
    monkeypatch.setattr(
        "backend.risk.detect_regime",
        lambda **_kwargs: SimpleNamespace(
            regime="TREND_UP", confidence=0.75, reasons=["test_regime"]
        ),
    )
    monkeypatch.setattr(
        "backend.risk.validate_long_entry",
        lambda **_kwargs: SimpleNamespace(allowed=True, reasons=["ok"], score=80.0),
    )
    monkeypatch.setattr(
        "backend.risk.build_long_plan",
        lambda **_kwargs: {"tp1": 101.0, "tp2": 102.0, "sl": 99.0},
    )


def test_build_live_signals_skips_stale_klines(
    monkeypatch: pytest.MonkeyPatch, db_session
):
    os.environ["MAX_KLINE_AGE_HOURS"] = "4"
    _insert_kline(db_session, symbol="ARBUSDC", hours_ago=12)

    calls = {"count": 0}

    def _get_regime_indicators(_db, _symbol):
        calls["count"] += 1
        return {
            "close": 100.0,
            "rsi_15m": 55.0,
            "ema21_15m": 100.0,
            "ema50_15m": 99.0,
            "ema21_1h": 100.0,
            "ema50_1h": 99.0,
            "ema200_1h": 95.0,
            "macd_hist_15m": 0.1,
            "volume_ratio_15m": 1.2,
            "atr_1h": 1.0,
        }

    _patch_live_signal_deps(monkeypatch, _get_regime_indicators)
    # W obecnej logice stale klines są najpierw odświeżane on-demand.
    # Aby przetestować ścieżkę "skip", wymuszamy niepowodzenie refreshu.
    monkeypatch.setattr(
        "backend.routers.signals._fetch_and_store_klines_ondemand",
        lambda *_args, **_kwargs: False,
    )
    results = _build_live_signals(db_session, ["ARBUSDC"], limit=10)

    assert results == []
    assert calls["count"] == 0


def test_build_live_signals_keeps_fresh_klines(
    monkeypatch: pytest.MonkeyPatch, db_session
):
    os.environ["MAX_KLINE_AGE_HOURS"] = "4"
    _insert_kline(db_session, symbol="ARBUSDC", hours_ago=1)

    def _get_regime_indicators(_db, _symbol):
        return {
            "close": 100.0,
            "rsi_15m": 55.0,
            "ema21_15m": 100.0,
            "ema50_15m": 99.0,
            "ema21_1h": 100.0,
            "ema50_1h": 99.0,
            "ema200_1h": 95.0,
            "macd_hist_15m": 0.1,
            "volume_ratio_15m": 1.2,
            "atr_1h": 1.0,
        }

    _patch_live_signal_deps(monkeypatch, _get_regime_indicators)
    results = _build_live_signals(db_session, ["ARBUSDC"], limit=10)

    assert len(results) == 1
    assert results[0]["symbol"] == "ARBUSDC"
    assert results[0]["source"] == "live_analysis"
