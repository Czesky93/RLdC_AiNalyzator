from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp_db = tempfile.NamedTemporaryFile(prefix="rldc_tg_", suffix=".db", delete=False)
_tmp_db.close()
_TEST_DB_URL = f"sqlite:///{_tmp_db.name}"

from backend.database import Base, Incident, PendingOrder, utc_now_naive
from telegram_bot import bot

engine = create_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


class _Ctx:
    def __init__(self, args):
        self.args = args


def _patch_common(monkeypatch, outbox):
    async def _always_auth(update):
        return True

    async def _capture(update, text, cmd):
        outbox.append((cmd, text))

    monkeypatch.setattr(bot, "_check_auth", _always_auth)
    monkeypatch.setattr(bot, "_send_reply", _capture)
    monkeypatch.setattr(bot, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(bot, "TRADING_MODE", "live", raising=False)


def test_confirm_disambiguates_incident_id(monkeypatch):
    db = TestingSessionLocal()
    try:
        inc = Incident(policy_action_id=1, status="open", priority="high")
        db.add(inc)
        db.commit()
        inc_id = inc.id
    finally:
        db.close()

    outbox = []
    _patch_common(monkeypatch, outbox)

    asyncio.run(bot.confirm_command(update=object(), context=_Ctx([str(inc_id)])))

    assert outbox
    msg = outbox[-1][1]
    assert "INCYDENT" in msg
    assert f"/close_incident {inc_id}" in msg


def test_close_incident_marks_resolved(monkeypatch):
    db = TestingSessionLocal()
    try:
        inc = Incident(policy_action_id=1, status="open", priority="medium")
        db.add(inc)
        db.commit()
        inc_id = inc.id
    finally:
        db.close()

    outbox = []
    _patch_common(monkeypatch, outbox)

    asyncio.run(
        bot.close_incident_command(update=object(), context=_Ctx([str(inc_id)]))
    )

    db = TestingSessionLocal()
    try:
        inc = db.query(Incident).filter(Incident.id == inc_id).first()
        assert inc is not None
        assert inc.status == "resolved"
        assert inc.resolved_by == "telegram_operator"
        assert inc.resolved_at is not None
    finally:
        db.close()


def test_pending_lists_active_trades(monkeypatch):
    db = TestingSessionLocal()
    try:
        db.add(
            PendingOrder(
                symbol="ETHUSDC",
                side="BUY",
                order_type="MARKET",
                quantity=0.05,
                mode="live",
                status="PENDING",
                created_at=utc_now_naive(),
            )
        )
        db.add(
            PendingOrder(
                symbol="BTCUSDC",
                side="BUY",
                order_type="MARKET",
                quantity=0.01,
                mode="live",
                status="REJECTED",
                created_at=utc_now_naive(),
            )
        )
        db.commit()
    finally:
        db.close()

    outbox = []
    _patch_common(monkeypatch, outbox)

    asyncio.run(bot.pending_command(update=object(), context=_Ctx([])))

    assert outbox
    text = outbox[-1][1]
    assert "Pending trades" in text
    assert "ETHUSDC" in text
    assert "BTCUSDC" not in text
