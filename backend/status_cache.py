from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def get_cached(key: str, ttl_seconds: float) -> Optional[Any]:
    now = time.monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        if now - float(entry.get("ts") or 0.0) > ttl_seconds:
            return None
        return entry.get("data")


def set_cached(key: str, data: Any) -> None:
    with _LOCK:
        _CACHE[key] = {"ts": time.monotonic(), "data": data}


def invalidate(key: str | None = None) -> None:
    with _LOCK:
        if key is None:
            _CACHE.clear()
        else:
            _CACHE.pop(key, None)
