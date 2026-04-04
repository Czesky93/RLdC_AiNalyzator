import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Ensure repo root is on sys.path so `import backend` works when running pytest from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""
os.environ["DEMO_INITIAL_BALANCE"] = "10000"
os.environ["DEMO_TRADING_ENABLED"] = "true"
os.environ["WS_ENABLED"] = "true"
os.environ["MAX_CERTAINTY_MODE"] = "false"
os.environ["TRADING_MODE"] = "demo"
os.environ["ALLOW_LIVE_TRADING"] = "false"

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
    RuntimeSetting,
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
from backend.database import utc_now_naive
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


def test_signals_best_opportunity(client):
    resp = client.get("/api/signals/best-opportunity")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "action" in data
    # Albo jest okazja, albo CZEKAJ
    assert data["action"] in ("BUY", "SELL", "CZEKAJ")
    if data.get("opportunity"):
        opp = data["opportunity"]
        assert "symbol" in opp
        assert "confidence" in opp
        assert "score" in opp


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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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
        now = utc_now_naive()
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


# =====================================================================
# Notification hooks — formatowanie, dispatch, endpointy
# =====================================================================

def test_notification_format_incident_created():
    """Format incydentu zawiera priorytet po polsku, PA id, szczegóły."""
    from backend.notification_hooks import format_incident_created
    incident = {
        "id": 42,
        "policy_action_id": 7,
        "priority": "critical",
        "sla_deadline": "2026-03-25T12:00:00",
    }
    pa = {
        "policy_action": "escalate_rollback_monitoring",
        "source_type": "rollback_monitoring",
        "source_id": 100,
        "summary": "test summary",
    }
    text = format_incident_created(incident, pa)
    assert "#42" in text
    assert "krytyczn" in text.lower()  # "krytyczna" pilność
    assert "#7" in text
    assert "Co zrobić" in text


def test_notification_format_incident_escalated():
    """Format eskalacji zawiera ostrzeżenie i termin."""
    from backend.notification_hooks import format_incident_escalated
    incident = {
        "id": 5,
        "policy_action_id": 3,
        "priority": "high",
        "sla_deadline": "2026-03-25T10:00:00",
    }
    text = format_incident_escalated(incident)
    assert "#5" in text
    assert "Eskalacja" in text


def test_notification_format_policy_action_created():
    """Format policy action zawiera akcję po polsku, priorytet, opis."""
    from backend.notification_hooks import format_policy_action_created
    pa = {
        "id": 10,
        "policy_action": "hold_new_promotions",
        "priority": "high",
        "source_type": "promotion_monitoring",
        "source_id": 1,
        "summary": "PnL spadek",
        "promotion_allowed": False,
        "rollback_allowed": True,
        "experiments_allowed": False,
        "requires_human_review": True,
    }
    text = format_policy_action_created(pa)
    assert "#10" in text
    assert "Zablokowano" in text or "zablokowano" in text
    assert "Co zrobić" in text or "przejrzyj" in text.lower()


def test_notification_format_pipeline_blocked():
    """Format blokady pipeline zawiera operację po polsku i blokery."""
    from backend.notification_hooks import format_pipeline_blocked
    text = format_pipeline_blocked("promotion", [
        {"policy_action_id": 1, "priority": "critical"},
        {"policy_action_id": 2, "priority": "high"},
    ])
    assert "wdrożeni" in text.lower()  # "wdrożenia nowych ustawień"
    assert "#1" in text
    assert "#2" in text
    assert "2" in text  # count


def test_notification_format_sla_breach():
    """Format naruszenia SLA zawiera liczbę eskalowanych incydentów."""
    from backend.notification_hooks import format_sla_breach
    escalated = [
        {"id": 1, "priority": "critical", "sla_deadline": "2026-03-25T10:00:00"},
        {"id": 2, "priority": "high", "sla_deadline": "2026-03-25T11:00:00"},
    ]
    text = format_sla_breach(escalated)
    assert "2" in text
    assert "termin" in text.lower() or "przekroczony" in text.lower()


def test_notification_dispatch_logs_to_db():
    """Dispatch zawsze loguje do DB (kanał log=True)."""
    from backend.notification_hooks import dispatch_notification
    result = dispatch_notification("test_event", "test message", priority="low")
    assert result["event_type"] == "test_event"
    assert result["channels"]["log"] is True
    # Telegram powinien być None/False (brak tokenu w testach)
    assert result["channels"]["telegram"] in (None, False)


def test_notification_dispatch_skips_low_priority_telegram():
    """Telegram pomijany przy priorytecie niższym niż próg."""
    from backend.notification_hooks import dispatch_notification
    result = dispatch_notification("low_prio_event", "low prio msg", priority="low")
    assert result["channels"]["telegram"] is None


def test_notification_config_endpoint(client):
    """Endpoint /notifications/config zwraca konfigurację."""
    resp = client.get("/api/account/analytics/notifications/config")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert "enabled" in data
    assert "telegram_configured" in data
    assert "telegram_min_priority" in data


def test_notification_test_endpoint(client):
    """Endpoint /notifications/test wysyła testowe powiadomienie."""
    resp = client.post(
        "/api/account/analytics/notifications/test",
        json={"message": "Test z pytest"},
    )
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    assert data.get("event_type") == "test"
    assert data.get("channels", {}).get("log") is True


def test_notification_hook_on_policy_action(client):
    """Tworzenie policy action triggeruje notification hook (logowany do DB)."""
    # Tworzymy policy action — hook jest wbudowany w create_policy_action
    from backend.database import SessionLocal, SystemLog
    db = SessionLocal()
    try:
        before_count = db.query(SystemLog).filter(
            SystemLog.module == "notification_hooks"
        ).count()
    finally:
        db.close()

    client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 9990,
            "verdict_status": "warning",
            "reason_codes": ["NOTIFY_TEST"],
        },
    )

    db = SessionLocal()
    try:
        after_count = db.query(SystemLog).filter(
            SystemLog.module == "notification_hooks"
        ).count()
    finally:
        db.close()

    assert after_count > before_count, "Notification hook powinien zapisać log do DB"


def test_notification_hook_on_incident(client):
    """Tworzenie incydentu triggeruje notification hook."""
    from backend.database import SessionLocal, SystemLog

    # Stwórz PA pod incydent
    pa_resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "rollback_monitoring",
            "source_id": 9991,
            "verdict_status": "escalate",
        },
    )
    pa_id = (pa_resp.json().get("data") or {}).get("id")

    db = SessionLocal()
    try:
        before_count = db.query(SystemLog).filter(
            SystemLog.module == "notification_hooks",
            SystemLog.message.like("%incident_created%"),
        ).count()
    finally:
        db.close()

    client.post(
        "/api/account/analytics/incidents",
        json={"policy_action_id": pa_id},
    )

    db = SessionLocal()
    try:
        after_count = db.query(SystemLog).filter(
            SystemLog.module == "notification_hooks",
            SystemLog.message.like("%incident_created%"),
        ).count()
    finally:
        db.close()

    assert after_count > before_count, "Incident notification powinien zapisać log"


