"""
Telegram Intelligence Layer — warstwa interpretacji i archiwizacji wiadomości Telegram.

Cel:
- Każda wiadomość Telegram (wysłana/odebrana) trafia do jednego miejsca (log_telegram_event).
- Parser klasyfikuje wiadomość i wyciąga strukturalne dane (symbol, side, confidence, itd.).
- build_telegram_intelligence_state() buduje aktualny "stan interpretacyjny" z DB.
- evaluate_goal() ocenia realność celu użytkownika (np. "chcę 300 EUR z tej pozycji").

Nie jest to zabawka — każda funkcja mierzy coś konkretnego wpływającego na zysk.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from backend.database import (
    SessionLocal,
    TelegramMessage,
    Signal,
    Order,
    Position,
    ExitQuality,
    utc_now_naive,
)
from backend.system_logger import log_exception

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kategorie wiadomości
# ---------------------------------------------------------------------------

CAT_SIGNAL = "SIGNAL_MESSAGE"
CAT_EXECUTION = "EXECUTION_MESSAGE"
CAT_BLOCKER = "BLOCKER_MESSAGE"
CAT_RISK = "RISK_MESSAGE"
CAT_STATUS = "SYSTEM_STATUS_MESSAGE"
CAT_OPERATOR = "OPERATOR_MESSAGE"
CAT_TARGET = "TARGET_MESSAGE"
CAT_UNKNOWN = "UNKNOWN"

# Kody blokerów (reason_code z collectora)
_BLOCKER_PATTERNS: list[tuple[str, str]] = [
    (r"cooldown", "cooldown_active"),
    (r"insufficient_cash|brak.*got|brak.*kapita", "insufficient_cash"),
    (r"hold_mode|tryb hold|no_new_entries", "hold_mode_no_new_entries"),
    (r"signal_filters|filters_not_met|za ni.ka pewno|za niskie rsi", "signal_filters_not_met"),
    (r"qty_below_min|za ma.a ilo", "qty_below_min"),
    (r"max_open_positions|za du.o pozycji", "max_open_positions"),
    (r"max_trades_per_day|dzienny limit", "max_trades_per_day"),
    (r"kill_switch|kill switch", "kill_switch"),
    (r"daily_loss_brake|hamulec strat|dzienna strata", "daily_loss_brake"),
    (r"cost_gate|koszty za wysokie", "cost_gate_failed"),
    (r"exposure_limit|za du.a ekspozycja", "exposure_limit"),
]

_RISK_PATTERNS: list[tuple[str, str]] = [
    (r"daily loss|drawdown exceeded|drawdown przekroczon", "daily_loss_brake"),
    (r"kill switch", "kill_switch"),
    (r"loss streak|seria strat", "loss_streak"),
    (r"ryzyko|risk.*wysok", "risk_high"),
]

_STATUS_PATTERNS: list[tuple[str, str]] = [
    (r"collector.*offline|kolektor.*zatrzyman", "collector_offline"),
    (r"websocket.*disconn|ws.*rozłączon", "ws_disconnected"),
    (r"openai.*invalid|openai.*error|klucz.*api.*niepraw", "openai_error"),
    (r"binance.*error|binance.*timeout|binance.*niedostępn", "binance_error"),
    (r"baza.*danych.*b..d|db.*error", "db_error"),
]

_EXECUTION_PATTERNS: list[tuple[str, str]] = [
    (r"filled|wykonan|zrealizowa", "order_filled"),
    (r"zamknięto pozycj|close.*position|pozycja.*zamknięt", "position_closed"),
    (r"tp.*hit|take profit.*osiągnięt|cel.*osiągnięt", "tp_hit"),
    (r"sl.*hit|stop loss.*aktyw|stop.*aktyw", "sl_hit"),
    (r"partial.*close|częściowe.*zamknięcie|50%", "partial_close"),
    (r"pending.*order|oczekuj.*zlecen|do potwierdzenia", "pending_order"),
]

_TARGET_PATTERNS: list[tuple[str, str]] = [
    (r"target|cel|docelowa", "target_set"),
    (r"sprzedaj.*przy|kup.*za\s+\d", "price_target"),
    (r"cel.*eur|\d+\s*eur.*cel", "eur_target"),
    (r"zysk.*osiągn|osiągnij.*zysk", "profit_target"),
]

_OPERATOR_CMDS = {"/confirm", "/reject", "/freeze", "/stop", "/start", "/status",
                  "/risk", "/portfolio", "/orders", "/positions", "/lastsignal",
                  "/blog", "/logs", "/report", "/governance", "/incidents",
                  "/top10", "/top5"}

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _extract_symbol(text: str) -> Optional[str]:
    m = re.search(r'\b([A-Z]{2,8}EUR|[A-Z]{2,8}USDT|[A-Z]{2,8}BTC)\b', text.upper())
    return m.group(1) if m else None


def _extract_side(text: str) -> Optional[str]:
    t = text.upper()
    if re.search(r'\bBUY\b|\bKUP\b|\bCUPIĆ\b|\bLONG\b|\bBUYING\b', t):
        return "BUY"
    if re.search(r'\bSELL\b|\bSPRZEDAJ\b|\bSHORT\b|\bSELLING\b|\bZAMKNIJ\b', t):
        return "SELL"
    if re.search(r'\bHOLD\b|\bTRZYMAJ\b|\bCZEKAJ\b', t):
        return "HOLD"
    return None


def _extract_confidence(text: str) -> Optional[float]:
    m = re.search(r'(\d{2,3})\s*%', text)
    if m:
        val = int(m.group(1))
        if 0 <= val <= 100:
            return val / 100.0
    m = re.search(r'confidence[:\s]+([0-9.]+)', text.lower())
    if m:
        val = float(m.group(1))
        return val if val <= 1.0 else val / 100.0
    return None


def _extract_eur_amount(text: str) -> Optional[float]:
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:eur|euro)', text.lower())
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _extract_price(text: str) -> Optional[float]:
    m = re.search(r'(?:cena|price|kurs)[:\s]+([0-9]+(?:[.,][0-9]+)?)', text.lower())
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def classify_message(text: str) -> dict:
    """
    Klasyfikuje tekst wiadomości Telegram.
    Zwraca słownik z kategorią, severity, parserem strukturalnym.
    """
    if not text:
        return {"category": CAT_UNKNOWN, "severity": "info", "parsed": {}}

    t_lower = text.lower()

    parsed: dict[str, Any] = {}
    symbol = _extract_symbol(text)
    side = _extract_side(text)
    confidence = _extract_confidence(text)
    eur_amount = _extract_eur_amount(text)
    price = _extract_price(text)
    if symbol:
        parsed["symbol"] = symbol
    if side:
        parsed["side"] = side
    if confidence is not None:
        parsed["confidence"] = confidence
    if eur_amount is not None:
        parsed["eur_amount"] = eur_amount
    if price is not None:
        parsed["price"] = price

    # Operator command
    for cmd in _OPERATOR_CMDS:
        if cmd in t_lower or t_lower.startswith(cmd[1:]):
            parsed["command"] = cmd
            return {"category": CAT_OPERATOR, "severity": "info", "parsed": parsed}

    # Risk (sprawdź przed blokerami — wyższy priorytet)
    for pattern, code in _RISK_PATTERNS:
        if re.search(pattern, t_lower):
            parsed["risk_code"] = code
            return {"category": CAT_RISK, "severity": "warning", "parsed": parsed}

    # Blockers
    for pattern, code in _BLOCKER_PATTERNS:
        if re.search(pattern, t_lower):
            parsed["block_code"] = code
            return {"category": CAT_BLOCKER, "severity": "info", "parsed": parsed}

    # Execution
    for pattern, code in _EXECUTION_PATTERNS:
        if re.search(pattern, t_lower):
            parsed["exec_code"] = code
            severity = "info"
            if "tp_hit" in code or "position_closed" in code:
                severity = "info"
            elif "sl_hit" in code:
                severity = "warning"
            return {"category": CAT_EXECUTION, "severity": severity, "parsed": parsed}

    # System status
    for pattern, code in _STATUS_PATTERNS:
        if re.search(pattern, t_lower):
            parsed["status_code"] = code
            return {"category": CAT_STATUS, "severity": "warning", "parsed": parsed}

    # Target
    for pattern, code in _TARGET_PATTERNS:
        if re.search(pattern, t_lower):
            parsed["target_code"] = code
            return {"category": CAT_TARGET, "severity": "info", "parsed": parsed}

    # Signal (po reszcie — najszerszy zakres)
    if side in ("BUY", "SELL") and symbol:
        return {"category": CAT_SIGNAL, "severity": "info", "parsed": parsed}
    if re.search(r'\bczekaj\b|\bwait\b|\bno (buy|sell)\b', t_lower):
        parsed["side"] = "WAIT"
        return {"category": CAT_SIGNAL, "severity": "info", "parsed": parsed}

    return {"category": CAT_UNKNOWN, "severity": "info", "parsed": parsed}


# ---------------------------------------------------------------------------
# log_telegram_event — jedyne miejsce zapisu wiadomości Telegram do DB
# ---------------------------------------------------------------------------

def log_telegram_event(
    *,
    chat_id: str = "system",
    direction: str = "outgoing",       # incoming | outgoing | internal
    raw_text: str,
    source_module: str = "unknown",    # collector | telegram_bot | risk | orders | control | ui
    message_type: str = "alert",       # command | alert | signal | execution | status | error | summary
    linked_order_id: Optional[int] = None,
    linked_position_id: Optional[int] = None,
    db=None,
) -> None:
    """
    Archiwizuje wiadomość Telegram z automatyczną klasyfikacją.
    Jeśli db=None, tworzy nową sesję i zamyka ją po zakończeniu.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        classification = classify_message(raw_text)
        cat = classification["category"]
        severity = classification["severity"]
        parsed = classification["parsed"]

        entry = TelegramMessage(
            chat_id=chat_id,
            message_type=message_type,
            command=parsed.get("command"),
            message=raw_text[:2000],
            is_sent=direction in ("outgoing", "internal"),
            direction=direction,
            msg_category=cat,
            severity=severity,
            source_module=source_module,
            parsed_symbol=parsed.get("symbol"),
            parsed_side=parsed.get("side"),
            parsed_confidence=parsed.get("confidence"),
            action_required=(cat in (CAT_OPERATOR, CAT_RISK) or severity == "warning"),
            parsed_payload_json=json.dumps(parsed, ensure_ascii=False),
            linked_order_id=linked_order_id,
            linked_position_id=linked_position_id,
            timestamp=utc_now_naive(),
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        log_exception("telegram_intelligence", "Błąd log_telegram_event", exc)
    finally:
        if own_session:
            db.close()


# ---------------------------------------------------------------------------
# build_telegram_intelligence_state — stan interpretacyjny z ostatnich wiadomości
# ---------------------------------------------------------------------------

def build_telegram_intelligence_state(db, mode: str = "demo") -> dict:
    """
    Buduje aktualny stan interpretacyjny systemu na podstawie ostatnich wiadomości Telegram.

    Zwraca słownik gotowy do serializacji JSON / wyświetlenia w UI.
    """
    now = utc_now_naive()
    window_15m = now - timedelta(minutes=15)
    window_30m = now - timedelta(minutes=30)
    window_2h = now - timedelta(hours=2)

    # Pobierz ostatnie wiadomości (max 200, z ostatnich 2h)
    recent_msgs = (
        db.query(TelegramMessage)
        .filter(TelegramMessage.timestamp >= window_2h)
        .order_by(TelegramMessage.timestamp.desc())
        .limit(200)
        .all()
    )

    # Segregacja
    signals = [m for m in recent_msgs if m.msg_category == CAT_SIGNAL]
    executions = [m for m in recent_msgs if m.msg_category == CAT_EXECUTION]
    blockers_15m = [m for m in recent_msgs if m.msg_category == CAT_BLOCKER and m.timestamp >= window_15m]
    risk_msgs = [m for m in recent_msgs if m.msg_category == CAT_RISK]
    status_msgs = [m for m in recent_msgs if m.msg_category == CAT_STATUS]
    operator_msgs = [m for m in recent_msgs if m.msg_category == CAT_OPERATOR]
    target_msgs = [m for m in recent_msgs if m.msg_category == CAT_TARGET]

    # Ostatni sygnał
    last_signal = None
    if signals:
        s = signals[0]
        p = _load_parsed(s)
        last_signal = {
            "symbol": s.parsed_symbol or p.get("symbol"),
            "side": s.parsed_side or p.get("side"),
            "confidence": s.parsed_confidence,
            "text": s.message[:120],
            "ts": s.timestamp.isoformat(),
            "age_minutes": round((now - s.timestamp).total_seconds() / 60, 1),
        }

    # Ostatnia egzekucja
    last_execution = None
    if executions:
        e = executions[0]
        p = _load_parsed(e)
        last_execution = {
            "symbol": e.parsed_symbol or p.get("symbol"),
            "side": e.parsed_side or p.get("side"),
            "exec_code": p.get("exec_code"),
            "text": e.message[:120],
            "ts": e.timestamp.isoformat(),
            "age_minutes": round((now - e.timestamp).total_seconds() / 60, 1),
        }

    # Blokery (15 min)
    blocker_summary = _summarize_blockers(blockers_15m)

    # System health
    system_health_flags = []
    for sm in status_msgs[:5]:
        p = _load_parsed(sm)
        system_health_flags.append({
            "code": p.get("status_code", "unknown"),
            "text": sm.message[:100],
            "ts": sm.timestamp.isoformat(),
        })

    # Operator intent
    operator_intent = {}
    if operator_msgs:
        op = operator_msgs[0]
        p = _load_parsed(op)
        operator_intent = {
            "command": p.get("command") or op.command,
            "ts": op.timestamp.isoformat(),
            "age_minutes": round((now - op.timestamp).total_seconds() / 60, 1),
        }

    # Portfolio targets
    portfolio_targets = []
    for tm in target_msgs[:5]:
        p = _load_parsed(tm)
        portfolio_targets.append({
            "symbol": tm.parsed_symbol or p.get("symbol"),
            "eur_amount": p.get("eur_amount"),
            "side": p.get("side"),
            "text": tm.message[:100],
            "ts": tm.timestamp.isoformat(),
        })

    # TP fills w ostatnich 30 minutach
    tp_fills_30m = sum(
        1 for m in executions
        if m.timestamp >= window_30m and _load_parsed(m).get("exec_code") == "tp_hit"
    )
    sl_hits_30m = sum(
        1 for m in executions
        if m.timestamp >= window_30m and _load_parsed(m).get("exec_code") == "sl_hit"
    )

    # Profit pressure
    profit_pressure = _compute_profit_pressure(db, mode)

    # Urgency score (0.0–1.0)
    urgency = 0.0
    if risk_msgs:
        urgency = min(1.0, urgency + 0.4)
    if system_health_flags:
        urgency = min(1.0, urgency + 0.3)
    if len(blockers_15m) >= 3:
        urgency = min(1.0, urgency + 0.2)
    if tp_fills_30m >= 2:
        urgency = min(1.0, urgency + 0.1)

    # Decision bias
    decision_bias = _compute_decision_bias(
        blockers_15m=blockers_15m,
        risk_msgs=risk_msgs,
        status_msgs=status_msgs,
        tp_fills_30m=tp_fills_30m,
        sl_hits_30m=sl_hits_30m,
        last_signal=last_signal,
        operator_msgs=operator_msgs,
    )

    # Główny problem i główna okazja
    main_problem = _detect_main_problem(blockers_15m, risk_msgs, status_msgs)
    main_opportunity = _detect_main_opportunity(last_signal, profit_pressure)

    return {
        "mode": mode,
        "generated_at": now.isoformat(),
        "last_signal": last_signal,
        "last_execution": last_execution,
        "last_blockers": blocker_summary,
        "system_health_flags": system_health_flags,
        "operator_intent": operator_intent,
        "portfolio_targets": portfolio_targets,
        "profit_pressure": profit_pressure,
        "urgency_score": round(urgency, 2),
        "decision_bias": decision_bias["bias"],
        "decision_bias_reason": decision_bias["reason"],
        "main_problem": main_problem,
        "main_opportunity": main_opportunity,
        "stats": {
            "signals_2h": len(signals),
            "blockers_15m": len(blockers_15m),
            "tp_fills_30m": tp_fills_30m,
            "sl_hits_30m": sl_hits_30m,
            "operator_actions_2h": len(operator_msgs),
        },
    }


def _load_parsed(msg: TelegramMessage) -> dict:
    if not msg.parsed_payload_json:
        return {}
    try:
        return json.loads(msg.parsed_payload_json)
    except Exception:
        return {}


def _summarize_blockers(blockers: list) -> list[dict]:
    """Zlicza i grupuje blokery."""
    counts: dict[str, int] = {}
    for m in blockers:
        p = _load_parsed(m)
        code = p.get("block_code", "unknown")
        counts[code] = counts.get(code, 0) + 1

    _BLOCKER_LABELS = {
        "cooldown_active": "Cooldown — za szybko po poprzednim zleceniu",
        "insufficient_cash": "Brak wolnej gotówki",
        "hold_mode_no_new_entries": "Symbol w trybie HOLD — brak nowych wejść",
        "signal_filters_not_met": "Filtry sygnałowe nie spełnione (RSI/EMA/confidence)",
        "qty_below_min": "Za mała ilość do zlecenia",
        "max_open_positions": "Zbyt dużo otwartych pozycji",
        "max_trades_per_day": "Dzienny limit transakcji wyczerpany",
        "kill_switch": "Kill switch aktywny",
        "daily_loss_brake": "Hamulec strat — dzienny limit przekroczony",
        "cost_gate_failed": "Bramka kosztów — koszty za wysokie vs oczekiwany zysk",
        "exposure_limit": "Limit ekspozycji na symbol/portfel przekroczony",
    }
    result = []
    for code, count in sorted(counts.items(), key=lambda x: -x[1]):
        result.append({
            "code": code,
            "count": count,
            "label": _BLOCKER_LABELS.get(code, code),
        })
    return result


def _compute_profit_pressure(db, mode: str) -> dict:
    """Oblicza presję zysku: czy bot aktywnie zarabia, czy stoi w miejscu."""
    now = utc_now_naive()
    window_24h = now - timedelta(hours=24)

    orders_24h = (
        db.query(Order)
        .filter(Order.mode == mode, Order.timestamp >= window_24h, Order.status == "FILLED")
        .all()
    )

    total_pnl = sum((o.net_pnl or 0.0) for o in orders_24h)
    profitable = sum(1 for o in orders_24h if (o.net_pnl or 0.0) > 0)
    lossy = sum(1 for o in orders_24h if (o.net_pnl or 0.0) < 0)
    open_pos = db.query(Position).filter(Position.mode == mode).count()
    unrealized = sum(
        (p.unrealized_pnl or 0.0)
        for p in db.query(Position).filter(Position.mode == mode).all()
    )

    status = "brak_aktywnosci"
    if len(orders_24h) > 0:
        if total_pnl > 0:
            status = "zarabia"
        elif total_pnl < 0:
            status = "traci"
        else:
            status = "neutralny"
    elif open_pos > 0:
        status = "otwarte_pozycje_bez_transakcji"

    return {
        "status": status,
        "orders_24h": len(orders_24h),
        "net_pnl_24h": round(total_pnl, 4),
        "profitable_orders": profitable,
        "lossy_orders": lossy,
        "open_positions": open_pos,
        "unrealized_pnl": round(unrealized, 4),
    }


def _compute_decision_bias(
    *,
    blockers_15m: list,
    risk_msgs: list,
    status_msgs: list,
    tp_fills_30m: int,
    sl_hits_30m: int,
    last_signal: Optional[dict],
    operator_msgs: list,
) -> dict:
    """Wyznacza kierunek decyzji na podstawie ostatnich sygnałów."""

    # Hard stops
    if status_msgs:
        codes = {_load_parsed(m).get("status_code") for m in status_msgs}
        if "collector_offline" in codes:
            return {"bias": "NO_TRADING_ALLOWED", "reason": "Kolektor offline — brak sygnałów i danych"}
        if "binance_error" in codes:
            return {"bias": "WAIT_BIAS", "reason": "Błąd Binance — zweryfikuj połączenie"}

    if risk_msgs:
        codes = {_load_parsed(m).get("risk_code") for m in risk_msgs}
        if "kill_switch" in codes:
            return {"bias": "NO_TRADING_ALLOWED", "reason": "Kill switch aktywny"}
        if "daily_loss_brake" in codes:
            return {"bias": "NO_TRADING_ALLOWED", "reason": "Dzienny limit strat osiągnięty"}
        return {"bias": "WAIT_BIAS", "reason": "Aktywne zdarzenie ryzyka — ostrożność"}

    # Operatorska nadpisanie
    if operator_msgs:
        op = operator_msgs[0]
        p = _load_parsed(op)
        cmd = p.get("command", "")
        if cmd in ("/freeze",):
            return {"bias": "WAIT_BIAS", "reason": "Operator uruchomił freeze"}
        if cmd in ("/stop",):
            return {"bias": "NO_TRADING_ALLOWED", "reason": "Operator zatrzymał trading (/stop)"}

    # Blokery operacyjne
    if len(blockers_15m) >= 4:
        codes = [_load_parsed(m).get("block_code") for m in blockers_15m]
        if codes.count("insufficient_cash") >= 2:
            return {"bias": "WAIT_BIAS", "reason": "Brak wolnej gotówki — nie można kupić"}
        return {"bias": "WAIT_BIAS", "reason": f"Wiele blokerów w ciągu 15 min ({len(blockers_15m)})"}

    # Po realizacji zysku
    if tp_fills_30m >= 2:
        return {"bias": "NEUTRAL", "reason": f"Bot realizował zyski ({tp_fills_30m} TP w ostatnich 30 min)"}

    # Na podstawie ostatniego sygnału
    if last_signal:
        age = last_signal.get("age_minutes", 999)
        if age <= 30:
            side = last_signal.get("side")
            conf = last_signal.get("confidence") or 0.0
            if side == "BUY" and conf >= 0.75:
                return {"bias": "BUY_BIAS", "reason": f"Sygnał BUY {last_signal.get('symbol')} pewność {int(conf*100)}%"}
            if side == "SELL" and conf >= 0.75:
                return {"bias": "SELL_BIAS", "reason": f"Sygnał SELL {last_signal.get('symbol')} pewność {int(conf*100)}%"}

    return {"bias": "NEUTRAL", "reason": "Brak wyraźnego sygnału — neutralny stan systemu"}


def _detect_main_problem(blockers_15m: list, risk_msgs: list, status_msgs: list) -> Optional[str]:
    if status_msgs:
        p = _load_parsed(status_msgs[0])
        code = p.get("status_code", "")
        _labels = {
            "collector_offline": "Kolektor offline — brak nowych sygnałów",
            "ws_disconnected": "WebSocket rozłączony — dane cenowe mogą być nieaktualne",
            "openai_error": "Błąd klucza OpenAI — bez zakresów AI, fallback na heurystykę",
            "binance_error": "Problem z Binance API — handel może być utrudniony",
            "db_error": "Błąd bazy danych",
        }
        return _labels.get(code, f"Problem systemowy: {code}")
    if risk_msgs:
        p = _load_parsed(risk_msgs[0])
        code = p.get("risk_code", "")
        _labels = {
            "kill_switch": "Kill switch aktywny — handel całkowicie zablokowany",
            "daily_loss_brake": "Hamulec strat aktywny — przekroczono dzienny limit",
            "loss_streak": "Seria strat — system ogranicza nowe wejścia",
        }
        return _labels.get(code, f"Aktywne ryzyko: {code}")
    if blockers_15m:
        b = _summarize_blockers(blockers_15m)
        if b:
            return f"{b[0]['label']} ({b[0]['count']}× w 15 min)"
    return None


def _detect_main_opportunity(last_signal: Optional[dict], profit_pressure: dict) -> Optional[str]:
    if last_signal:
        side = last_signal.get("side")
        sym = last_signal.get("symbol")
        conf = last_signal.get("confidence")
        age = last_signal.get("age_minutes", 999)
        if side in ("BUY", "SELL") and conf and conf >= 0.7 and age <= 60:
            return (
                f"Sygnał {side} dla {sym} z pewnością {int(conf*100)}% "
                f"(wygenerowany {int(age)} min temu)"
            )
    unreal = profit_pressure.get("unrealized_pnl", 0)
    if unreal > 5:
        return f"Otwarte pozycje z potencjalnym zyskiem {unreal:.2f} EUR — sprawdź czy zamknąć"
    return None


# ---------------------------------------------------------------------------
# evaluate_goal — ocena realności celu użytkownika
# ---------------------------------------------------------------------------

_REALISM_LABELS = {
    "bardzo_realny": "Cel realistyczny i bliski — prawdopodobnie osiągalny dziś lub jutro",
    "realny": "Cel realistyczny — możliwy w ciągu kilku dni przy sprzyjającym rynku",
    "możliwy": "Cel możliwy, ale wymaga korzystnego ruchu rynku",
    "trudny": "Cel trudny — wymaga silnego trendu lub dłuższego horyzontu",
    "mało_realny": "Cel mało realny w krótkim terminie — rozważ redukcję oczekiwań",
}

_REALISM_THRESHOLDS = [
    (0.02, "bardzo_realny"),
    (0.05, "realny"),
    (0.10, "możliwy"),
    (0.20, "trudny"),
    (float("inf"), "mało_realny"),
]


def evaluate_goal(
    *,
    target_type: str = "position_value",
    current_value: float,
    target_value: float,
    symbol: Optional[str] = None,
    entry_price: Optional[float] = None,
    quantity: Optional[float] = None,
    atr: Optional[float] = None,
    daily_volatility_pct: Optional[float] = None,
    db=None,
) -> dict:
    """
    Ocenia realność celu użytkownika.

    target_type:
      - "position_value"  → current_value = aktualna wartość pozycji EUR, target_value = cel EUR
      - "portfolio_value" → current_value = equity, target_value = docelowy equity
      - "profit_pct"      → current_value = aktualne PnL%, target_value = docelowe PnL%
      - "price_target"    → current_value = aktualna cena, target_value = docelowa cena

    Zwraca:
      target_type, current_value, target_value,
      required_move_pct, required_price,
      realism (label), confidence,
      time_horizon_estimate (1h/4h/24h/7d),
      explanation_pl
    """
    if target_value <= 0 or current_value <= 0:
        return _goal_error("Wartości muszą być większe od 0")

    missing = target_value - current_value
    required_move_pct = abs(missing / current_value) if current_value != 0 else 0.0

    # Wyestymuj dzienny ruch rynku (jeśli brak danych — użyj konserwatywnych założeń)
    if daily_volatility_pct is None:
        # Domyślne założenia per typ aktywa
        if symbol:
            s = symbol.upper()
            if "BTC" in s:
                daily_volatility_pct = 3.0
            elif "ETH" in s:
                daily_volatility_pct = 4.0
            elif "SOL" in s or "BNB" in s:
                daily_volatility_pct = 5.0
            elif "WLFI" in s:
                daily_volatility_pct = 8.0
            else:
                daily_volatility_pct = 4.0
        else:
            daily_volatility_pct = 4.0

    # Zakres ruchów w różnych horyzontach
    hourly_vol = daily_volatility_pct / 24  # upraszczamy linearnie
    moves = {
        "1h": hourly_vol,
        "4h": hourly_vol * 2.5,
        "24h": daily_volatility_pct,
        "7d": daily_volatility_pct * 3.5,  # konsolidacja, nie liniowe
    }

    # Szacowane prawdopodobieństwo realizacji celu w danym oknie (uproszczona heurystyka)
    time_horizon: dict[str, str] = {}
    for window, max_move in moves.items():
        pct_achievable = min(100, int(max_move / max(required_move_pct, 0.001) * 50))
        if pct_achievable >= 80:
            label = f"bardzo prawdopodobne (~{pct_achievable}%)"
        elif pct_achievable >= 50:
            label = f"prawdopodobne (~{pct_achievable}%)"
        elif pct_achievable >= 25:
            label = f"możliwe (~{pct_achievable}%)"
        else:
            label = f"mało prawdopodobne (~{pct_achievable}%)"
        time_horizon[window] = label

    # Realism label
    realism = "mało_realny"
    for threshold, label in _REALISM_THRESHOLDS:
        if required_move_pct <= threshold:
            realism = label
            break

    # Confidence
    if required_move_pct <= 0.01:
        confidence = 0.92
    elif required_move_pct <= 0.03:
        confidence = 0.78
    elif required_move_pct <= 0.07:
        confidence = 0.58
    elif required_move_pct <= 0.15:
        confidence = 0.38
    else:
        confidence = 0.18

    # Wymagana cena (tylko gdy dotyczy pozycji z ilością)
    required_price = None
    if entry_price and quantity and quantity > 0 and target_type == "position_value":
        required_price = round(target_value / quantity, 6)

    # Wylicz brakujący % z ATR
    atr_note = ""
    if atr and entry_price:
        daily_atr_pct = (atr / entry_price) * 100
        atr_note = f" ATR dzienny ≈ {daily_atr_pct:.2f}% ceny."

    # Opis słowny
    direction = "wzrostu" if missing > 0 else "spadku"
    explanation = (
        f"Cel: {target_value:.2f} EUR, aktualnie {current_value:.2f} EUR "
        f"(brakuje {abs(missing):.2f} EUR = {required_move_pct*100:.2f}% ruchu {direction}).{atr_note} "
        f"Ocena: {_REALISM_LABELS.get(realism, realism)}"
    )
    if required_price:
        explanation += f" Wymagana cena aktywa: {required_price:.4f} EUR."

    return {
        "target_type": target_type,
        "current_value": round(current_value, 4),
        "target_value": round(target_value, 4),
        "missing_value": round(missing, 4),
        "required_move_pct": round(required_move_pct * 100, 4),
        "required_price": required_price,
        "realism": realism,
        "confidence": round(confidence, 3),
        "time_horizon_estimate": time_horizon,
        "explanation_pl": explanation,
    }


def _goal_error(msg: str) -> dict:
    return {
        "target_type": "error",
        "current_value": 0,
        "target_value": 0,
        "missing_value": 0,
        "required_move_pct": 0,
        "required_price": None,
        "realism": "błąd",
        "confidence": 0,
        "time_horizon_estimate": {},
        "explanation_pl": msg,
    }


# ---------------------------------------------------------------------------
# get_messages_page — stronicowanie wiadomości do UI
# ---------------------------------------------------------------------------

def get_messages_page(
    db,
    limit: int = 50,
    category: Optional[str] = None,
    since_minutes: int = 120,
) -> list[dict]:
    """Zwraca ostatnie wiadomości Telegram jako listę słowników."""
    now = utc_now_naive()
    since = now - timedelta(minutes=since_minutes)

    q = db.query(TelegramMessage).filter(TelegramMessage.timestamp >= since)
    if category:
        q = q.filter(TelegramMessage.msg_category == category)
    msgs = q.order_by(TelegramMessage.timestamp.desc()).limit(limit).all()

    result = []
    for m in msgs:
        result.append({
            "id": m.id,
            "ts": m.timestamp.isoformat(),
            "direction": m.direction or "outgoing",
            "category": m.msg_category or CAT_UNKNOWN,
            "severity": m.severity or "info",
            "source_module": m.source_module or "unknown",
            "symbol": m.parsed_symbol,
            "side": m.parsed_side,
            "confidence": m.parsed_confidence,
            "text": m.message[:200],
            "action_required": bool(m.action_required),
        })
    return result
