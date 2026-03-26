"""
Notification hooks — operacyjne powiadomienia o zdarzeniach governance i safety pipeline.

Adapter pattern:
  1. Hook function wywoływana z governance/policy → formatuje zdarzenie,
  2. Dispatcher wysyła do zarejestrowanych kanałów (Telegram, log).

Telegram jest adapterem, NIE źródłem prawdy.
Moduł NIE wykonuje technicznych akcji (rollback, promotion, apply).
NIE rusza accounting/risk/reporting.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

from backend.system_logger import log_to_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konfiguracja
# ---------------------------------------------------------------------------

def _get_config() -> Dict[str, Any]:
    """Lazy config — odczytuje ENV przy każdym wywołaniu (pozwala na zmianę w runtime)."""
    return {
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "enabled": os.getenv("NOTIFICATIONS_ENABLED", "true").lower() in ("1", "true", "yes"),
        "telegram_min_priority": os.getenv("TELEGRAM_MIN_PRIORITY", "high"),
    }


_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Zdarzenia
EVENT_INCIDENT_CREATED = "incident_created"
EVENT_INCIDENT_ESCALATED = "incident_escalated"
EVENT_POLICY_ACTION_CREATED = "policy_action_created"
EVENT_PIPELINE_BLOCKED = "pipeline_blocked"
EVENT_SLA_BREACH = "sla_breach"


# ---------------------------------------------------------------------------
# Mapowanie akcji → opis po polsku
# ---------------------------------------------------------------------------

_ACTION_LABELS: dict[str, str] = {
    "REQUIRE_MANUAL_REVIEW": "Wymagany ręczny przegląd",
    "ESCALATE_TO_OPERATOR": "Eskalacja do operatora",
    "PREPARE_ROLLBACK": "Przygotowanie cofnięcia zmian",
    "BLOCK_PIPELINE": "Blokada pipeline",
    "AUTO_FREEZE": "Automatyczne zamrożenie",
}

_SOURCE_LABELS: dict[str, str] = {
    "promotion_monitoring": "monitoring po wdrożeniu",
    "rollback_monitoring": "monitoring po cofnięciu",
    "post_promotion_monitoring": "monitoring po wdrożeniu",
    "post_rollback_monitoring": "monitoring po cofnięciu",
    "reevaluation_worker": "cykliczna rewaluacja",
    "trading_effectiveness": "diagnostyka skuteczności",
    "risk": "moduł ryzyka",
}

_REASON_LABELS: dict[str, str] = {
    "POST_PROMOTION_NET_PNL_DEGRADATION": "po wdrożeniu ustawień wynik netto się pogorszył",
    "POST_PROMOTION_RISK_PRESSURE_INCREASED": "po wdrożeniu wzrosło ciśnienie ryzyka",
    "POST_ROLLBACK_RISK_PRESSURE_PERSISTENT": "po cofnięciu zmian ryzyko nadal jest wysokie",
    "NET_PNL_NEGATIVE": "wynik netto jest ujemny",
    "COST_LEAKAGE_HIGH": "koszty transakcyjne są za wysokie",
    "OVERTRADING_DETECTED": "wykryto za dużo transakcji",
}

_PRIORITY_LABELS: dict[str, str] = {
    "critical": "krytyczna",
    "high": "wysoka",
    "medium": "średnia",
    "low": "niska",
}


def _human_source(source_type: str | None) -> str:
    return _SOURCE_LABELS.get(source_type or "", source_type or "nieznane")


def _human_action(action: str | None) -> str:
    return _ACTION_LABELS.get(action or "", action or "nieznana")


def _human_priority(prio: str | None) -> str:
    return _PRIORITY_LABELS.get(prio or "", prio or "?")


def _human_reasons(summary: str | None) -> str:
    if not summary:
        return ""
    for code, label in _REASON_LABELS.items():
        if code in (summary or ""):
            return label
    return summary or ""


# ---------------------------------------------------------------------------
# Formattery (czyste funkcje → str)
# ---------------------------------------------------------------------------

def format_incident_created(incident: Dict[str, Any], policy_action: Dict[str, Any] | None = None) -> str:
    """Formatuj powiadomienie o nowym incydencie."""
    priority = incident.get("priority", "medium")
    icon = "🔴" if priority == "critical" else "🟠" if priority == "high" else "🟡"
    prio_pl = _human_priority(priority)

    source_desc = ""
    reason_desc = ""
    if policy_action:
        source_desc = _human_source(policy_action.get("source_type"))
        reason_desc = _human_reasons(policy_action.get("summary"))

    lines = [f"{icon} Nowy incydent"]

    if reason_desc:
        lines.append(f"Co się stało: {reason_desc}")
    elif source_desc:
        lines.append(f"Źródło: {source_desc}")

    lines.append(f"Pilność: {prio_pl}")

    if policy_action:
        action_pl = _human_action(policy_action.get("policy_action"))
        lines.append(f"System: {action_pl}")

    if priority == "critical":
        lines.append("Co zrobić: natychmiast sprawdź sytuację")
    elif priority == "high":
        lines.append("Co zrobić: przejrzyj i podejmij decyzję")
    else:
        lines.append("Co zrobić: weź pod uwagę przy następnej kontroli")

    inc_id = incident.get("id", "?")
    pa_id = incident.get("policy_action_id", "?")
    lines.append(f"\nSzczegóły: incydent #{inc_id}, PA #{pa_id}")
    return "\n".join(lines)


def format_incident_escalated(incident: Dict[str, Any]) -> str:
    """Formatuj powiadomienie o eskalacji incydentu (SLA breach)."""
    inc_id = incident.get("id", "?")
    priority = incident.get("priority", "high")
    prio_pl = _human_priority(priority)
    return (
        f"⚠️ Eskalacja — incydent #{inc_id}\n"
        f"Termin (SLA) został przekroczony.\n"
        f"Pilność: {prio_pl}\n"
        f"Co zrobić: natychmiast sprawdź i zamknij ten incydent"
    )


def format_policy_action_created(policy_action: Dict[str, Any]) -> str:
    """Formatuj powiadomienie o nowej policy action."""
    priority = policy_action.get("priority", "medium")
    icon = "🔴" if priority == "critical" else "🟠" if priority == "high" else "🟡"
    prio_pl = _human_priority(priority)
    action_pl = _human_action(policy_action.get("policy_action"))
    source_pl = _human_source(policy_action.get("source_type"))
    reason_pl = _human_reasons(policy_action.get("summary"))

    lines = [f"{icon} {action_pl}"]

    if reason_pl:
        lines.append(f"Co się stało: {reason_pl}")
    else:
        lines.append(f"Źródło: {source_pl}")

    lines.append(f"Pilność: {prio_pl}")

    blocked_parts = []
    if not policy_action.get("promotion_allowed", True):
        blocked_parts.append("promocje")
    if not policy_action.get("experiments_allowed", True):
        blocked_parts.append("eksperymenty")
    if not policy_action.get("rollback_allowed", True):
        blocked_parts.append("rollback")
    if blocked_parts:
        lines.append(f"Zablokowano: {', '.join(blocked_parts)}")

    if policy_action.get("requires_human_review"):
        lines.append("Co zrobić: przejrzyj sytuację i potwierdź")
    elif priority in ("critical", "high"):
        lines.append("Co zrobić: sprawdź ostatnie zmiany konfiguracji")

    pa_id = policy_action.get("id", "?")
    source_id = policy_action.get("source_id", "?")
    lines.append(f"\nSzczegóły: PA #{pa_id}, źródło {policy_action.get('source_type', '?')}/{source_id}")
    return "\n".join(lines)


def format_pipeline_blocked(operation: str, blocking_actions: list) -> str:
    """Formatuj powiadomienie o zablokowanej operacji pipeline."""
    op_labels = {
        "promotion": "wdrożenia nowych ustawień",
        "experiment": "uruchomienia eksperymentu",
        "rollback": "cofnięcia zmian",
        "recommendation": "zastosowania rekomendacji",
    }
    op_pl = op_labels.get(operation, operation)
    count = len(blocking_actions)

    lines = [
        f"🔒 Nie można wykonać: {op_pl}",
        f"System zablokował tę operację, bo są aktywne alerty bezpieczeństwa ({count}).",
        "Co zrobić: najpierw zamknij lub przejrzyj aktywne alerty",
    ]
    for b in blocking_actions[:3]:
        pa_id = b.get("policy_action_id", "?")
        prio = _human_priority(b.get("priority"))
        lines.append(f"  • alert #{pa_id} (pilność: {prio})")
    if count > 3:
        lines.append(f"  … i {count - 3} więcej")
    return "\n".join(lines)


def format_sla_breach(escalated: List[Dict[str, Any]]) -> str:
    """Formatuj powiadomienie o naruszeniu SLA (batch)."""
    count = len(escalated)
    lines = [
        f"⏰ Przekroczony termin reakcji — {count} incydent(ów)",
        "Nie zareagowano w wymaganym czasie. Wymagana natychmiastowa uwaga.",
    ]
    for inc in escalated[:5]:
        inc_id = inc.get("id", "?")
        prio_pl = _human_priority(inc.get("priority"))
        lines.append(f"  • incydent #{inc_id} (pilność: {prio_pl})")
    if count > 5:
        lines.append(f"  … i {count - 5} więcej")
    lines.append("Co zrobić: przejrzyj i zamknij zaległe incydenty")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Low-level adaptery
# ---------------------------------------------------------------------------

def _should_send_telegram(priority: str) -> bool:
    """Sprawdź, czy priorytet zdarzenia kwalifikuje się do wysyłki Telegram."""
    cfg = _get_config()
    if not cfg["enabled"] or not cfg["telegram_bot_token"] or not cfg["telegram_chat_id"]:
        return False
    min_rank = _PRIORITY_RANK.get(cfg["telegram_min_priority"], 1)
    event_rank = _PRIORITY_RANK.get(priority, 3)
    return event_rank <= min_rank


def send_telegram_message(text: str) -> bool:
    """
    Wyślij wiadomość przez Telegram Bot API (HTTP POST).
    Zwraca True jeśli wysłano pomyślnie.
    """
    cfg = _get_config()
    token = cfg["telegram_bot_token"]
    chat_id = cfg["telegram_chat_id"]
    if not token or not chat_id:
        logger.debug("Telegram: brak konfiguracji (token/chat_id), pomijam wysyłkę")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram: wiadomość wysłana pomyślnie")
            return True
        else:
            logger.warning("Telegram: błąd wysyłki, status=%s, body=%s", resp.status_code, resp.text[:200])
            return False
    except requests.RequestException as exc:
        logger.error("Telegram: błąd połączenia: %s", exc)
        return False


def _log_notification(event_type: str, message: str) -> None:
    """Zapisz powiadomienie do system log (DB)."""
    try:
        log_to_db(
            level="INFO",
            module="notification_hooks",
            message=f"[{event_type}] {message[:500]}",
        )
    except Exception as exc:
        logger.error("Błąd logowania powiadomienia do DB: %s", exc)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def dispatch_notification(
    event_type: str,
    message: str,
    priority: str = "medium",
) -> Dict[str, Any]:
    """
    Wyślij powiadomienie do wszystkich skonfigurowanych kanałów.
    Zwraca status wysyłki per kanał.
    """
    result = {"event_type": event_type, "priority": priority, "channels": {}}

    # Zawsze loguj
    _log_notification(event_type, message)
    result["channels"]["log"] = True

    # Telegram — tylko jeśli priorytet spełnia próg
    if _should_send_telegram(priority):
        telegram_ok = send_telegram_message(message)
        result["channels"]["telegram"] = telegram_ok
    else:
        result["channels"]["telegram"] = None  # pominięto (priorytet poniżej progu)

    return result


# ---------------------------------------------------------------------------
# High-level hook functions
# ---------------------------------------------------------------------------

def notify_incident_created(
    incident: Dict[str, Any],
    policy_action: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Hook: nowy incydent utworzony."""
    message = format_incident_created(incident, policy_action)
    priority = incident.get("priority", "medium")
    return dispatch_notification(EVENT_INCIDENT_CREATED, message, priority)


