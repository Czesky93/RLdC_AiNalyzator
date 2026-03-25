import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Ensure repo root is on sys.path so `import backend` works when running pytest from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""
os.environ["DEMO_INITIAL_BALANCE"] = "10000"
os.environ["DEMO_TRADING_ENABLED"] = "true"
os.environ["WS_ENABLED"] = "true"
os.environ["MAX_CERTAINTY_MODE"] = "false"

# Isolated DB per test run
_tmp_db = tempfile.NamedTemporaryFile(prefix="rldc_test_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from fastapi.testclient import TestClient
from backend.app import app
from backend.accounting import compute_demo_account_state
from backend.risk import build_risk_context, evaluate_risk
from backend.database import (
    ConfigRollback,
    ConfigSnapshot,
    PendingOrder,
    Recommendation,
    SessionLocal,
    Position,
    MarketData,
    Order,
    attach_costs_to_order,
    compare_config_snapshots,
    get_config_snapshot,
    load_order_cost_summary,
    save_cost_entry,
    save_decision_trace,
)
from backend.experiments import compare_snapshots_for_experiment
from backend.recommendations import evaluate_recommendation
from backend.runtime_settings import apply_runtime_updates, build_runtime_state


import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "healthy"


def test_market_summary(client):
    resp = client.get("/api/market/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_positions(client):
    resp = client.get("/api/positions?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_signals_top5(client):
    resp = client.get("/api/signals/top5")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_account_summary_demo(client):
    resp = client.get("/api/account/summary?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("mode") == "demo"
    assert abs(float(data.get("equity") or 0.0) - 10000.0) < 1e-6


def test_pending_confirm_reject_demo(client):
    # create pending order
    db = SessionLocal()
    try:
        p = PendingOrder(
            symbol="BTCEUR",
            side="BUY",
            order_type="MARKET",
            price=100.0,
            quantity=0.1,
            mode="demo",
            status="PENDING",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        pid = int(p.id)
    finally:
        db.close()

    resp = client.post(f"/api/orders/pending/{pid}/confirm")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("status") == "CONFIRMED"

    # reject needs a fresh PENDING record
    db = SessionLocal()
    try:
        p2 = PendingOrder(
            symbol="ETHEUR",
            side="SELL",
            order_type="MARKET",
            price=50.0,
            quantity=1.0,
            mode="demo",
            status="PENDING",
        )
        db.add(p2)
        db.commit()
        db.refresh(p2)
        pid2 = int(p2.id)
    finally:
        db.close()

    resp = client.post(f"/api/orders/pending/{pid2}/reject")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("status") == "REJECTED"

    # cancel needs a fresh PENDING record
    db = SessionLocal()
    try:
        p3 = PendingOrder(
            symbol="XRPEUR",
            side="BUY",
            order_type="MARKET",
            price=1.0,
            quantity=10.0,
            mode="demo",
            status="PENDING",
        )
        db.add(p3)
        db.commit()
        db.refresh(p3)
        pid3 = int(p3.id)
    finally:
        db.close()

    resp = client.post(f"/api/orders/pending/{pid3}/cancel")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("status") == "REJECTED"


def test_pending_create_demo(client):
    resp = client.post(
        "/api/orders/pending?mode=demo",
        json={"symbol": "BTC/EUR", "side": "BUY", "quantity": 0.01, "price": 100.0, "reason": "manual"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("status") == "PENDING"
    assert data.get("symbol") == "BTCEUR"


def test_control_state_no_admin_token(client):
    resp = client.get("/api/control/state")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert "demo_trading_enabled" in data


def test_control_state_setters(client):
    resp = client.post("/api/control/state", json={"demo_trading_enabled": False})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("demo_trading_enabled") is False

    resp = client.post("/api/control/state", json={"watchlist": ["BTC/EUR", "WLFI/EUR"]})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("watchlist_source") == "override"
    assert isinstance(data.get("watchlist_override"), list)
    # normalized: strip "/" and "-" and upper
    assert "BTCEUR" in data.get("watchlist_override")


def test_close_position_creates_pending_sell(client):
    db = SessionLocal()
    try:
        md = MarketData(symbol="CLOSE1EUR", price=123.45)
        pos = Position(
            symbol="CLOSE1EUR",
            side="LONG",
            entry_price=120.0,
            quantity=0.5,
            current_price=123.45,
            unrealized_pnl=1.72,
            mode="demo",
        )
        db.add(md)
        db.add(pos)
        db.commit()
        db.refresh(pos)
        pid = int(pos.id)
    finally:
        db.close()

    resp = client.post(f"/api/positions/{pid}/close?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True

    db = SessionLocal()
    try:
        p = (
            db.query(PendingOrder)
            .filter(PendingOrder.symbol == "CLOSE1EUR", PendingOrder.mode == "demo")
            .order_by(PendingOrder.created_at.desc())
            .first()
        )
        assert p is not None
        assert p.status == "PENDING"
        assert p.side == "SELL"
        assert abs(float(p.quantity) - 0.5) < 1e-9
    finally:
        db.close()


def test_partial_close_position_creates_pending_sell_qty(client):
    db = SessionLocal()
    try:
        db.add(MarketData(symbol="CLOSE4EUR", price=50.0))
        pos = Position(
            symbol="CLOSE4EUR",
            side="LONG",
            entry_price=40.0,
            quantity=1.0,
            current_price=50.0,
            unrealized_pnl=10.0,
            mode="demo",
        )
        db.add(pos)
        db.commit()
        db.refresh(pos)
        pid = int(pos.id)
    finally:
        db.close()

    resp = client.post(f"/api/positions/{pid}/close?mode=demo&quantity=0.25")
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        p = (
            db.query(PendingOrder)
            .filter(PendingOrder.symbol == "CLOSE4EUR", PendingOrder.mode == "demo")
            .order_by(PendingOrder.created_at.desc())
            .first()
        )
        assert p is not None
        assert p.side == "SELL"
        assert abs(float(p.quantity) - 0.25) < 1e-9
    finally:
        db.close()


def test_close_all_positions_creates_multiple_pending(client):
    db = SessionLocal()
    try:
        db.add(MarketData(symbol="CLOSE2EUR", price=10.0))
        db.add(MarketData(symbol="CLOSE3EUR", price=20.0))
        db.add(
            Position(
                symbol="CLOSE2EUR",
                side="LONG",
                entry_price=9.0,
                quantity=1.0,
                current_price=10.0,
                unrealized_pnl=1.0,
                mode="demo",
            )
        )
        db.add(
            Position(
                symbol="CLOSE3EUR",
                side="LONG",
                entry_price=19.0,
                quantity=2.0,
                current_price=20.0,
                unrealized_pnl=2.0,
                mode="demo",
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/positions/close-all?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert int(data.get("created") or 0) >= 2

    db = SessionLocal()
    try:
        syms = {p.symbol for p in db.query(PendingOrder).filter(PendingOrder.mode == "demo").all()}
        assert "CLOSE2EUR" in syms
        assert "CLOSE3EUR" in syms
    finally:
        db.close()


def test_decision_trace_persists():
    db = SessionLocal()
    try:
        trace = save_decision_trace(
            db,
            symbol="BTCEUR",
            mode="demo",
            action_type="entry_blocked",
            reason_code="cost_gate_failed",
            signal_summary={"signal_type": "BUY", "confidence": 0.91},
            risk_gate_result={"daily_loss_triggered": False},
            cost_gate_result={"eligible": False, "required_move_ratio": 0.01},
            execution_gate_result={"eligible": True},
            config_snapshot_id="snap123",
            payload={"source": "test"},
        )
        db.commit()
        assert trace.id is not None
    finally:
        db.close()


def test_cost_ledger_rollup_updates_order():
    db = SessionLocal()
    try:
        order = Order(
            symbol="BTCEUR",
            side="SELL",
            order_type="MARKET",
            price=100.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=105.0,
            executed_quantity=1.0,
        )
        db.add(order)
        db.commit()
        db.refresh(order)

        save_cost_entry(db, symbol="BTCEUR", cost_type="taker_fee", order_id=order.id, actual_value=0.10, expected_value=0.10)
        save_cost_entry(db, symbol="BTCEUR", cost_type="slippage", order_id=order.id, actual_value=0.05, expected_value=0.05)
        save_cost_entry(db, symbol="BTCEUR", cost_type="spread", order_id=order.id, actual_value=0.02, expected_value=0.02)
        db.flush()

        summary = load_order_cost_summary(db, order.id)
        assert round(summary["total_cost"], 2) == 0.17

        attach_costs_to_order(db, order=order, gross_pnl=5.0, config_snapshot_id="snap123", exit_reason_code="tp_exit")
        db.commit()
        db.refresh(order)

        assert round(float(order.net_pnl or 0.0), 2) == 4.83
        assert order.config_snapshot_id == "snap123"
    finally:
        db.close()


def test_compute_demo_account_state_is_cost_aware():
    db = SessionLocal()
    try:
        buy = Order(
            symbol="TESTEUR",
            side="BUY",
            order_type="MARKET",
            price=100.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=100.0,
            executed_quantity=1.0,
        )
        db.add(buy)
        db.commit()
        db.refresh(buy)
        save_cost_entry(db, symbol="TESTEUR", cost_type="taker_fee", order_id=buy.id, actual_value=0.10, expected_value=0.10)
        attach_costs_to_order(db, order=buy, gross_pnl=0.0, config_snapshot_id="snapbuy", entry_reason_code="entry")

        sell = Order(
            symbol="TESTEUR",
            side="SELL",
            order_type="MARKET",
            price=110.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=110.0,
            executed_quantity=1.0,
        )
        db.add(sell)
        db.commit()
        db.refresh(sell)
        save_cost_entry(db, symbol="TESTEUR", cost_type="taker_fee", order_id=sell.id, actual_value=0.10, expected_value=0.10)
        attach_costs_to_order(db, order=sell, gross_pnl=10.0, config_snapshot_id="snapsell", exit_reason_code="exit")
        db.commit()

        state = compute_demo_account_state(db, quote_ccy="EUR")
        assert round(float(state["realized_pnl_total"]), 2) == 9.90
        assert round(float(state["total_cost"]), 2) == 0.10
        assert "profit_factor_net" in state
    finally:
        db.close()


def test_risk_blocks_when_max_open_positions_reached():
    db = SessionLocal()
    try:
        db.query(Position).delete()
        db.commit()
        apply_runtime_updates(
            db,
            {"max_open_positions": 1, "max_total_exposure_ratio": 0.95, "max_symbol_exposure_ratio": 0.95},
            actor="test",
            active_position_count=0,
        )
        db.add(
            Position(
                symbol="RISK1EUR",
                side="LONG",
                entry_price=100.0,
                quantity=1.0,
                current_price=100.0,
                unrealized_pnl=0.0,
                mode="demo",
            )
        )
        db.commit()

        ctx = build_risk_context(
            db,
            symbol="RISK2EUR",
            side="BUY",
            notional=50.0,
            strategy_name="demo_collector",
            mode="demo",
        )
        decision = evaluate_risk(ctx)
        assert decision.allowed is False
        assert "max_open_positions_gate" in decision.reason_codes
    finally:
        db.close()


def test_risk_can_reduce_size_near_exposure_limit():
    db = SessionLocal()
    try:
        db.query(Position).delete()
        db.commit()
        apply_runtime_updates(
            db,
            {"max_total_exposure_ratio": 0.2, "max_symbol_exposure_ratio": 0.9, "max_open_positions": 50},
            actor="test",
            active_position_count=0,
        )
        db.add(
            Position(
                symbol="RISK3EUR",
                side="LONG",
                entry_price=100.0,
                quantity=19.0,
                current_price=100.0,
                unrealized_pnl=0.0,
                mode="demo",
            )
        )
        db.commit()

        ctx = build_risk_context(
            db,
            symbol="RISK4EUR",
            side="BUY",
            notional=50.0,
            strategy_name="demo_collector",
            mode="demo",
        )
        decision = evaluate_risk(ctx)
        assert decision.allowed is True
        assert decision.position_size_multiplier < 1.0
        assert decision.action == "allow_with_reduced_size"
    finally:
        db.close()


def test_account_analytics_bundle_is_cost_aware(client):
    db = SessionLocal()
    try:
        buy = Order(
            symbol="ANAEUR",
            side="BUY",
            order_type="MARKET",
            price=100.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=100.0,
            executed_quantity=1.0,
        )
        db.add(buy)
        db.commit()
        db.refresh(buy)
        save_cost_entry(db, symbol="ANAEUR", cost_type="taker_fee", order_id=buy.id, actual_value=0.12, expected_value=0.12)
        attach_costs_to_order(db, order=buy, gross_pnl=0.0, config_snapshot_id="ana-snap-a", entry_reason_code="entry")

        sell = Order(
            symbol="ANAEUR",
            side="SELL",
            order_type="MARKET",
            price=110.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=110.0,
            executed_quantity=1.0,
        )
        db.add(sell)
        db.commit()
        db.refresh(sell)
        save_cost_entry(db, symbol="ANAEUR", cost_type="taker_fee", order_id=sell.id, actual_value=0.13, expected_value=0.13)
        save_cost_entry(db, symbol="ANAEUR", cost_type="slippage", order_id=sell.id, actual_value=0.07, expected_value=0.07)
        attach_costs_to_order(db, order=sell, gross_pnl=10.0, config_snapshot_id="ana-snap-a", exit_reason_code="take_profit")

        save_decision_trace(
            db,
            symbol="ANAEUR",
            mode="demo",
            action_type="entry_blocked",
            reason_code="cost_gate_failed",
            strategy_name="analytics_test",
            config_snapshot_id="ana-snap-a",
            payload={"stage": "analytics-test"},
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/account/analytics?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    overview = data.get("overview") or {}
    assert float(overview.get("net_pnl") or 0.0) >= 9.6
    assert float(overview.get("total_cost") or 0.0) >= 0.32
    cost_by_type = {item["cost_type"]: item["total_cost"] for item in (data.get("cost_by_type") or [])}
    assert float(cost_by_type.get("taker_fee") or 0.0) >= 0.35
    blocked = {item["reason_code"]: item["count"] for item in (data.get("blocked_by_reason") or [])}
    assert int(blocked.get("cost_gate_failed") or 0) >= 1
    snapshots = data.get("config_snapshots") or []
    assert any((item.get("config_snapshot_id") == "ana-snap-a") for item in snapshots)


def test_account_analytics_risk_effectiveness_endpoint(client):
    db = SessionLocal()
    try:
        save_decision_trace(
            db,
            symbol="RISKANAEUR",
            mode="demo",
            action_type="entry_blocked",
            reason_code="loss_streak_gate",
            strategy_name="risk_analytics_test",
            config_snapshot_id="risk-snap-a",
        )
        save_decision_trace(
            db,
            symbol="RISKANAEUR",
            mode="demo",
            action_type="entry_blocked",
            reason_code="kill_switch_gate",
            strategy_name="risk_analytics_test",
            config_snapshot_id="risk-snap-a",
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/account/analytics/risk-effectiveness?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    blocked = data.get("blocked_by_reason") or {}
    assert int(blocked.get("loss_streak_gate") or 0) >= 1
    assert int(blocked.get("kill_switch_gate") or 0) >= 1
    assert int(data.get("kill_switch_activations") or 0) >= 1


def test_portfolio_summary_uses_accounting_fields(client):
    db = SessionLocal()
    try:
        db.add(
            Position(
                symbol="PORTANAEUR",
                side="LONG",
                entry_price=50.0,
                current_price=55.0,
                quantity=2.0,
                unrealized_pnl=10.0,
                gross_pnl=10.0,
                net_pnl=9.7,
                total_cost=0.3,
                fee_cost=0.2,
                slippage_cost=0.05,
                spread_cost=0.05,
                mode="demo",
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/portfolio/summary?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert int(data.get("total_positions") or 0) >= 1
    assert float(data.get("net_pnl") or 0.0) >= 9.7
    assert float(data.get("total_cost") or 0.0) >= 0.3


def test_runtime_updates_persist_full_config_snapshot_payload():
    db = SessionLocal()
    try:
        baseline = build_runtime_state(db, active_position_count=0)
        baseline_snapshot_id = baseline.get("config_snapshot_id")
        baseline_snapshot = get_config_snapshot(db, baseline_snapshot_id)
        assert baseline_snapshot is not None
        assert "sections" in (baseline_snapshot.get("payload") or {})

        result = apply_runtime_updates(
            db,
            {"min_edge_multiplier": 3.4, "max_trades_per_day": 7},
            actor="test_snapshot",
            active_position_count=0,
        )
        snapshot_id = (result.get("snapshot") or {}).get("id") or (result.get("state") or {}).get("config_snapshot_id")
        snapshot = get_config_snapshot(db, snapshot_id)
        assert snapshot is not None
        payload = snapshot.get("payload") or {}
        assert float((((payload.get("sections") or {}).get("costs") or {}).get("min_edge_multiplier") or 0.0)) == 3.4
        assert int((((payload.get("sections") or {}).get("trading") or {}).get("max_trades_per_day") or 0)) == 7
        assert snapshot.get("previous_snapshot_id") == baseline_snapshot_id
        changed_fields = snapshot.get("changed_fields") or []
        assert "min_edge_multiplier" in changed_fields
        assert "max_trades_per_day" in changed_fields
    finally:
        db.close()


def test_compare_config_snapshots_returns_field_diff():
    db = SessionLocal()
    try:
        first = apply_runtime_updates(
            db,
            {"risk_per_trade": 0.0125},
            actor="test_compare_a",
            active_position_count=0,
        )
        second = apply_runtime_updates(
            db,
            {"risk_per_trade": 0.02, "max_cost_leakage_ratio": 0.4},
            actor="test_compare_b",
            active_position_count=0,
        )
        first_id = (first.get("snapshot") or {}).get("id")
        second_id = (second.get("snapshot") or {}).get("id")
        comparison = compare_config_snapshots(db, first_id, second_id)
        changed = set(comparison.get("changed_fields") or [])
        assert "sections.risk.risk_per_trade" in changed
        assert "sections.risk.max_cost_leakage_ratio" in changed
    finally:
        db.close()


def test_config_snapshot_compare_endpoint(client):
    db = SessionLocal()
    try:
        a = apply_runtime_updates(
            db,
            {"min_expected_rr": 1.7},
            actor="test_compare_endpoint_a",
            active_position_count=0,
        )
        b = apply_runtime_updates(
            db,
            {"min_expected_rr": 2.2},
            actor="test_compare_endpoint_b",
            active_position_count=0,
        )
        snapshot_a = (a.get("snapshot") or {}).get("id")
        snapshot_b = (b.get("snapshot") or {}).get("id")
    finally:
        db.close()

    resp = client.get(
        f"/api/account/analytics/config-snapshots/compare?snapshot_a={snapshot_a}&snapshot_b={snapshot_b}&mode=demo"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    changed = set(data.get("changed_fields") or [])
    assert "sections.execution.min_expected_rr" in changed
    assert (data.get("snapshot_a") or {}).get("id") == snapshot_a
    assert (data.get("snapshot_b") or {}).get("id") == snapshot_b


def test_experiment_comparison_verdict_candidate_wins():
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(
            db,
            {"min_edge_multiplier": 2.8},
            actor="exp_baseline",
            active_position_count=0,
        )
        candidate = apply_runtime_updates(
            db,
            {"min_edge_multiplier": 3.2},
            actor="exp_candidate",
            active_position_count=0,
        )
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")

        buy_a = Order(symbol="EXPEUR", side="BUY", order_type="MARKET", price=100.0, quantity=1.0, status="FILLED", mode="demo", executed_price=100.0, executed_quantity=1.0, config_snapshot_id=baseline_id)
        sell_a = Order(symbol="EXPEUR", side="SELL", order_type="MARKET", price=105.0, quantity=1.0, status="FILLED", mode="demo", executed_price=105.0, executed_quantity=1.0, config_snapshot_id=baseline_id)
        db.add_all([buy_a, sell_a])
        db.commit()
        db.refresh(sell_a)
        attach_costs_to_order(db, order=buy_a, gross_pnl=0.0, config_snapshot_id=baseline_id, entry_reason_code="entry")
        save_cost_entry(db, symbol="EXPEUR", cost_type="taker_fee", order_id=sell_a.id, actual_value=0.30, expected_value=0.30, config_snapshot_id=baseline_id)
        attach_costs_to_order(db, order=sell_a, gross_pnl=5.0, config_snapshot_id=baseline_id, exit_reason_code="exit")

        buy_b = Order(symbol="EXPEUR", side="BUY", order_type="MARKET", price=100.0, quantity=1.0, status="FILLED", mode="demo", executed_price=100.0, executed_quantity=1.0, config_snapshot_id=candidate_id)
        sell_b = Order(symbol="EXPEUR", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", executed_price=108.0, executed_quantity=1.0, config_snapshot_id=candidate_id)
        db.add_all([buy_b, sell_b])
        db.commit()
        db.refresh(sell_b)
        attach_costs_to_order(db, order=buy_b, gross_pnl=0.0, config_snapshot_id=candidate_id, entry_reason_code="entry")
        save_cost_entry(db, symbol="EXPEUR", cost_type="taker_fee", order_id=sell_b.id, actual_value=0.10, expected_value=0.10, config_snapshot_id=candidate_id)
        attach_costs_to_order(db, order=sell_b, gross_pnl=8.0, config_snapshot_id=candidate_id, exit_reason_code="exit")

        save_decision_trace(db, symbol="EXPEUR", mode="demo", action_type="entry_blocked", reason_code="cost_gate_failed", strategy_name="exp_strategy", config_snapshot_id=baseline_id)
        save_decision_trace(db, symbol="EXPEUR", mode="demo", action_type="position_closed", reason_code="take_profit", strategy_name="exp_strategy", order_id=sell_a.id, config_snapshot_id=baseline_id)
        save_decision_trace(db, symbol="EXPEUR", mode="demo", action_type="position_closed", reason_code="take_profit", strategy_name="exp_strategy", order_id=sell_b.id, config_snapshot_id=candidate_id)
        db.commit()

        comparison = compare_snapshots_for_experiment(
            db,
            baseline_snapshot_id=baseline_id,
            candidate_snapshot_id=candidate_id,
            mode="demo",
        )
        assert comparison["verdict"]["winner"] == "candidate"
        assert "candidate_net_pnl_up" in comparison["verdict"]["reason_codes"]
    finally:
        db.close()


def test_experiment_compare_endpoint_and_create_experiment(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(
            db,
            {"max_trades_per_day": 8},
            actor="exp_api_baseline",
            active_position_count=0,
        )
        candidate = apply_runtime_updates(
            db,
            {"max_trades_per_day": 5},
            actor="exp_api_candidate",
            active_position_count=0,
        )
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")

        sell_a = Order(symbol="EXPAEUR", side="SELL", order_type="MARKET", price=104.0, quantity=1.0, status="FILLED", mode="demo", executed_price=104.0, executed_quantity=1.0, gross_pnl=4.0, net_pnl=3.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id)
        sell_b = Order(symbol="EXPAEUR", side="SELL", order_type="MARKET", price=107.0, quantity=1.0, status="FILLED", mode="demo", executed_price=107.0, executed_quantity=1.0, gross_pnl=7.0, net_pnl=6.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id)
        db.add_all([sell_a, sell_b])
        db.commit()
        db.refresh(sell_a)
        db.refresh(sell_b)
        save_decision_trace(db, symbol="EXPAEUR", mode="demo", action_type="position_closed", reason_code="tp", strategy_name="exp_api_strategy", order_id=sell_a.id, config_snapshot_id=baseline_id)
        save_decision_trace(db, symbol="EXPAEUR", mode="demo", action_type="position_closed", reason_code="tp", strategy_name="exp_api_strategy", order_id=sell_b.id, config_snapshot_id=candidate_id)
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/account/analytics/experiments/compare?baseline_snapshot_id={baseline_id}&candidate_snapshot_id={candidate_id}&mode=demo")
    assert resp.status_code == 200
    data = (resp.json().get("data") or {})
    assert data["verdict"]["winner"] in {"candidate", "baseline", "inconclusive"}

    resp = client.post(
        "/api/account/analytics/experiments",
        json={
            "name": "Daily cap comparison",
            "baseline_snapshot_id": baseline_id,
            "candidate_snapshot_id": candidate_id,
            "mode": "demo",
            "scope": "global",
            "notes": "smoke test",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    experiment = payload.get("data") or {}
    assert experiment.get("name") == "Daily cap comparison"
    experiment_id = experiment.get("id")
    assert experiment.get("baseline") is not None
    assert experiment.get("candidate") is not None

    resp = client.get(f"/api/account/analytics/experiments/{experiment_id}")
    assert resp.status_code == 200
    assert (resp.json().get("data") or {}).get("id") == experiment_id

    resp = client.get("/api/account/analytics/experiments")
    assert resp.status_code == 200
    experiments = resp.json().get("data") or []
    assert any(item.get("id") == experiment_id for item in experiments)


def test_recommendation_evaluate_promote():
    experiment = {
        "verdict": {"winner": "candidate", "reason_codes": ["candidate_net_pnl_up", "candidate_expectancy_up"]},
        "baseline": {"metrics": {"net_pnl": 5.0, "cost_leakage_ratio": 0.20, "drawdown_net": -2.0, "net_expectancy": 1.0, "trade_count": 5, "risk_actions_count": 1}},
        "candidate": {"metrics": {"net_pnl": 8.0, "cost_leakage_ratio": 0.15, "drawdown_net": -1.5, "net_expectancy": 1.4, "trade_count": 5, "risk_actions_count": 1}},
    }
    comparison = {"diff": [{"field": "sections.costs.min_edge_multiplier", "old_value": 2.5, "new_value": 3.0}]}
    result = evaluate_recommendation(experiment, comparison)
    assert result["recommendation"] == "promote"
    assert "candidate_outperformed_net" in result["reason_codes"]


def test_recommendation_evaluate_rollback_candidate():
    experiment = {
        "verdict": {"winner": "baseline", "reason_codes": ["candidate_net_pnl_down", "candidate_drawdown_worse"]},
        "baseline": {"metrics": {"net_pnl": 7.0, "cost_leakage_ratio": 0.12, "drawdown_net": -1.0, "net_expectancy": 1.2, "trade_count": 6, "risk_actions_count": 1}},
        "candidate": {"metrics": {"net_pnl": 3.0, "cost_leakage_ratio": 0.25, "drawdown_net": -3.5, "net_expectancy": 0.4, "trade_count": 8, "risk_actions_count": 4}},
    }
    comparison = {"diff": [{"field": "sections.risk.risk_per_trade", "old_value": 0.01, "new_value": 0.03}]}
    result = evaluate_recommendation(experiment, comparison)
    assert result["recommendation"] == "rollback_candidate"
    assert "candidate_degraded_risk_or_cost" in result["reason_codes"]


def test_recommendation_evaluate_needs_more_data():
    experiment = {
        "verdict": {"winner": "inconclusive", "reason_codes": ["insufficient_edge"]},
        "baseline": {"metrics": {"net_pnl": 1.0, "cost_leakage_ratio": 0.10, "drawdown_net": -0.5, "net_expectancy": 1.0, "trade_count": 0, "risk_actions_count": 0}},
        "candidate": {"metrics": {"net_pnl": 1.2, "cost_leakage_ratio": 0.09, "drawdown_net": -0.5, "net_expectancy": 1.1, "trade_count": 0, "risk_actions_count": 0}},
    }
    comparison = {"diff": []}
    result = evaluate_recommendation(experiment, comparison)
    assert result["recommendation"] == "needs_more_data"
    assert "insufficient_trade_sample" in result["reason_codes"]


def test_recommendation_create_read_list_flow(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(
            db,
            {"max_open_positions": 6},
            actor="rec_flow_baseline",
            active_position_count=0,
        )
        candidate = apply_runtime_updates(
            db,
            {"max_open_positions": 4},
            actor="rec_flow_candidate",
            active_position_count=0,
        )
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        baseline_sell = Order(symbol="RECEUR", side="SELL", order_type="MARKET", price=104.0, quantity=1.0, status="FILLED", mode="demo", executed_price=104.0, executed_quantity=1.0, gross_pnl=4.0, net_pnl=3.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id)
        candidate_sell = Order(symbol="RECEUR", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", executed_price=108.0, executed_quantity=1.0, gross_pnl=8.0, net_pnl=7.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id)
        db.add_all([baseline_sell, candidate_sell])
        db.commit()
        db.refresh(baseline_sell)
        db.refresh(candidate_sell)
        save_decision_trace(db, symbol="RECEUR", mode="demo", action_type="position_closed", reason_code="tp", strategy_name="rec_strategy", order_id=baseline_sell.id, config_snapshot_id=baseline_id)
        save_decision_trace(db, symbol="RECEUR", mode="demo", action_type="position_closed", reason_code="tp", strategy_name="rec_strategy", order_id=candidate_sell.id, config_snapshot_id=candidate_id)
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/account/analytics/experiments",
        json={
            "name": "Recommendation flow experiment",
            "baseline_snapshot_id": baseline_id,
            "candidate_snapshot_id": candidate_id,
            "mode": "demo",
            "scope": "global",
        },
    )
    assert resp.status_code == 200
    experiment = resp.json().get("data") or {}
    experiment_id = experiment.get("id")

    resp = client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id, "notes": "smoke recommendation"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    recommendation = payload.get("data") or {}
    recommendation_id = recommendation.get("id")
    assert recommendation.get("recommendation") in {"promote", "reject", "watch", "needs_more_data", "rollback_candidate"}
    assert isinstance(recommendation.get("parameter_changes"), list)

    resp = client.get(f"/api/account/analytics/recommendations/{recommendation_id}")
    assert resp.status_code == 200
    assert (resp.json().get("data") or {}).get("id") == recommendation_id

    resp = client.get("/api/account/analytics/recommendations")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    assert any(item.get("id") == recommendation_id for item in items)

    resp = client.get("/api/account/analytics/recommendations/overview")
    assert resp.status_code == 200
    overview = (resp.json().get("data") or {}).get("overview") or {}
    assert int(overview.get("total") or 0) >= 1


def test_recommendation_review_approve_flow(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"loss_streak_limit": 4}, actor="review_baseline", active_position_count=0)
        candidate = apply_runtime_updates(db, {"loss_streak_limit": 3}, actor="review_candidate", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="REVAEUR", side="SELL", order_type="MARKET", price=106.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=6.0, net_pnl=5.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="REVAEUR", side="SELL", order_type="MARKET", price=110.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=10.0, net_pnl=9.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.commit()
        exp_resp = client.post("/api/account/analytics/experiments", json={"name": "Approve review flow", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"})
        experiment_id = (exp_resp.json().get("data") or {}).get("id")
        rec_resp = client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id})
        recommendation_id = (rec_resp.json().get("data") or {}).get("id")
    finally:
        db.close()

    resp = client.get(f"/api/account/analytics/recommendations/{recommendation_id}/review")
    assert resp.status_code == 200
    assert ((resp.json().get("data") or {}).get("current_status")) == "open"

    resp = client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/start-review",
        json={"reviewed_by": "tester", "decision_reason": "initial_review"},
    )
    assert resp.status_code == 200
    assert (((resp.json().get("data") or {}).get("current_status"))) == "under_review"

    resp = client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/approve",
        json={"reviewed_by": "tester", "decision_reason": "looks_good", "notes": "ready for later promotion"},
    )
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("current_status") == "approved"
    latest = data.get("latest_review") or {}
    assert latest.get("promotion_ready") is True


def test_recommendation_review_reject_and_invalid_transition(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"max_symbol_exposure_ratio": 0.5}, actor="reject_baseline", active_position_count=0)
        candidate = apply_runtime_updates(db, {"max_symbol_exposure_ratio": 0.9}, actor="reject_candidate", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="REVREJ", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="REVREJ", side="SELL", order_type="MARKET", price=103.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=3.0, net_pnl=2.5, total_cost=0.5, fee_cost=0.5, config_snapshot_id=candidate_id))
        db.commit()
        experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Reject review flow", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
        recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    finally:
        db.close()

    resp = client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/reject",
        json={"reviewed_by": "tester", "decision_reason": "risk_too_high"},
    )
    assert resp.status_code == 200
    assert ((resp.json().get("data") or {}).get("current_status")) == "rejected"

    resp = client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/approve",
        json={"reviewed_by": "tester", "decision_reason": "conflicting"},
    )
    assert resp.status_code == 409


def test_recommendation_review_defer_flow(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"max_trades_per_hour_per_symbol": 1}, actor="defer_baseline", active_position_count=0)
        candidate = apply_runtime_updates(db, {"max_trades_per_hour_per_symbol": 3}, actor="defer_candidate", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="REVDEF", side="SELL", order_type="MARKET", price=101.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=1.0, net_pnl=0.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=baseline_id))
        db.add(Order(symbol="REVDEF", side="SELL", order_type="MARKET", price=101.2, quantity=1.0, status="FILLED", mode="demo", gross_pnl=1.2, net_pnl=1.1, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.commit()
        experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Defer review flow", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
        recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    finally:
        db.close()

    resp = client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/defer",
        json={"reviewed_by": "tester", "decision_reason": "need_longer_window", "notes": "wait for more samples"},
    )
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("current_status") == "deferred"
    assert (data.get("latest_review") or {}).get("promotion_ready") is False

    resp = client.get("/api/account/analytics/recommendations/review-queue")
    assert resp.status_code == 200
    queue = resp.json().get("data") or []
    assert any(item.get("id") == recommendation_id for item in queue)


def test_controlled_promotion_success_flow(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"max_open_positions": 5}, actor="promo_baseline", active_position_count=0)
        candidate = apply_runtime_updates(db, {"max_open_positions": 3}, actor="promo_candidate", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PROMOEUR", side="SELL", order_type="MARKET", price=104.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=4.0, net_pnl=3.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PROMOEUR", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Promotion flow", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    resp = client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/approve",
        json={"reviewed_by": "tester", "decision_reason": "approve_for_promotion"},
    )
    assert resp.status_code == 200

    # Restore the active runtime to the approved baseline before promotion.
    db = SessionLocal()
    try:
        db.query(Position).delete()
        db.commit()
        apply_runtime_updates(db, {"max_open_positions": 5}, actor="promo_restore_baseline", active_position_count=0)
    finally:
        db.close()

    resp = client.post(
        "/api/account/analytics/promotions",
        json={"recommendation_id": recommendation_id, "initiated_by": "tester", "notes": "controlled promotion"},
    )
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "applied"
    assert data.get("from_snapshot_id") == baseline_id
    assert data.get("to_snapshot_id") == candidate_id
    assert data.get("post_promotion_monitoring_status") == "pending"
    promotion_id = data.get("id")
    apply_result = data.get("runtime_apply_result") or {}

    resp = client.get(f"/api/account/analytics/promotions/{promotion_id}")
    assert resp.status_code == 200
    assert ((resp.json().get("data") or {}).get("id")) == promotion_id

    resp = client.get("/api/control/state")
    assert resp.status_code == 200
    assert ((resp.json().get("data") or {}).get("config_snapshot_id")) == ((apply_result.get("state") or {}).get("config_snapshot_id"))


def test_controlled_promotion_requires_approval(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"loss_streak_limit": 6}, actor="promo_req_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"loss_streak_limit": 2}, actor="promo_req_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PROMOREQ", side="SELL", order_type="MARKET", price=103.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=3.0, net_pnl=2.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PROMOREQ", side="SELL", order_type="MARKET", price=107.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=7.0, net_pnl=6.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Promotion requires approval", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    resp = client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"})
    assert resp.status_code == 409


def test_controlled_promotion_missing_snapshot_fails(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 45}, actor="promo_miss_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 15}, actor="promo_miss_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PROMOMISS", side="SELL", order_type="MARKET", price=105.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=5.0, net_pnl=4.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PROMOMISS", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Promotion missing snapshot", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/approve",
        json={"reviewed_by": "tester", "decision_reason": "approved_before_missing_snapshot"},
    )

    db = SessionLocal()
    try:
        snap = db.query(ConfigSnapshot).filter(ConfigSnapshot.id == candidate_id).first()
        if snap is not None:
            db.delete(snap)
            db.commit()
    finally:
        db.close()

    resp = client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"})
    assert resp.status_code == 409


def test_controlled_promotion_duplicate_attempt_fails(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"max_daily_drawdown": 0.04}, actor="promo_dup_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"max_daily_drawdown": 0.02}, actor="promo_dup_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PROMODUP", side="SELL", order_type="MARKET", price=104.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=4.0, net_pnl=3.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PROMODUP", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Promotion duplicate", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(
        f"/api/account/analytics/recommendations/{recommendation_id}/approve",
        json={"reviewed_by": "tester", "decision_reason": "approve_duplicate_case"},
    )
    db = SessionLocal()
    try:
        db.query(Position).delete()
        db.commit()
        apply_runtime_updates(db, {"max_daily_drawdown": 0.04}, actor="promo_dup_restore", active_position_count=0)
    finally:
        db.close()

    first = client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"})
    assert first.status_code == 200
    second = client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"})
    assert second.status_code == 409


def test_post_promotion_monitoring_initializes_after_promotion(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 60}, actor="mon_init_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 20}, actor="mon_init_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="MONINIT", side="SELL", order_type="MARKET", price=104.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=4.0, net_pnl=3.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="MONINIT", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Monitoring init", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "monitoring_init"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 60}, actor="mon_init_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")

    resp = client.get(f"/api/account/analytics/promotions/{promotion_id}/monitoring")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "pending"
    assert (data.get("promotion") or {}).get("post_promotion_monitoring_status") == "pending"


def test_post_promotion_monitoring_healthy_verdict(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"loss_streak_limit": 5}, actor="mon_health_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"loss_streak_limit": 2}, actor="mon_health_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="MONHEAL", side="SELL", order_type="MARKET", price=103.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=3.0, net_pnl=2.7, total_cost=0.3, fee_cost=0.3, config_snapshot_id=baseline_id))
        db.add(Order(symbol="MONHEAL", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Monitoring healthy", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "monitoring_healthy"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"loss_streak_limit": 5}, actor="mon_health_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="MONHEAL", side="SELL", order_type="MARKET", price=110.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=10.0, net_pnl=9.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="MONHEAL", side="SELL", order_type="MARKET", price=111.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=11.0, net_pnl=10.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "healthy check"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "healthy"
    assert data.get("rollback_recommended") is False


def test_post_promotion_monitoring_collecting_and_rollback_candidate(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"risk_per_trade": 0.01}, actor="mon_warn_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"risk_per_trade": 0.02}, actor="mon_warn_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="MONWARN", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="MONWARN", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Monitoring rollback", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "monitoring_warning"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"risk_per_trade": 0.01}, actor="mon_warn_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    resp = client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "too early"})
    assert resp.status_code == 200
    early = resp.json().get("data") or {}
    assert early.get("status") == "collecting"
    assert "POST_PROMOTION_SAMPLE_TOO_SMALL" in (early.get("reason_codes") or [])

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        losing_a = Order(symbol="MONWARN", side="SELL", order_type="MARKET", price=95.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-5.0, net_pnl=-6.5, total_cost=1.5, fee_cost=1.5, config_snapshot_id=promoted_snapshot_id, timestamp=now)
        losing_b = Order(symbol="MONWARN", side="SELL", order_type="MARKET", price=94.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-6.0, net_pnl=-7.8, total_cost=1.8, fee_cost=1.8, config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.add_all([losing_a, losing_b])
        db.commit()
        db.refresh(losing_a)
        db.refresh(losing_b)
        save_decision_trace(db, symbol="MONWARN", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="MONWARN", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "rollback check"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") in {"warning", "rollback_candidate"}
    assert data.get("rollback_recommended") is (data.get("status") == "rollback_candidate")
    resp = client.get("/api/account/analytics/promotion-monitoring")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    assert any(item.get("promotion_id") == promotion_id for item in items)


def test_rollback_decision_no_action_for_healthy_monitoring(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"loss_streak_limit": 6}, actor="rb_noop_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"loss_streak_limit": 3}, actor="rb_noop_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="RBNOOP", side="SELL", order_type="MARKET", price=103.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=3.0, net_pnl=2.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="RBNOOP", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Rollback no action", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "rollback_no_action"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"loss_streak_limit": 6}, actor="rb_noop_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="RBNOOP", side="SELL", order_type="MARKET", price=111.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=11.0, net_pnl=10.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="RBNOOP", side="SELL", order_type="MARKET", price=112.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=12.0, net_pnl=11.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "healthy for rollback"})
    resp = client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "healthy decision"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("decision_status") == "no_action"
    assert "ROLLBACK_NO_ACTION_HEALTHY" in (data.get("reason_codes") or [])


def test_rollback_decision_continue_monitoring_for_collecting(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 70}, actor="rb_collect_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 15}, actor="rb_collect_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="RBCOLL", side="SELL", order_type="MARKET", price=104.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=4.0, net_pnl=3.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="RBCOLL", side="SELL", order_type="MARKET", price=107.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=7.0, net_pnl=6.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Rollback collect", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "rollback_collect"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 70}, actor="rb_collect_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")

    resp = client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "collecting decision"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("decision_status") == "continue_monitoring"
    assert "ROLLBACK_SAMPLE_TOO_SMALL" in (data.get("reason_codes") or [])


def test_rollback_decision_required_for_rollback_candidate(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"risk_per_trade": 0.012}, actor="rb_req_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"risk_per_trade": 0.025}, actor="rb_req_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="RBREQ", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=baseline_id))
        db.add(Order(symbol="RBREQ", side="SELL", order_type="MARKET", price=110.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=10.0, net_pnl=9.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Rollback required", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "rollback_required"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"risk_per_trade": 0.012}, actor="rb_req_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="RBREQ", side="SELL", order_type="MARKET", price=94.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-6.0, net_pnl=-8.0, total_cost=2.0, fee_cost=2.0, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="RBREQ", side="SELL", order_type="MARKET", price=93.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-7.0, net_pnl=-9.3, total_cost=2.3, fee_cost=2.3, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="RBREQ", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="RBREQ", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "rollback required monitor"})
    resp = client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "required decision"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("decision_status") == "rollback_required"
    assert "ROLLBACK_NET_PNL_DEGRADATION" in (data.get("reason_codes") or [])
    assert data.get("urgency") == "critical"


def test_rollback_decision_read_and_list_flow(client):
    resp = client.get("/api/account/analytics/rollbacks")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    assert len(items) >= 1
    rollback_id = items[0].get("id")

    resp = client.get(f"/api/account/analytics/rollbacks/{rollback_id}")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("id") == rollback_id

    promotion_id = ((data.get("promotion") or {}).get("id"))
    resp = client.get(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision")
    assert resp.status_code == 200
    latest = resp.json().get("data") or {}
    assert latest.get("promotion_id") == promotion_id


def test_rollback_execution_success_flow(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"risk_per_trade": 0.013}, actor="rb_exec_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"risk_per_trade": 0.03}, actor="rb_exec_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="RBEXEC", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=baseline_id))
        db.add(Order(symbol="RBEXEC", side="SELL", order_type="MARKET", price=110.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=10.0, net_pnl=9.7, total_cost=0.3, fee_cost=0.3, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Rollback execute", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "rollback_execute"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"risk_per_trade": 0.013}, actor="rb_exec_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="RBEXEC", side="SELL", order_type="MARKET", price=93.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-7.0, net_pnl=-9.5, total_cost=2.5, fee_cost=2.5, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="RBEXEC", side="SELL", order_type="MARKET", price=92.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-8.0, net_pnl=-10.8, total_cost=2.8, fee_cost=2.8, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="RBEXEC", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="RBEXEC", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "rollback execution monitor"})
    rollback = (client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "execute me"}).json().get("data") or {})
    rollback_id = rollback.get("id")

    resp = client.post(f"/api/account/analytics/rollbacks/{rollback_id}/execute", json={"initiated_by": "tester", "notes": "rollback now"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("execution_status") == "executed"
    hook = (((data.get("runtime_apply_result") or {}).get("post_rollback_hook")) or {})
    assert hook.get("status") == "pending"
    assert data.get("post_rollback_monitoring_status") == "pending"

    db = SessionLocal()
    try:
        state = build_runtime_state(db, active_position_count=0)
    finally:
        db.close()
    assert state.get("config_snapshot_id") == rollback.get("rollback_snapshot_id")


def test_rollback_execution_invalid_state_rejected(client):
    items = (client.get("/api/account/analytics/rollbacks").json().get("data") or [])
    no_action = next((item for item in items if item.get("decision_status") == "no_action"), None)
    assert no_action is not None
    resp = client.post(
        f"/api/account/analytics/rollbacks/{no_action['id']}/execute",
        json={"initiated_by": "tester", "notes": "should fail"},
    )
    assert resp.status_code == 409


def test_rollback_execution_missing_target_fails(client):
    items = (client.get("/api/account/analytics/rollbacks").json().get("data") or [])
    candidate = next((item for item in items if item.get("decision_status") in {"rollback_recommended", "rollback_required"} and item.get("execution_status") == "pending"), None)
    if candidate is None:
        pytest.skip("No pending rollback candidate available")
    rollback_id = candidate["id"]

    db = SessionLocal()
    try:
        rollback_ref = db.query(ConfigRollback).filter(ConfigRollback.id == rollback_id).first()
        rollback_ref.rollback_snapshot_id = "missing-snapshot-id"
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/account/analytics/rollbacks/{rollback_id}/execute",
        json={"initiated_by": "tester", "notes": "missing target"},
    )
    assert resp.status_code == 409


def test_rollback_execution_duplicate_attempt_fails(client):
    items = (client.get("/api/account/analytics/rollback-executions").json().get("data") or [])
    executed = next((item for item in items if item.get("execution_status") == "executed"), None)
    assert executed is not None
    resp = client.post(
        f"/api/account/analytics/rollbacks/{executed['id']}/execute",
        json={"initiated_by": "tester", "notes": "duplicate"},
    )
    assert resp.status_code == 409


def test_rollback_execution_runtime_drift_case(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 80}, actor="rb_drift_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 10}, actor="rb_drift_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="RBDRIFT", side="SELL", order_type="MARKET", price=108.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=8.0, net_pnl=7.9, total_cost=0.1, fee_cost=0.1, config_snapshot_id=baseline_id))
        db.add(Order(symbol="RBDRIFT", side="SELL", order_type="MARKET", price=110.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=10.0, net_pnl=9.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Rollback drift", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "rollback_drift"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 80}, actor="rb_drift_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="RBDRIFT", side="SELL", order_type="MARKET", price=91.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-9.0, net_pnl=-11.5, total_cost=2.5, fee_cost=2.5, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="RBDRIFT", side="SELL", order_type="MARKET", price=90.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-10.0, net_pnl=-12.8, total_cost=2.8, fee_cost=2.8, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="RBDRIFT", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="RBDRIFT", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
        apply_runtime_updates(db, {"max_open_positions": 9}, actor="rb_drift_runtime_change", active_position_count=0)
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "rollback drift monitor"})
    rollback = (client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "drift decision"}).json().get("data") or {})
    rollback_id = rollback.get("id")
    resp = client.post(
        f"/api/account/analytics/rollbacks/{rollback_id}/execute",
        json={"initiated_by": "tester", "notes": "drift execute"},
    )
    assert resp.status_code == 409

    resp = client.get(f"/api/account/analytics/rollbacks/{rollback_id}")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("execution_status") == "failed"
    assert "ROLLBACK_RUNTIME_DRIFT" in (data.get("failure_reason") or "")