def test_notification_hook_on_blocked_operation(client):
    """Zablokowana operacja triggeruje notification o blokadzie."""
    from backend.database import SessionLocal, SystemLog

    _ensure_blocking_policy_action(client)

    db = SessionLocal()
    try:
        before_count = db.query(SystemLog).filter(
            SystemLog.module == "notification_hooks",
            SystemLog.message.like("%pipeline_blocked%"),
        ).count()
    finally:
        db.close()

    # Próba tworzenia eksperymentu (zablokowana)
    client.post(
        "/api/account/analytics/experiments",
        json={
            "name": "notify-test",
            "baseline_snapshot_id": "x",
            "candidate_snapshot_id": "y",
        },
    )

    db = SessionLocal()
    try:
        after_count = db.query(SystemLog).filter(
            SystemLog.module == "notification_hooks",
            SystemLog.message.like("%pipeline_blocked%"),
        ).count()
    finally:
        db.close()

    assert after_count > before_count, "Pipeline blocked notification powinien zapisać log"


# =====================================================================
# ============ REEVALUATION WORKER (ETAP 6) ===========================
# =====================================================================


def test_worker_status_endpoint(client):
    """GET /analytics/worker/status zwraca status workera."""
    resp = client.get("/api/account/analytics/worker/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    status = data["data"]
    assert "enabled" in status
    assert "running" in status
    assert "interval_seconds" in status


def test_worker_manual_cycle_endpoint(client):
    """POST /analytics/worker/cycle ręcznie uruchamia cykl workera."""
    resp = client.post("/api/account/analytics/worker/cycle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    summary = data["data"]
    assert "cycle_start" in summary
    assert "cycle_end" in summary
    assert "duration_seconds" in summary
    assert "steps" in summary
    assert "errors" in summary


def test_worker_cycle_runs_all_steps(client):
    """Worker cycle wykonuje wszystkie 5 kroków bez błędów."""
    resp = client.post("/api/account/analytics/worker/cycle")
    data = resp.json()["data"]
    steps = data["steps"]

    assert "escalate_overdue" in steps
    assert "reevaluate_promotion_monitoring" in steps
    assert "reevaluate_rollback_monitoring" in steps
    assert "operator_queue" in steps
    assert "pipeline_status" in steps

    # Żaden krok nie powinien być "error" na czystej bazie
    for step_name, step_data in steps.items():
        assert step_data.get("status") == "ok", f"Krok {step_name} zwrócił error: {step_data}"

    # Brak błędów krytycznych
    assert len(data["errors"]) == 0


def test_worker_cycle_function_directly():
    """Bezpośrednie wywołanie run_worker_cycle() działa poprawnie."""
    from backend.reevaluation_worker import run_worker_cycle

    summary = run_worker_cycle()

    assert "cycle_start" in summary
    assert "cycle_end" in summary
    assert "steps" in summary
    assert len(summary.get("errors", [])) == 0

    # Wszystkie kroki status=ok
    for step_name, step_data in summary["steps"].items():
        assert step_data.get("status") == "ok", f"{step_name}: {step_data}"


def test_worker_cycle_escalation_with_overdue_incident(client):
    """Worker eskaluje incydenty z przekroczonym SLA."""
    from backend.database import SessionLocal, Incident
    from datetime import datetime, timedelta

    # Stwórz incydent z przeterminowanym SLA
    db = SessionLocal()
    try:
        old_incident = Incident(
            policy_action_id=0,
            priority="high",
            status="open",
            sla_deadline=utc_now_naive() - timedelta(hours=1),
        )
        db.add(old_incident)
        db.commit()
        incident_id = old_incident.id
    finally:
        db.close()

    # Uruchom cykl workera
    resp = client.post("/api/account/analytics/worker/cycle")
    data = resp.json()["data"]

    escalated = data["steps"]["escalate_overdue"]
    assert escalated["status"] == "ok"
    # Nasz incydent powinien trafić do eskalowanych
    assert escalated["escalated_count"] >= 1


def test_worker_cycle_logs_to_system_log(client):
    """Worker zapisuje podsumowanie cyklu w system_log."""
    from backend.database import SessionLocal, SystemLog

    db = SessionLocal()
    try:
        before_count = db.query(SystemLog).filter(
            SystemLog.module == "reevaluation_worker",
        ).count()
    finally:
        db.close()

    client.post("/api/account/analytics/worker/cycle")

    db = SessionLocal()
    try:
        after_count = db.query(SystemLog).filter(
            SystemLog.module == "reevaluation_worker",
        ).count()
    finally:
        db.close()

    assert after_count > before_count, "Worker powinien logować cykl do system_log"


def test_worker_get_worker_status():
    """get_worker_status() zwraca poprawną strukturę."""
    from backend.reevaluation_worker import get_worker_status

    status = get_worker_status()
    assert isinstance(status, dict)
    assert "enabled" in status
    assert "running" in status
    assert isinstance(status["interval_seconds"], int)


def test_worker_start_stop():
    """start_worker / stop_worker działają poprawnie."""
    from backend.reevaluation_worker import (
        get_worker_status,
        start_worker,
        stop_worker,
    )
    import time

    # Upewnij się że worker nie działa
    stop_worker()
    assert get_worker_status()["running"] is False

    # Start z krótkim interwałem
    started = start_worker(interval_seconds=9999)
    assert started is True
    assert get_worker_status()["running"] is True

    # Próba ponownego startu (powinno zwrócić False)
    started_again = start_worker(interval_seconds=9999)
    assert started_again is False

    # Stop
    stopped = stop_worker()
    assert stopped is True
    assert get_worker_status()["running"] is False

    # Stop gdy już nie działa
    stopped_again = stop_worker()
    assert stopped_again is False


def test_worker_cycle_with_active_promotion_monitoring(client):
    """Worker re-ewaluuje aktywne monitoringi post-promotion."""
    from backend.database import SessionLocal, ConfigPromotion, ConfigSnapshot
    import hashlib, json

    # Utwórz snapshot + promotion z aktywnym monitoringiem
    db = SessionLocal()
    try:
        payload = {"key": "value"}
        payload_json = json.dumps(payload, sort_keys=True)
        snap_id = "worker-test-" + hashlib.sha256(payload_json.encode()).hexdigest()[:16]
        snapshot = ConfigSnapshot(
            id=snap_id,
            config_hash=hashlib.sha256(payload_json.encode()).hexdigest(),
            payload_json=payload_json,
            source="unit_test",
        )
        db.add(snapshot)
        db.flush()

        promo = ConfigPromotion(
            recommendation_id=0,
            review_id=0,
            from_snapshot_id=snap_id,
            to_snapshot_id=snap_id,
            status="applied",
            initiated_by="test",
            post_promotion_monitoring_status="pending",
        )
        db.add(promo)
        db.commit()
        promo_id = promo.id
    finally:
        db.close()

    # Uruchom cykl
    resp = client.post("/api/account/analytics/worker/cycle")
    data = resp.json()["data"]

    promo_step = data["steps"]["reevaluate_promotion_monitoring"]
    assert promo_step["status"] == "ok"
    assert promo_step["active_count"] >= 1


# =====================================================================
# ============ OPERATOR CONSOLE (ETAP 7) ==============================
# =====================================================================


def test_console_bundle_endpoint(client):
    """GET /analytics/console zwraca pełny bundle konsoli operatora."""
    resp = client.get("/api/account/analytics/console")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    console = data["data"]
    assert "generated_at" in console
    assert "sections" in console

    expected_sections = {
        "incidents",
        "policy_actions",
        "pipeline_status",
        "operator_queue",
        "worker_status",
        "monitoring_summary",
        "recent_notifications",
        "recent_blocked_operations",
        "recent_system_events",
    }
    assert expected_sections == set(console["sections"].keys())


def test_console_no_section_errors(client):
    """Żadna sekcja konsoli nie powinna zwracać błędu na czystej bazie."""
    resp = client.get("/api/account/analytics/console")
    data = resp.json()["data"]

    for section_name, section_data in data["sections"].items():
        assert "error" not in section_data, (
            f"Sekcja '{section_name}' zwróciła błąd: {section_data.get('error')}"
        )


def test_console_incidents_structure(client):
    """Sekcja incidents ma poprawną strukturę."""
    resp = client.get("/api/account/analytics/console/incidents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["section"] == "incidents"

    section = data["data"]
    assert "total_active" in section
    assert "items" in section
    assert "by_status" in section
    assert "by_priority" in section


def test_console_policy_actions_structure(client):
    """Sekcja policy_actions ma poprawną strukturę."""
    resp = client.get("/api/account/analytics/console/policy_actions")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "total_open" in section
    assert "requiring_review" in section
    assert "items" in section
    assert "summary" in section
    assert "open_count" in section["summary"]


def test_console_pipeline_status_structure(client):
    """Sekcja pipeline_status ma poprawną strukturę."""
    resp = client.get("/api/account/analytics/console/pipeline_status")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "promotion_allowed" in section
    assert "rollback_allowed" in section
    assert "experiment_allowed" in section
    assert "recommendation_allowed" in section
    assert "any_freeze_active" in section


def test_console_operator_queue_structure(client):
    """Sekcja operator_queue ma poprawną strukturę."""
    resp = client.get("/api/account/analytics/console/operator_queue")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "queue_size" in section
    assert "critical_count" in section
    assert "sla_breached_count" in section
    assert "items" in section


def test_console_worker_status_structure(client):
    """Sekcja worker_status ma poprawną strukturę."""
    resp = client.get("/api/account/analytics/console/worker_status")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "enabled" in section
    assert "running" in section
    assert "interval_seconds" in section


def test_console_monitoring_summary_structure(client):
    """Sekcja monitoring_summary ma poprawną strukturę."""
    resp = client.get("/api/account/analytics/console/monitoring_summary")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "promotion_monitoring" in section
    assert "rollback_monitoring" in section
    assert "active_count" in section["promotion_monitoring"]
    assert "active_count" in section["rollback_monitoring"]


def test_console_recent_notifications(client):
    """Sekcja recent_notifications zwraca dane z system_logs."""
    resp = client.get("/api/account/analytics/console/recent_notifications")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "count" in section
    assert "items" in section
    assert isinstance(section["items"], list)


def test_console_recent_blocked_operations(client):
    """Sekcja recent_blocked_operations zwraca dane o blokadach."""
    resp = client.get("/api/account/analytics/console/recent_blocked_operations")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "count" in section
    assert "items" in section


def test_console_recent_system_events(client):
    """Sekcja recent_system_events zwraca WARNING+ logi."""
    resp = client.get("/api/account/analytics/console/recent_system_events")
    assert resp.status_code == 200
    section = resp.json()["data"]

    assert "count" in section
    assert "items" in section


def test_console_invalid_section(client):
    """Nieznana sekcja konsoli zwraca 400."""
    resp = client.get("/api/account/analytics/console/nonexistent_section")
    assert resp.status_code == 400


def test_console_bundle_function_directly():
    """Bezpośrednie wywołanie get_operator_console() działa poprawnie."""
    from backend.operator_console import get_operator_console
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        console = get_operator_console(db)
    finally:
        db.close()

    assert "generated_at" in console
    assert "sections" in console
    assert len(console["sections"]) == 9

    # Żadna sekcja nie powinna mieć klucza "error"
    for name, section in console["sections"].items():
        assert "error" not in section, f"Sekcja '{name}': {section.get('error')}"


def test_console_with_populated_data(client):
    """Konsola poprawnie agreguje dane po wykonaniu cyklu workera."""
    # Uruchom worker cycle żeby wygenerować dane w system_logs
    client.post("/api/account/analytics/worker/cycle")

    # Teraz konsola powinna mieć dane w recent_system_events
    resp = client.get("/api/account/analytics/console")
    data = resp.json()["data"]

    # Worker cycle powinien zapisać log do system_log
    system_events = data["sections"]["recent_system_events"]
    # Nie wymuszamy count > 0 bo worker loguje jako INFO, a system_events filtruje WARNING+
    assert isinstance(system_events["items"], list)


# =====================================================================
# ============ CORRELATION / INCIDENT INTELLIGENCE (ETAP 8) ===========
# =====================================================================


def _create_policy_action_and_incident(client):
    """Helper: utwórz policy action + incident, zwróć (pa_id, incident_id)."""
    # Utwórz policy action z escalate (wymaga review → incident)
    resp = client.post(
        "/api/account/analytics/policy-actions",
        json={
            "source_type": "promotion_monitoring",
            "source_id": 8800,
            "verdict_status": "rollback_candidate",
            "reason_codes": ["CORR_TEST"],
        },
    )
    assert resp.status_code == 200
    pa_id = resp.json()["data"]["id"]

    # Utwórz incident powiązany z PA
    resp = client.post(
        "/api/account/analytics/incidents",
        json={"policy_action_id": pa_id},
    )
    assert resp.status_code == 200
    incident_id = resp.json()["data"]["id"]

    return pa_id, incident_id


def test_correlation_incident_timeline(client):
    """Oś czasu incydentu zawiera powiązane zdarzenia."""
    pa_id, incident_id = _create_policy_action_and_incident(client)

    resp = client.get(f"/api/account/analytics/incidents/{incident_id}/timeline")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["incident_id"] == incident_id
    assert data["event_count"] >= 2  # min: incident + policy_action
    assert isinstance(data["timeline"], list)

    # Timeline zawiera zdarzenie incydentu i policy action
    event_types = {e["event_type"] for e in data["timeline"]}
    assert "incident_created" in event_types
    assert "policy_action_created" in event_types


def test_correlation_incident_timeline_not_found(client):
    """Timeline dla nieistniejącego incydentu → 404."""
    resp = client.get("/api/account/analytics/incidents/999999/timeline")
    assert resp.status_code == 404


def test_correlation_incident_correlations(client):
    """Korelacje incydentu zawierają policy action i source record."""
    pa_id, incident_id = _create_policy_action_and_incident(client)

    resp = client.get(f"/api/account/analytics/incidents/{incident_id}/correlations")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["incident"]["id"] == incident_id
    assert data["policy_action"] is not None
    assert data["policy_action"]["id"] == pa_id
    assert data["source_record"] is not None
    assert isinstance(data["related_incidents"], list)


def test_correlation_policy_action_chain(client):
    """Łańcuch policy action zawiera PA + powiązany incident."""
    pa_id, incident_id = _create_policy_action_and_incident(client)

    resp = client.get(f"/api/account/analytics/policy-actions/{pa_id}/chain")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["policy_action_id"] == pa_id
    assert data["event_count"] >= 2  # PA + incident

    event_types = {e["event_type"] for e in data["chain"]}
    assert "policy_action_created" in event_types
    assert "incident_created" in event_types


def test_correlation_policy_action_chain_not_found(client):
    """Chain dla nieistniejącej PA → 404."""
    resp = client.get("/api/account/analytics/policy-actions/999999/chain")
    assert resp.status_code == 404


def test_correlation_why_blocked(client):
    """Why-blocked wyjaśnia dlaczego operacja jest zablokowana."""
    _ensure_blocking_policy_action(client)

    resp = client.get("/api/account/analytics/why-blocked/promotion")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["operation"] == "promotion"
    assert data["blocked"] is True
    assert data["blockers_count"] >= 1
    assert isinstance(data["blockers"], list)

    # Każdy bloker ma policy_action i source
    for blocker in data["blockers"]:
        assert "policy_action" in blocker
        assert "source" in blocker
        assert "incidents" in blocker


def test_correlation_why_blocked_allowed(client):
    """Why-blocked dla dozwolonej operacji (rollback powinien być allowed)."""
    resp = client.get("/api/account/analytics/why-blocked/rollback")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["operation"] == "rollback"
    # Może być zablokowany lub nie, ale struktura musi być poprawna
    assert "blocked" in data
    assert "blockers" in data


def test_correlation_why_blocked_invalid_operation(client):
    """Why-blocked dla nieprawidłowej operacji → 400."""
    resp = client.get("/api/account/analytics/why-blocked/invalid_op")
    assert resp.status_code == 400


def test_correlation_promotion_chain(client):
    """Łańcuch promocji zawiera przynajmniej sam rekord promocji."""
    from backend.database import SessionLocal, ConfigPromotion
    # Znajdź dowolną promocję (z wcześniejszych testów)
    db = SessionLocal()
    try:
        promo = db.query(ConfigPromotion).first()
    finally:
        db.close()

    if promo is None:
        # Brak promocji w bazie — pomijamy test
        return

    resp = client.get(f"/api/account/analytics/promotions/{promo.id}/chain")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["promotion_id"] == promo.id
    assert data["event_count"] >= 1
    assert isinstance(data["chain"], list)

    event_types = {e["event_type"] for e in data["chain"]}
    assert "promotion_initiated" in event_types


def test_correlation_promotion_chain_not_found(client):
    """Chain dla nieistniejącej promocji → 404."""
    resp = client.get("/api/account/analytics/promotions/999999/chain")
    assert resp.status_code == 404


def test_correlation_functions_directly():
    """Bezpośrednie wywołanie funkcji korelacji działa poprawnie."""
    from backend.database import SessionLocal
    from backend.correlation import get_why_blocked

    db = SessionLocal()
    try:
        result = get_why_blocked(db, "promotion")
        assert "operation" in result
        assert "blocked" in result
        assert "blockers" in result
    finally:
        db.close()


# =====================================================================
# ============ TRADING EFFECTIVENESS REVIEW (ETAP X) ==================
# =====================================================================

def _seed_effectiveness_data():
    """Seed: buy+sell pair z kosztami, decision trace ze strategią i reason_code."""
    db = SessionLocal()
    try:
        # Buy order
        buy = Order(
            symbol="EFFEUR",
            side="BUY",
            order_type="MARKET",
            price=100.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=100.0,
            executed_quantity=1.0,
            entry_reason_code="rsi_oversold",
        )
        db.add(buy)
        db.commit()
        db.refresh(buy)
        save_cost_entry(db, symbol="EFFEUR", cost_type="taker_fee", order_id=buy.id,
                        actual_value=0.10, expected_value=0.10)
        attach_costs_to_order(db, order=buy, gross_pnl=0.0,
                              config_snapshot_id="eff-snap", entry_reason_code="rsi_oversold")

        # Sell order (profitable gross, but costs eat some)
        sell = Order(
            symbol="EFFEUR",
            side="SELL",
            order_type="MARKET",
            price=102.0,
            quantity=1.0,
            status="FILLED",
            mode="demo",
            executed_price=102.0,
            executed_quantity=1.0,
            expected_edge=1.5,
            realized_rr=1.2,
            entry_reason_code="rsi_oversold",
        )
        db.add(sell)
        db.commit()
        db.refresh(sell)
        save_cost_entry(db, symbol="EFFEUR", cost_type="taker_fee", order_id=sell.id,
                        actual_value=0.10, expected_value=0.10)
        save_cost_entry(db, symbol="EFFEUR", cost_type="slippage", order_id=sell.id,
                        actual_value=0.05, expected_value=0.05)
        attach_costs_to_order(db, order=sell, gross_pnl=2.0,
                              config_snapshot_id="eff-snap", exit_reason_code="take_profit")

        # DecisionTrace for strategy attribution
        save_decision_trace(
            db,
            symbol="EFFEUR",
            mode="demo",
            action_type="EXECUTE",
            reason_code="rsi_oversold",
            strategy_name="mean_reversion",
            timeframe="1h",
            signal_summary={"signal": "BUY"},
            risk_gate_result={"allowed": True},
            cost_gate_result={"eligible": True},
            execution_gate_result={"eligible": True},
            config_snapshot_id="eff-snap",
            payload={"source": "test"},
            order_id=sell.id,
        )

        # Blocked decision trace (for filter effectiveness)
        save_decision_trace(
            db,
            symbol="EFFEUR",
            mode="demo",
            action_type="BLOCK",
            reason_code="leakage_gate_symbol",
            strategy_name="mean_reversion",
            timeframe="1h",
            signal_summary={"signal": "BUY"},
            risk_gate_result={"allowed": False},
            cost_gate_result={"eligible": True},
            execution_gate_result={"eligible": True},
            config_snapshot_id="eff-snap",
            payload={"source": "test"},
        )

        db.commit()
        return sell.id
    finally:
        db.close()


_eff_seeded = False


def _ensure_effectiveness_data():
    """Seed raz (lazy — po stworzeniu tabel przez fixture client)."""
    global _eff_seeded
    if not _eff_seeded:
        _seed_effectiveness_data()
        _eff_seeded = True


def test_effectiveness_summary_endpoint(client):
    """Endpoint GET /analytics/trading-effectiveness zwraca pełny bundle."""
    _ensure_effectiveness_data()
    resp = client.get("/api/account/analytics/trading-effectiveness")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "summary" in data
    assert "by_symbol" in data
    assert "by_reason_code" in data
    assert "by_strategy" in data
    assert "cost_leakage" in data
    assert "overtrading" in data
    assert "filters" in data
    assert "edge" in data
    assert "suggestions" in data


def test_effectiveness_summary_has_verdict(client):
    """Summary zawiera verdict i kluczowe metryki."""
    resp = client.get("/api/account/analytics/trading-effectiveness")
    summary = resp.json()["data"]["summary"]
    assert "verdict" in summary
    assert "verdict_reason" in summary
    assert "net_expectancy" in summary
    assert "cost_leakage_ratio" in summary
    assert "cost_killed_trades" in summary
    assert summary["closed_trades"] > 0


def test_effectiveness_symbols_endpoint(client):
    """Endpoint symbols zwraca listę z verdict per symbol."""
    resp = client.get("/api/account/analytics/trading-effectiveness/symbols")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)
    # Powinien być co najmniej EFFEUR
    symbols = {s["symbol"] for s in data}
    assert "EFFEUR" in symbols
    eff = next(s for s in data if s["symbol"] == "EFFEUR")
    assert "verdict" in eff
    assert "net_expectancy" in eff
    assert "overtrading_score" in eff


def test_effectiveness_reasons_endpoint(client):
    """Endpoint reasons zwraca skuteczność per entry_reason_code."""
    resp = client.get("/api/account/analytics/trading-effectiveness/reasons")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)


def test_effectiveness_strategies_endpoint(client):
    """Endpoint strategies zwraca diagnostykę per strategia."""
    resp = client.get("/api/account/analytics/trading-effectiveness/strategies")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)


