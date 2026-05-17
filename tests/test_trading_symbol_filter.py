"""
test_trading_symbol_filter.py — Testy jednostkowe dla backend/trading/symbol_filter.py

Testuje:
  - parsowanie filtrów exchangeInfo (PRICE_FILTER, LOT_SIZE, PERCENT_PRICE_BY_SIDE, NOTIONAL)
  - round_qty, round_price
  - meets_min_notional
  - check_price_filter
  - check_percent_price_side
  - validate_order (pełna walidacja)
  - odrzucenie zbyt małego zlecenia
"""
import math
import pytest

from backend.trading.symbol_filter import (
    SymbolMeta,
    _parse_symbol_info,
    round_qty,
    round_price,
    meets_min_notional,
    check_price_filter,
    check_percent_price_side,
    validate_order,
    can_trade,
    invalidate_cache,
)


# ── Fixture: podstawowe SymbolMeta dla BTC/USDC ─────────────────────────────

def _make_meta(
    symbol="BTCUSDC",
    step_size=0.00001,
    tick_size=0.01,
    min_price=0.01,
    max_price=9999999.0,
    min_qty=0.00001,
    max_qty=9000.0,
    min_notional=5.0,
    bid_up=5.0,
    bid_down=0.2,
    ask_up=5.0,
    ask_down=0.2,
) -> SymbolMeta:
    qty_prec = max(0, -int(math.floor(math.log10(step_size)))) if step_size > 0 else 8
    price_prec = max(0, -int(math.floor(math.log10(tick_size)))) if tick_size > 0 else 8
    return SymbolMeta(
        symbol=symbol,
        base_asset=symbol[:-4],
        quote_asset=symbol[-4:],
        status="TRADING",
        is_spot=True,
        oco_allowed=True,
        min_qty=min_qty,
        max_qty=max_qty,
        step_size=step_size,
        tick_size=tick_size,
        min_price=min_price,
        max_price=max_price,
        bid_mult_up=bid_up,
        bid_mult_down=bid_down,
        ask_mult_up=ask_up,
        ask_mult_down=ask_down,
        min_notional=min_notional,
        max_notional=0.0,
        apply_min_to_market=True,
        max_num_orders=0,
        max_num_algo_orders=0,
        qty_precision=qty_prec,
        price_precision=price_prec,
    )


# ── 1. can_trade ─────────────────────────────────────────────────────────────

def test_can_trade_ok():
    meta = _make_meta()
    assert can_trade(meta) is True


def test_can_trade_wrong_status():
    meta = _make_meta()
    meta.status = "BREAK"
    assert can_trade(meta) is False


def test_can_trade_wrong_quote():
    meta = _make_meta(symbol="BTCEUR")
    meta.quote_asset = "EUR"
    assert can_trade(meta, quote="USDC") is False
    assert can_trade(meta, quote="EUR") is True


def test_can_trade_zero_step():
    meta = _make_meta()
    meta.step_size = 0.0
    assert can_trade(meta) is False


def test_can_trade_zero_tick():
    meta = _make_meta()
    meta.tick_size = 0.0
    assert can_trade(meta) is False


# ── 2. round_qty ─────────────────────────────────────────────────────────────

def test_round_qty_floor_to_step():
    """round_qty musi zawsze zaokrąglić w dół do step_size."""
    meta = _make_meta(step_size=0.1, min_qty=0.1)
    assert round_qty(1.25, meta) == 1.2
    assert round_qty(1.29999, meta) == 1.2
    assert round_qty(1.30001, meta) == 1.3


def test_round_qty_large_step():
    meta = _make_meta(step_size=1.0, min_qty=1.0)
    assert round_qty(3.9, meta) == 3.0
    assert round_qty(1.5, meta) == 1.0


def test_round_qty_below_min_returns_zero():
    """Jeśli wynik < min_qty → zwróć 0.0."""
    meta = _make_meta(step_size=1.0, min_qty=5.0)
    assert round_qty(3.9, meta) == 0.0


def test_round_qty_exact_step():
    meta = _make_meta(step_size=0.00001, min_qty=0.00001)
    assert round_qty(0.00001, meta) == 0.00001
    assert round_qty(0.000014999, meta) == 0.00001


# ── 3. round_price ───────────────────────────────────────────────────────────

def test_round_price_to_tick():
    meta = _make_meta(tick_size=0.01)
    assert round_price(100.0052, meta) == 100.01
    assert round_price(100.004, meta) == 100.0