def test_rollback_execution_audit_trail_read(client):
    resp = client.get("/api/account/analytics/rollback-executions")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    assert len(items) >= 1
    rollback_id = items[0].get("id")

    resp = client.get(f"/api/account/analytics/rollback-executions/{rollback_id}")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("id") == rollback_id
    assert data.get("rollback") is not None


def test_post_rollback_monitoring_initializes_after_execution(client):
    resp = client.get("/api/account/analytics/rollback-executions")
    assert resp.status_code == 200
    executed = next((item for item in (resp.json().get("data") or []) if item.get("execution_status") == "executed"), None)
    assert executed is not None
    rollback_id = executed.get("id")

    resp = client.get(f"/api/account/analytics/rollbacks/{rollback_id}/post-monitoring")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "pending"
    assert (data.get("rollback") or {}).get("post_rollback_monitoring_status") == "pending"


def test_post_rollback_monitoring_stabilized_verdict(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"max_daily_drawdown": 0.06}, actor="prm_stable_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"max_daily_drawdown": 0.02}, actor="prm_stable_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PRMSTAB", side="SELL", order_type="MARKET", price=106.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=6.0, net_pnl=5.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PRMSTAB", side="SELL", order_type="MARKET", price=110.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=10.0, net_pnl=9.6, total_cost=0.4, fee_cost=0.4, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Post rollback stabilized", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "prm_stabilized"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"max_daily_drawdown": 0.06}, actor="prm_stable_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="PRMSTAB", side="SELL", order_type="MARKET", price=92.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-8.0, net_pnl=-10.2, total_cost=2.2, fee_cost=2.2, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="PRMSTAB", side="SELL", order_type="MARKET", price=91.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-9.0, net_pnl=-11.3, total_cost=2.3, fee_cost=2.3, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="PRMSTAB", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="PRMSTAB", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "stabilized rollback monitor"})
    rollback = (client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "stabilized rollback decision"}).json().get("data") or {})
    rollback_id = rollback.get("id")
    execution = (client.post(f"/api/account/analytics/rollbacks/{rollback_id}/execute", json={"initiated_by": "tester", "notes": "stabilized rollback execute"}).json().get("data") or {})
    target_snapshot_id = (((execution.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="PRMSTAB", side="SELL", order_type="MARKET", price=113.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=13.0, net_pnl=12.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=target_snapshot_id, timestamp=now))
        db.add(Order(symbol="PRMSTAB", side="SELL", order_type="MARKET", price=114.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=14.0, net_pnl=13.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=target_snapshot_id, timestamp=now))
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/account/analytics/rollbacks/{rollback_id}/post-monitoring/evaluate", json={"notes": "stabilized check"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "stabilized"


def test_post_rollback_monitoring_collecting_verdict(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"loss_streak_limit": 7}, actor="prm_collect_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"loss_streak_limit": 2}, actor="prm_collect_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PRMCOLL", side="SELL", order_type="MARKET", price=105.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=5.0, net_pnl=4.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PRMCOLL", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.7, total_cost=0.3, fee_cost=0.3, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Post rollback collect", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "prm_collect"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"loss_streak_limit": 7}, actor="prm_collect_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="PRMCOLL", side="SELL", order_type="MARKET", price=94.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-6.0, net_pnl=-8.0, total_cost=2.0, fee_cost=2.0, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="PRMCOLL", side="SELL", order_type="MARKET", price=93.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-7.0, net_pnl=-9.1, total_cost=2.1, fee_cost=2.1, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="PRMCOLL", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="PRMCOLL", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "collect rollback monitor"})
    rollback = (client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "collect rollback decision"}).json().get("data") or {})
    rollback_id = rollback.get("id")
    client.post(f"/api/account/analytics/rollbacks/{rollback_id}/execute", json={"initiated_by": "tester", "notes": "collect rollback execute"})

    resp = client.post(f"/api/account/analytics/rollbacks/{rollback_id}/post-monitoring/evaluate", json={"notes": "too early"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "collecting"
    assert "POST_ROLLBACK_SAMPLE_TOO_SMALL" in (data.get("reason_codes") or [])


def test_post_rollback_monitoring_escalate_verdict(client):
    db = SessionLocal()
    try:
        baseline = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 75}, actor="prm_escalate_base", active_position_count=0)
        candidate = apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 5}, actor="prm_escalate_cand", active_position_count=0)
        baseline_id = (baseline.get("snapshot") or {}).get("id")
        candidate_id = (candidate.get("snapshot") or {}).get("id")
        db.add(Order(symbol="PRMESC", side="SELL", order_type="MARKET", price=106.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=6.0, net_pnl=5.8, total_cost=0.2, fee_cost=0.2, config_snapshot_id=baseline_id))
        db.add(Order(symbol="PRMESC", side="SELL", order_type="MARKET", price=109.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=9.0, net_pnl=8.7, total_cost=0.3, fee_cost=0.3, config_snapshot_id=candidate_id))
        db.query(Position).delete()
        db.commit()
    finally:
        db.close()

    experiment_id = ((client.post("/api/account/analytics/experiments", json={"name": "Post rollback escalate", "baseline_snapshot_id": baseline_id, "candidate_snapshot_id": candidate_id, "mode": "demo", "scope": "global"}).json().get("data") or {}).get("id"))
    recommendation_id = ((client.post("/api/account/analytics/recommendations", json={"experiment_id": experiment_id}).json().get("data") or {}).get("id"))
    client.post(f"/api/account/analytics/recommendations/{recommendation_id}/approve", json={"reviewed_by": "tester", "decision_reason": "prm_escalate"})
    db = SessionLocal()
    try:
        apply_runtime_updates(db, {"cooldown_after_loss_streak_minutes": 75}, actor="prm_escalate_restore", active_position_count=0)
    finally:
        db.close()
    promotion = (client.post("/api/account/analytics/promotions", json={"recommendation_id": recommendation_id, "initiated_by": "tester"}).json().get("data") or {})
    promotion_id = promotion.get("id")
    promoted_snapshot_id = (((promotion.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="PRMESC", side="SELL", order_type="MARKET", price=92.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-8.0, net_pnl=-10.6, total_cost=2.6, fee_cost=2.6, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.add(Order(symbol="PRMESC", side="SELL", order_type="MARKET", price=91.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-9.0, net_pnl=-11.9, total_cost=2.9, fee_cost=2.9, config_snapshot_id=promoted_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="PRMESC", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="PRMESC", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=promoted_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    client.post(f"/api/account/analytics/promotions/{promotion_id}/monitoring/evaluate", json={"notes": "escalate rollback monitor"})
    rollback = (client.post(f"/api/account/analytics/promotions/{promotion_id}/rollback-decision", json={"initiated_by": "tester", "notes": "escalate rollback decision"}).json().get("data") or {})
    rollback_id = rollback.get("id")
    execution = (client.post(f"/api/account/analytics/rollbacks/{rollback_id}/execute", json={"initiated_by": "tester", "notes": "escalate rollback execute"}).json().get("data") or {})
    rollback_snapshot_id = (((execution.get("runtime_apply_result") or {}).get("state") or {}).get("config_snapshot_id"))

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(Order(symbol="PRMESC", side="SELL", order_type="MARKET", price=88.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-12.0, net_pnl=-14.8, total_cost=2.8, fee_cost=2.8, config_snapshot_id=rollback_snapshot_id, timestamp=now))
        db.add(Order(symbol="PRMESC", side="SELL", order_type="MARKET", price=87.0, quantity=1.0, status="FILLED", mode="demo", gross_pnl=-13.0, net_pnl=-15.9, total_cost=2.9, fee_cost=2.9, config_snapshot_id=rollback_snapshot_id, timestamp=now))
        db.commit()
        save_decision_trace(db, symbol="PRMESC", mode="demo", action_type="entry_blocked", reason_code="kill_switch_gate", config_snapshot_id=rollback_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="PRMESC", mode="demo", action_type="entry_blocked", reason_code="loss_streak_gate", config_snapshot_id=rollback_snapshot_id, timestamp=now)
        save_decision_trace(db, symbol="PRMESC", mode="demo", action_type="entry_blocked", reason_code="daily_net_drawdown_gate", config_snapshot_id=rollback_snapshot_id, timestamp=now)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/account/analytics/rollbacks/{rollback_id}/post-monitoring/evaluate", json={"notes": "escalate check"})
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "escalate"


def test_post_rollback_monitoring_audit_trail_read(client):
    resp = client.get("/api/account/analytics/post-rollback-monitoring")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    assert len(items) >= 1
    monitoring_id = items[0].get("id")

    resp = client.get(f"/api/account/analytics/post-rollback-monitoring/{monitoring_id}")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("id") == monitoring_id
    assert data.get("rollback") is not None


# ---------------------------------------------------------------------------
# Policy layer smoke tests
# ---------------------------------------------------------------------------

from backend.policy_layer import evaluate_policy


def test_policy_evaluate_healthy_promotion_monitoring():
    result = evaluate_policy(
        source_type="promotion_monitoring",
        verdict_status="healthy",
        reason_codes=[],
    )
    assert result["policy_action"] == "NO_ACTION"
    assert result["priority"] == "low"
    assert result["requires_human_review"] is False
    assert result["promotion_allowed"] is True


def test_policy_evaluate_warning_promotion_monitoring():
    result = evaluate_policy(
        source_type="promotion_monitoring",
        verdict_status="warning",
        reason_codes=["POST_PROMOTION_NET_PNL_DEGRADATION"],
    )
    assert result["policy_action"] == "REQUIRE_MANUAL_REVIEW"
    assert result["priority"] == "high"
    assert result["requires_human_review"] is True
    assert result["promotion_allowed"] is False
    assert result["freeze_recommendations"] is True


def test_policy_evaluate_rollback_candidate_promotion_monitoring():
    result = evaluate_policy(
        source_type="promotion_monitoring",
        verdict_status="rollback_candidate",
        reason_codes=["POST_PROMOTION_DRAWDOWN_WORSE"],
    )
    assert result["policy_action"] == "PREPARE_ROLLBACK"
    assert result["priority"] == "critical"
    assert result["rollback_allowed"] is True


def test_policy_evaluate_rollback_required_decision():
    result = evaluate_policy(
        source_type="rollback_decision",
        verdict_status="rollback_required",
        urgency="critical",
        reason_codes=["ROLLBACK_NET_PNL_DEGRADATION", "ROLLBACK_DRAWDOWN_BREACH"],
    )
    assert result["policy_action"] == "ESCALATE_TO_OPERATOR"
    assert result["priority"] == "critical"
    assert result["requires_human_review"] is True
    assert result["experiments_allowed"] is False


def test_policy_evaluate_rollback_recommended_decision():
    result = evaluate_policy(
        source_type="rollback_decision",
        verdict_status="rollback_recommended",
        urgency="high",
        reason_codes=["ROLLBACK_MONITORING_WARNING_PERSISTENT"],
    )
    assert result["policy_action"] == "PREPARE_ROLLBACK"
    assert result["priority"] == "high"
    assert result["rollback_allowed"] is True


def test_policy_evaluate_no_action_rollback_decision():
    result = evaluate_policy(
        source_type="rollback_decision",
        verdict_status="no_action",
        reason_codes=["ROLLBACK_NO_ACTION_HEALTHY"],
    )
    assert result["policy_action"] == "NO_ACTION"
    assert result["promotion_allowed"] is True


def test_policy_evaluate_stabilized_post_rollback():
    result = evaluate_policy(
        source_type="rollback_monitoring",
        verdict_status="stabilized",
        reason_codes=[],
    )
    assert result["policy_action"] == "CLOSE_INCIDENT"
    assert result["priority"] == "low"
    assert result["promotion_allowed"] is True
    assert result["experiments_allowed"] is True


def test_policy_evaluate_escalate_post_rollback():
    result = evaluate_policy(
        source_type="rollback_monitoring",
        verdict_status="escalate",
        reason_codes=["POST_ROLLBACK_NET_PNL_STILL_DOWN"],
    )
    assert result["policy_action"] == "ESCALATE_TO_OPERATOR"
    assert result["priority"] == "critical"
    assert result["freeze_recommendations"] is True
    assert result["experiments_allowed"] is False


def test_policy_evaluate_watch_post_rollback():
    result = evaluate_policy(
        source_type="rollback_monitoring",
        verdict_status="watch",
        reason_codes=[],
    )
    assert result["policy_action"] == "CONTINUE_MONITORING"
    assert result["priority"] == "medium"


def test_policy_evaluate_warning_post_rollback():
    result = evaluate_policy(
        source_type="rollback_monitoring",
        verdict_status="warning",
        reason_codes=["POST_ROLLBACK_DRAWDOWN_WORSE"],
    )
    assert result["policy_action"] == "REQUIRE_MANUAL_REVIEW"
    assert result["priority"] == "high"
    assert result["requires_human_review"] is True


def test_policy_create_and_read_via_api(client):
    resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 999,
            "verdict_status": "healthy",
            "reason_codes": [],
            "notes": "smoke test",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("policy_action") == "NO_ACTION"
    assert data.get("source_type") == "promotion_monitoring"
    assert data.get("status") == "open"
    action_id = data.get("id")

    resp = client.get(f"/api/account/analytics/policy-actions/{action_id}")
    assert resp.status_code == 200
    assert (resp.json().get("data") or {}).get("id") == action_id


def test_policy_supersede_on_new_action(client):
    resp1 = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 888,
            "verdict_status": "watch",
        },
    )
    assert resp1.status_code == 200
    first_id = (resp1.json().get("data") or {}).get("id")

    resp2 = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 888,
            "verdict_status": "warning",
            "reason_codes": ["POST_PROMOTION_NET_PNL_DEGRADATION"],
        },
    )
    assert resp2.status_code == 200
    second = resp2.json().get("data") or {}
    assert second.get("policy_action") == "REQUIRE_MANUAL_REVIEW"

    resp = client.get(f"/api/account/analytics/policy-actions/{first_id}")
    assert resp.status_code == 200
    old = resp.json().get("data") or {}
    assert old.get("status") == "superseded"
    assert old.get("superseded_by") == second.get("id")


def test_policy_resolve_action(client):
    resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_monitoring",
            "source_id": 777,
            "verdict_status": "stabilized",
        },
    )
    assert resp.status_code == 200
    action_id = (resp.json().get("data") or {}).get("id")

    resp = client.post(
        f"/api/account/analytics/policy-actions/{action_id}/resolve",
        json={"notes": "incydent zamknięty"},
    )
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "resolved"
    assert data.get("resolved_at") is not None


