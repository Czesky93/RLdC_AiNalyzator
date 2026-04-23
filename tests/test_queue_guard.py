from __future__ import annotations

from backend.database import PendingOrder, RuntimeSetting, SessionLocal, utc_now_naive
from backend.queue_guard import get_queue_pressure_state


def test_queue_backpressure_switches_local_only_mode(monkeypatch):
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.query(RuntimeSetting).filter(
            RuntimeSetting.key.in_(
                ["queue_backpressure_threshold", "force_local_only_on_queue_pressure"]
            )
        ).delete(synchronize_session=False)
        db.add(RuntimeSetting(key="queue_backpressure_threshold", value="2"))
        db.add(RuntimeSetting(key="force_local_only_on_queue_pressure", value="true"))
        db.add_all(
            [
                PendingOrder(
                    symbol="BTCUSDC",
                    side="BUY",
                    order_type="MARKET",
                    quantity=0.01,
                    mode="demo",
                    status="PENDING_CREATED",
                    created_at=utc_now_naive(),
                ),
                PendingOrder(
                    symbol="ETHUSDC",
                    side="BUY",
                    order_type="MARKET",
                    quantity=0.02,
                    mode="demo",
                    status="PENDING_CREATED",
                    created_at=utc_now_naive(),
                ),
            ]
        )
        db.commit()
        monkeypatch.setattr("backend.queue_guard.get_operator_queue", lambda _db: [])
        state = get_queue_pressure_state(db)
    finally:
        db.close()

    assert state["level"] == "elevated"
    assert state["local_only"] is True
