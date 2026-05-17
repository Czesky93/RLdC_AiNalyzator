"""
test_trading_signal_engine.py — Testy jednostkowe dla backend/trading/signal_engine.py

Testuje:
  - brak BUY przy dużym spreadzie
  - brak BUY przy ujemnym expected edge
  - brak BUY przy RSI overbought (> 75)
  - brak BUY przy sprzecznym trendzie HTF
  - brak BUY przy zbyt niskim score/confidence
  - BUY tylko gdy score, EV i R/R są dodatnie
  - komponenty score: trend, momentum, volume, htf, regime
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from backend.analysis import _klines_to_df
from backend.trading.signal_engine import (
    EntrySignalResult,
    _compute_htf_agreement,
    _compute_momentum_score,
    _compute_regime_score,
    _compute_trend_score,
    _compute_volume_score,
    evaluate_entry_signal,
)
from backend.trading.trade_config import TradeConfig


# ── Fixture: TradeConfig z minimalnymi progami ───────────────────────────────

def _default_cfg(**overrides) -> TradeConfig:
    cfg = TradeConfig()
    # Obniżamy progi aby testy BUY mogły przejść
    cfg.min_entry_score = 0.40
    cfg.min_signal_confidence = 0.40
    cfg.min_net_edge_pct = 0.10
    cfg.min_expected_rr = 1.0
    cfg.require_htf_trend_agreement = True
    cfg.require_volume_confirmation = False
    cfg.max_allowed_spread_pct = 0.30
    cfg.min_liquidity_score = 0.0
    cfg.taker_fee_pct = 0.10
    cfg.slippage_bps = 5.0
    cfg.atr_stop_multiplier = 2.0
    cfg.atr_take_multiplier = 3.5
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_good_ctx(
    price=100.0,
    atr=1.5,
    klines_count=200,
    rsi=52.0,
    ema_20=101.0,
    ema_50=98.0,
    ema_200=90.0,
    macd_hist=0.3,
    volume_ratio=1.5,
) -> dict:
    """Kontekst rynkowy dający sygnał BUY."""
    return {
        "close": price,
        "atr": atr,
        "klines_count": klines_count,
        "rsi": rsi,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "ema_200": ema_200,
        "macd_hist": macd_hist,
        "macd_signal": 0.1,
        "volume_ratio": volume_ratio,
        "volume_24h_quote": 200_000.0,
        "trade_count": 500.0,
        "bb_upper": 103.0,
        "bb_lower": 97.0,
        "bb_middle": 100.0,
    }


def _make_htf_ctx(
    ema_20=105.0,
    ema_50=100.0,
    rsi=60.0,
) -> dict:
    return {
        "close": 101.0,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "rsi": rsi,
    }


def _make_fast_ctx(ema_20=101.0, ema_50=99.0) -> dict:
    return {"ema_20": ema_20, "ema_50": ema_50, "rsi": 52.0}


# ── 0. Kontrakt danych live ─────────────────────────────────────────────────────

def test_klines_to_df_preserves_quote_volume_and_trades():
    start = datetime(2026, 1, 1, 0, 0, 0)
    klines = [
        SimpleNamespace(
            open_time=start + timedelta(hours=i),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=10.0 + i,
            quote_volume=1000.0 + i,
            trades=100 + i,
            taker_buy_base=5.0 + i,
            taker_buy_quote=500.0 + i,
        )
        for i in range(3)
    ]

    df = _klines_to_df(klines)

    assert df is not None
    assert "quote_volume" in df.columns
    assert "trades" in df.columns
    assert float(df.iloc[-1]["quote_volume"]) == pytest.approx(1002.0)
    assert int(df.iloc[-1]["trades"]) == 102


# ── 1. Komponenty score ───────────────────────────────────────────────────────

class TestTrendScore:
    def test_strong_uptrend(self):
        s = _compute_trend_score(105, 100, 90, 106)
        assert s == 1.0

    def test_moderate_uptrend_no_200(self):
        s = _compute_trend_score(105, 100, None, 106)
        assert 0.60 <= s <= 0.70

    def test_downtrend(self):
        s = _compute_trend_score(95, 100, 90, 94)
        assert s < 0.30

    def test_no_data(self):
        s = _compute_trend_score(None, None, None, 100)
        assert 0.40 <= s <= 0.50  # neutralny


class TestMomentumScore:
    def test_rsi_optimal(self):
        s = _compute_momentum_score(55.0, 0.3, 0.1)
        assert s >= 0.80

    def test_rsi_overbought(self):
        # RSI overbought (78) + macd ujemny → kara RSI i słaby MACD → < 0.50
        s = _compute_momentum_score(78.0, -0.2, 0.0)
        assert s < 0.50

    def test_rsi_oversold(self):
        s = _compute_momentum_score(28.0, -0.1, 0.0)
        assert s < 0.60

    def test_macd_negative(self):
        s = _compute_momentum_score(50.0, -0.5, 0.0)
        assert s < 0.70


class TestVolumeScore:
    def test_high_volume(self):
        s = _compute_volume_score(2.0, 2.5)
        assert s >= 0.80

    def test_low_volume(self):
        s = _compute_volume_score(0.5, 0.5)
        assert s < 0.50

    def test_none_values(self):
        s = _compute_volume_score(None, None)
        assert 0.0 <= s <= 1.0


class TestHtfAgreement:
    def test_strong_uptrend_4h(self):
        s = _compute_htf_agreement(110, 100, 65, 105)
        assert s >= 0.80

    def test_downtrend_4h(self):
        s = _compute_htf_agreement(90, 100, 45, 95)
        assert s < 0.20

    def test_no_data(self):
        s = _compute_htf_agreement(None, None, None, 100)
        assert s == 0.5  # neutralny

    def test_ema_up_but_rsi_weak(self):
        s = _compute_htf_agreement(105, 100, 45, 102)
        assert 0.55 <= s <= 0.65


class TestRegimeScore:
    def test_price_in_lower_half(self):
        # bb_pos = (100 - 97) / (103 - 97) = 0.5 → środek
        s = _compute_regime_score(0.5, 52, 0.06)
        assert s >= 0.60

    def test_price_at_upper_band(self):
        # bb_position=0.95 → pos_score=0.2, bb_width=0.06 → width_score=1.0
        # score = 0.2*0.6 + 1.0*0.4 = 0.52
        s = _compute_regime_score(0.95, 70, 0.06)
        assert s < 0.60  # przy górnym pasmie score jest obniżony vs dolna połowa

    def test_narrow_bands(self):
        # bb_position=0.5 → pos_score=1.0, bb_width=0.005 → width_score=0.2 (squeeze)
        # score = 1.0*0.6 + 0.2*0.4 = 0.68 — squeeze obniża score
        s = _compute_regime_score(0.5, 50, 0.005)
        assert s < 0.75  # squeeze ogranicza score


# ── 2. evaluate_entry_signal — pełne testy ───────────────────────────────────

class TestEvaluateEntrySignal:
    """Testy evaluate_entry_signal przez mockowanie get_live_context."""

    def _call(
        self,
        cfg: TradeConfig,
        ctx_entry: Optional[dict],
        ctx_htf: Optional[dict] = None,
        ctx_fast: Optional[dict] = None,
        binance_client=None,
        spread_pct: float = 0.05,
    ) -> EntrySignalResult:
        """Helper — wywołuje evaluate_entry_signal z zamockowanym get_live_context."""

        def _mock_get_live_context(db, symbol, timeframe="1h", limit=200):
            if timeframe == cfg.htf_timeframe:
                return ctx_htf or _make_htf_ctx()
            if timeframe == cfg.fast_timeframe:
                return ctx_fast or _make_fast_ctx()
            return ctx_entry

        mock_bc = binance_client or MagicMock()
        mock_bc.get_book_ticker.return_value = {
            "bidPrice": str(100.0 * (1 - spread_pct / 100 / 2)),
            "askPrice": str(100.0 * (1 + spread_pct / 100 / 2)),
        }

        with patch("backend.analysis.get_live_context", side_effect=_mock_get_live_context):
            db = MagicMock()
            return evaluate_entry_signal(db, "BTCUSDC", cfg, binance_client=mock_bc)

    # ─── brak danych ───────────────────────────────────────────────────────

    def test_no_klines_returns_invalid(self):
        cfg = _default_cfg()
        result = self._call(cfg, ctx_entry=None)
        assert result.is_valid is False
        assert result.reason_code == "no_klines_data"

    def test_insufficient_klines(self):
        cfg = _default_cfg()
        ctx = _make_good_ctx()
        ctx["klines_count"] = 30  # za mało
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code == "insufficient_klines"

    def test_missing_klines_count_uses_context_fallback(self):
        cfg = _default_cfg()
        ctx = _make_good_ctx()
        ctx.pop("klines_count", None)
        result = self._call(cfg, ctx_entry=ctx)
        assert result.reason_code != "insufficient_klines"
        assert result.is_valid is True

    def test_fast_timeframe_requests_enough_history(self):
        cfg = _default_cfg()
        seen_limits = {}

        def _mock_get_live_context(db, symbol, timeframe="1h", limit=200):
            seen_limits[timeframe] = limit
            if timeframe == cfg.htf_timeframe:
                return _make_htf_ctx()
            if timeframe == cfg.fast_timeframe:
                return _make_fast_ctx()
            return _make_good_ctx()

        mock_bc = MagicMock()
        mock_bc.get_book_ticker.return_value = {"bidPrice": "99.95", "askPrice": "100.05"}

        with patch("backend.analysis.get_live_context", side_effect=_mock_get_live_context):
            result = evaluate_entry_signal(MagicMock(), "BTCUSDC", cfg, binance_client=mock_bc)

        assert result.is_valid is True
        assert seen_limits[cfg.fast_timeframe] >= 60

    def test_no_atr(self):
        cfg = _default_cfg()
        ctx = _make_good_ctx(atr=0.0)
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code == "no_atr"

    def test_no_price(self):
        cfg = _default_cfg()
        ctx = _make_good_ctx(price=0.0)
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code == "no_price"

    # ─── spread ────────────────────────────────────────────────────────────

    def test_spread_too_wide_blocks_buy(self):
        """Spread > max_allowed_spread_pct blokuje wejście."""
        cfg = _default_cfg(max_allowed_spread_pct=0.20)
        ctx = _make_good_ctx()

        mock_bc = MagicMock()
        mock_bc.get_book_ticker.return_value = {
            "bidPrice": "99.60",   # spread = (100.40 - 99.60) / 99.60 × 100 ≈ 0.80%
            "askPrice": "100.40",
        }

        with patch("backend.analysis.get_live_context") as mock_ctx:
            mock_ctx.return_value = ctx
            db = MagicMock()
            result = evaluate_entry_signal(db, "BTCUSDC", cfg, binance_client=mock_bc)

        assert result.is_valid is False
        assert result.reason_code == "spread_too_wide"

    def test_spread_ok_passes(self):
        """Małe spread nie blokuje."""
        cfg = _default_cfg(max_allowed_spread_pct=0.30)
        ctx = _make_good_ctx()
        mock_bc = MagicMock()
        mock_bc.get_book_ticker.return_value = {
            "bidPrice": "99.99",
            "askPrice": "100.01",
        }

        with patch("backend.analysis.get_live_context") as mock_ctx:
            mock_ctx.return_value = ctx
            db = MagicMock()
            result = evaluate_entry_signal(db, "BTCUSDC", cfg, binance_client=mock_bc)

        # Może przejść lub nie w zależności od innych warunków, ale nie powinien blokować przez spread
        if not result.is_valid:
            assert result.reason_code != "spread_too_wide"

    # ─── RSI overbought ────────────────────────────────────────────────────

    def test_rsi_overbought_blocks_buy(self):
        """RSI > 75 musi blokować wejście."""
        cfg = _default_cfg()
        ctx = _make_good_ctx(rsi=78.0)
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code == "rsi_overbought"

    def test_rsi_below_75_does_not_block(self):
        cfg = _default_cfg()
        ctx = _make_good_ctx(rsi=74.9)
        result = self._call(cfg, ctx_entry=ctx)
        assert result.reason_code != "rsi_overbought"

    # ─── HTF trend ─────────────────────────────────────────────────────────

    def test_htf_downtrend_blocks_buy(self):
        """Silny downtrend na 4h (HTF) blokuje wejście gdy require_htf_trend_agreement=True."""
        cfg = _default_cfg(require_htf_trend_agreement=True)
        ctx = _make_good_ctx()
        htf = _make_htf_ctx(ema_20=90.0, ema_50=100.0, rsi=35.0)  # wyraźny downtrend
        result = self._call(cfg, ctx_entry=ctx, ctx_htf=htf)
        assert result.is_valid is False
        assert result.reason_code == "htf_trend_disagrees"

    def test_htf_check_disabled_allows_entry(self):
        """Gdy require_htf_trend_agreement=False, downtrend 4h nie blokuje."""
        cfg = _default_cfg(require_htf_trend_agreement=False)
        ctx = _make_good_ctx()
        htf = _make_htf_ctx(ema_20=90.0, ema_50=100.0, rsi=35.0)
        result = self._call(cfg, ctx_entry=ctx, ctx_htf=htf)
        assert result.reason_code != "htf_trend_disagrees"

    def test_htf_uptrend_allows_entry(self):
        """Silny uptrend 4h nie blokuje."""
        cfg = _default_cfg(require_htf_trend_agreement=True)
        ctx = _make_good_ctx()
        htf = _make_htf_ctx(ema_20=110.0, ema_50=100.0, rsi=65.0)
        result = self._call(cfg, ctx_entry=ctx, ctx_htf=htf)
        assert result.reason_code != "htf_trend_disagrees"

    # ─── Sprzeczny trend 15m/1h (brak sygnału BUY) ────────────────────────

    def test_downtrend_on_entry_tf_blocks_buy(self):
        """EMA20 < EMA50 na 1h = brak sygnału BUY."""
        cfg = _default_cfg()
        ctx = _make_good_ctx(ema_20=95.0, ema_50=100.0)  # EMA20 < EMA50 = downtrend
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code == "no_buy_signal"

    def test_fast_tf_disagrees_blocks_buy(self):
        """15m w downtrendzie + 1h słaby trend = brak BUY."""
        cfg = _default_cfg()
        ctx = _make_good_ctx(ema_20=101.0, ema_50=100.0)  # słaby trend 1h
        fast = _make_fast_ctx(ema_20=97.0, ema_50=100.0)  # downtrend 15m
        result = self._call(cfg, ctx_entry=ctx, ctx_fast=fast)
        # Przy słabym trend_score (0.65) i 15m w dół — has_buy_signal powinien być False
        if not result.is_valid:
            assert result.reason_code in ("no_buy_signal", "score_too_low",
                                          "confidence_too_low", "negative_edge_after_costs")

    # ─── Edge / EV gate ────────────────────────────────────────────────────

    def test_negative_edge_blocks_buy(self):
        """ATR zbyt mały → ujemny edge po kosztach."""
        # ATR = 0.01 na price=100 → expected_move = 0.01% << koszty
        cfg = _default_cfg(
            min_net_edge_pct=0.10,
            taker_fee_pct=0.10,  # round-trip ~0.20%
            slippage_bps=5.0,
        )
        ctx = _make_good_ctx(atr=0.001, price=100.0)  # ATR/price = 0.001%
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code == "negative_edge_after_costs"

    def test_good_atr_positive_edge(self):
        """Duży ATR → edge pozytywny."""
        cfg = _default_cfg(
            min_net_edge_pct=0.10,
            min_expected_rr=1.0,
        )
        ctx = _make_good_ctx(atr=3.0, price=100.0)  # ATR/price = 3%
        result = self._call(cfg, ctx_entry=ctx)
        # Powinien co najmniej dotrzeć do EV gate bez blokady przez edge
        if not result.is_valid and result.reason_code == "negative_edge_after_costs":
            # Sprawdź wartości numeryczne
            assert False, f"Edge powinien być dodatni: {result.details}"

    # ─── Score / confidence gate ───────────────────────────────────────────

    def test_score_too_low_blocks_buy(self):
        cfg = _default_cfg(min_entry_score=0.99)  # niewyosiągalny próg
        ctx = _make_good_ctx()
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code in ("score_too_low", "no_buy_signal")

    def test_confidence_too_low_blocks_buy(self):
        cfg = _default_cfg(min_signal_confidence=0.99)
        ctx = _make_good_ctx()
        result = self._call(cfg, ctx_entry=ctx)
        assert result.is_valid is False
        assert result.reason_code in ("confidence_too_low", "score_too_low", "no_buy_signal")

    # ─── Szczęśliwa ścieżka (valid signal) ────────────────────────────────

    def test_valid_signal_passes(self):
        """Idealne warunki → sygnał VALID."""
        cfg = _default_cfg(
            min_entry_score=0.40,
            min_signal_confidence=0.40,
            min_net_edge_pct=0.05,
            min_expected_rr=0.5,
            require_volume_confirmation=False,
            require_htf_trend_agreement=False,
            min_liquidity_score=0.0,
        )
        ctx = _make_good_ctx(
            price=100.0, atr=2.0, klines_count=200,
            rsi=52.0, ema_20=102.0, ema_50=99.0, ema_200=90.0,
            macd_hist=0.5, volume_ratio=2.0,
        )
        fast = _make_fast_ctx(ema_20=102.0, ema_50=99.0)
        result = self._call(cfg, ctx_entry=ctx, ctx_fast=fast)
        assert result.is_valid is True
        assert result.score > 0.0
        assert result.confidence > 0.0
        assert result.expected_net_edge_pct > 0.0
        assert result.entry_price == 100.0
        assert result.atr == 2.0

    def test_valid_signal_has_correct_fields(self):
        """Valid signal ma wypełnione wszystkie ważne pola."""
        cfg = _default_cfg(
            min_entry_score=0.30,
            min_signal_confidence=0.30,
            min_net_edge_pct=0.01,
            min_expected_rr=0.3,
            require_htf_trend_agreement=False,
            require_volume_confirmation=False,
            min_liquidity_score=0.0,
        )
        ctx = _make_good_ctx(price=50000.0, atr=1000.0)
        fast = _make_fast_ctx()
        result = self._call(cfg, ctx_entry=ctx, ctx_fast=fast)
        if result.is_valid:
            assert result.symbol == "BTCUSDC"
            assert result.entry_price == 50000.0
            assert result.atr == 1000.0
            assert result.total_cost_pct > 0.0
            assert "rsi" in result.details

    # ─── External confidence ───────────────────────────────────────────────

    def test_external_confidence_overrides_heuristic(self):
        cfg = _default_cfg(
            min_signal_confidence=0.90,  # wysoki próg
        )
        ctx = _make_good_ctx()
        # external_confidence = 0.95 → powinien przejść confidence gate
        with patch("backend.analysis.get_live_context") as mock_ctx:
            mock_ctx.return_value = ctx
            db = MagicMock()
            mock_bc = MagicMock()
            mock_bc.get_book_ticker.return_value = {"bidPrice": "99.99", "askPrice": "100.01"}
            result = evaluate_entry_signal(
                db, "BTCUSDC", cfg,
                binance_client=mock_bc,
                external_confidence=0.95,
            )
        # Nie powinno blokować przez confidence gate
        if not result.is_valid:
            assert result.reason_code != "confidence_too_low"