def test_policy_active_and_summary_endpoints(client):
    resp = client.get("/api/account/analytics/policy-actions/active")
    assert resp.status_code == 200
    active = resp.json().get("data") or []
    assert isinstance(active, list)

    resp = client.get("/api/account/analytics/policy-actions/summary")
    assert resp.status_code == 200
    summary = resp.json().get("data") or {}
    assert "open_count" in summary
    assert "total_policy_actions" in summary
    assert "by_action" in summary
    assert "by_priority" in summary


def test_policy_list_with_filters(client):
    resp = client.get("/api/account/analytics/policy-actions?status=open")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    for item in items:
        assert item.get("status") == "open"

    resp = client.get("/api/account/analytics/policy-actions?source_type=promotion_monitoring")
    assert resp.status_code == 200
    items = resp.json().get("data") or []
    for item in items:
        assert item.get("source_type") == "promotion_monitoring"


def test_policy_create_invalid_source_type(client):
    resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "nieznane_zrodlo",
            "source_id": 1,
            "verdict_status": "healthy",
        },
    )
    assert resp.status_code == 400


def test_policy_resolve_already_resolved(client):
    resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_decision",
            "source_id": 666,
            "verdict_status": "no_action",
        },
    )
    action_id = (resp.json().get("data") or {}).get("id")
    client.post(f"/api/account/analytics/policy-actions/{action_id}/resolve", json={})
    resp = client.post(f"/api/account/analytics/policy-actions/{action_id}/resolve", json={})
    assert resp.status_code == 409


