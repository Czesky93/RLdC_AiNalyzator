"""
Dashboard router — agregator snapshotów dla głównego widoku dashboardu.

Jeden endpoint zwraca spójny payload ze wspólnym snapshot_id:
 - top opportunities (analityczne)
 - best analytical candidate
 - best executable candidate (rzeczywiście możliwy do wykonania)
 - rejected candidates z reason codes
 - positions snapshot
 - market distribution
 - portfolio constraints

Frontend NIE składa tego z wielu niezależnych endpointów.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db

logger = logging.getLogger("dashboard_router")
router = APIRouter()


@router.get("/market-scan")
def get_dashboard_market_scan(
    mode: str = Query("demo", description="demo lub live"),
    force: bool = Query(False, description="Wymuś odświeżenie cache"),
    db: Session = Depends(get_db),
):
    """
    Kanoniczny endpoint dashboard market-scan.

    Zwraca MarketScanSnapshot ze spójnym snapshot_id:
    - best_analytical_candidate: najwyżej oceniony kandydat (analitycznie)
    - best_executable_candidate: najwyższy kandydat, który przeszedł WSZYSTKIE bramki
    - rejected_candidates: lista z reason_code + reason_text dla każdego kandydata
    - opportunities_top_n: ranking czysto analityczny (top 10)
    - positions_snapshot: aktualne pozycje z tego samego snapshotu
    - final_market_status: ENTRY_FOUND | WAIT | NO_EXECUTABLE_CANDIDATE | DEGRADED
    - final_user_message: ludzki opis stanu rynku z licznikami

    Caching 18s — ten sam snapshot_id zwracany do frontendowych komponentów.
    """
    try:
        from backend.market_scanner import run_market_scan

        snapshot = run_market_scan(db, mode=mode, force=force)
        return {"success": True, "data": snapshot}
    except Exception as exc:
        logger.error("dashboard_market_scan_error: %s", str(exc), exc_info=True)
        return {
            "success": False,
            "error": str(exc),
            "data": None,
        }


@router.get("/market-scan/status")
def get_scan_status(db: Session = Depends(get_db)):
    """
    Zwraca uproszczony status: czy istnieje aktualny cache scan i kiedy wygasa.
    Używane przez diagnostykę.
    """
    import time as _time

    from backend.market_scanner import (
        _scan_cache,
        _scan_cache_mode,
        _scan_cache_ts,
        _scan_cache_ttl,
    )

    age = round(_time.monotonic() - _scan_cache_ts, 1) if _scan_cache else None
    return {
        "cache_exists": _scan_cache is not None,
        "cache_age_seconds": age,
        "cache_ttl_seconds": _scan_cache_ttl,
        "cache_mode": _scan_cache_mode if _scan_cache else None,
        "snapshot_id": _scan_cache.get("snapshot_id") if _scan_cache else None,
        "final_status": _scan_cache.get("final_market_status") if _scan_cache else None,
    }
