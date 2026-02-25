"""
System logger that persists logs into the database.
"""
from typing import Optional
from datetime import datetime

from backend.database import SessionLocal, SystemLog


def log_to_db(
    level: str,
    module: str,
    message: str,
    exception: Optional[str] = None,
    db=None,
):
    """Zapisz log do bazy danych (SystemLog)."""
    created_local = False
    if db is None:
        db = SessionLocal()
        created_local = True

    try:
        entry = SystemLog(
            level=level.upper(),
            module=module,
            message=message,
            exception=exception,
            timestamp=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if created_local:
            db.close()


def log_exception(module: str, message: str, exc: Exception, db=None):
    """Helper do logowania wyjątków."""
    log_to_db(
        level="ERROR",
        module=module,
        message=message,
        exception=str(exc),
        db=db,
    )