# ===========================================================================
# Governance / Operator Workflow
# ===========================================================================


def test_governance_pipeline_status(client):
    """Pipeline status endpoint zwraca zagregowany stan blokad."""
    resp = client.get("/api/account/analytics/pipeline-status")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert "promotion_allowed" in data
    assert "rollback_allowed" in data
    assert "experiment_allowed" in data
    assert "recommendation_allowed" in data


def test_governance_pipeline_permission_no_blockers(client):
    """Pipeline permission endpoint zwraca poprawną strukturę."""
    resp = client.get("/api/account/analytics/pipeline-permission/promotion")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert "allowed" in data
    assert "blocking_actions" in data
    assert isinstance(data.get("blocking_actions"), list)


def test_governance_pipeline_permission_invalid_operation(client):
    """Nieznana operacja zwraca 400."""
    resp = client.get("/api/account/analytics/pipeline-permission/unknown_op")
    assert resp.status_code == 400


def test_governance_pipeline_permission_blocked_by_policy(client):
    """Po dodaniu policy action blokującej promotions — promotion zablokowana."""
    client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 5000,
            "verdict_status": "warning",
            "reason_codes": ["POST_PROMOTION_NET_PNL_DEGRADATION"],
        },
    )
    resp = client.get("/api/account/analytics/pipeline-permission/promotion")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("allowed") is False
    assert len(data.get("blocking_actions", [])) > 0


