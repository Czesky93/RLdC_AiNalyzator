"""
Optional admin auth for sensitive endpoints.

If `ADMIN_TOKEN` is set (non-empty), endpoints protected with `require_admin`
require header:

  X-Admin-Token: <ADMIN_TOKEN>

If `ADMIN_TOKEN` is empty, auth is disabled (local/dev friendly).
"""

from __future__ import annotations

import os
from fastapi import Header, HTTPException


def require_admin(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> None:
    token = (os.getenv("ADMIN_TOKEN", "") or "").strip()
    if not token:
        return
    if not x_admin_token or x_admin_token != token:
        raise HTTPException(status_code=401, detail="Unauthorized")