def test_round_price_large_tick():
    # round_price używa round() (zaokrąglanie standardowe), nie floor
    meta = _make_meta(tick_size=10.0)
    assert round_price(105.0, meta) == 100.0   # 105/10 = 10.5 → round → 10 → 100
    assert round_price(109.9, meta) == 110.0   # 109.9/10 = 10.99 → round → 11 → 110
    assert round_price(110.0, meta) == 110.0


# ── 4. meets_min_notional ────────────────────────────────────────────────────

def test_meets_min_notional_ok():
    meta = _make_meta(min_notional=5.0)
    assert meets_min_notional(0.1, 60.0, meta) is True  # 6.0 > 5.0


def test_meets_min_notional_fail():
    meta = _make_meta(min_notional=10.0)
    assert meets_min_notional(0.1, 50.0, meta) is False  # 5.0 < 10.0


def test_meets_min_notional_skip_if_apply_false():
    meta = _make_meta(min_notional=100.0)
    meta.apply_min_to_market = False
    # apply_min_to_market = False → zawsze True dla market orders
    assert meets_min_notional(0.001, 1.0, meta) is True


def test_meets_min_notional_zero_min():
    meta = _make_meta(min_notional=0.0)
    assert meets_min_notional(0.00001, 0.001, meta) is True


# ── 5. check_price_filter ────────────────────────────────────────────────────

def test_check_price_filter_ok():
    meta = _make_meta(min_price=1.0, max_price=999999.0, tick_size=0.01)
    ok, code = check_price_filter(100.0, meta)
    assert ok is True
    assert code == ""


def test_check_price_filter_below_min():
    meta = _make_meta(min_price=10.0)
    ok, code = check_price_filter(5.0, meta)
    assert ok is False
    assert code == "price_below_min_price_filter"


def test_check_price_filter_above_max():
    meta = _make_meta(max_price=100.0)
    ok, code = check_price_filter(200.0, meta)
    assert ok is False
    assert code == "price_above_max_price_filter"


def test_check_price_filter_zero_bounds():
    """min_price/max_price = 0 → brak filtrowania."""
    meta = _make_meta(min_price=0.0, max_price=0.0)
    ok, code = check_price_filter(999999.0, meta)
    assert ok is True


# ── 6. check_percent_price_side ─────────────────────────────────────────────

def test_percent_price_bid_ok():
    meta = _make_meta(bid_up=5.0, bid_down=0.2)
    avg = 100.0
    ok, code = check_percent_price_side(150.0, "BUY", avg, meta)
    assert ok is True  # 150 < 500 (avg × 5)


def test_percent_price_bid_too_high():
    meta = _make_meta(bid_up=2.0, bid_down=0.2)
    avg = 100.0
    ok, code = check_percent_price_side(250.0, "BUY", avg, meta)
    assert ok is False
    assert code == "price_exceeds_percent_price_bid_up"


def test_percent_price_bid_too_low():
    meta = _make_meta(bid_up=5.0, bid_down=0.5)
    avg = 100.0
    ok, code = check_percent_price_side(40.0, "BUY", avg, meta)
    assert ok is False
    assert code == "price_below_percent_price_bid_down"


def test_percent_price_ask_ok():
    meta = _make_meta(ask_up=5.0, ask_down=0.2)
    avg = 100.0
    ok, code = check_percent_price_side(120.0, "SELL", avg, meta)
    assert ok is True


def test_percent_price_no_avg():
    """avg_price = 0 → walidacja pomijana."""
    meta = _make_meta(bid_up=2.0, bid_down=0.2)
    ok, code = check_percent_price_side(999.0, "BUY", 0.0, meta)
    assert ok is True
    assert code == ""


# ── 7. validate_order — pełna walidacja ─────────────────────────────────────

def test_validate_order_ok():
    meta = _make_meta(
        min_qty=0.001, max_qty=1000.0, step_size=0.001,
        min_price=1.0, max_price=999999.0, tick_size=0.01,
        min_notional=5.0,
    )
    ok, code = validate_order("BTCUSDC", "BUY", 0.1, 100.0, meta)
    assert ok is True
    assert code == ""


def test_validate_order_qty_below_min():
    meta = _make_meta(min_qty=1.0, step_size=1.0)
    ok, code = validate_order("BTCUSDC", "BUY", 0.5, 100.0, meta)
    assert ok is False
    assert code == "qty_below_min_lot_size"