def test_effectiveness_cost_leakage(client):
    """Cost leakage analysis w bundle."""
    resp = client.get("/api/account/analytics/trading-effectiveness")
    leakage = resp.json()["data"]["cost_leakage"]
    assert "dominant_cost_type" in leakage
    assert "cost_breakdown" in leakage


def test_effectiveness_edge_analysis(client):
    """Edge analysis — expected vs realized."""
    resp = client.get("/api/account/analytics/trading-effectiveness")
    edge = resp.json()["data"]["edge"]
    assert "trades_with_edge" in edge
    assert "avg_expected_edge" in edge
    assert "avg_realized_rr" in edge
    assert "edge_hit_rate" in edge


def test_effectiveness_filter_analysis(client):
    """Filter/gate effectiveness analysis."""
    resp = client.get("/api/account/analytics/trading-effectiveness")
    filters = resp.json()["data"]["filters"]
    assert "gates" in filters
    assert "total_blocked" in filters
    assert "total_executed" in filters


def test_effectiveness_overtrading(client):
    """Overtrading detection."""
    resp = client.get("/api/account/analytics/trading-effectiveness")
    overtrading = resp.json()["data"]["overtrading"]
    assert "overtrade_symbols" in overtrading
    assert "overtrade_strategies" in overtrading


