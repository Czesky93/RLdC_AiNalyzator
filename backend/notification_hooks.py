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
# Formattery (czyste funkcje → str)
# ---------------------------------------------------------------------------

def format_incident_created(incident: Dict[str, Any], policy_action: Dict[str, Any] | None = None) -> str:
    """Formatuj powiadomienie o nowym incydencie."""
    priority = incident.get("priority", "?")
    inc_id = incident.get("id", "?")
    pa_id = incident.get("policy_action_id", "?")
    sla = incident.get("sla_deadline", "brak")

    icon = "🔴" if priority == "critical" else "🟠" if priority == "high" else "🟡"
    lines = [
        f"{icon} NOWY INCYDENT #{inc_id}",
        f"Priorytet: {priority}",
        f"Policy Action: #{pa_id}",
    ]
    if policy_action:
        lines.append(f"Akcja: {policy_action.get('policy_action', '?')}")
        lines.append(f"Źródło: {policy_action.get('source_type', '?')}/{policy_action.get('source_id', '?')}")
        lines.append(f"Opis: {policy_action.get('summary', '-')}")
    if sla and sla != "brak":
        lines.append(f"SLA deadline: {sla}")
    return "\n".join(lines)


def format_incident_escalated(incident: Dict[str, Any]) -> str:
    """Formatuj powiadomienie o eskalacji incydentu (SLA breach)."""
    inc_id = incident.get("id", "?")
    pa_id = incident.get("policy_action_id", "?")
    priority = incident.get("priority", "?")
    sla = incident.get("sla_deadline", "?")
    return (
        f"⚠️ ESKALACJA INCYDENTU #{inc_id}\n"
        f"Priorytet: {priority}\n"
        f"Policy Action: #{pa_id}\n"
        f"SLA deadline przekroczony: {sla}\n"
        f"Wymagana natychmiastowa reakcja operatora!"
    )


def format_policy_action_created(policy_action: Dict[str, Any]) -> str:
    """Formatuj powiadomienie o nowej policy action."""
    pa_id = policy_action.get("id", "?")
    action = policy_action.get("policy_action", "?")
    priority = policy_action.get("priority", "?")
    source = f"{policy_action.get('source_type', '?')}/{policy_action.get('source_id', '?')}"
    summary = policy_action.get("summary", "-")

    promo = "zablokowana" if not policy_action.get("promotion_allowed", True) else "dozwolona"
    rollback = "dozwolony" if policy_action.get("rollback_allowed", True) else "zablokowany"
    experiments = "dozwolone" if policy_action.get("experiments_allowed", True) else "zablokowane"

    icon = "🔴" if priority == "critical" else "🟠" if priority == "high" else "🟡"
    lines = [
        f"{icon} NOWA POLICY ACTION #{pa_id}",
        f"Akcja: {action}",
        f"Priorytet: {priority}",
        f"Źródło: {source}",
        f"Opis: {summary}",
        f"Promocja: {promo} | Rollback: {rollback} | Eksperymenty: {experiments}",
    ]
    if policy_action.get("requires_human_review"):
        lines.append("👤 Wymaga przeglądu operatora")
    return "\n".join(lines)


def format_pipeline_blocked(operation: str, blocking_actions: list) -> str:
    """Formatuj powiadomienie o zablokowanej operacji pipeline."""
    blockers_desc = ", ".join(
        f"PA#{b.get('policy_action_id', '?')} ({b.get('priority', '?')})"
        for b in blocking_actions[:5]
    )
    return (
        f"🚫 OPERACJA ZABLOKOWANA\n"
        f"Operacja: {operation}\n"
        f"Blokery: {blockers_desc}\n"
        f"Liczba blokad: {len(blocking_actions)}"
    )


def format_sla_breach(escalated: List[Dict[str, Any]]) -> str:
    """Formatuj powiadomienie o naruszeniu SLA (batch)."""
    lines = [f"⏰ NARUSZENIE SLA — {len(escalated)} incydent(ów) eskalowanych:"]
    for inc in escalated[:10]:
        inc_id = inc.get("id", "?")
        priority = inc.get("priority", "?")
        sla = inc.get("sla_deadline", "?")
        lines.append(f"  • Incydent #{inc_id} (priorytet: {priority}, SLA: {sla})")
    if len(escalated) > 10:
        lines.append(f"  … i {len(escalated) - 10} więcej")
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