def test_governance_operator_queue_empty(client):
    """Operator queue zwraca listę (może być pusta na starcie)."""
    resp = client.get("/api/account/analytics/operator-queue")
    assert resp.status_code == 200
    data = resp.json().get("data")
    assert isinstance(data, list)


def test_governance_incident_create(client):
    """Tworzenie incydentu powiązanego z policy action."""
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_monitoring",
            "source_id": 6000,
            "verdict_status": "escalate",
            "reason_codes": ["POST_ROLLBACK_RISK_PRESSURE_PERSISTENT"],
        },
    )
    assert pa_resp.status_code == 200
    pa_id = (pa_resp.json().get("data") or {}).get("id")

    resp = client.post(
        "/api/account/analytics/incidents",
        json={"policy_action_id": pa_id},
    )
    assert resp.status_code == 200
    inc = resp.json().get("data") or {}
    assert inc.get("status") == "open"
    assert inc.get("policy_action_id") == pa_id
    assert inc.get("priority") == "critical"
    assert inc.get("sla_deadline") is not None


def test_governance_incident_duplicate_blocked(client):
    """Nie można utworzyć duplikatu incydentu dla tej samej policy action."""
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 6001,
            "verdict_status": "rollback_candidate",
        },
    )
    pa_id = (pa_resp.json().get("data") or {}).get("id")

    client.post("/api/account/analytics/incidents", json={"policy_action_id": pa_id})
    resp = client.post("/api/account/analytics/incidents", json={"policy_action_id": pa_id})
    assert resp.status_code == 400
    assert "już istnieje" in resp.json().get("detail", "")