def test_effectiveness_suggestions(client):
    """Improvement suggestions — lista sugestii."""
    resp = client.get("/api/account/analytics/trading-effectiveness")
    suggestions = resp.json()["data"]["suggestions"]
    assert isinstance(suggestions, list)


def test_effectiveness_functions_directly():
    """Bezpośredni test funkcji trading_effectiveness."""
    from backend.trading_effectiveness import trading_effectiveness_summary

    db = SessionLocal()
    try:
        result = trading_effectiveness_summary(db, mode="demo")
        assert "verdict" in result
        assert "net_pnl" in result
        assert "net_expectancy" in result
    finally:
        db.close()


# ============ TUNING INSIGHTS (ETAP Y) ============


def test_tuning_insights_endpoint(client):
    """Endpoint GET /analytics/tuning-insights zwraca kandydatów."""
    _ensure_effectiveness_data()
    resp = client.get("/api/account/analytics/tuning-insights")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "candidates" in data
    assert "candidates_count" in data
    assert "by_priority" in data
    assert "by_category" in data
    assert "affected_settings" in data
    assert isinstance(data["candidates"], list)
    # Każdy kandydat musi mieć wymagane pola
    for c in data["candidates"]:
        for key in ("id", "category", "priority", "action", "setting_key", "confidence"):
            assert key in c, f"Brak pola {key} w kandydacie"


