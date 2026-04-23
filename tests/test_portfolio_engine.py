from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.portfolio_engine import (
    compute_entry_score,
    compute_replacement_decision,
    rank_entry_candidates,
    rank_open_positions,
)


def utc_now():
    return datetime.now(timezone.utc)


def _pos(
    symbol: str,
    qty: float,
    entry: float,
    current: float,
    pnl: float,
    opened_minutes_ago: int,
    tp: float,
    sl: float,
):
    return SimpleNamespace(
        symbol=symbol,
        quantity=qty,
        entry_price=entry,
        current_price=current,
        unrealized_pnl=pnl,
        opened_at=utc_now() - timedelta(minutes=opened_minutes_ago),
        planned_tp=tp,
        planned_sl=sl,
        total_cost=1.0,
    )


def test_replace_weakest_when_no_slot_and_candidate_much_better():
    cfg = {
        "min_replacement_edge": 0.01,
        "min_confidence_delta_for_replacement": 0.02,
        "taker_fee_rate": 0.001,
        "spread_buffer_bps": 6,
        "slippage_bps": 8,
    }
    now = utc_now()
    open_positions = [
        _pos("WLFIEUR", 10, 1.0, 0.9, -1.0, 180, 1.2, 0.8),
        _pos("ETHEUR", 1, 2000, 2100, 100, 120, 2300, 1900),
    ]
    worst = rank_open_positions(open_positions, now, cfg)[0]

    cand = {
        "symbol": "SOLEUR",
        "confidence": 0.82,
        "expected_move_ratio": 0.08,
        "total_cost_ratio": 0.01,
        "risk_reward": 2.4,
        "qty": 5,
        "price": 120,
    }
    best = compute_entry_score(cand, cfg)
    d = compute_replacement_decision(best, worst, cfg)
    assert d.should_replace is True
    assert d.reason_code == "buy_replaced_worst_position"


def test_keep_current_when_candidate_only_slightly_better():
    cfg = {
        "min_replacement_edge": 0.03,
        "min_confidence_delta_for_replacement": 0.02,
        "taker_fee_rate": 0.001,
        "spread_buffer_bps": 10,
        "slippage_bps": 12,
    }
    now = utc_now()
    open_positions = [_pos("ARBEUR", 100, 1.0, 1.02, 2.0, 90, 1.08, 0.95)]
    worst = rank_open_positions(open_positions, now, cfg)[0]

    cand = {
        "symbol": "ADAEUR",
        "confidence": 0.66,
        "expected_move_ratio": 0.025,
        "total_cost_ratio": 0.012,
        "risk_reward": 1.6,
        "qty": 100,
        "price": 0.55,
    }
    best = compute_entry_score(cand, cfg)
    d = compute_replacement_decision(best, worst, cfg)
    assert d.should_replace is False
    assert d.reason_code in {
        "buy_deferred_insufficient_rotation_edge",
        "buy_rejected_inferior_to_open_positions",
    }


def test_keep_current_when_gross_better_but_net_worse_after_costs():
    cfg = {
        "min_replacement_edge": 0.01,
        "min_confidence_delta_for_replacement": 0.01,
        "taker_fee_rate": 0.002,
        "spread_buffer_bps": 20,
        "slippage_bps": 25,
    }
    now = utc_now()
    open_positions = [_pos("BTCEUR", 0.1, 40000, 40500, 50, 200, 43000, 39000)]
    worst = rank_open_positions(open_positions, now, cfg)[0]

    cand = {
        "symbol": "ETHEUR",
        "confidence": 0.72,
        "expected_move_ratio": 0.03,
        "total_cost_ratio": 0.018,
        "risk_reward": 1.8,
        "qty": 1,
        "price": 2000,
    }
    best = compute_entry_score(cand, cfg)
    d = compute_replacement_decision(best, worst, cfg)
    assert d.should_replace is False


def test_rank_open_positions_position_near_tp_scores_better():
    cfg = {}
    now = utc_now()
    near_tp = _pos("ETHEUR", 1, 2000, 2290, 290, 60, 2300, 1900)
    weak = _pos("WLFIEUR", 50, 1.0, 0.92, -4.0, 60, 1.15, 0.88)
    ranked = rank_open_positions([weak, near_tp], now, cfg)
    assert ranked[0].symbol == "WLFIEUR"
    assert ranked[1].symbol == "ETHEUR"


def test_rank_entry_candidates_prefers_higher_net_and_confidence():
    cfg = {}
    cands = [
        {
            "symbol": "A",
            "confidence": 0.55,
            "expected_move_ratio": 0.03,
            "total_cost_ratio": 0.01,
            "risk_reward": 1.5,
            "qty": 1,
            "price": 1,
        },
        {
            "symbol": "B",
            "confidence": 0.8,
            "expected_move_ratio": 0.06,
            "total_cost_ratio": 0.012,
            "risk_reward": 2.0,
            "qty": 1,
            "price": 1,
        },
    ]
    ranked = rank_entry_candidates(cands, cfg)
    assert ranked[0].symbol == "B"
