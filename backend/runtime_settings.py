"""
Runtime overrides persisted in DB (Control Plane).

These settings are optional: if a key isn't present in DB, the system falls back to ENV defaults.
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Dict, Iterable, Optional

from sqlalchemy.orm import Session

from backend.database import RuntimeSetting


_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name, "true" if default else "false") or "").strip().lower()
    return raw in _TRUE


def _parse_bool(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    v = str(raw).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def get_overrides(db: Session, keys: Iterable[str]) -> Dict[str, str]:
    key_list = [k for k in keys if k]
    if not key_list:
        return {}
    rows = db.query(RuntimeSetting).filter(RuntimeSetting.key.in_(key_list)).all()
    return {r.key: (r.value or "") for r in rows if r and r.key}


def parse_watchlist(raw: str) -> list[str]:
    items = [s.strip() for s in (raw or "").split(",") if s.strip()]
    wl: list[str] = []
    for item in items:
        sym = (item or "").strip()
        if not sym:
            continue
        sym = sym.replace(" ", "").replace("/", "").replace("-", "").upper()
        if sym and sym not in wl:
            wl.append(sym)
    return wl


def watchlist_override(db: Session) -> Optional[list[str]]:
    """
    If override exists -> returns parsed list (can be empty).
    If no override -> returns None.
    """
    overrides = get_overrides(db, ["watchlist"])
    if "watchlist" not in overrides:
        return None
    return parse_watchlist(overrides.get("watchlist") or "")


def upsert_overrides(db: Session, updates: Dict[str, Optional[str]]) -> None:
    """
    Upsert many overrides in a single transaction.

    - value=None => delete override
    - value=str  => set override
    """
    if not updates:
        return

    keys = [k for k in updates.keys() if k]
    existing = {}
    if keys:
        rows = db.query(RuntimeSetting).filter(RuntimeSetting.key.in_(keys)).all()
        existing = {r.key: r for r in rows if r and r.key}

    now = datetime.utcnow()
    for key, value in updates.items():
        if not key:
            continue
        row = existing.get(key)
        if value is None:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(RuntimeSetting(key=key, value=value, updated_at=now))
        else:
            row.value = value
            row.updated_at = now

    db.commit()


def effective_bool(db: Session, key: str, env_var: str, default: bool) -> bool:
    """
    Resolve bool setting:
      override DB key -> ENV var -> default.
    """
    try:
        overrides = get_overrides(db, [key])
    except Exception:
        overrides = {}
    parsed = _parse_bool(overrides.get(key))
    if parsed is not None:
        return parsed
    return _env_bool(env_var, default)
