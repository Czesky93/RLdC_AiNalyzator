"""
Control Plane API - thin HTTP layer over runtime settings.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.accounting import get_demo_quote_ccy
from backend.ai_orchestrator import get_ai_budget_status, get_ai_orchestrator_status
from backend.auth import require_admin
from backend.database import (
    DecisionTrace,
    MarketData,
    Order,
    PendingOrder,
    Position,
    SessionLocal,
    Signal,
    SystemLog,
    get_db,
    utc_now_naive,
)
from backend.governance import get_operator_queue_with_summary
from backend.quote_currency import (
    convert_eur_amount_to_quote,
    is_test_symbol,
    parse_nl_quote_command,
    preferred_symbol_for_asset,
    resolve_eur_usdc_rate,
    resolve_required_quote_usdc,
)
from backend.runtime_settings import (
    RuntimeSettingsError,
    apply_runtime_updates,
    build_runtime_state,
    build_symbol_tier_map,
    get_runtime_config,
)
from backend.symbol_universe import (
    get_symbol_registry,
    resolve_asset_symbol,
    validate_symbol,
)
from backend.system_logger import log_to_db

router = APIRouter()

_ACTIVE_PENDING_STATUSES = [
    "PENDING_CREATED",
    "PENDING",
    "CONFIRMED",
    "PENDING_CONFIRMED",
    "EXCHANGE_SUBMITTED",
    "PARTIALLY_FILLED",
]


class ControlStateUpdate(BaseModel):
    trading_mode: Optional[str] = None
    allow_live_trading: Optional[bool] = None
    demo_trading_enabled: Optional[bool] = None
    ws_enabled: Optional[bool] = None
    max_certainty_mode: Optional[bool] = None
    watchlist: Optional[List[str]] = None
    enabled_strategies: Optional[List[str]] = None
    max_open_positions: Optional[int] = None
    max_trades_per_day: Optional[int] = None
    max_trades_per_hour_per_symbol: Optional[int] = None
    loss_streak_limit: Optional[int] = None
    cooldown_after_loss_streak_minutes: Optional[int] = None
    risk_per_trade: Optional[float] = None
    max_daily_drawdown: Optional[float] = None
    max_weekly_drawdown: Optional[float] = None
    kill_switch_enabled: Optional[bool] = None
    maker_fee_rate: Optional[float] = None
    taker_fee_rate: Optional[float] = None
    slippage_bps: Optional[float] = None
    spread_buffer_bps: Optional[float] = None
    min_edge_multiplier: Optional[float] = None
    min_expected_rr: Optional[float] = None
    min_order_notional: Optional[float] = None
    min_buy_eur: Optional[float] = None
    ai_enabled: Optional[bool] = None
    market_data_timeout_seconds: Optional[int] = None
    log_level: Optional[str] = None
    symbol_tiers: Optional[Dict[str, Any]] = None


def _active_position_count(db: Session) -> int:
    return int(db.query(Position).filter(Position.exit_reason_code.is_(None)).count())


def _collector_watchlist(request: Request) -> Optional[list[str]]:
    collector = getattr(request.app.state, "collector", None)
    watchlist = getattr(collector, "watchlist", None) if collector is not None else None
    if isinstance(watchlist, list) and watchlist:
        return [str(item) for item in watchlist if item]
    return None


def _build_response_state(request: Request, db: Session) -> Dict[str, Any]:
    state = build_runtime_state(
        db,
        collector_watchlist=_collector_watchlist(request),
        active_position_count=_active_position_count(db),
    )
    state["demo_quote_ccy"] = get_demo_quote_ccy()
    # Alias dla frontendu — spójność z /api/account/trading-status
    state["live_trading_enabled"] = bool(state.get("allow_live_trading", False))
    state["trading_enabled"] = state.get("trading_mode") == "live" and state.get(
        "live_trading_enabled", False
    )
    return state


def _actor_from_request(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"control_api:{client_host}"


def _update_payload(update: ControlStateUpdate) -> Dict[str, Any]:
    return update.model_dump(exclude_none=True)


@router.get("/state")
def get_control_state(request: Request, db: Session = Depends(get_db)):
    try:
        return {"success": True, "data": _build_response_state(request, db)}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting control state: {str(exc)}"
        ) from exc


@router.post("/state")
def set_control_state(
    request: Request,
    update: ControlStateUpdate,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        payload = _update_payload(update)
        result = apply_runtime_updates(
            db,
            payload,
            actor=_actor_from_request(request),
            active_position_count=_active_position_count(db),
        )
        state = _build_response_state(request, db)
        return {
            "success": True,
            "data": state,
            "changes": result.get("changed", []),
        }
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error setting control state: {str(exc)}"
        ) from exc


@router.get("/hold-status")
def get_hold_status(db: Session = Depends(get_db)):
    """
    Zwraca status pozycji HOLD (np. WLFI) — aktualną wartość vs. cel.
    Używane do wyświetlania paska postępu WLFI w UI.
    """
    try:
        cfg = get_runtime_config(db)
        tiers_cfg = cfg.get("symbol_tiers") or {}
        tier_map = build_symbol_tier_map(tiers_cfg)

        hold_symbols = [
            sym for sym, overrides in tier_map.items() if overrides.get("hold_mode")
        ]

        items = []
        for sym in hold_symbols:
            overrides = tier_map[sym]
            target_eur = float(overrides.get("target_value_eur") or 0)

            # szukamy aktualnej ceny z MarketData
            from sqlalchemy import desc as _desc

            md = (
                db.query(MarketData)
                .filter(MarketData.symbol == sym)
                .order_by(_desc(MarketData.timestamp))
                .first()
            )
            current_price = float(md.price) if md and md.price else None

            # szukamy pozycji w DB (demo lub live)
            pos = (
                db.query(Position)
                .filter(Position.symbol == sym)
                .order_by(_desc(Position.opened_at))
                .first()
            )
            quantity = float(pos.quantity) if pos and pos.quantity else None
            if current_price and quantity:
                position_value = round(current_price * quantity, 2)
            elif pos and pos.current_price and quantity:
                position_value = round(float(pos.current_price) * quantity, 2)
            else:
                position_value = None

            progress_pct = None
            if position_value is not None and target_eur > 0:
                progress_pct = round(min(100.0, position_value / target_eur * 100), 1)

            items.append(
                {
                    "symbol": sym,
                    "quantity": quantity,
                    "current_price": current_price,
                    "position_value": position_value,
                    "target_eur": target_eur,
                    "progress_pct": progress_pct,
                    "reached": (
                        (position_value or 0) >= target_eur if target_eur > 0 else False
                    ),
                }
            )

        return {"success": True, "data": items}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting hold status: {str(exc)}"
        ) from exc


@router.get("/operator-queue")
def get_operator_queue_alias(db: Session = Depends(get_db)):
    """
    Alias kompatybilnosci: /api/control/operator-queue.
    Docelowy endpoint nadal pozostaje pod /api/account/analytics/operator-queue.
    """
    try:
        payload = get_operator_queue_with_summary(db)
        return {
            "success": True,
            "data": payload.get("items", []),
            "summary": payload.get("summary", {}),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting operator queue: {str(exc)}"
        ) from exc


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _REPO_ROOT / ".env"
_ENV_BACKUP_DIR = _REPO_ROOT / ".env_backups"
_ENV_EDITABLE_KEYS: Dict[str, Dict[str, Any]] = {
    "AI_PROVIDER": {
        "type": "str",
        "allowed": {
            "auto",
            "openai",
            "gemini",
            "groq",
            "ollama",
            "local",
            "heuristic",
            "offline",
        },
    },
    "PRIMARY_AI": {
        "type": "str",
        "allowed": {"auto", "openai", "gemini", "groq", "ollama", "local", "heuristic"},
    },
    "FALLBACK_AI": {
        "type": "str",
        "allowed": {"auto", "openai", "gemini", "groq", "ollama", "local", "heuristic"},
    },
    "AI_HYBRID_MODE": {"type": "bool"},
    "TRADING_MODE": {"type": "str", "allowed": {"demo", "live", "paper"}},
    "ALLOW_LIVE_TRADING": {"type": "bool"},
    "QUOTE_CURRENCY_MODE": {"type": "str", "allowed": {"eur", "usdc", "both"}},
    "PRIMARY_QUOTE": {"type": "str", "allowed": {"eur", "usdc"}},
    "ALLOW_AUTO_CONVERT_EUR_TO_USDC": {"type": "bool"},
    "MIN_EUR_RESERVE": {"type": "float", "min": 0.0, "max": 1000000.0},
    "MIN_USDC_RESERVE": {"type": "float", "min": 0.0, "max": 1000000.0},
    "MIN_CONVERSION_NOTIONAL": {"type": "float", "min": 1.0, "max": 1000000.0},
    "MIN_BUY_EUR": {"type": "float", "min": 1.0, "max": 1000000.0},
    "CONVERSION_COOLDOWN_MINUTES": {"type": "int", "min": 1, "max": 10080},
    "TARGET_USDC_BUFFER": {"type": "float", "min": 0.0, "max": 1000000.0},
    "MAX_CONVERSION_PER_HOUR": {"type": "int", "min": 1, "max": 100},
    "MAX_OPEN_POSITIONS": {"type": "int", "min": 1, "max": 30},
    "WS_ENABLED": {"type": "bool"},
    "APP_DOMAIN": {"type": "str"},
    "API_DOMAIN": {"type": "str"},
    "PUBLIC_DOMAIN": {"type": "str"},
    "CLOUDFLARE_TUNNEL_URL": {"type": "str"},
    "SAFE_MODE_CONFIG_OUTPUT": {"type": "bool"},
    "ADMIN_ONLY_COMMANDS": {"type": "bool"},
    "OPENAI_MODEL": {"type": "str"},
    "GEMINI_MODEL": {"type": "str"},
    "GROQ_MODEL": {"type": "str"},
    "OLLAMA_MODEL": {"type": "str"},
    "OPENAI_UNPAID": {"type": "bool"},
    "OPENAI_BILLING_AVAILABLE": {"type": "bool"},
    "OPENAI_API_KEY": {"type": "secret"},
    "GEMINI_API_KEY": {"type": "secret"},
    "GROQ_API_KEY": {"type": "secret"},
}
_SECRET_KEYWORDS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "AUTH",
    "CREDENTIAL",
)
_TERMINAL_ALLOWED = {
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "rg",
    "ps",
    "uptime",
    "df",
    "free",
    "whoami",
    "echo",
}


class EnvSetRequest(BaseModel):
    key: str
    value: str
    actor: Optional[str] = "telegram_or_web"


class CommandRequest(BaseModel):
    text: str
    source: str = "telegram"
    execute_mode: str = "advisory"  # advisory | execute
    force: bool = False


class TerminalExecRequest(BaseModel):
    command: str
    timeout_seconds: int = 6


def _mask_env_value(key: str, value: Optional[str]) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    key_up = key.upper()
    if any(tok in key_up for tok in _SECRET_KEYWORDS):
        safe_mode = (
            os.getenv("SAFE_MODE_CONFIG_OUTPUT", "true") or "true"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if safe_mode:
            return "[REDACTED]"
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:3]}...{value[-3:]}"
    return value


def _read_env_lines() -> List[str]:
    if not _ENV_PATH.exists():
        return []
    return _ENV_PATH.read_text(encoding="utf-8").splitlines()


def _parse_env(lines: List[str]) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _write_env(lines: List[str]) -> None:
    content = "\n".join(lines).rstrip() + "\n"
    _ENV_PATH.write_text(content, encoding="utf-8")


def _env_backup(actor: str) -> str:
    _ENV_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_id = utc_now_naive().strftime("%Y%m%d_%H%M%S")
    dst = _ENV_BACKUP_DIR / f"{backup_id}_{actor.replace(':', '_')}.env"
    if _ENV_PATH.exists():
        dst.write_text(_ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dst.write_text("", encoding="utf-8")
    return dst.name


def _validate_env_value(key: str, value: str) -> str:
    spec = _ENV_EDITABLE_KEYS.get(key)
    if spec is None:
        raise RuntimeSettingsError(
            f"Key {key} is not editable via API", status_code=403
        )

    typ = spec.get("type")
    normalized = value.strip()
    if typ == "bool":
        lower = normalized.lower()
        if lower not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise RuntimeSettingsError(f"Invalid bool value for {key}")
        return "true" if lower in {"true", "1", "yes", "on"} else "false"
    if typ == "int":
        try:
            iv = int(normalized)
        except Exception as exc:
            raise RuntimeSettingsError(f"Invalid integer value for {key}") from exc
        min_v = spec.get("min")
        max_v = spec.get("max")
        if min_v is not None and iv < min_v:
            raise RuntimeSettingsError(f"{key} must be >= {min_v}")
        if max_v is not None and iv > max_v:
            raise RuntimeSettingsError(f"{key} must be <= {max_v}")
        return str(iv)
    if typ == "str":
        allowed = spec.get("allowed")
        if allowed and normalized.lower() not in allowed:
            raise RuntimeSettingsError(f"Unsupported value for {key}: {normalized}")
        return normalized
    if typ == "secret":
        if not normalized:
            raise RuntimeSettingsError(f"{key} cannot be empty")
        return normalized
    return normalized


def _set_env_key(key: str, value: str) -> Dict[str, Any]:
    lines = _read_env_lines()
    found = False
    new_lines: List[str] = []
    for ln in lines:
        if ln.strip().startswith("#") or "=" not in ln:
            new_lines.append(ln)
            continue
        k, _ = ln.split("=", 1)
        if k.strip() == key:
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(ln)
    if not found:
        new_lines.append(f"{key}={value}")
    _write_env(new_lines)
    os.environ[key] = value
    return {"key": key, "value": value, "found": found}


def _get_env_diff_preview(max_items: int = 50) -> List[Dict[str, Any]]:
    file_env = _parse_env(_read_env_lines())
    diff: List[Dict[str, Any]] = []
    for key in sorted(_ENV_EDITABLE_KEYS.keys()):
        file_v = file_env.get(key)
        proc_v = os.getenv(key)
        if (file_v or "") != (proc_v or ""):
            diff.append(
                {
                    "key": key,
                    "file_value": _mask_env_value(key, file_v),
                    "process_value": _mask_env_value(key, proc_v),
                }
            )
        if len(diff) >= max_items:
            break
    return diff


_KNOWN_QUOTES = {"EUR", "USDC", "USDT", "USD"}
_SYSTEM_SLASH_COMMANDS = {
    "/logs",
    "/execution",
    "/quote",
    "/quote_status",
    "/trade",
    "/universe",
    "/universe_stats",
    "/ai",
    "/ai_budget",
    "/reconcile",
    "/help",
    "/menu",
    "/status",
}
_COMMAND_WORDS = {
    "KUP",
    "SPRZEDAJ",
    "WYMUS",
    "WYMU",
    "WYMUŚ",
    "ANALIZUJ",
    "USTAW",
    "TRYB",
    "AGRESYWNY",
    "OSTROZNY",
    "OSTROŻNY",
    "STATUS",
    "PORTFEL",
    "TERAZ",
    "CZY",
    "WARTO",
    "NAJSLABSZA",
    "NAJSLABSZA",
    "ZA",
    "NA",
    "I",
    "LOGS",
    "EXECUTION",
    "QUOTE",
    "TRADE",
    "UNIVERSE",
    "AI",
    "RECONCILE",
}


def _trade_context(text: str) -> bool:
    low = str(text or "").lower()
    return bool(
        re.search(r"\bkup\b|\bsprzedaj\b|\bzamknij\b|\banalizuj\b|\bquote\b", low)
    ) or low.startswith("/quote")


def _parse_symbol_from_text(text: str) -> Optional[str]:
    text = (text or "").replace("wymuś", "wymus").replace("Wymuś", "Wymus")
    if not text.strip():
        return None

    registry = get_symbol_registry()
    words = re.findall(r"\b[A-Za-z]{2,20}\b", text)

    for word in words:
        candidate = word.upper()
        if candidate in _COMMAND_WORDS:
            continue
        validation = validate_symbol(candidate, registry=registry)
        if validation.get("valid"):
            return candidate

    if not _trade_context(text):
        return None

    explicit_global_quote: Optional[str] = None
    match_quote = re.search(r"\bza\s+(EUR|USDC|USDT|USD)\b", text, re.IGNORECASE)
    if match_quote:
        explicit_global_quote = (
            "EUR" if match_quote.group(1).upper() == "EUR" else "USDC"
        )

    preferred_quotes: List[str] = []
    if explicit_global_quote:
        preferred_quotes.append(explicit_global_quote)
    primary_quote = os.getenv("PRIMARY_QUOTE", "USDC").strip().upper()
    if primary_quote and primary_quote not in preferred_quotes:
        preferred_quotes.append(primary_quote)
    for fallback_quote in ("USDC", "USDT", "EUR"):
        if fallback_quote not in preferred_quotes:
            preferred_quotes.append(fallback_quote)

    pair_match = re.search(
        r"\b([A-Za-z]{2,10})\s+(EUR|USDC|USDT|USD)\b", text, re.IGNORECASE
    )
    if pair_match:
        asset = pair_match.group(1).upper()
        if asset not in _COMMAND_WORDS:
            explicit_symbol = f"{asset}{'EUR' if pair_match.group(2).upper() == 'EUR' else 'USDC'}"
            validation = validate_symbol(explicit_symbol, registry=registry)
            if validation.get("valid"):
                return explicit_symbol

    for word in words:
        asset = word.upper()
        if asset in _COMMAND_WORDS or asset in _KNOWN_QUOTES:
            continue
        resolved = resolve_asset_symbol(
            asset, registry=registry, preferred_quotes=preferred_quotes
        )
        if resolved:
            return resolved
    return None


def _symbol_base(symbol: Optional[str]) -> str:
    sym = (symbol or "").upper()
    for q in ("USDC", "USDT", "USD", "EUR"):
        if sym.endswith(q) and len(sym) > len(q):
            return sym[: -len(q)]
    return sym


def _parse_command_intent(text: str, req_force: bool = False) -> Dict[str, Any]:
    low = (text or "").lower().strip()
    force = bool(req_force) or any(tok in low for tok in ("wymus", "wymuś", "force"))
    symbol = None

    result: Dict[str, Any] = {
        "type": "chat",
        "side": None,
        "symbol": symbol,
        "force": force,
        "config_key": None,
        "config_value": None,
        "action": "chat",
    }

    if not low:
        return result

    if low.startswith("/"):
        slash = low.split()[0]
        if slash in _SYSTEM_SLASH_COMMANDS:
            if slash == "/quote":
                result.update({"type": "query", "action": "quote_symbol"})
                result["symbol"] = _parse_symbol_from_text(text)
            elif slash == "/quote_status":
                result.update({"type": "query", "action": "quote_status"})
            elif slash == "/execution":
                result.update({"type": "query", "action": "execution_status"})
            elif slash == "/universe":
                result.update({"type": "query", "action": "universe_status"})
            elif slash == "/universe_stats":
                result.update({"type": "query", "action": "universe_stats"})
            elif slash == "/ai":
                result.update({"type": "query", "action": "ai_status"})
            elif slash == "/ai_budget":
                result.update({"type": "query", "action": "ai_budget"})
            elif slash == "/reconcile":
                result.update({"type": "query", "action": "reconcile_status"})
            elif slash == "/logs":
                result.update({"type": "query", "action": "logs_status"})
            else:
                result.update({"type": "query", "action": "status"})
            return result

    if low.startswith("status") or low in {"help", "pomoc", "menu"}:
        result.update({"type": "query", "action": "status"})
        return result

    if low.startswith("logs"):
        result.update({"type": "query", "action": "logs_status"})
        return result
    if low.startswith("execution"):
        result.update({"type": "query", "action": "execution_status"})
        return result
    if low.startswith("universe stats"):
        result.update({"type": "query", "action": "universe_stats"})
        return result
    if low.startswith("universe"):
        result.update({"type": "query", "action": "universe_status"})
        return result
    if low.startswith("ai budget"):
        result.update({"type": "query", "action": "ai_budget"})
        return result
    if low == "ai" or low.startswith("ai "):
        result.update({"type": "query", "action": "ai_status"})
        return result
    if low.startswith("reconcile"):
        result.update({"type": "query", "action": "reconcile_status"})
        return result
    if low.startswith("quote "):
        result.update({"type": "query", "action": "quote_symbol"})
        result["symbol"] = _parse_symbol_from_text(text)
        return result

    buy_intent = bool(re.search(r"\bkup\b", low))
    sell_intent = bool(re.search(r"\bsprzedaj\b|\bzamknij\b", low))

    # Priorytet 1: intencje tradingowe (BUY/SELL/FORCE)
    if buy_intent:
        result["symbol"] = _parse_symbol_from_text(text)
        result.update({"type": "trade", "side": "BUY", "action": "buy_symbol"})
        return result
    if sell_intent:
        result["symbol"] = _parse_symbol_from_text(text)
        action = (
            "sell_weakest"
            if "najsłabsz" in low or "najsłabsza" in low
            else "sell_symbol"
        )
        result.update({"type": "trade", "side": "SELL", "action": action})
        return result

    # Priorytet 2: komendy config/runtime
    if (
        "tryb agresywny" in low
        or low.startswith("ustaw agresywny")
        or low.startswith("agresywny tryb")
    ):
        result.update(
            {
                "type": "config",
                "action": "set_aggressive_mode",
                "config_key": "trading_aggressiveness",
                "config_value": "aggressive",
            }
        )
        return result

    if (
        low.startswith("ustaw ostrozny")
        or low.startswith("ustaw ostrożny")
        or "tryb ostrozny" in low
        or "tryb ostrożny" in low
    ):
        result.update(
            {
                "type": "config",
                "action": "set_cautious_mode",
                "config_key": "trading_aggressiveness",
                "config_value": "safe",
            }
        )
        return result

    if "max pozycji" in low and any(ch.isdigit() for ch in low):
        m = re.search(r"(\d+)", low)
        result.update(
            {
                "type": "config",
                "action": "set_max_positions",
                "config_key": "max_open_positions",
                "config_value": int(m.group(1)) if m else None,
            }
        )
        return result

    nl_quote_cmd = parse_nl_quote_command(text)
    if nl_quote_cmd:
        if nl_quote_cmd.get("action") == "set_quote_mode":
            result.update(
                {
                    "type": "config",
                    "action": "set_quote_mode",
                    "config_key": "quote_currency_mode",
                    "config_value": (nl_quote_cmd.get("mode") or "BOTH").upper(),
                }
            )
            return result
        if nl_quote_cmd.get("action") == "convert_eur_to_usdc":
            result.update(
                {
                    "type": "config",
                    "action": "convert_eur_to_usdc",
                    "config_key": "funding_conversion",
                    "config_value": "EUR_TO_USDC",
                }
            )
            return result

    if low.startswith("status"):
        result.update({"type": "control", "action": "status"})
        return result

    if low.startswith("analizuj") or "czy teraz warto" in low:
        result["symbol"] = _parse_symbol_from_text(text)
        result.update({"type": "trade", "side": "BUY", "action": "analyze_symbol"})
        return result

    if low.startswith("zamknij wszystkie"):
        result.update({"type": "control", "action": "close_all"})
        return result

    return result


def _calculate_buy_quantity(
    symbol: str,
    available_cash: float,
    config: dict,
    price: float = 0.0,
    db=None,
) -> tuple[float, str]:
    """
    Oblicza ilość do zakupu na podstawie dostępnej gotówki i konfiguracji.
    Zwraca (quantity, reason_note).
    """
    from backend.database import MarketData

    # Pobierz aktualną cenę jeśli nie podano
    if price <= 0 and db is not None:
        try:
            md = (
                db.query(MarketData)
                .filter(MarketData.symbol == symbol)
                .order_by(MarketData.timestamp.desc())
                .first()
            )
            price = float(md.price) if md else 0.0
        except Exception:
            price = 0.0

    if price <= 0:
        return 0.0, "brak_ceny"

    max_position_pct = float(config.get("max_position_pct_per_trade", 0.15))
    min_notional = float(config.get("min_order_notional", 25.0))
    min_buy_reference_eur = float(config.get("min_buy_eur", 60.0))
    quote_asset = "USDC" if str(symbol).upper().endswith("USDC") else "EUR"
    try:
        from backend.binance_client import get_binance_client as _gbc

        if quote_asset == "USDC":
            min_required_notional, _rq_meta = resolve_required_quote_usdc(
                min_buy_reference_eur,
                _gbc(),
                exchange_min_notional=min_notional,
            )
        else:
            eur_usdc_rate, _rate_src = resolve_eur_usdc_rate(_gbc())
            min_required_notional = max(min_buy_reference_eur, min_notional)
    except Exception:
        min_required_notional = max(
            float(config.get("min_buy_eur", 60.0)), min_notional
        )
    max_notional = float(config.get("max_order_notional_usdc", 500.0))

    # Użyj max_position_pct z dostępnej gotówki, ale nie więcej niż max_notional
    notional = min(available_cash * max_position_pct, max_notional)
    notional = max(notional, min_required_notional)

    if notional > available_cash:
        notional = available_cash

    if notional < min_required_notional:
        return 0.0, f"notional_za_niski_{notional:.2f}"

    qty = notional / price
    return round(qty, 8), f"notional={notional:.2f}_price={price:.6g}"


def _last_signal_for_symbol(db: Session, symbol: str) -> Optional[DecisionTrace]:
    return (
        db.query(DecisionTrace)
        .filter(DecisionTrace.symbol == symbol)
        .order_by(DecisionTrace.timestamp.desc())
        .first()
    )


def _build_ai_chat_context(db: Session, source: str = "telegram") -> str:
    """Buduje kontekst chatu AI z realnych danych collectora i sygnałów."""
    mode = (os.getenv("TRADING_MODE", "demo") or "demo").lower()
    ai_status = get_ai_orchestrator_status(force=False)
    primary = ai_status.get("primary") or "unknown"
    fallback_active = bool(ai_status.get("fallback_active"))

    market_rows = (
        db.query(MarketData).order_by(MarketData.timestamp.desc()).limit(300).all()
    )
    latest_by_symbol: Dict[str, MarketData] = {}
    for row in market_rows:
        sym = str(row.symbol or "").upper()
        if not sym or sym in latest_by_symbol:
            continue
        latest_by_symbol[sym] = row
        if len(latest_by_symbol) >= 12:
            break

    latest_market: List[Dict[str, Any]] = []
    recent_signals = db.query(Signal).order_by(Signal.timestamp.desc()).limit(120).all()
    latest_signal_by_symbol: Dict[str, Signal] = {}
    for sig in recent_signals:
        sym = str(sig.symbol or "").upper()
        if sym and sym not in latest_signal_by_symbol:
            latest_signal_by_symbol[sym] = sig

    for sym, row in latest_by_symbol.items():
        indicators = {}
        sig = latest_signal_by_symbol.get(sym)
        if sig is not None and sig.indicators:
            try:
                indicators = json.loads(str(sig.indicators))
            except Exception:
                indicators = {}

        ema20 = indicators.get("ema_20")
        ema50 = indicators.get("ema_50")
        trend = None
        if ema20 is not None and ema50 is not None:
            trend = "UP" if float(ema20) >= float(ema50) else "DOWN"
        latest_market.append(
            {
                "symbol": sym,
                "price": float(row.price or 0.0),
                "volume": float(row.volume or 0.0),
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "rsi": indicators.get("rsi_14"),
                "ema20": ema20,
                "ema50": ema50,
                "trend": trend,
            }
        )

    recent_signals = recent_signals[:60]
    best_by_symbol: Dict[str, Signal] = {}
    for sig in recent_signals:
        sym = str(sig.symbol or "").upper()
        if not sym:
            continue
        prev = best_by_symbol.get(sym)
        curr_conf = float(sig.confidence or 0.0)
        prev_conf = float(prev.confidence or 0.0) if prev is not None else -1.0
        if prev is None or curr_conf >= prev_conf:
            best_by_symbol[sym] = sig

    top_opportunities = sorted(
        [
            {
                "symbol": s.symbol,
                "signal_type": s.signal_type,
                "confidence": float(s.confidence or 0.0),
                "price": float(s.price or 0.0),
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            }
            for s in best_by_symbol.values()
        ],
        key=lambda x: x["confidence"],
        reverse=True,
    )[:8]

    payload = {
        "mode": mode,
        "source": source,
        "ai_primary": primary,
        "ai_fallback_active": fallback_active,
        "market_scan_snapshot": latest_market,
        "top_opportunities": top_opportunities,
    }
    return json.dumps(payload, ensure_ascii=False)


def _current_context_symbol(db: Session) -> Optional[str]:
    for model, order_field in (
        (PendingOrder, PendingOrder.created_at),
        (Position, Position.opened_at),
        (Signal, Signal.timestamp),
    ):
        row = (
            db.query(model)
            .order_by(order_field.desc())
            .first()
        )
        symbol = str(getattr(row, "symbol", "") or "").upper() if row else ""
        validation = validate_symbol(symbol)
        if validation.get("valid"):
            return symbol
    return None


def _manual_confirmation_enabled(config: Dict[str, Any], mode: str) -> bool:
    if bool(config.get("require_manual_confirmation")):
        return True
    if str(mode or "").lower() == "demo":
        return bool(config.get("demo_require_manual_confirm"))
    return False


def _pending_status_for_manual_action(config: Dict[str, Any], mode: str) -> str:
    if not bool(config.get("enable_auto_execute", True)):
        return "PENDING_CREATED"
    if _manual_confirmation_enabled(config, mode):
        return "PENDING_CREATED"
    return "PENDING_CONFIRMED"


def _command_brain(db: Session, req: CommandRequest) -> Dict[str, Any]:
    text = (req.text or "").strip()
    mode = (req.execute_mode or "advisory").lower()
    runtime_cfg = get_runtime_config(db)
    trading_mode_current = str(
        runtime_cfg.get("trading_mode") or os.getenv("TRADING_MODE", "demo")
    ).lower()

    parser_result = _parse_command_intent(text, req.force)
    req.force = bool(parser_result.get("force"))
    action = str(parser_result.get("action") or "chat")

    permission = "read_only"
    requires_confirmation = False
    symbol = parser_result.get("symbol")
    validated_symbol: Optional[Dict[str, Any]] = None
    low = text.lower()

    if action == "quote_symbol" and not symbol:
        symbol = _current_context_symbol(db)
    if action in {"buy_symbol", "sell_symbol", "analyze_symbol", "quote_symbol"}:
        validated_symbol = validate_symbol(symbol)
        if validated_symbol.get("valid"):
            symbol = validated_symbol.get("symbol")
        elif action != "quote_symbol" or symbol:
            symbol = None

    if action in {
        "buy_symbol",
        "sell_symbol",
        "sell_weakest",
        "set_cautious_mode",
        "set_aggressive_mode",
        "set_max_positions",
        "set_quote_mode",
        "convert_eur_to_usdc",
    }:
        permission = "confirm_required"
        requires_confirmation = _manual_confirmation_enabled(
            runtime_cfg, trading_mode_current
        )
    if action == "close_all":
        permission = "critical"
        requires_confirmation = True

    response_summary = ""
    decision = "odradzam"
    execution = "dry_run"
    execution_flow = "CHAT"
    created_pending_id = None
    buy_trace_data: dict = {}

    if action == "quote_symbol":
        if not symbol:
            decision = "nie_moge_wykonac"
            execution = "quote_invalid_symbol"
            response_summary = "Komenda /quote wymaga prawdziwego symbolu Binance albo aktywnego bieżącego symbolu."
        else:
            from backend.quote_service import get_validated_quote

            quote = get_validated_quote(symbol)
            if quote.get("success"):
                decision = "informacja"
                execution = "quote_ok"
                response_summary = (
                    f"Quote {symbol}: price={float(quote.get('price') or 0.0):.8g} "
                    f"bid={float(quote.get('bid') or 0.0):.8g} ask={float(quote.get('ask') or 0.0):.8g} "
                    f"source={quote.get('quote_source')}"
                )
            else:
                decision = "nie_moge_wykonac"
                execution = "quote_soft_fail"
                response_summary = f"Quote {symbol}: invalid symbol lub chwilowy brak danych ({quote.get('error')})."
    elif action == "quote_status":
        decision = "informacja"
        execution = "quote_status"
        response_summary = (
            f"Quote mode={runtime_cfg.get('quote_currency_mode')} "
            f"primary={runtime_cfg.get('primary_quote')} "
            f"allowed_quotes={','.join(runtime_cfg.get('allowed_quotes') or [])}"
        )
    elif action == "execution_status":
        decision = "informacja"
        execution = "execution_status"
        response_summary = (
            f"Execution mode={trading_mode_current} "
            f"enabled={bool(runtime_cfg.get('execution_enabled', True))} "
            f"auto_execute={bool(runtime_cfg.get('enable_auto_execute', True))} "
            f"manual_confirmation={bool(_manual_confirmation_enabled(runtime_cfg, trading_mode_current))}"
        )
    elif action == "universe_status":
        from backend.symbol_universe import get_symbol_universe_stats

        stats = get_symbol_universe_stats()
        decision = "informacja"
        execution = "universe_status"
        response_summary = (
            f"Universe full={stats.get('full_count')} tradable={stats.get('tradable_count')} "
            f"filtered={stats.get('filtered_count')} scanned={stats.get('active_scanned_count')}"
        )
    elif action == "universe_stats":
        from backend.symbol_universe import get_symbol_universe_stats

        stats = get_symbol_universe_stats()
        decision = "informacja"
        execution = "universe_stats"
        response_summary = (
            f"Universe stats: full={stats.get('full_count')}, tradable={stats.get('tradable_count')}, "
            f"filtered={stats.get('filtered_count')}, active_scanned={stats.get('active_scanned_count')}."
        )
    elif action == "ai_status":
        ai = get_ai_orchestrator_status(force=False)
        decision = "informacja"
        execution = "ai_status"
        response_summary = (
            f"AI primary={ai.get('primary')} local_only={bool(ai.get('local_only_mode'))} "
            f"fallback_active={bool(ai.get('fallback_active'))}"
        )
    elif action == "ai_budget":
        budget = get_ai_budget_status()
        decision = "informacja"
        execution = "ai_budget"
        parts = []
        for provider_name, item in (budget.get("providers") or {}).items():
            parts.append(
                f"{provider_name}:{item.get('used_today')}/{item.get('daily_limit')}"
                f"{'*' if item.get('fallback_active') else ''}"
            )
        response_summary = "AI budget " + " ".join(parts)
    elif action == "reconcile_status":
        from backend.portfolio_reconcile import get_reconcile_status

        info = get_reconcile_status(db)
        decision = "informacja"
        execution = "reconcile_status"
        response_summary = (
            f"Reconcile running={bool(info.get('currently_running'))} "
            f"manual_synced={int(info.get('total_manual_trades_synced') or 0)} "
            f"pending_manual={int(info.get('pending_manual_trades') or 0)}"
        )
    elif action == "logs_status":
        decision = "informacja"
        execution = "logs_status"
        response_summary = "Logs status dostępny bez external AI."

    if execution == "dry_run" and action in {"buy_symbol", "sell_symbol", "analyze_symbol"} and not symbol:
        decision = "nie_moge_wykonac"
        execution = "invalid_symbol"
        response_summary = "Nie rozpoznano prawdziwego symbolu Binance w aktywnym universe. Zwracam CHAT/READ_ONLY zamiast tworzyć fake symbol."
        permission = "read_only"
        requires_confirmation = False
    if execution == "dry_run" and action in {"buy_symbol", "analyze_symbol"} and symbol:
        last_signal = _last_signal_for_symbol(db, symbol)
        open_positions = (
            db.query(Position).filter(Position.exit_reason_code.is_(None)).all()
        )
        existing = next(
            (
                p
                for p in open_positions
                if p.symbol == symbol and float(p.quantity or 0.0) > 0
            ),
            None,
        )

        if action == "analyze_symbol":
            decision = (
                "doradzam"
                if last_signal
                and (
                    last_signal.reason_code
                    in {"all_gates_passed", "pending_confirmed_execution"}
                )
                else "neutral"
            )
            response_summary = f"Analiza {symbol}: ostatni reason_code={last_signal.reason_code if last_signal else 'brak'}"
        else:
            # — BUY action —
            # W trybie execute: uruchom buy_trace pipeline i odpowiedz konkretnie.
            # W trybie advisory: informuj bez tworzenia pending.
            if mode == "execute":
                _trading_mode = trading_mode_current
                if _trading_mode == "live" and is_test_symbol(symbol):
                    decision = "odrzucono"
                    execution = "rejected"
                    response_summary = f"Nie kupiono {symbol} — symbol testowy jest zablokowany w trybie LIVE."
                    buy_trace_data = {
                        "final_decision": "REJECT",
                        "final_reason_code": "live_test_symbol_blocked",
                        "final_reason_pl": "Symbol testowy zablokowany w LIVE",
                    }
                # Sprawdź czy pozycja już istnieje (i nie ma force)
                if (
                    buy_trace_data.get("final_reason_code")
                    == "live_test_symbol_blocked"
                ):
                    pass
                elif existing and not req.force:
                    decision = "odrzucono"
                    execution = "rejected"
                    response_summary = (
                        f"Nie kupiono {symbol} — pozycja już otwarta "
                        f"(wejście {float(existing.entry_price or 0):.6g}). "
                        f"Użyj 'kup {symbol.lower().replace('usdc','').replace('eur','')} wymuś' aby override."
                    )
                else:
                    # Sprawdź buy_trace pipeline jeśli NIE FORCE.
                    # Force omija filtry sygnałów i tworzy pending bezwarunkowo.
                    if not req.force:
                        try:
                            from backend.routers.signals import (
                                get_buy_trace as _get_buy_trace,
                            )

                            _trading_mode = trading_mode_current
                            _raw = (
                                _get_buy_trace(symbol, mode=_trading_mode, db=db) or {}
                            )
                            # get_buy_trace zwraca {"success": True, "data": result}
                            # — unwrappujemy żeby czytać final_decision bezpośrednio
                            buy_trace_data = (
                                _raw.get("data") or _raw
                                if isinstance(_raw, dict) and "data" in _raw
                                else _raw
                            )
                        except Exception as _bt_err:
                            buy_trace_data = {
                                "final_decision": "ERROR",
                                "final_reason_code": f"PIPELINE_EXCEPTION: {str(_bt_err)[:80]}",
                                "final_reason_pl": f"Błąd wewnętrzny pipeline: {str(_bt_err)[:120]}",
                            }

                    bt_decision = (
                        buy_trace_data.get("final_decision")
                        if not req.force
                        else "ALLOW"
                    )
                    bt_code = (
                        buy_trace_data.get("final_reason_code")
                        or "UNKNOWN_INTERNAL_ERROR"
                        if not req.force
                        else "force_override"
                    )
                    bt_pl = (
                        buy_trace_data.get("final_reason_pl") or bt_code
                        if not req.force
                        else "force override — filtry pominięte"
                    )
                    # Twarde zabezpieczenie: REJECT musi mieć powód
                    if bt_decision == "REJECT" and not buy_trace_data.get(
                        "final_reason_code"
                    ):
                        bt_code = "UNKNOWN_INTERNAL_ERROR"
                        bt_pl = "Brak powodu decyzji — błąd wewnętrzny pipeline"

                    if bt_decision == "ALLOW":
                        # Wszystkie filtry przeszły — pobierz ilość i utwórz CONFIRMED pending
                        from backend.runtime_settings import get_runtime_config as _grc

                        _cfg = _grc(db)
                        # Pobierz gotówkę (Live: Binance spot; Demo: AccountSnapshot)
                        available_cash = 0.0
                        try:
                            from concurrent.futures import ThreadPoolExecutor
                            from concurrent.futures import TimeoutError as _FTE

                            from backend.routers.portfolio import (
                                _build_live_spot_portfolio,
                            )

                            with ThreadPoolExecutor(max_workers=1) as _pool:
                                _fut = _pool.submit(_build_live_spot_portfolio, db)
                                try:
                                    _live = _fut.result(timeout=3.0)
                                    available_cash = float(
                                        _live.get("free_cash_eur", 0.0)
                                    )
                                except _FTE:
                                    available_cash = 0.0
                        except Exception:
                            from backend.database import AccountSnapshot

                            _snap = (
                                db.query(AccountSnapshot)
                                .filter(
                                    AccountSnapshot.mode
                                    == trading_mode_current
                                )
                                .order_by(AccountSnapshot.timestamp.desc())
                                .first()
                            )
                            available_cash = (
                                float(_snap.free_margin or 0.0) if _snap else 0.0
                            )

                        # Sprawdź czy user podał kwotę "kup pepe za 50"
                        explicit_notional: float = 0.0
                        m_notional = re.search(r"za\s+(\d+(?:[.,]\d+)?)", low)
                        if m_notional:
                            try:
                                explicit_notional = float(
                                    m_notional.group(1).replace(",", ".")
                                )
                            except Exception:
                                pass

                        if explicit_notional > 0:
                            # Pobierz cenę do obliczenia qty
                            from backend.database import MarketData as _MD

                            _md = (
                                db.query(_MD)
                                .filter(_MD.symbol == symbol)
                                .order_by(_MD.timestamp.desc())
                                .first()
                            )
                            _price = float(_md.price) if _md else 0.0
                            _min_notional_cfg = float(
                                _cfg.get("min_order_notional", 25.0)
                            )
                            _min_ref_eur = float(_cfg.get("min_buy_eur", 60.0))
                            _min_required = _min_notional_cfg
                            try:
                                if str(symbol).upper().endswith("USDC"):
                                    from backend.binance_client import (
                                        get_binance_client as _gbc,
                                    )

                                    _min_required, _rq_meta = (
                                        resolve_required_quote_usdc(
                                            _min_ref_eur,
                                            _gbc(),
                                            exchange_min_notional=_min_notional_cfg,
                                        )
                                    )
                                else:
                                    _min_required = max(_min_ref_eur, _min_notional_cfg)
                            except Exception:
                                _min_required = max(_min_ref_eur, _min_notional_cfg)
                            if explicit_notional < _min_required:
                                explicit_notional = _min_required
                            qty = (
                                round(explicit_notional / _price, 8)
                                if _price > 0
                                else 0.0
                            )
                            qty_note = f"explicit_notional={explicit_notional}"
                        else:
                            qty, qty_note = _calculate_buy_quantity(
                                symbol, available_cash, _cfg, db=db
                            )

                        if qty <= 0 and not req.force:
                            decision = "odrzucono"
                            execution = "rejected"
                            response_summary = (
                                f"Nie kupiono {symbol} — nie można obliczyć ilości "
                                f"({qty_note}). Gotówka: {available_cash:.2f}"
                            )
                        else:
                            if qty <= 0:
                                qty = 0.00000001
                                qty_note = f"{qty_note}|force_min_placeholder_qty"

                            existing_pending = (
                                db.query(PendingOrder)
                                .filter(
                                    PendingOrder.symbol == symbol,
                                    PendingOrder.side == "BUY",
                                    PendingOrder.mode
                                    == (
                                        os.getenv("TRADING_MODE", "demo") or "demo"
                                    ).lower(),
                                    PendingOrder.status.in_(_ACTIVE_PENDING_STATUSES),
                                )
                                .order_by(PendingOrder.created_at.desc())
                                .first()
                            )
                            if existing_pending is not None:
                                decision = "odrzucono"
                                execution = "rejected"
                                created_pending_id = int(existing_pending.id)
                                response_summary = (
                                    f"Nie kupiono {symbol} — istnieje już aktywne zlecenie "
                                    f"(PendingOrder #{existing_pending.id}, status={existing_pending.status})."
                                )
                            else:
                                pending_status = _pending_status_for_manual_action(
                                    runtime_cfg, trading_mode_current
                                )
                                pending_reason = (
                                    f"nl_execute:{text[:180]}|qty_calc:{qty_note}|"
                                    f"source=telegram|mode={trading_mode_current}"
                                )
                                pending = PendingOrder(
                                    symbol=symbol,
                                    side="BUY",
                                    order_type="MARKET",
                                    quantity=qty,
                                    mode=trading_mode_current,
                                    status=pending_status,
                                    reason=pending_reason,
                                    strategy_name="manual_telegram_trade",
                                    created_at=utc_now_naive(),
                                    confirmed_at=(
                                        utc_now_naive()
                                        if pending_status == "PENDING_CONFIRMED"
                                        else None
                                    ),
                                )
                                db.add(pending)
                                db.commit()
                                db.refresh(pending)
                                created_pending_id = int(pending.id)
                                decision = "przyjeto_do_realizacji"
                                execution = (
                                    "manual_pending_created"
                                    if pending_status == "PENDING_CREATED"
                                    else (
                                        "manual_force_pending_confirmed_queued"
                                        if req.force
                                        else "manual_pending_confirmed_queued"
                                    )
                                )
                                execution_flow = (
                                    "MANUAL_FORCE" if req.force else "MANUAL"
                                )
                                response_summary = (
                                    f"Zlecenie BUY {symbol} przyjęte do wykonania "
                                    f"(PendingOrder #{created_pending_id} status={pending_status}). "
                                    + (
                                        "Wymaga potwierdzenia /confirm."
                                        if pending_status == "PENDING_CREATED"
                                        else "Oczekiwanie na wysłanie na giełdę i fill."
                                    )
                                )
                    else:
                        # Filtry odrzuciły — jasna odpowiedź z reason_code
                        decision = "odrzucono"
                        execution = "rejected_by_pipeline"
                        response_summary = f"Nie kupiono {symbol} — {bt_code}: {bt_pl}"
            else:
                # Advisory mode
                if existing and not req.force:
                    decision = "odradzam"
                    response_summary = (
                        f"{symbol}: pozycja juz istnieje, zakup zablokowany bez force."
                    )
                else:
                    decision = "wymaga_potwierdzenia"
                    response_summary = f"{symbol}: tryb doradczy — użyj execute_mode=execute lub napisz w Telegramie 'kup {symbol}'."
    elif execution == "dry_run" and action == "sell_symbol" and symbol:
        open_positions = (
            db.query(Position).filter(Position.exit_reason_code.is_(None)).all()
        )
        base = _symbol_base(symbol)
        matching = [
            p
            for p in open_positions
            if _symbol_base(getattr(p, "symbol", "")) == base
            and float(getattr(p, "quantity", 0.0) or 0.0) > 0
        ]
        position = matching[0] if matching else None
        if position is None:
            decision = "nie_moge_wykonac"
            execution = "rejected"
            execution_flow = "MANUAL_FORCE" if req.force else "MANUAL"
            response_summary = f"Brak otwartej pozycji dla {base} do sprzedaży."
        elif mode == "execute":
            qty = float(position.quantity or 0.0)
            if qty <= 0:
                decision = "odrzucono"
                execution = "rejected"
                execution_flow = "MANUAL_FORCE" if req.force else "MANUAL"
                response_summary = (
                    f"Sprzedaż {position.symbol} odrzucona — qty={qty:.8f}."
                )
            else:
                existing_pending = (
                    db.query(PendingOrder)
                    .filter(
                        PendingOrder.symbol == str(position.symbol),
                        PendingOrder.side == "SELL",
                        PendingOrder.mode
                        == trading_mode_current,
                        PendingOrder.status.in_(_ACTIVE_PENDING_STATUSES),
                    )
                    .order_by(PendingOrder.created_at.desc())
                    .first()
                )
                if existing_pending is not None:
                    decision = "odrzucono"
                    execution = "rejected"
                    execution_flow = "MANUAL_FORCE" if req.force else "MANUAL"
                    created_pending_id = int(existing_pending.id)
                    response_summary = (
                        f"Sprzedaż {position.symbol} odrzucona — aktywne zlecenie już istnieje "
                        f"(PendingOrder #{existing_pending.id}, status={existing_pending.status})."
                    )
                else:
                    pending_status = _pending_status_for_manual_action(
                        runtime_cfg, trading_mode_current
                    )
                    pending = PendingOrder(
                        symbol=str(position.symbol),
                        side="SELL",
                        order_type="MARKET",
                        quantity=qty,
                        mode=trading_mode_current,
                        status=pending_status,
                        reason=(
                            f"nl_execute_sell:{text[:180]}|matched_position:{position.id}|"
                            f"source=telegram|mode={trading_mode_current}"
                        ),
                        strategy_name="manual_telegram_trade",
                        created_at=utc_now_naive(),
                        confirmed_at=(
                            utc_now_naive()
                            if pending_status == "PENDING_CONFIRMED"
                            else None
                        ),
                    )
                    db.add(pending)
                    db.commit()
                    db.refresh(pending)
                    created_pending_id = int(pending.id)
                    decision = "przyjeto_do_realizacji"
                    execution = (
                        "manual_pending_created"
                        if pending_status == "PENDING_CREATED"
                        else (
                            "manual_force_pending_confirmed_queued"
                            if req.force
                            else "manual_pending_confirmed_queued"
                        )
                    )
                    execution_flow = "MANUAL_FORCE" if req.force else "MANUAL"
                    response_summary = (
                        f"Zlecenie SELL {position.symbol} przyjęte do wykonania "
                        f"(PendingOrder #{created_pending_id} status={pending_status}). "
                        + (
                            "Wymaga potwierdzenia /confirm."
                            if pending_status == "PENDING_CREATED"
                            else "Oczekiwanie na wysłanie na giełdę i fill."
                        )
                    )
        else:
            decision = "wymaga_potwierdzenia"
            execution_flow = "MANUAL_FORCE" if req.force else "MANUAL"
            response_summary = f"{position.symbol}: tryb doradczy — użyj execute_mode=execute lub napisz 'sprzedaj {base.lower()}'."
    elif execution == "dry_run" and action == "sell_weakest":
        open_positions = (
            db.query(Position)
            .filter(Position.exit_reason_code.is_(None))
            .order_by(Position.unrealized_pnl.asc())
            .all()
        )
        weakest = open_positions[0] if open_positions else None
        if weakest is None:
            decision = "nie_moge_wykonac"
            response_summary = "Brak pozycji do zamkniecia."
        else:
            decision = "wymaga_potwierdzenia"
            response_summary = f"Najsłabsza pozycja: {weakest.symbol}, PnL={float(weakest.unrealized_pnl or 0.0):+.2f}."
            if mode == "execute":
                pending_status = _pending_status_for_manual_action(
                    runtime_cfg, trading_mode_current
                )
                pending = PendingOrder(
                    symbol=weakest.symbol,
                    side="SELL",
                    order_type="MARKET",
                    quantity=float(weakest.quantity or 0.0),
                    mode=trading_mode_current,
                    status=pending_status,
                    reason=f"nl_command:{text[:180]}|source=telegram|mode={trading_mode_current}",
                    strategy_name="manual_telegram_trade",
                    created_at=utc_now_naive(),
                    confirmed_at=(
                        utc_now_naive()
                        if pending_status == "PENDING_CONFIRMED"
                        else None
                    ),
                )
                db.add(pending)
                db.commit()
                db.refresh(pending)
                created_pending_id = int(pending.id)
                execution = (
                    "manual_pending_created"
                    if pending_status == "PENDING_CREATED"
                    else "manual_pending_confirmed_queued"
                )
                execution_flow = "MANUAL"
    elif action == "set_max_positions":
        m = re.search(r"(\d+)", low)
        if m:
            val = int(m.group(1))
            apply_runtime_updates(
                db,
                {"max_open_positions": val},
                actor=f"command_brain:{req.source}",
            )
            decision = "wykonano"
            execution = "runtime_updated"
            response_summary = f"Ustawiono max_open_positions={val}."
        else:
            decision = "nie_moge_wykonac"
            response_summary = "Nie rozpoznano wartosci max pozycji."
    elif action == "set_cautious_mode":
        apply_runtime_updates(
            db,
            {
                "trading_aggressiveness": "safe",
                "max_open_positions": 2,
                "demo_min_signal_confidence": 0.7,
            },
            actor=f"command_brain:{req.source}",
        )
        decision = "wykonano"
        execution = "runtime_updated"
        response_summary = "Wlaczono ostrozny tryb handlu."
    elif action == "set_aggressive_mode":
        apply_runtime_updates(
            db,
            {
                "trading_aggressiveness": "aggressive",
                "max_open_positions": 4,
                "demo_min_signal_confidence": 0.48,
                "demo_min_entry_score": 45.0,
            },
            actor=f"command_brain:{req.source}",
        )
        decision = "wykonano"
        execution = "runtime_updated"
        response_summary = (
            "Wlaczono tryb agresywny. Zachowane zabezpieczenia: min_notional, "
            "max_open_positions, risk gates i kill switch."
        )
    elif action == "status":
        ai = get_ai_orchestrator_status(force=False)
        decision = "informacja"
        response_summary = (
            f"Status: mode={trading_mode_current}, ai_primary={ai.get('primary')}, "
            f"fallback_active={ai.get('fallback_active')}, "
            f"local_only={bool(ai.get('local_only_mode'))}"
        )
    elif action == "set_quote_mode":
        mode_req = parser_result.get("config_value") or "BOTH"
        normalized = mode_req.strip().upper()
        if normalized not in {"EUR", "USDC", "BOTH"}:
            normalized = "BOTH"
        apply_runtime_updates(
            db,
            updates={"quote_currency_mode": normalized},
            actor=f"command_brain:{req.source}",
        )
        decision = "wykonano"
        execution = "runtime_updated"
        response_summary = f"Ustawiono QUOTE_CURRENCY_MODE={normalized}."
    elif action == "convert_eur_to_usdc":
        decision = "potwierdz"
        execution = "queued"
        response_summary = (
            "Polecenie konwersji EUR→USDC przyjęte. "
            "Konwersja wykona się gdy collector oceni funding_conversion_required."
        )
    else:
        # Natural conversation — generate real AI response via provider chain
        try:
            from backend.ai_orchestrator import generate_ai_chat_response

            context = _build_ai_chat_context(db, source=req.source or "telegram")
            ai_response, provider_used = generate_ai_chat_response(
                text, context_summary=context, task="chat", symbols=[symbol] if symbol else None
            )
            decision = "ai_chat"
            response_summary = ai_response
            execution = "chat_response"
            log_to_db(
                "INFO",
                "command_brain",
                f"[ai_chat] provider={provider_used} len={len(ai_response)} text_preview={text[:60]}",
                db=db,
            )
        except Exception as _chat_exc:
            ai_status = get_ai_orchestrator_status(force=False)
            decision = "ai_chat_error"
            response_summary = (
                f"Nie mogę odpowiedzieć teraz ({type(_chat_exc).__name__}: {str(_chat_exc)[:80]}). "
                f"AI primary={ai_status.get('primary')}. Spróbuj ponownie lub wpisz 'pomoc'."
            )
            execution = "chat_error"

    payload = {
        "text": text,
        "action": action,
        "decision": decision,
        "permission": permission,
        "requires_confirmation": requires_confirmation,
        "execute_mode": mode,
        "force": bool(req.force),
        "symbol": symbol,
        "validated_symbol": validated_symbol,
        "execution": execution,
        "execution_flow": execution_flow,
        "pending_order_id": created_pending_id,
        "summary": response_summary,
        "buy_trace": buy_trace_data or None,
        "parser": {
            "type": parser_result.get("type"),
            "side": parser_result.get("side"),
            "symbol": parser_result.get("symbol"),
            "force": parser_result.get("force"),
            "config_key": parser_result.get("config_key"),
            "config_value": parser_result.get("config_value"),
            "validated_symbol": validated_symbol,
        },
    }

    log_to_db(
        "INFO",
        "command_brain",
        f"parser_decision={payload.get('parser')} execution_path={execution_flow} command={payload}",
        db=db,
    )
    return payload


class CommandTraceRequest(BaseModel):
    text: str
    mode: str = "execute"


@router.post("/command-trace")
def command_trace(req: CommandTraceRequest, db: Session = Depends(get_db)):
    """
    Debuguje pipeline NL command bez tworzenia PendingOrder.
    Zwraca parse_trace, symbol resolution, buy_trace, env state.
    """
    import re as _re

    text = req.text.strip()
    parser_result = _parse_command_intent(text, req_force=False)

    # 1) Parse symbol
    parsed_symbol = _parse_symbol_from_text(text)

    # 2) Env state (z procesu + z pliku)
    file_env = _parse_env(_read_env_lines())
    quote_mode_proc = os.getenv("QUOTE_CURRENCY_MODE", "?")
    quote_mode_file = file_env.get("QUOTE_CURRENCY_MODE", "?")
    primary_quote_proc = os.getenv("PRIMARY_QUOTE", "?")
    primary_quote_file = file_env.get("PRIMARY_QUOTE", "?")
    trading_mode_proc = os.getenv("TRADING_MODE", "?")

    # 3) Asset resolution details
    from backend.quote_currency import get_supported_base_assets as _bases
    from backend.quote_currency import preferred_symbol_for_asset as _pref

    # Wyodrębnij asset część z parsed_symbol
    known_assets = set(_bases())
    base_asset = None
    if parsed_symbol:
        for q in ("USDC", "EUR", "USDT"):
            if parsed_symbol.endswith(q):
                base_asset = parsed_symbol[: -len(q)]
                break
    asset_in_map = base_asset in known_assets if base_asset else False
    preferred = (
        _pref(base_asset, quote_mode_proc, primary_quote_proc) if base_asset else None
    )

    # 4) Buy trace (fast, czytanie z DB bezpośrednio)
    buy_trace_data: dict = {}
    if parsed_symbol:
        try:
            from backend.routers.signals import get_buy_trace as _get_buy_trace

            _trading_mode = os.getenv("TRADING_MODE", "demo").lower()
            _raw = _get_buy_trace(parsed_symbol, mode=_trading_mode, db=db) or {}
            # get_buy_trace zwraca {"success": True, "data": result} — unwrappujemy
            buy_trace_data = (
                _raw.get("data") or _raw
                if isinstance(_raw, dict) and "data" in _raw
                else _raw
            )
        except Exception as e:
            buy_trace_data = {"error": str(e)[:80]}

    return {
        "success": True,
        "data": {
            "input_text": text,
            "parser": {
                "type": parser_result.get("type"),
                "side": parser_result.get("side"),
                "symbol": parser_result.get("symbol"),
                "force": parser_result.get("force"),
                "config_key": parser_result.get("config_key"),
                "config_value": parser_result.get("config_value"),
            },
            "parsed_symbol": parsed_symbol,
            "base_asset": base_asset,
            "asset_in_map": asset_in_map,
            "preferred_symbol": preferred,
            "env": {
                "QUOTE_CURRENCY_MODE_proc": quote_mode_proc,
                "QUOTE_CURRENCY_MODE_file": quote_mode_file,
                "PRIMARY_QUOTE_proc": primary_quote_proc,
                "PRIMARY_QUOTE_file": primary_quote_file,
                "TRADING_MODE_proc": trading_mode_proc,
            },
            "buy_trace": buy_trace_data,
            "final_decision": buy_trace_data.get("final_decision"),
            "final_reason_code": buy_trace_data.get("final_reason_code"),
        },
    }


@router.get("/env")
def get_env_config(admin: None = Depends(require_admin)):
    file_env = _parse_env(_read_env_lines())
    keys = sorted(_ENV_EDITABLE_KEYS.keys())
    data = []
    for k in keys:
        file_v = file_env.get(k)
        proc_v = os.getenv(k)
        data.append(
            {
                "key": k,
                "file_value": _mask_env_value(k, file_v),
                "process_value": _mask_env_value(k, proc_v),
                "in_file": file_v is not None,
                "editable": True,
            }
        )
    return {"success": True, "data": data}


@router.get("/env/get")
def get_env_key(key: str, admin: None = Depends(require_admin)):
    key = (key or "").strip()
    if key not in _ENV_EDITABLE_KEYS:
        raise HTTPException(status_code=403, detail="Key is not editable")
    file_env = _parse_env(_read_env_lines())
    return {
        "success": True,
        "data": {
            "key": key,
            "file_value": _mask_env_value(key, file_env.get(key)),
            "process_value": _mask_env_value(key, os.getenv(key)),
        },
    }


@router.post("/env/set")
def set_env_key(
    body: EnvSetRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    key = (body.key or "").strip()
    raw_value = (body.value or "").strip()
    if key not in _ENV_EDITABLE_KEYS:
        raise HTTPException(status_code=403, detail="Key is not editable")

    value = _validate_env_value(key, raw_value)
    backup = _env_backup(actor=(body.actor or "api"))
    result = _set_env_key(key, value)

    log_to_db(
        "INFO",
        "control_env",
        f"env_set key={key} actor={body.actor or 'api'} backup={backup}",
        db=db,
    )

    return {
        "success": True,
        "data": {
            "key": key,
            "value": _mask_env_value(key, value),
            "backup": backup,
            "updated": True,
            "existed": result.get("found", False),
        },
    }


@router.get("/env/diff")
def get_env_diff(admin: None = Depends(require_admin)):
    diff = _get_env_diff_preview()
    return {"success": True, "data": diff, "count": len(diff)}


@router.post("/env/backup")
def backup_env(
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    backup = _env_backup(actor="manual")
    log_to_db("INFO", "control_env", f"env_backup backup={backup}", db=db)
    return {"success": True, "data": {"backup": backup}}


@router.post("/env/rollback")
def rollback_env(
    backup: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    _ENV_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if backup:
        src = _ENV_BACKUP_DIR / backup
        if not src.exists():
            raise HTTPException(status_code=404, detail="Backup not found")
    else:
        backups = sorted(_ENV_BACKUP_DIR.glob("*.env"))
        if not backups:
            raise HTTPException(status_code=404, detail="No backups available")
        src = backups[-1]

    _ENV_PATH.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    for k, v in _parse_env(_read_env_lines()).items():
        os.environ[k] = v

    log_to_db("WARNING", "control_env", f"env_rollback backup={src.name}", db=db)
    return {"success": True, "data": {"restored_from": src.name}}


@router.post("/env/reload")
def reload_env(admin: None = Depends(require_admin)):
    file_env = _parse_env(_read_env_lines())
    for k, v in file_env.items():
        os.environ[k] = v
    return {"success": True, "data": {"reloaded_keys": len(file_env)}}


@router.post("/command/execute")
def execute_nl_command(
    body: CommandRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        data = _command_brain(db, body)
        return {"success": True, "data": data}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Command execution error: {str(exc)}"
        ) from exc


@router.post("/terminal/exec")
def exec_terminal_command(
    body: TerminalExecRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    command = (body.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")

    parts = shlex.split(command)
    if not parts:
        raise HTTPException(status_code=400, detail="Command is empty")

    base = parts[0]
    if base not in _TERMINAL_ALLOWED:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{base}' is not allowed in online terminal",
        )

    timeout = max(1, min(int(body.timeout_seconds or 6), 20))
    try:
        proc = subprocess.run(
            parts,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = (proc.stdout or "")[:12000]
        stderr = (proc.stderr or "")[:12000]
        log_to_db(
            "INFO",
            "online_terminal",
            f"terminal_exec base={base} exit_code={proc.returncode}",
            db=db,
        )
        return {
            "success": True,
            "data": {
                "command": command,
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "allowed": True,
                "timeout_seconds": timeout,
                "executed_at": utc_now_naive().isoformat(),
            },
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail=f"Command timeout after {timeout}s")


@router.get("/terminal/permissions")
def get_terminal_permissions(admin: None = Depends(require_admin)):
    return {
        "success": True,
        "data": {
            "allowed_commands": sorted(_TERMINAL_ALLOWED),
            "critical_commands_blocked": [
                "rm",
                "mv",
                "chmod",
                "chown",
                "git",
                "python",
                "bash",
                "sh",
            ],
        },
    }
