"""
Telegram Message Formatter — profesjonalny, czytelny formatter dla wiadomości Telegram.

Zawiera:
- TelegramMessage: klasa do budowania sformatowanych wiadomości
- formattery dla: status, alert, decision, sync, risk
- throttling dla powtarzalnych alertów
- metody do agregacji i podsumowania
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional


class MessageType(str, Enum):
    STATUS = "status"  # Status cyklu / rynku
    ALERT = "alert"  # Alert operacyjny
    DECISION = "decision"  # Decyzja handlowa (wejście/wyjście)
    SYNC = "sync"  # Synchronizacja DB↔Binance
    RISK = "risk"  # Alert ryzyka
    REPORT = "report"  # Raport periodicny


class MessageSeverity(str, Enum):
    INFO = "info"  # Informacyjne
    WARNING = "warning"  # Ostrzeżenie
    ERROR = "error"  # Błąd
    CRITICAL = "critical"  # Krytyczne


@dataclass
class TelegramMessage:
    """
    Formatowana wiadomość Telegram z metadanymi.
    """

    msg_type: MessageType
    severity: MessageSeverity
    title: str
    subject: str = ""  # np. symbol, komponent
    sections: Dict[str, str] = field(default_factory=dict)  # {nagłówek: zawartość}
    emoji_prefix: str = "📊"
    footer: Optional[str] = None
    repeat_count: int = 1  # Licznik powtórzeń dla throttlingu

    def __post_init__(self):
        """Ustaw domyślne emoji na podstawie typu i severity."""
        emoji_map = {
            (MessageType.STATUS, MessageSeverity.INFO): "📊",
            (MessageType.ALERT, MessageSeverity.WARNING): "⚠️",
            (MessageType.ALERT, MessageSeverity.ERROR): "🚨",
            (MessageType.ALERT, MessageSeverity.CRITICAL): "🔴",
            (MessageType.DECISION, MessageSeverity.INFO): "🔄",
            (MessageType.DECISION, MessageSeverity.WARNING): "⏸️",
            (MessageType.SYNC, MessageSeverity.WARNING): "🔄",
            (MessageType.SYNC, MessageSeverity.ERROR): "❌",
            (MessageType.RISK, MessageSeverity.WARNING): "⚡",
            (MessageType.RISK, MessageSeverity.CRITICAL): "🛑",
            (MessageType.REPORT, MessageSeverity.INFO): "📈",
        }
        self.emoji_prefix = emoji_map.get((self.msg_type, self.severity), "📊")

    def format_telegram(self) -> str:
        """
        Formatuj wiadomość jako tekst Telegram (max 4096 znaków, czytelny na iPhone).
        """
        lines = []

        # Header
        header = f"{self.emoji_prefix} {self.title}"
        if self.subject:
            header += f" — {self.subject}"
        if self.repeat_count > 1:
            header += f" (x{self.repeat_count})"
        lines.append(header)
        lines.append("━" * 40)

        # Sections
        if self.sections:
            for sec_title, sec_content in self.sections.items():
                lines.append(f"\n{sec_title}:")
                # Zachowaj wcięcia i linie z src
                for line in sec_content.split("\n"):
                    if line.strip():
                        lines.append(f"  {line}" if not line.startswith("  ") else line)
                    else:
                        lines.append("")

        # Footer
        if self.footer:
            lines.append("\n" + "━" * 40)
            lines.append(f"ℹ️ {self.footer}")

        text = "\n".join(lines)
        # Obetnij do limitu Telegrama
        if len(text) > 4000:
            text = text[:3990] + "\n…"
        return text

    def format_compact(self) -> str:
        """Formatuj jako jednoliniowy tekst dla logów."""
        header = f"{self.title}"
        if self.subject:
            header += f" [{self.subject}]"
        if self.repeat_count > 1:
            header += f" (x{self.repeat_count})"
        return header


# ─────────────────────────────────────────────────────────────────────────────
# FORMATTERY SZABLONOWE
# ─────────────────────────────────────────────────────────────────────────────


def format_status_message(
    mode: str,
    positions_count: int,
    max_positions: int,
    watchlist_count: int,
    aggressiveness: str,
    candidates_considered: int,
    candidates_skipped: int,
    skip_reasons: Dict[str, int],  # {reason: count}
    avg_confidence: float,
    last_entry_minutes_ago: Optional[int],
    last_exit_minutes_ago: Optional[int],
    heartbeat_ok: bool = True,
) -> TelegramMessage:
    """
    Formatuj status operacyjny bota zamiast "Bot bezczynny".

    Pokazuje: tryb, pozycje, watchlista, powody pominięcia, confidence, czas ostatniej akcji.
    """

    skip_lines = []
    for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1])[:5]:
        skip_lines.append(f"  • {reason}: {count}")

    last_entry_str = (
        f"{last_entry_minutes_ago} min temu"
        if last_entry_minutes_ago is not None
        else "—"
    )
    last_exit_str = (
        f"{last_exit_minutes_ago} min temu"
        if last_exit_minutes_ago is not None
        else "—"
    )

    status_emoji = "✅" if heartbeat_ok else "⚠️"
    status_text = "Działa poprawnie" if heartbeat_ok else "Obniżona wydajność"

    msg = TelegramMessage(
        msg_type=MessageType.STATUS,
        severity=MessageSeverity.INFO,
        title="Cykl monitoringu",
        subject=mode.upper(),
        sections={
            "Konfiguracja": (
                f"Tryb: {aggressiveness.upper()}\n"
                f"Pozycje: {positions_count}/{max_positions}\n"
                f"Watchlist: {watchlist_count} symboli"
            ),
            "Ostatni cykl": (
                f"Rozważano: {candidates_considered} kandydatów\n"
                f"Odrzucono: {candidates_skipped}\n"
                f"Śr. confidence: {avg_confidence:.2f}"
            ),
            "Powody pominięcia (TOP 5)": (
                "\n".join(skip_lines) if skip_lines else "  —"
            ),
            "Ostatnie akcje": (
                f"Wejście: {last_entry_str}\n" f"Wyjście: {last_exit_str}"
            ),
        },
        footer=f"{status_emoji} System {status_text}. Rynek monitorowany.",
    )
    return msg


def format_sync_mismatch_message(
    mismatches: List[str],  # ["BNB: Binance=0 DB=0.128", ...]
    repeat_count: int = 1,
) -> TelegramMessage:
    """
    Formatuj alert niezgodności DB↔Binance z agregacją.

    Pokazuje niezgodności pogrupowane, z licznikiem powtórzeń.
    """

    # Podsumuj niezgodności
    summary_lines = []
    for mismatch in mismatches[:5]:  # Max 5, aby nie był za długi
        summary_lines.append(f"  • {mismatch}")
    if len(mismatches) > 5:
        summary_lines.append(f"  • … i {len(mismatches) - 5} więcej")

    severity = MessageSeverity.CRITICAL if repeat_count > 3 else MessageSeverity.WARNING

    msg = TelegramMessage(
        msg_type=MessageType.SYNC,
        severity=severity,
        title="Niezgodność pozycji",
        subject="DB ↔ Binance",
        sections={
            "Napięcia": "\n".join(summary_lines),
        },
        footer="Przyczyny: fee, rounding, partial fill, dust. System reconcile to naprawiał.",
        repeat_count=repeat_count,
    )
    return msg


def format_alert_message(
    alert_type: str,  # "API_ERROR", "ORDER_REJECTED", "STALE_DATA", ...
    symbol: Optional[str] = None,
    details: Optional[str] = None,
    action: Optional[str] = None,
) -> TelegramMessage:
    """
    Formatuj alert operacyjny.
    """

    severity_map = {
        "API_ERROR": MessageSeverity.ERROR,
        "ORDER_REJECTED": MessageSeverity.WARNING,
        "STALE_DATA": MessageSeverity.WARNING,
        "SYNC_FAILED": MessageSeverity.ERROR,
        "TIMEOUT": MessageSeverity.WARNING,
        "BINANCE_ERROR": MessageSeverity.CRITICAL,
    }

    severity = severity_map.get(alert_type, MessageSeverity.WARNING)

    sections = {}
    if details:
        sections["Szczegóły"] = details
    if action:
        sections["Akcja"] = action

    msg = TelegramMessage(
        msg_type=MessageType.ALERT,
        severity=severity,
        title=alert_type.replace("_", " "),
        subject=symbol or "",
        sections=sections,
        footer="Jeśli problem się powtarza, sprawdź logi w UI (Diagnostyka).",
    )
    return msg


def format_decision_message(
    action: str,  # "BUY", "SELL", "PARTIAL_TP", "SKIPPED"
    symbol: str,
    reason: str,
    confidence: Optional[float] = None,
    filter_blocked: Optional[str] = None,  # Jaki filtr zablokował
    pnl: Optional[float] = None,
    qty: Optional[float] = None,
) -> TelegramMessage:
    """
    Formatuj decyzję handlową.
    """

    action_emoji_map = {
        "BUY": "🟢",
        "SELL": "🔴",
        "PARTIAL_TP": "📈",
        "TP_HIT": "✅",
        "SL_HIT": "❌",
        "SKIPPED": "⏸️",
        "PENDING": "⏳",
    }

    emoji = action_emoji_map.get(action, "🔄")
    severity_map = {
        "BUY": MessageSeverity.INFO,
        "SELL": MessageSeverity.INFO,
        "TP_HIT": MessageSeverity.INFO,
        "SL_HIT": MessageSeverity.WARNING,
        "SKIPPED": MessageSeverity.INFO,
    }

    severity = severity_map.get(action, MessageSeverity.INFO)

    sections = {
        "Symbol": symbol,
        "Powód": reason,
    }

    if confidence is not None:
        sections["Confidence"] = f"{confidence:.2%}"
    if filter_blocked:
        sections["Blokada"] = filter_blocked
    if qty is not None:
        sections["Ilość"] = f"{qty:.8g}"
    if pnl is not None:
        sign = "+" if pnl >= 0 else ""
        sections["PnL"] = f"{sign}{pnl:.2f} EUR"

    msg = TelegramMessage(
        msg_type=MessageType.DECISION,
        severity=severity,
        title=f"{emoji} {action}",
        subject=symbol,
        sections=sections,
        emoji_prefix=emoji,
    )
    return msg


# ─────────────────────────────────────────────────────────────────────────────
# THROTTLER — agregacja alertów
# ─────────────────────────────────────────────────────────────────────────────


class AlertThrottler:
    """
    Skupuj powtarzalne alerty i zwiększaj repeat_count zamiast wysyłać duplikaty.
    """

    def __init__(self, cooldown_seconds: int = 600):
        self.cooldown_seconds = cooldown_seconds
        self.last_alerts: Dict[str, tuple[datetime, TelegramMessage]] = {}

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def should_send(self, alert_signature: str) -> bool:
        """Sprawdź czy powinniśmy wysłać alert czy go pominąć (throttle)."""
        now = self._utc_now()
        if alert_signature not in self.last_alerts:
            self.last_alerts[alert_signature] = (now, None)  # type: ignore
            return True

        last_time, last_msg = self.last_alerts[alert_signature]
        elapsed = (now - last_time).total_seconds()
        if elapsed >= self.cooldown_seconds:
            # Wyślij nowy alert
            self.last_alerts[alert_signature] = (now, None)  # type: ignore
            return True

        # W innym wypadku zwiększ repeat_count w memory ale nie wysyłaj
        return False

    def track_sent(self, alert_signature: str, msg: TelegramMessage):
        """Zarejestruj wysłany alert."""
        self.last_alerts[alert_signature] = (self._utc_now(), msg)