def test_governance_incident_lifecycle(client):
    """Pełny lifecycle: open → acknowledged → in_progress → resolved."""
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_decision",
            "source_id": 6002,
            "verdict_status": "rollback_required",
        },
    )
    pa_id = (pa_resp.json().get("data") or {}).get("id")

    inc_resp = client.post("/api/account/analytics/incidents", json={"policy_action_id": pa_id})
    inc_id = (inc_resp.json().get("data") or {}).get("id")

    # open → acknowledged
    resp = client.post(
        f"/api/account/analytics/incidents/{inc_id}/transition",
        json={"new_status": "acknowledged", "operator": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json().get("data", {}).get("status") == "acknowledged"
    assert resp.json().get("data", {}).get("acknowledged_by") == "admin"

    # acknowledged → in_progress
    resp = client.post(
        f"/api/account/analytics/incidents/{inc_id}/transition",
        json={"new_status": "in_progress", "operator": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json().get("data", {}).get("status") == "in_progress"

    # in_progress → resolved
    resp = client.post(
        f"/api/account/analytics/incidents/{inc_id}/transition",
        json={"new_status": "resolved", "operator": "admin", "notes": "przyczyna usunięta"},
    )
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("status") == "resolved"
    assert data.get("resolved_at") is not None
    assert data.get("resolution_notes") == "przyczyna usunięta"


def test_governance_incident_invalid_transition(client):
    """Niedozwolone przejście stanu zwraca 400."""
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 6003,
            "verdict_status": "watch",
        },
    )
    pa_id = (pa_resp.json().get("data") or {}).get("id")

    inc_resp = client.post("/api/account/analytics/incidents", json={"policy_action_id": pa_id})
    inc_id = (inc_resp.json().get("data") or {}).get("id")

    # open → in_progress (niedozwolone — trzeba najpierw acknowledged)
    resp = client.post(
        f"/api/account/analytics/incidents/{inc_id}/transition",
        json={"new_status": "in_progress"},
    )
    assert resp.status_code == 400
    assert "Niedozwolone" in resp.json().get("detail", "")


def test_governance_incident_list_and_get(client):
    """Lista i get incydentów z filtrami."""
    resp = client.get("/api/account/analytics/incidents")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("data"), list)

    resp = client.get("/api/account/analytics/incidents?status=open")
    assert resp.status_code == 200

    resp = client.get("/api/account/analytics/incidents?priority=critical")
    assert resp.status_code == 200


def test_governance_incident_get_by_id(client):
    """GET pojedynczego incydentu."""
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_monitoring",
            "source_id": 6004,
            "verdict_status": "warning",
        },
    )
    pa_id = (pa_resp.json().get("data") or {}).get("id")

    inc_resp = client.post("/api/account/analytics/incidents", json={"policy_action_id": pa_id})
    inc_id = (inc_resp.json().get("data") or {}).get("id")

    resp = client.get(f"/api/account/analytics/incidents/{inc_id}")
    assert resp.status_code == 200
    assert resp.json().get("data", {}).get("id") == inc_id


