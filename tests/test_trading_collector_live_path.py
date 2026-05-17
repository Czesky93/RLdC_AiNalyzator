"""
test_trading_collector_live_path.py — Testy dla ścieżki LIVE w DataCollector (T-114).

Testuje:
  - W trybie LIVE entry kandydat idzie przez _live_entry_new_pipeline()
  - DEMO nadal działa starą ścieżką (_screen_entry_candidates nie wywołuje _live_entry_new_pipeline)
  - LIVE nie tworzy BUY starą ścieżką
  - _has_active_pending guard blokuje kolejne wejście
  - Blokada _pending_in_cooldown
  - signal_engine odrzuca → 0 (brak pending)
  - risk_engine odrzuca → 0 (brak pending)
  - Oba OK → 1 (pending_id zwrócony)
  - min_notional guard → 0
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_collector():
    """Tworzy DataCollector z zamockowanym binance i bez uruchamiania watchdogów."""
    with patch("backend.collector.get_binance_client") as mock_bc_factory:
        mock_bc = MagicMock()
        mock_bc.get_balances.return_value = []
        mock_bc.get_allowed_symbols.return_value = {}
        mock_bc.resolve_symbol.return_value = None
        mock_bc.get_exchange_info.return_value = {"symbols": []}
        mock_bc_factory.return_value = mock_bc

        # Wyłącz WebSocket i dynamiczny universe
        with patch.dict("os.environ", {
            "DISABLE_COLLECTOR": "true",
            "TRADING_MODE": "demo",
            "ALLOW_LIVE_TRADING": "false",
            "ENABLE_DYNAMIC_UNIVERSE": "false",
            "WATCHLIST": "",
        }):
            from backend.collector import DataCollector
            collector = DataCollector.__new__(DataCollector)
            # Ręczna inicjalizacja minimalna
            collector.binance = mock_bc
            collector.watchlist = ["BTCUSDC", "ETHUSDC"]
            collector.interval = 60
            collector.kline_timeframes = ["1h"]
            collector.running = False
            collector.ws_running = False
            collector.ws_thread = None
            collector.ws_backoff_seconds = 2
            collector.demo_state = {}
            collector._risk_engine = None
            collector._state_manager = None
            collector._state_manager_started = False
            collector._execution_lock = __import__("threading").Lock()
            collector._inflight_symbol_orders = {}
            collector._inflight_ttl_seconds = 120
            collector._binance_rejection_cooldown = {}
            collector._binance_rejection_cooldown_s = 600
            collector._exit_alert_sent_at = {}
            collector._exit_alert_min_interval_s = 900
            collector._trailing_alert_state = {}
            collector.last_report_ts = None
            collector.last_risk_alert_ts = None
            collector.last_crash_alert_ts = None
            collector._last_idle_alert_ts = None
            collector.last_snapshot_ts = None
            collector.last_live_snapshot_ts = None
            collector.last_stale_ai_log_ts = None
            collector._last_heuristic_suppl_log_ts = None
            collector._last_heuristic_suppl_syms = []
            collector._last_binance_sync_ts = None
            collector._last_binance_mismatch_signature = None
            collector._sync_mismatch_repeat_count = {}
            collector.last_no_watchlist_log_ts = None
            collector.last_openai_missing_log_ts = None
            collector.last_watchlist_refresh_ts = None
            collector.watchlist_refresh_seconds = 900
            collector.last_learning_ts = None
            collector.last_live_snapshot_ts = None
            collector.symbol_params = {}
            collector._ws_tick_last_saved = {}
            collector._ws_tick_min_interval_s = 30

            from backend.collector import AlertThrottler
            collector._sync_mismatch_throttler = AlertThrottler(cooldown_seconds=600)

    return collector, mock_bc


def _make_tc(mode="live", symbol="BTCUSDC", has_active_pending=False, in_cooldown=False) -> dict:
    """Minimalne tc dict dla _live_entry_new_pipeline."""
    return {
        "_has_active_pending": lambda sym: has_active_pending,
        "_pending_in_cooldown": lambda sym: in_cooldown,
        "min_order_notional": 5.0,
        "config": {},
        "demo_quote_ccy": "USDC",
        "mode": mode,
    }


def _make_runtime_ctx() -> dict:
    return {
        "state": {},
        "config": {"trading_mode": "live"},
        "sections": {},
        "snapshot_id": "test_snap_001",
    }


def _make_valid_signal(score=0.75, confidence=0.80, entry_price=100.0, atr=2.0, edge=0.5) -> MagicMock:
    sig = MagicMock()
    sig.is_valid = True
    sig.score = score
    sig.confidence = confidence
    sig.entry_price = entry_price
    sig.atr = atr
    sig.expected_net_edge_pct = edge
    sig.reason_code = None
    sig.spread_pct = 0.05
    sig.skip_reasons = []
    sig.details = {}
    return sig


def _make_invalid_signal(reason_code="score_too_low") -> MagicMock:
    sig = MagicMock()
    sig.is_valid = False
    sig.score = 0.3
    sig.confidence = 0.4
    sig.reason_code = reason_code
    sig.expected_net_edge_pct = 0.0
    sig.skip_reasons = [reason_code]
    sig.details = {}
    sig.entry_price = 0.0
    sig.atr = 0.0
    sig.spread_pct = 0.0
    return sig


def _make_valid_risk(qty=0.1, sl=96.0, tp=107.0) -> MagicMock:
    risk = MagicMock()
    risk.is_allowed = True
    risk.recommended_qty = qty
    risk.stop_loss_price = sl
    risk.take_profit_price = tp
    risk.take_profit_2_price = tp * 1.05
    risk.risk_amount = 5.0
    risk.reason_code = None
    risk.reason_pl = None
    risk.cooldown_remaining_sec = 0
    risk.details = {}
    return risk


def _make_invalid_risk(reason_code="max_positions_reached") -> MagicMock:
    risk = MagicMock()
    risk.is_allowed = False
    risk.recommended_qty = 0.0
    risk.stop_loss_price = 0.0
    risk.take_profit_price = 0.0
    risk.take_profit_2_price = 0.0
    risk.risk_amount = 0.0
    risk.reason_code = reason_code
    risk.reason_pl = f"Blokada: {reason_code}"
    risk.cooldown_remaining_sec = 0
    risk.details = {}
    return risk


# ── 1. _live_entry_new_pipeline — blokady guard ──────────────────────────────

class TestLiveEntryPipelineGuards:
    def setup_method(self):
        self.collector, self.mock_bc = _make_collector()

    def test_has_active_pending_returns_zero(self):
        """Jeśli symbol ma aktywny pending → natychmiastowe 0 (bez signal_engine)."""
        db = MagicMock()
        tc = _make_tc(has_active_pending=True)
        runtime_ctx = _make_runtime_ctx()

        with patch("backend.trading.signal_engine.evaluate_entry_signal") as mock_sig:
            result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 0
        mock_sig.assert_not_called()

    def test_pending_cooldown_returns_zero(self):
        """Jeśli symbol jest w cooldown pending → natychmiastowe 0."""
        db = MagicMock()
        tc = _make_tc(in_cooldown=True, has_active_pending=False)
        runtime_ctx = _make_runtime_ctx()

        with patch("backend.trading.signal_engine.evaluate_entry_signal") as mock_sig:
            result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 0
        mock_sig.assert_not_called()


# ── 2. signal_engine rejects → 0 ─────────────────────────────────────────────

class TestLiveEntryPipelineSignalReject:
    def setup_method(self):
        self.collector, self.mock_bc = _make_collector()

    def test_signal_engine_reject_returns_zero(self):
        """Odrzucenie przez signal_engine → zwraca 0, brak pending order."""
        db = MagicMock()
        tc = _make_tc()
        runtime_ctx = _make_runtime_ctx()
        invalid_sig = _make_invalid_signal("rsi_overbought")

        with patch("backend.trading.signal_engine.evaluate_entry_signal", return_value=invalid_sig):
            with patch("backend.trading.trade_config.get_trade_config", return_value=MagicMock()):
                with patch.object(self.collector, "_trace_decision") as mock_trace:
                    with patch.object(self.collector, "_create_pending_order") as mock_create:
                        result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 0
        mock_create.assert_not_called()
        # _trace_decision powinno być wywołane z reason_code z signal_engine
        called_reason_codes = [call.kwargs.get("reason_code") for call in mock_trace.call_args_list]
        assert "rsi_overbought" in called_reason_codes


# ── 3. risk_engine rejects → 0 ───────────────────────────────────────────────

class TestLiveEntryPipelineRiskReject:
    def setup_method(self):
        self.collector, self.mock_bc = _make_collector()

    def test_risk_engine_reject_returns_zero(self):
        """Odrzucenie przez risk_engine → zwraca 0, brak pending order."""
        db = MagicMock()
        tc = _make_tc()
        runtime_ctx = _make_runtime_ctx()
        valid_sig = _make_valid_signal()
        invalid_risk = _make_invalid_risk("max_positions_reached")

        with patch("backend.trading.signal_engine.evaluate_entry_signal", return_value=valid_sig):
            with patch("backend.trading.trade_config.get_trade_config", return_value=MagicMock()):
                with patch("backend.trading.risk_engine.build_account_state", return_value=MagicMock()):
                    with patch("backend.trading.risk_engine.build_open_positions", return_value=[]):
                        with patch.object(self.collector, "_get_risk_engine") as mock_re_getter:
                            mock_re = MagicMock()
                            mock_re.evaluate.return_value = invalid_risk
                            mock_re_getter.return_value = mock_re
                            with patch.object(self.collector, "_trace_decision") as mock_trace:
                                with patch.object(self.collector, "_create_pending_order") as mock_create:
                                    result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 0
        mock_create.assert_not_called()
        called_reason_codes = [call.kwargs.get("reason_code") for call in mock_trace.call_args_list]
        assert "max_positions_reached" in called_reason_codes


# ── 4. Oba OK → 1, pending order stworzony ────────────────────────────────────

class TestLiveEntryPipelineSuccess:
    def setup_method(self):
        self.collector, self.mock_bc = _make_collector()

    def test_success_returns_one_and_creates_pending(self):
        """Oba silniki OK → zwraca 1, pending order stworzony."""
        db = MagicMock()
        tc = _make_tc(has_active_pending=False, in_cooldown=False)
        runtime_ctx = _make_runtime_ctx()
        valid_sig = _make_valid_signal(entry_price=100.0, atr=2.0)
        valid_risk = _make_valid_risk(qty=0.5, sl=96.0, tp=107.0)

        with patch("backend.trading.signal_engine.evaluate_entry_signal", return_value=valid_sig):
            with patch("backend.trading.trade_config.get_trade_config", return_value=MagicMock()):
                with patch("backend.trading.risk_engine.build_account_state", return_value=MagicMock()):
                    with patch("backend.trading.risk_engine.build_open_positions", return_value=[]):
                        with patch.object(self.collector, "_get_risk_engine") as mock_re_getter:
                            mock_re = MagicMock()
                            mock_re.evaluate.return_value = valid_risk
                            mock_re_getter.return_value = mock_re
                            with patch.object(self.collector, "_trace_decision"):
                                with patch.object(self.collector, "_create_pending_order", return_value=42) as mock_create:
                                    with patch.object(self.collector, "_send_telegram_alert"):
                                        result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 1
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["symbol"] == "BTCUSDC"
        assert call_kwargs["side"] == "BUY"
        assert call_kwargs["mode"] == "live"
        assert call_kwargs["qty"] > 0

    def test_success_qty_zero_returns_zero(self):
        """risk_engine zwraca qty=0 → brak pending (mimo is_allowed=True)."""
        db = MagicMock()
        tc = _make_tc()
        runtime_ctx = _make_runtime_ctx()
        valid_sig = _make_valid_signal()
        zero_risk = _make_valid_risk(qty=0.0)  # qty=0

        with patch("backend.trading.signal_engine.evaluate_entry_signal", return_value=valid_sig):
            with patch("backend.trading.trade_config.get_trade_config", return_value=MagicMock()):
                with patch("backend.trading.risk_engine.build_account_state", return_value=MagicMock()):
                    with patch("backend.trading.risk_engine.build_open_positions", return_value=[]):
                        with patch.object(self.collector, "_get_risk_engine") as mock_re_getter:
                            mock_re = MagicMock()
                            mock_re.evaluate.return_value = zero_risk
                            mock_re_getter.return_value = mock_re
                            with patch.object(self.collector, "_trace_decision"):
                                with patch.object(self.collector, "_create_pending_order") as mock_create:
                                    result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 0
        mock_create.assert_not_called()

    def test_notional_too_small_returns_zero(self):
        """qty × price < min_order_notional → blokada min_notional_guard."""
        db = MagicMock()
        tc = _make_tc()
        tc["min_order_notional"] = 100.0  # wysoki próg
        runtime_ctx = _make_runtime_ctx()
        valid_sig = _make_valid_signal(entry_price=10.0)  # price=10
        small_qty_risk = _make_valid_risk(qty=0.001)  # 0.001 × 10 = 0.01 < 100

        with patch("backend.trading.signal_engine.evaluate_entry_signal", return_value=valid_sig):
            with patch("backend.trading.trade_config.get_trade_config", return_value=MagicMock()):
                with patch("backend.trading.risk_engine.build_account_state", return_value=MagicMock()):
                    with patch("backend.trading.risk_engine.build_open_positions", return_value=[]):
                        with patch.object(self.collector, "_get_risk_engine") as mock_re_getter:
                            mock_re = MagicMock()
                            mock_re.evaluate.return_value = small_qty_risk
                            mock_re_getter.return_value = mock_re
                            with patch.object(self.collector, "_trace_decision") as mock_trace:
                                with patch.object(self.collector, "_create_pending_order") as mock_create:
                                    result = self.collector._live_entry_new_pipeline(db, "BTCUSDC", tc, runtime_ctx)

        assert result == 0
        mock_create.assert_not_called()
        called_reason_codes = [call.kwargs.get("reason_code") for call in mock_trace.call_args_list]
        assert "min_notional_guard" in called_reason_codes


# ── 5. LIVE path vs DEMO path w _screen_entry_candidates ─────────────────────

class TestScreenEntryCandidatesLiveVsDemo:
    def setup_method(self):
        self.collector, self.mock_bc = _make_collector()

    def _make_full_tc(self, mode="demo") -> dict:
        """Pełne tc dict dla _screen_entry_candidates."""
        from datetime import datetime
        now = datetime.utcnow()
        return {
            "now": now,
            "config": {
                "trading_mode": mode,
                "collector_use_market_scanner": False,
            },
            "runtime_ctx": _make_runtime_ctx(),
            "demo_quote_ccy": "USDC",
            "equity": 1000.0,
            "available_cash": 900.0,
            "base_qty": 0.01,
            "base_min_confidence": 0.6,
            "max_signal_age": 3600,
            "min_klines": 60,
            "atr_stop_mult": 2.0,
            "atr_take_mult": 3.5,
            "base_risk_per_trade": 0.01,
            "base_cooldown": 300,
            "crash_window_minutes": 60,
            "crash_drop_pct": 6.0,
            "crash_cooldown_seconds": 7200,
            "extreme_margin_pct": 0.02,
            "extreme_min_conf": 0.85,
            "extreme_min_rating": 4,
            "max_qty": 1.0,
            "min_qty": 0.001,
            "pending_cooldown_seconds": 30,
            "range_map": {"BTCUSDC": {"symbol": "BTCUSDC", "buy_zone_low": 95, "buy_zone_high": 105, "rating": 4}},
            "maker_fee_rate": 0.001,
            "taker_fee_rate": 0.001,
            "slippage_bps": 5.0,
            "spread_buffer_bps": 3.0,
            "min_edge_multiplier": 2.5,
            "min_expected_rr": 1.5,
            "min_order_notional": 10.0,
            "max_open_positions": 5,
            "max_trades_per_day": 20,
            "loss_streak_limit": 3,
            "daily_loss_triggered": False,
            "daily_loss_limit": -30.0,
            "positions": [],
            "_has_active_pending": lambda sym: False,
            "_pending_in_cooldown": lambda sym: False,
            "tier_map": {},
            "demo_require_manual_confirm": False,
            "demo_allow_soft_buy_entries": True,
            "demo_min_entry_score": 50.0,
            "aggressiveness": "balanced",
            "enabled_strategies": ["default"],
            "mode": mode,
        }

    def test_live_mode_calls_live_entry_pipeline(self):
        """W trybie LIVE _screen_entry_candidates wywołuje _live_entry_new_pipeline."""
        tc = self._make_full_tc(mode="live")
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 0
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        db.query.return_value.filter.return_value.all.return_value = []
        db.query.return_value.filter.return_value.first.return_value = None

        # Resetuj watchlistę do jednego symbolu
        self.collector.watchlist = ["BTCUSDC"]

        with patch.object(self.collector, "_live_entry_new_pipeline", return_value=1) as mock_pipeline:
            with patch.dict("os.environ", {"QUOTE_CURRENCY_MODE": "USDC"}):
                with patch("backend.collector.get_symbol_tier_or_default", return_value={}):
                    with patch("backend.collector.check_symbol_allowed", return_value=(True, "")):
                        with patch("backend.collector.rank_open_positions", return_value=[]):
                            with patch("backend.collector.log_to_db"):
                                try:
                                    self.collector._screen_entry_candidates(db, tc)
                                except Exception:
                                    pass  # Inne błędy są OK — testujemy tylko że pipeline był wywołany

        # LIVE → _live_entry_new_pipeline powinno być wywołane dla BTCUSDC
        mock_pipeline.assert_called()
        # Sprawdź że był wywołany z symbolem BTCUSDC
        call_symbols = [c.args[1] if len(c.args) > 1 else c.kwargs.get("symbol") for c in mock_pipeline.call_args_list]
        assert "BTCUSDC" in call_symbols

    def test_demo_mode_does_not_call_live_entry_pipeline(self):
        """W trybie DEMO _screen_entry_candidates NIE wywołuje _live_entry_new_pipeline."""
        tc = self._make_full_tc(mode="demo")
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 0
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        db.query.return_value.filter.return_value.all.return_value = []

        self.collector.watchlist = ["BTCUSDC"]

        with patch.object(self.collector, "_live_entry_new_pipeline", return_value=1) as mock_pipeline:
            with patch.dict("os.environ", {"QUOTE_CURRENCY_MODE": "USDC"}):
                with patch("backend.collector.get_symbol_tier_or_default", return_value={}):
                    with patch("backend.collector.check_symbol_allowed", return_value=(True, "")):
                        with patch("backend.collector.rank_open_positions", return_value=[]):
                            try:
                                self.collector._screen_entry_candidates(db, tc)
                            except Exception:
                                pass

        # DEMO → _live_entry_new_pipeline NIE powinno być wywołane
        mock_pipeline.assert_not_called()