def notify_incident_escalated(incident: Dict[str, Any]) -> Dict[str, Any]:
    """Hook: incydent eskalowany (SLA breach)."""
    message = format_incident_escalated(incident)
    priority = incident.get("priority", "high")
    return dispatch_notification(EVENT_INCIDENT_ESCALATED, message, priority)


def notify_policy_action_created(policy_action: Dict[str, Any]) -> Dict[str, Any]:
    """Hook: nowa policy action utworzona."""
    message = format_policy_action_created(policy_action)
    priority = policy_action.get("priority", "medium")
    return dispatch_notification(EVENT_POLICY_ACTION_CREATED, message, priority)


def notify_pipeline_blocked(operation: str, blocking_actions: list) -> Dict[str, Any]:
    """Hook: operacja pipeline zablokowana przez freeze."""
    message = format_pipeline_blocked(operation, blocking_actions)
    # Blokada jest zawsze ważna — używamy najwyższego priorytetu blokerów
    priorities = [b.get("priority", "medium") for b in blocking_actions]
    best = min(priorities, key=lambda p: _PRIORITY_RANK.get(p, 3)) if priorities else "medium"
    return dispatch_notification(EVENT_PIPELINE_BLOCKED, message, best)


def notify_sla_breach(escalated: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Hook: SLA breach — batch eskalacja incydentów."""
    if not escalated:
        return {"event_type": EVENT_SLA_BREACH, "skipped": True}
    message = format_sla_breach(escalated)
    return dispatch_notification(EVENT_SLA_BREACH, message, "high")