def test_governance_incident_not_found(client):
    """Nieistniejący incydent → 404."""
    resp = client.get("/api/account/analytics/incidents/999999")
    assert resp.status_code == 404


def test_governance_escalate_overdue(client):
    """Endpoint eskalacji przeterminowanych incydentów."""
    resp = client.post("/api/account/analytics/incidents/escalate-overdue")
    assert resp.status_code == 200
    assert "escalated_count" in resp.json()


def test_governance_operator_queue_with_incidents(client):
    """Operator queue zawiera incydenty i policy actions wymagające review."""
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 6005,
            "verdict_status": "warning",
        },
    )
    pa_id = (pa_resp.json().get("data") or {}).get("id")
    client.post("/api/account/analytics/incidents", json={"policy_action_id": pa_id})

    resp = client.get("/api/account/analytics/operator-queue")
    assert resp.status_code == 200
    queue = resp.json().get("data") or []
    assert len(queue) > 0
    item = queue[0]
    assert "type" in item
    assert "priority" in item
    assert "policy_action_id" in item


def test_governance_pipeline_status_reflects_freezes(client):
    """Pipeline status pokazuje blokady z aktywnych policy actions."""
    # Dodaj critical action blokującą promotions i experiments
    client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_monitoring",
            "source_id": 6006,
            "verdict_status": "escalate",
        },
    )

    resp = client.get("/api/account/analytics/pipeline-status")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    # escalate blokuje promotion i experiment
    assert data.get("promotion_allowed") is False
    assert data.get("experiment_allowed") is False