def test_validate_order_qty_above_max():
    meta = _make_meta(max_qty=10.0, step_size=0.001, min_qty=0.001)
    ok, code = validate_order("BTCUSDC", "BUY", 100.0, 100.0, meta)
    assert ok is False
    assert code == "qty_above_max_lot_size"


def test_validate_order_step_size_violation():
    """qty nie jest wielokrotnością step_size."""
    meta = _make_meta(step_size=0.1, min_qty=0.1)
    # 0.15 nie jest wielokrotnością 0.1 (bo 0.15/0.1 = 1.5, reszta = 0.05)
    ok, code = validate_order("BTCUSDC", "BUY", 0.15, 100.0, meta)
    assert ok is False
    assert code == "qty_not_multiple_of_step_size"


def test_validate_order_notional_too_low():
    meta = _make_meta(min_notional=10.0, min_qty=0.001, step_size=0.001)
    # 0.001 * 5.0 = 0.005 < 10.0
    ok, code = validate_order("BTCUSDC", "BUY", 0.001, 5.0, meta)
    assert ok is False
    assert code == "notional_below_min_notional_filter"


def test_validate_order_price_filter_fail():
    meta = _make_meta(min_price=200.0, min_qty=0.001, step_size=0.001)
    ok, code = validate_order("BTCUSDC", "BUY", 0.1, 100.0, meta)
    assert ok is False
    assert code == "price_below_min_price_filter"


def test_validate_order_not_tradable():
    meta = _make_meta()
    meta.step_size = 0.0  # uniemożliwia can_trade
    ok, code = validate_order("BTCUSDC", "BUY", 0.1, 100.0, meta)
    assert ok is False
    assert code == "symbol_not_tradable"


# ── 8. _parse_symbol_info ────────────────────────────────────────────────────

def _make_exchange_info_symbol(**overrides) -> dict:
    base = {
        "symbol": "BTCUSDC",
        "baseAsset": "BTC",
        "quoteAsset": "USDC",
        "status": "TRADING",
        "ocoAllowed": True,
        "permissions": ["SPOT"],
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.00001", "maxQty": "9000.0", "stepSize": "0.00001"},
            {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "9999999.0", "tickSize": "0.01"},
            {"filterType": "NOTIONAL", "minNotional": "5.0", "maxNotional": "0.0", "applyMinToMarket": True},
        ],
    }
    base.update(overrides)
    return base


def test_parse_symbol_info_basic():
    sym_info = _make_exchange_info_symbol()
    meta = _parse_symbol_info(sym_info)
    assert meta is not None
    assert meta.symbol == "BTCUSDC"
    assert meta.min_qty == 0.00001
    assert meta.tick_size == 0.01
    assert meta.min_notional == 5.0


def test_parse_symbol_info_non_trading():
    sym_info = _make_exchange_info_symbol(status="BREAK")
    meta = _parse_symbol_info(sym_info)
    assert meta is None


def test_parse_symbol_info_no_spot_permission():
    sym_info = _make_exchange_info_symbol(permissions=["MARGIN"])
    meta = _parse_symbol_info(sym_info)
    assert meta is None


def test_parse_symbol_info_permission_sets():
    """Nowy format permissionSets (lista list)."""
    sym_info = _make_exchange_info_symbol()
    del sym_info["permissions"]
    sym_info["permissionSets"] = [["SPOT", "MARGIN"]]
    meta = _parse_symbol_info(sym_info)
    assert meta is not None


def test_parse_symbol_info_permission_sets_no_spot():
    sym_info = _make_exchange_info_symbol()
    del sym_info["permissions"]
    sym_info["permissionSets"] = [["MARGIN"]]
    meta = _parse_symbol_info(sym_info)
    assert meta is None


def test_parse_symbol_info_percent_price_by_side():
    sym_info = _make_exchange_info_symbol()
    sym_info["filters"].append({
        "filterType": "PERCENT_PRICE_BY_SIDE",
        "bidMultiplierUp": "3.0",
        "bidMultiplierDown": "0.5",
        "askMultiplierUp": "3.0",
        "askMultiplierDown": "0.5",
    })
    meta = _parse_symbol_info(sym_info)
    assert meta is not None
    assert meta.bid_mult_up == 3.0
    assert meta.bid_mult_down == 0.5