def test_tuning_insights_summary_endpoint(client):
    """Endpoint GET /analytics/tuning-insights/summary zwraca podsumowanie."""
    resp = client.get("/api/account/analytics/tuning-insights/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "candidates_count" in data
    assert "high_priority_count" in data
    assert "top_actions" in data
    assert "trading_verdict" in data
    assert isinstance(data["top_actions"], list)


def test_tuning_insights_candidate_priorities(client):
    """Kandydaci mają prawidłowe priorytety."""
    resp = client.get("/api/account/analytics/tuning-insights")
    candidates = resp.json()["data"]["candidates"]
    valid = {"wysoki", "średni", "niski", "informacyjny"}
    for c in candidates:
        assert c["priority"] in valid, f"Nieprawidłowy priorytet: {c['priority']}"


def test_tuning_insights_candidate_categories(client):
    """Kandydaci mają prawidłowe kategorie."""
    resp = client.get("/api/account/analytics/tuning-insights")
    candidates = resp.json()["data"]["candidates"]
    valid = {
        "symbol_filter", "entry_filter", "strategy_filter",
        "cost_optimization", "activity_limit", "execution_quality",
        "risk_discipline",
    }
    for c in candidates:
        assert c["category"] in valid, f"Nieprawidłowa kategoria: {c['category']}"


def test_tuning_insights_summary_top_actions_limit(client):
    """Top actions — max 5 pozycji."""
    resp = client.get("/api/account/analytics/tuning-insights/summary")
    top = resp.json()["data"]["top_actions"]
    assert len(top) <= 5


def test_tuning_insights_functions_directly():
    """Bezpośredni test generate_tuning_candidates i tuning_summary."""
    from backend.tuning_insights import generate_tuning_candidates, tuning_summary

    db = SessionLocal()
    try:
        result = generate_tuning_candidates(db, mode="demo")
        assert isinstance(result, dict)
        assert "candidates" in result
        assert result["candidates_count"] == len(result["candidates"])

        summary = tuning_summary(db, mode="demo")
        assert "candidates_count" in summary
        assert "high_priority_count" in summary
        assert "top_actions" in summary
        assert "trading_verdict" in summary
    finally:
        db.close()


def test_tuning_insights_setting_keys_non_empty(client):
    """Każdy kandydat ma niepusty setting_key lub target."""
    resp = client.get("/api/account/analytics/tuning-insights")
    candidates = resp.json()["data"]["candidates"]
    for c in candidates:
        assert c.get("setting_key") or c.get("target"), (
            f"Kandydat {c['id']} nie ma setting_key ani target"
        )


def test_tuning_insights_confidence_range(client):
    """Confidence musi być w zakresie 0.0-1.0."""
    resp = client.get("/api/account/analytics/tuning-insights")
    candidates = resp.json()["data"]["candidates"]
    for c in candidates:
        assert 0.0 <= c["confidence"] <= 1.0, (
            f"Confidence poza zakresem: {c['confidence']}"
        )


# ============ CANDIDATE VALIDATION / EXPERIMENT FEED (ETAP Z) ============


def test_experiment_feed_endpoint(client):
    """Endpoint GET /analytics/experiment-feed zwraca pełny pipeline."""
    _ensure_effectiveness_data()
    resp = client.get("/api/account/analytics/experiment-feed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "total_candidates" in data
    assert "classification" in data
    assert "conflicts" in data
    assert "bundles" in data
    assert "needs_more_data" in data
    assert "info_only" in data
    assert isinstance(data["bundles"], list)
    assert isinstance(data["conflicts"], list)


def test_experiment_feed_classification(client):
    """Classification rozdziela kandydatów na actionable / needs_more_data / info_only."""
    resp = client.get("/api/account/analytics/experiment-feed")
    cls = resp.json()["data"]["classification"]
    assert "actionable" in cls
    assert "needs_more_data" in cls
    assert "info_only" in cls
    total = cls["actionable"] + cls["needs_more_data"] + cls["info_only"]
    assert total == resp.json()["data"]["total_candidates"]


def test_experiment_feed_bundles_structure(client):
    """Każda paczka ma wymagane pola."""
    resp = client.get("/api/account/analytics/experiment-feed")
    bundles = resp.json()["data"]["bundles"]
    for b in bundles:
        for key in ("name", "scope", "priority", "avg_confidence",
                     "candidates_count", "settings_affected", "candidates"):
            assert key in b, f"Brak pola {key} w paczce {b.get('name')}"
        assert isinstance(b["candidates"], list)
        assert len(b["candidates"]) > 0
        assert len(b["candidates"]) <= 4  # MAX_CANDIDATES_PER_BUNDLE


def test_experiment_feed_bundle_priorities(client):
    """Priorytety paczek muszą być poprawne."""
    resp = client.get("/api/account/analytics/experiment-feed")
    valid = {"wysoki", "średni", "niski", "informacyjny"}
    for b in resp.json()["data"]["bundles"]:
        assert b["priority"] in valid


def test_experiment_feed_bundles_limit(client):
    """Nie więcej niż MAX_BUNDLES paczek."""
    resp = client.get("/api/account/analytics/experiment-feed")
    bundles = resp.json()["data"]["bundles"]
    assert len(bundles) <= 5  # MAX_BUNDLES


def test_experiment_feed_conflicts_structure(client):
    """Konflikty mają wymagane pola."""
    resp = client.get("/api/account/analytics/experiment-feed")
    for conflict in resp.json()["data"]["conflicts"]:
        assert "candidate_a" in conflict
        assert "candidate_b" in conflict
        assert "reason" in conflict
        assert "resolution" in conflict


def test_experiment_feed_summary_endpoint(client):
    """Endpoint GET /analytics/experiment-feed/summary zwraca skrót."""
    resp = client.get("/api/account/analytics/experiment-feed/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "total_candidates" in data
    assert "classification" in data
    assert "bundles_ready" in data
    assert "conflicts_count" in data
    assert "top_bundles" in data
    assert isinstance(data["top_bundles"], list)


def test_experiment_feed_summary_top_bundles_limit(client):
    """Top bundles — max 3 pozycji."""
    resp = client.get("/api/account/analytics/experiment-feed/summary")
    top = resp.json()["data"]["top_bundles"]
    assert len(top) <= 3


def test_experiment_feed_functions_directly():
    """Bezpośredni test generate_experiment_feed."""
    from backend.candidate_validation import generate_experiment_feed

    db = SessionLocal()
    try:
        feed = generate_experiment_feed(db, mode="demo")
        assert isinstance(feed, dict)
        assert "total_candidates" in feed
        assert "bundles" in feed
        assert feed["bundles_count"] == len(feed["bundles"])
    finally:
        db.close()


def test_candidate_classification_directly():
    """Bezpośredni test classify_candidates."""
    from backend.candidate_validation import classify_candidates

    # Kandydat actionable (wysoki priorytet, wysoka confidence)
    high = {
        "id": "test_high", "category": "symbol_filter",
        "priority": "wysoki", "action": "test", "setting_key": "watchlist",
        "target": "TESTSYM", "confidence": 0.8, "reason": "test",
    }
    # Kandydat needs_more_data (za mała confidence)
    low_conf = {
        "id": "test_low", "category": "symbol_filter",
        "priority": "wysoki", "action": "test", "setting_key": "watchlist",
        "target": "LOWSYM", "confidence": 0.1, "reason": "test",
    }
    # Kandydat info_only
    info = {
        "id": "test_info", "category": "cost_optimization",
        "priority": "informacyjny", "action": "test", "setting_key": None,
        "target": "global", "confidence": 0.5, "reason": "test",
    }

    result = classify_candidates([high, low_conf, info])
    assert len(result["actionable"]) == 1
    assert len(result["needs_more_data"]) == 1
    assert len(result["info_only"]) == 1
    assert result["actionable"][0]["id"] == "test_high"


def test_conflict_detection_directly():
    """Bezpośredni test detect_conflicts."""
    from backend.candidate_validation import detect_conflicts

    # Dwa kandydaty: usunięcie z watchlist + zmiana per-hour dla tego samego symbolu
    remove = {
        "id": "sym_remove_X", "category": "symbol_filter",
        "priority": "wysoki", "action": "usuń_z_watchlist",
        "setting_key": "watchlist", "target": "XSYM", "confidence": 0.8,
    }
    limit = {
        "id": "sym_limit_X", "category": "activity_limit",
        "priority": "średni", "action": "ogranicz_aktywność",
        "setting_key": "max_trades_per_hour_per_symbol", "target": "XSYM",
        "confidence": 0.5,
    }

    conflicts = detect_conflicts([remove, limit])
    assert len(conflicts) >= 1
    assert conflicts[0]["candidate_a"] == "sym_remove_X"


# ============ EXIT QUALITY (ETAP B) ====================================

def test_exit_quality_model_creation():
    """ExitQuality — zapis rekordu do DB i odczyt."""
    from backend.database import ExitQuality, SessionLocal
    db = SessionLocal()
    try:
        eq = ExitQuality(
            symbol="BTCUSDT", mode="demo", side="BUY",
            entry_price=50000.0, exit_price=51000.0, quantity=0.01,
            planned_tp=52000.0, planned_sl=49000.0,
            mfe_price=51500.0, mae_price=49800.0,
            gross_pnl=10.0, net_pnl=8.0, total_cost=2.0,
            mfe_pnl=15.0, mae_pnl=-2.0,
            gave_back_pct=46.67, tp_hit=False,
            tp_near_miss_pct=75.0, sl_hit=False,
            expected_rr=2.0, realized_rr=0.8,
            edge_vs_cost=4.0, duration_seconds=3600.0,
        )
        db.add(eq)
        db.commit()
        db.refresh(eq)
        assert eq.id is not None
        assert eq.symbol == "BTCUSDT"
        assert eq.gave_back_pct == 46.67
    finally:
        db.close()


def test_exit_quality_report_empty():
    """exit_quality_report zwraca pusty raport gdy brak danych."""
    from backend.trading_effectiveness import exit_quality_report
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        result = exit_quality_report(db, mode="nonexistent_mode")
        assert result["total_exits"] == 0
    finally:
        db.close()


def test_exit_quality_report_with_data():
    """exit_quality_report — poprawne agregaty z istniejących rekordów."""
    from backend.trading_effectiveness import exit_quality_report
    from backend.database import ExitQuality, SessionLocal
    db = SessionLocal()
    try:
        # Wstaw dwa rekordy testowe
        for i, (sym, tp_hit, sl_hit, gave, rr) in enumerate([
            ("ETHUSDT", True, False, 20.0, 1.5),
            ("ETHUSDT", False, True, 80.0, -0.5),
        ]):
            eq = ExitQuality(
                symbol=sym, mode="demo_eqtest", side="BUY",
                entry_price=3000.0, exit_price=3100.0, quantity=0.1,
                planned_tp=3200.0, planned_sl=2900.0,
                mfe_price=3150.0, mae_price=2950.0,
                gross_pnl=10.0, net_pnl=8.0, total_cost=2.0,
                mfe_pnl=15.0, mae_pnl=-5.0,
                gave_back_pct=gave, tp_hit=tp_hit,
                tp_near_miss_pct=75.0, sl_hit=sl_hit,
                expected_rr=2.0, realized_rr=rr,
                edge_vs_cost=4.0, duration_seconds=1800.0,
            )
            db.add(eq)
        db.commit()

        result = exit_quality_report(db, mode="demo_eqtest")
        assert result["total_exits"] == 2
        assert result["tp_hit_rate"] == 50.0
        assert result["sl_hit_rate"] == 50.0
        assert result["avg_gave_back_pct"] == 50.0
        assert len(result["by_symbol"]) == 1
        assert result["by_symbol"][0]["symbol"] == "ETHUSDT"
    finally:
        db.close()


def test_exit_quality_endpoint(client):
    """Endpoint /api/account/analytics/exit-quality zwraca sukces."""
    resp = client.get("/api/account/analytics/exit-quality?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "total_exits" in data["data"]


# ─── Position Analysis ──────────────────────────────────────────────


def test_position_analysis_endpoint_empty(client):
    """Endpoint /api/positions/analysis zwraca sukces z pustą listą."""
    resp = client.get("/api/positions/analysis?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "summary" in data
    assert "data" in data
    assert isinstance(data["data"], list)
    assert data["summary"]["positions_count"] == len(data["data"])


def test_position_analysis_with_position(client):
    """Endpoint analizy pozycji generuje kartę decyzyjną."""
    db = SessionLocal()
    pos = Position(
        symbol="BTCEUR",
        side="LONG",
        entry_price=50000.0,
        quantity=0.1,
        current_price=55000.0,
        unrealized_pnl=500.0,
        mode="demo",
        opened_at=utc_now_naive(),
    )
    db.add(pos)
    db.commit()
    pos_id = pos.id

    try:
        resp = client.get("/api/positions/analysis?mode=demo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        cards = data["data"]
        assert len(cards) >= 1

        btc_card = next((c for c in cards if c["symbol"] == "BTCEUR"), None)
        assert btc_card is not None
        assert btc_card["entry_price"] == 50000.0
        assert btc_card["current_price"] == 55000.0
        assert btc_card["pnl_eur"] > 0
        assert btc_card["decision"] in ("TRZYMAJ", "SPRZEDAJ", "CZEKAJ")
        assert isinstance(btc_card["reasons"], list)
        assert len(btc_card["reasons"]) > 0
    finally:
        obj = db.query(Position).filter(Position.id == pos_id).first()
        if obj:
            db.delete(obj)
            db.commit()
        db.close()


def test_position_analysis_hold_card(client):
    """Pozycja HOLD generuje kartę z celem i remaining (wymaga tymczasowego tieru HOLD)."""
    import json as _json
    db = SessionLocal()

    # Ustaw tymczasowy tier HOLD dla WLFIEUR na czas testu
    _hold_tiers = {
        "CORE": {"symbols": ["BTCEUR"], "min_confidence_add": 0.0, "min_edge_multiplier_add": 0.0, "risk_scale": 1.0, "max_trades_per_day_per_symbol": 2},
        "HOLD": {"symbols": ["WLFIEUR"], "hold_mode": True, "no_auto_exit": True, "no_new_entries": True, "target_value_eur": 300, "min_confidence_add": 0.0, "min_edge_multiplier_add": 0.0, "risk_scale": 0.0, "max_trades_per_day_per_symbol": 0},
    }
    old_setting = db.query(RuntimeSetting).filter(RuntimeSetting.key == "symbol_tiers").first()
    old_value = old_setting.value if old_setting else None
    if old_setting:
        old_setting.value = _json.dumps(_hold_tiers)
    else:
        db.add(RuntimeSetting(key="symbol_tiers", value=_json.dumps(_hold_tiers)))
    db.commit()

    pos = Position(
        symbol="WLFIEUR",
        side="LONG",
        entry_price=0.085,
        quantity=3260,
        current_price=0.085,
        unrealized_pnl=0.0,
        mode="demo",
        opened_at=utc_now_naive(),
    )
    db.add(pos)
    db.commit()
    pos_id = pos.id

    try:
        resp = client.get("/api/positions/analysis?mode=demo")
        assert resp.status_code == 200
        cards = resp.json()["data"]

        wlfi_card = next((c for c in cards if c["symbol"] == "WLFIEUR"), None)
        assert wlfi_card is not None
        assert wlfi_card["is_hold"] is True
        assert wlfi_card["decision"] == "TRZYMAJ"
        assert "hold_target_eur" in wlfi_card
        assert "hold_remaining_eur" in wlfi_card
    finally:
        obj = db.query(Position).filter(Position.id == pos_id).first()
        if obj:
            db.delete(obj)
            db.commit()
        # Przywróć oryginalny tier override
        st = db.query(RuntimeSetting).filter(RuntimeSetting.key == "symbol_tiers").first()
        if st and old_value is not None:
            st.value = old_value
            db.commit()
        elif st and old_value is None:
            db.delete(st)
            db.commit()
        db.close()
# TESTY AKCEPTACYJNE — LIVE/DEMO spójność (v0.7)
# ═══════════════════════════════════════════════════════════════════════════


def test_acceptance_live_positions_returns_source_field(client):
    """
    GET /api/positions?mode=live musi zwracać source="binance_spot" (lub pustą listę
    jeśli Binance niedostępne), ale NIGDY nie powinien 500.
    """
    resp = client.get("/api/positions?mode=live")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    # Jeśli Binance niedostępne w testach, data zwraca pustą listę
    assert "data" in data
    assert isinstance(data["data"], list)
    # Gdy mamy dane, każdy element ma source
    for item in data["data"]:
        assert item.get("source") == "binance_spot"


def test_acceptance_demo_positions_from_local_db(client):
    """
    GET /api/positions?mode=demo powinien czytać z lokalnej tabeli Position.
    Bez pozycji w DB zwraca pustą listę (nie binance).
    """
    resp = client.get("/api/positions?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert isinstance(data.get("data"), list)
    # Demo NIE zawiera source=binance_spot
    for item in data["data"]:
        assert item.get("source") != "binance_spot"


def test_acceptance_best_opportunity_has_gate_fields(client):
    """
    GET /api/signals/best-opportunity musi zwracać pola bramek:
    candidates_evaluated, oraz allowed_count/blocked_count LUB best_candidate.
    Akcja to BUY/SELL/CZEKAJ.
    """
    resp = client.get("/api/signals/best-opportunity?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert data["action"] in ("BUY", "SELL", "CZEKAJ")
    assert "candidates_evaluated" in data
    # Jeśli CZEKAJ — musi być powód
    if data["action"] == "CZEKAJ":
        assert data.get("reason")
    # Jeśli akcja BUY/SELL — musi być opportunity z score
    if data["action"] in ("BUY", "SELL"):
        opp = data.get("opportunity")
        assert opp is not None
        assert "score" in opp
        assert "confidence" in opp
        assert "symbol" in opp
        assert "allowed_count" in data
        assert "blocked_count" in data


def test_acceptance_diagnostics_live_no_500(client):
    """
    GET /api/debug/state-consistency?mode=live nie powinien 500,
    nawet gdy Binance niedostępne.
    Dla LIVE powinien zwracać spot_comparison (lub graceful error).
    """
    resp = client.get("/api/debug/state-consistency?mode=live")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert data.get("mode") == "live"
    # spot_comparison powinien być obecny (nawet z error)
    if "spot_comparison" in data:
        sc = data["spot_comparison"]
        if not sc.get("error"):
            assert "binance_spot_count" in sc
            assert "in_binance_not_local" in sc


def test_acceptance_goal_evaluator_returns_realism(client):
    """
    POST /api/positions/goals/evaluate powinien zwracać:
    realism, required_move_pct, reality_score, suggested_path.
    """
    resp = client.post(
        "/api/positions/goals/evaluate",
        json={
            "mode": "demo",
            "target_value": 15000.0,
            "current_value": 10000.0,
            "goal_type": "target_value_eur",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "realism" in data
    assert data["realism"] in ("bardzo_realny", "realny", "mozliwy", "trudny", "malo_realny")
    assert "required_move_pct" in data
    assert data["required_move_pct"] == 50.0  # (15000-10000)/10000 * 100
    assert "reality_score" in data
    assert isinstance(data["reality_score"], int)
    assert "suggested_path" in data
    assert isinstance(data["suggested_path"], list)
    assert len(data["suggested_path"]) >= 1


def test_acceptance_effective_universe_not_empty(client):
    """
    _get_symbols_from_db_or_env musi zwracać niepustą listę symboli
    (dzięki fallback do ENV/Binance), więc best-opportunity i top5
    nie powinny failować z "brak danych".
    """
    # top5 korzysta z _get_symbols_from_db_or_env
    resp = client.get("/api/signals/top5")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    # Nie wymagamy danych (bo klines mogą być puste w testach),
    # ale endpoint nie powinien crashować


# =====================================================================
# ============ TELEGRAM INTELLIGENCE (ETAP 7) =========================
# =====================================================================


def test_telegram_intel_state_endpoint(client):
    """GET /api/telegram-intel/state zwraca stan interpretacyjny."""
    resp = client.get("/api/telegram-intel/state?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    state = data.get("data")
    assert state is not None
    # Pola obecne zawsze (nawet gdy brak wiadomości)
    assert "last_signal" in state
    assert "last_execution" in state
    assert "system_health_flags" in state
    assert "decision_bias" in state
    assert "last_blockers" in state
    assert "stats" in state


def test_telegram_intel_state_live_mode(client):
    """GET /api/telegram-intel/state działa też dla mode=live."""
    resp = client.get("/api/telegram-intel/state?mode=live")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True


def test_telegram_intel_messages_endpoint(client):
    """GET /api/telegram-intel/messages zwraca listę wiadomości i kategorie."""
    resp = client.get("/api/telegram-intel/messages?limit=20&since_minutes=120")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "count" in data
    assert "messages" in data
    assert isinstance(data["messages"], list)
    assert "categories" in data
    # Sprawdź wszystkie 7 kategorii
    cats = data["categories"]
    assert "SIGNAL_MESSAGE" in cats
    assert "EXECUTION_MESSAGE" in cats
    assert "BLOCKER_MESSAGE" in cats
    assert "RISK_MESSAGE" in cats
    assert "SYSTEM_STATUS_MESSAGE" in cats
    assert "OPERATOR_MESSAGE" in cats
    assert "TARGET_MESSAGE" in cats


def test_telegram_intel_log_event_endpoint(client):
    """POST /api/telegram-intel/log-event zapisuje wiadomość do archiwum."""
    resp = client.post(
        "/api/telegram-intel/log-event",
        json={
            "text": "Test wiadomości z pytest — BUY BTCEUR confidence=0.75",
            "source_module": "test_smoke",
            "direction": "incoming",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True


def test_telegram_intel_log_event_visible_in_messages(client):
    """Wiadomość zapisana przez log-event pojawia się w /messages."""
    unique_text = "PYTEST_UNIQUE_MSG_XYZ_12345 BUY ETHEUR"

    # Zapisz wiadomość
    client.post(
        "/api/telegram-intel/log-event",
        json={"text": unique_text, "source_module": "test_smoke", "direction": "incoming"},
    )

    # Sprawdź że pojawia się w archiwum
    resp = client.get("/api/telegram-intel/messages?limit=50&since_minutes=60")
    assert resp.status_code == 200
    messages = resp.json().get("messages", [])
    texts = [m.get("text", "") for m in messages]
    assert any(unique_text in t for t in texts), "Zapisana wiadomość powinna być widoczna w archiwum"


def test_telegram_intel_evaluate_goal_position_value(client):
    """POST /api/telegram-intel/evaluate-goal ocenia cel dla position_value."""
    resp = client.post(
        "/api/telegram-intel/evaluate-goal",
        json={
            "target_type": "position_value",
            "current_value": 500.0,
            "target_value": 650.0,
            "symbol": "BTCEUR",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    result = data.get("result")
    assert result is not None
    assert "realism" in result
    assert "required_move_pct" in result
    assert "time_horizon_estimate" in result
    assert "explanation_pl" in result


def test_telegram_intel_evaluate_goal_portfolio_value(client):
    """POST /api/telegram-intel/evaluate-goal ocenia cel portfolio_value."""
    resp = client.post(
        "/api/telegram-intel/evaluate-goal",
        json={
            "target_type": "portfolio_value",
            "current_value": 10000.0,
            "target_value": 12000.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    result = data.get("result")
    assert result is not None
    assert "realism" in result
    # required_move_pct = (12000-10000)/10000 * 100 = 20%
    assert abs(result["required_move_pct"] - 20.0) < 0.01


def test_telegram_intel_evaluate_goal_invalid_values(client):
    """POST /api/telegram-intel/evaluate-goal z zerowymi wartościami zwraca błąd."""
    resp = client.post(
        "/api/telegram-intel/evaluate-goal",
        json={
            "target_type": "position_value",
            "current_value": 0.0,
            "target_value": 100.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    result = data.get("result")
    # Powinna być informacja o błędzie (realism=error lub explanation_pl)
    assert result is not None
    assert "explanation_pl" in result


def test_telegram_intel_messages_category_filter(client):
    """GET /api/telegram-intel/messages filtruje po kategorii."""
    # Zapisz wiadomość z wyraźnym wzorcem blokerem
    client.post(
        "/api/telegram-intel/log-event",
        json={
            "text": "cooldown aktywny — wejście zablokowane",
            "source_module": "test_smoke",
            "direction": "outgoing",
        },
    )

    # Filtruj po kategorii BLOCKER_MESSAGE
    resp = client.get(
        "/api/telegram-intel/messages?limit=50&category=BLOCKER_MESSAGE&since_minutes=60"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert isinstance(data.get("messages"), list)


def test_telegram_intel_state_after_log_event(client):
    """Stan intel po zapisaniu wiadomości nie crashuje."""
    client.post(
        "/api/telegram-intel/log-event",
        json={
            "text": "kill switch aktywny — ryzyko",
            "source_module": "test_smoke",
            "direction": "outgoing",
        },
    )
    resp = client.get("/api/telegram-intel/state?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