# =====================================================================
# Pipeline Guard Integration – freeze-blocked operations → 403
# =====================================================================

def _ensure_blocking_policy_action(client):
    """Upewnij się, że jest aktywna policy action blokująca promotions/experiments/recommendations."""
    # Sprawdź czy coś już blokuje
    resp = client.get("/api/account/analytics/pipeline-permission/promotion")
    if resp.json().get("data", {}).get("allowed") is False:
        return
    # Dodaj blokującą z verdict_status=escalate
    client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 9900,
            "verdict_status": "escalate",
            "reason_codes": ["FREEZE_GUARD_TEST"],
        },
    )


def test_guard_experiment_blocked(client):
    """Tworzenie eksperymentu zablokowane przez governance freeze → 403."""
    _ensure_blocking_policy_action(client)
    resp = client.post(
        "/api/account/analytics/experiments",
        json={
            "name": "freeze-test-exp",
            "baseline_snapshot_id": "nonexistent-base",
            "candidate_snapshot_id": "nonexistent-cand",
        },
    )
    assert resp.status_code == 403
    detail = resp.json().get("detail") or {}
    assert detail.get("error") == "pipeline_freeze"
    assert detail.get("operation") == "experiment"
    assert detail.get("blockers_count", 0) > 0
    assert isinstance(detail.get("blocking_actions"), list)


def test_guard_recommendation_blocked(client):
    """Generowanie rekomendacji zablokowane przez governance freeze → 403."""
    _ensure_blocking_policy_action(client)
    resp = client.post(
        "/api/account/analytics/recommendations",
        json={"experiment_id": 999999},
    )
    assert resp.status_code == 403
    detail = resp.json().get("detail") or {}
    assert detail.get("error") == "pipeline_freeze"
    assert detail.get("operation") == "recommendation"
    assert detail.get("blockers_count", 0) > 0


def test_guard_promotion_blocked(client):
    """Tworzenie promocji zablokowane przez governance freeze → 403."""
    _ensure_blocking_policy_action(client)
    resp = client.post(
        "/api/account/analytics/promotions",
        json={
            "recommendation_id": 999999,
            "initiated_by": "guard-test",
        },
    )
    assert resp.status_code == 403
    detail = resp.json().get("detail") or {}
    assert detail.get("error") == "pipeline_freeze"
    assert detail.get("operation") == "promotion"
    assert detail.get("blockers_count", 0) > 0


def test_guard_rollback_blocked(client):
    """Wykonanie rollbacku zablokowane przez governance freeze → 403."""
    # Rollback wymaga specyficznej policy action blokującej rollback
    # (escalate domyślnie: rollback_allowed=True, więc trzeba dodać akcję z rollback_allowed=False)
    # Tworzymy dedykowaną policy action która blokuje rollbacki
    from backend.database import SessionLocal, PolicyAction
    db = SessionLocal()
    try:
        # Dodaj PA z rollback_allowed=False
        pa = PolicyAction(
            source_type="rollback_monitoring",
            source_id=9901,
            policy_action="rollback_freeze_test",
            priority="critical",
            promotion_allowed=True,
            rollback_allowed=False,
            experiments_allowed=True,
            freeze_recommendations=False,
            requires_human_review=True,
            summary="Test: blokada rollbacku",
            status="open",
        )
        db.add(pa)
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/account/analytics/rollbacks/999999/execute",
        json={"initiated_by": "guard-test"},
    )
    assert resp.status_code == 403
    detail = resp.json().get("detail") or {}
    assert detail.get("error") == "pipeline_freeze"
    assert detail.get("operation") == "rollback"
    assert detail.get("blockers_count", 0) > 0


def test_guard_error_format_consistency(client):
    """Spójny format błędu freeze we wszystkich operacjach."""
    _ensure_blocking_policy_action(client)
    required_keys = {"error", "operation", "message", "blocking_actions", "blockers_count"}

    # Experiment
    resp = client.post(
        "/api/account/analytics/experiments",
        json={
            "name": "format-test",
            "baseline_snapshot_id": "x",
            "candidate_snapshot_id": "y",
        },
    )
    assert resp.status_code == 403
    detail = resp.json().get("detail") or {}
    assert required_keys.issubset(detail.keys()), f"Brakujące klucze: {required_keys - detail.keys()}"

    # Recommendation
    resp2 = client.post(
        "/api/account/analytics/recommendations",
        json={"experiment_id": 1},
    )
    assert resp2.status_code == 403
    detail2 = resp2.json().get("detail") or {}
    assert required_keys.issubset(detail2.keys()), f"Brakujące klucze: {required_keys - detail2.keys()}"
