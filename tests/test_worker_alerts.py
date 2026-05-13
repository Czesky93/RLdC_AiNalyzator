from __future__ import annotations

from backend import reevaluation_worker as worker


def test_worker_queue_alert_dedup(monkeypatch):
    sent = []
    monkeypatch.setattr(worker, "_LAST_QUEUE_ALERT_SIGNATURE", "")
    monkeypatch.setattr(worker, "_LAST_QUEUE_ALERT_TS", 0.0)
    monkeypatch.setattr(worker, "get_operator_queue", lambda db: [{"priority": "critical", "sla_breached": True}])
    monkeypatch.setattr(worker, "dispatch_notification", lambda *args, **kwargs: sent.append((args, kwargs)))

    first = worker._step_refresh_operator_queue(db=None)
    second = worker._step_refresh_operator_queue(db=None)

    assert first["queue_size"] == 1
    assert second["queue_size"] == 1
    assert len(sent) == 1
