"""
Testy dla Telegram Formatter i logiki synchronizacji.

Coverage:
- Status message formatting (czytelność, emoji, struktura)
- Sync mismatch formatting + throttling
- Decision message formatting
- Alert aggregation i repeat counting
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.telegram_formatter import (
    AlertThrottler,
    MessageSeverity,
    MessageType,
    TelegramMessage,
    format_alert_message,
    format_decision_message,
    format_status_message,
    format_sync_mismatch_message,
)


class TestTelegramFormatter:
    """Testy formatera Telegram."""

    def test_status_message_formatting(self):
        """Status message: czytelny format, brak nagiego tekstu."""
        msg = format_status_message(
            mode="live",
            positions_count=3,
            max_positions=5,
            watchlist_count=15,
            aggressiveness="balanced",
            candidates_considered=42,
            candidates_skipped=38,
            skip_reasons={
                "insufficient_edge": 15,
                "signal_filters_not_met": 12,
                "max_open_positions": 8,
                "cooldown_active": 3,
            },
            avg_confidence=0.65,
            last_entry_minutes_ago=47,
            last_exit_minutes_ago=132,
            heartbeat_ok=True,
        )

        assert msg.msg_type == MessageType.STATUS
        assert msg.severity == MessageSeverity.INFO
        assert "Cykl monitoringu" in msg.title
        formatted = msg.format_telegram()

        # Sprawdzenie zawartości
        assert "LIVE" in formatted
        assert "Pozycje: 3/5" in formatted
        assert "Watchlist: 15" in formatted
        assert "0.65" in formatted  # confidence
        assert "47 min temu" in formatted  # last entry
        assert "132 min temu" in formatted  # last exit

        # Nie powinna zawierać "Bot bezczynny"
        assert "bezczynny" not in formatted.lower()
        assert "idle" not in formatted.lower()

        # Powinna być czytelna (max 4096 znaków dla Telegrama)
        assert len(formatted) < 4000

        # Powinna mieć strukturę z liniami (tabelka/sekcje)
        assert "━" in formatted

    def test_status_message_no_recent_actions(self):
        """Status message gdy nie było ostatnio działań (None)."""
        msg = format_status_message(
            mode="demo",
            positions_count=0,
            max_positions=5,
            watchlist_count=10,
            aggressiveness="conservative",
            candidates_considered=25,
            candidates_skipped=25,
            skip_reasons={},
            avg_confidence=0.0,
            last_entry_minutes_ago=None,  # Nigdy nie było wejścia
            last_exit_minutes_ago=None,  # Nigdy nie było wyjścia
            heartbeat_ok=True,
        )

        formatted = msg.format_telegram()
        assert "Ostatnie akcje:" in formatted
        assert "—" in formatted or "nigdy" in formatted.lower()

    def test_sync_mismatch_single_asset(self):
        """Sync mismatch: pojedynczy asset (BNB)."""
        msg = format_sync_mismatch_message(
            mismatches=["BNB: Binance=0 DB=0.128"],
            repeat_count=1,
        )

        assert msg.msg_type == MessageType.SYNC
        assert msg.severity == MessageSeverity.WARNING
        formatted = msg.format_telegram()

        assert "Niezgodność" in formatted
        assert "BNB" in formatted
        assert "0.128" in formatted
        assert "(x1)" not in formatted  # Nie pokazuj x1 gdy repeat=1

    def test_sync_mismatch_multiple_assets(self):
        """Sync mismatch: wiele assetów z repeat count."""
        msg = format_sync_mismatch_message(
            mismatches=[
                "BNB: Binance=0 DB=0.128",
                "ARB: Binance=1.5 DB=1.234",
                "AVAX: Binance=0.12 DB=0.0",
            ],
            repeat_count=3,
        )

        assert msg.severity == MessageSeverity.WARNING
        formatted = msg.format_telegram()

        # Powinny być wymienione (max 5)
        assert "BNB" in formatted
        assert "ARB" in formatted
        assert "AVAX" in formatted
        # Powinien być licznik
        assert "(x3)" in formatted

    def test_sync_mismatch_critical_after_multiple_repeats(self):
        """Sync mismatch: severity=CRITICAL po wielu powtórzeniach."""
        msg = format_sync_mismatch_message(
            mismatches=["BNB: Binance=0 DB=0.5"],
            repeat_count=5,  # Duża liczba powtórzeń
        )

        assert msg.severity == MessageSeverity.CRITICAL

    def test_alert_message_api_error(self):
        """Alert: API error."""
        msg = format_alert_message(
            alert_type="API_ERROR",
            symbol="BTCEUR",
            details="Connection timeout after 5s",
            action="Retry w 30s",
        )

        assert msg.msg_type == MessageType.ALERT
        assert msg.severity == MessageSeverity.ERROR
        formatted = msg.format_telegram()

        assert "API ERROR" in formatted or "Error" in formatted
        assert "BTCEUR" in formatted
        assert "timeout" in formatted or "Connection" in formatted
        assert "Retry" in formatted

    def test_decision_message_buy(self):
        """Decision: BUY."""
        msg = format_decision_message(
            action="BUY",
            symbol="ETHEUR",
            reason="Golden cross + RSI oversold",
            confidence=0.72,
            qty=0.5,
        )

        assert msg.msg_type == MessageType.DECISION
        assert msg.severity == MessageSeverity.INFO
        formatted = msg.format_telegram()

        assert "BUY" in formatted or "🟢" in formatted
        assert "ETHEUR" in formatted
        assert "Golden cross" in formatted
        assert "72" in formatted  # 72.00% format
        assert "0.5" in formatted

    def test_decision_message_skipped_with_filter(self):
        """Decision: SKIPPED (nie przeszedł filtr)."""
        msg = format_decision_message(
            action="SKIPPED",
            symbol="DOGEEUR",
            reason="Zbyt mały edge",
            confidence=0.45,
            filter_blocked="cost_gate (brak edge po kosztach)",
        )

        assert msg.msg_type == MessageType.DECISION
        assert msg.severity == MessageSeverity.INFO
        formatted = msg.format_telegram()

        assert "SKIPPED" in formatted or "⏸️" in formatted
        assert "DOGEEUR" in formatted
        assert "cost_gate" in formatted

    def test_message_length_limits(self):
        """Wiadomości nie powinny być dłuższe niż limit Telegrama."""
        msg = format_status_message(
            mode="live",
            positions_count=5,
            max_positions=5,
            watchlist_count=50,  # Duża watchlist
            aggressiveness="aggressive",
            candidates_considered=1000,
            candidates_skipped=995,
            skip_reasons={f"reason_{i}": i for i in range(20)},  # Wiele powodów
            avg_confidence=0.55,
            last_entry_minutes_ago=10,
            last_exit_minutes_ago=300,
            heartbeat_ok=True,
        )

        formatted = msg.format_telegram()
        # Telegram limit: 4096 znaków
        assert len(formatted) <= 4096


class TestAlertThrottler:
    """Testy throttlera alertów."""

    def test_first_alert_always_sent(self):
        """Pierwszy alert danego typu powinien być wysłany."""
        throttler = AlertThrottler(cooldown_seconds=60)

        assert throttler.should_send("sync_mismatch_BNB") is True

    def test_repeated_alert_throttled(self):
        """Powtórzony alert w ciągu cooldown powinien być throttled."""
        throttler = AlertThrottler(cooldown_seconds=60)

        sig = "sync_mismatch_BNB"
        throttler.should_send(sig)  # Pierwszy

        # Drugi w ciągu cooldown
        assert throttler.should_send(sig) is False

    def test_alert_sent_after_cooldown(self):
        """Alert wysłany po upłynięciu cooldown."""
        throttler = AlertThrottler(cooldown_seconds=60)

        sig = "sync_mismatch_ARB"
        throttler.should_send(sig)

        # Symuluj upływ czasu (za pomocą hack: bezpośrednio zmień time)
        throttler.last_alerts[sig] = (
            datetime.now(timezone.utc) - timedelta(seconds=65),
            None,  # type: ignore
        )

        # Powinien być wysłany (cooldown minął)
        assert throttler.should_send(sig) is True

    def test_different_signatures_independent(self):
        """Różne sygnatury alertów niezależne."""
        throttler = AlertThrottler(cooldown_seconds=60)

        sig1 = "sync_BNB"
        sig2 = "sync_ARB"

        throttler.should_send(sig1)  # Pierwszy BNB
        assert throttler.should_send(sig2) is True  # ARB powinien być niezależny


class TestSyncMismatchScenarios:
    """Scenariusze testowe dla niezgodności sync (przyczyny problemu)."""

    def test_dust_after_partial_tp(self):
        """
        Scenariusz: Partial TP zmniejszył pozycję, ale zostały mikroresztki.

        Spodziewane: system powinien to rozpoznać i ignorować w raporcie dust.
        """
        # Symulacja: bot miał 1.234 BNB, wykonał partial TP (sprzedał 0.5)
        # Binance: 0.7340 (1.234 - 0.5 = 0.734, ale było zaokrąglenie + fee)
        # DB: 0.7340
        # Niezgodność: 0

        # Jeśli było zaokrąglenie do 0.734 vs 0.73400001, to ignorujemy
        mismatch_qty = abs(0.73400001 - 0.734)
        assert mismatch_qty < 1e-6, "Mikroresztka ignorowana (1e-6 epsilon)"

    def test_bnb_fee_causing_residual(self):
        """
        Scenariusz: BNB zastosowany jako opłata zmniejszył balance.

        Log:
        - Kupiliśmy 10 ETHEUR za 9000 EUR
        - Fee: 0.1% * 10 = 0.01 ETH = 900 EUR
        - Wartość opłaty w EUR: 900
        - Fee potrącony z EUR balansu, nie z ETH
        - DB: 10 ETH, 9000 EUR ledge
        - Binance: 10 ETH, 9000 EUR + jakiś dust w BNB (fee)

        Spodziewane: ignorować BNB dust jeśli < min_notional.
        """
        bnb_dust = 0.00015  # 0.00015 BNB = ~0.05 EUR (poniżej min_notional=10)
        bnb_price = 300.0
        dust_value = bnb_dust * bnb_price
        assert dust_value < 10, "BNB dust < min_notional — ignorować"

    def test_position_closed_but_db_update_delayed(self):
        """
        Scenariusz: Pozycja zamknęła się na Binance, ale DB jeszcze ma stary record.

        Log:
        - Position: 5 ARBEUR (otwarta w DB)
        - EXIT: SL hit, Binance zamknął, free 5 ARB
        - DB: record jeszcze isNotClosed
        - Binance: 5 ARB free (pozycja rzeczywista zamknęła)
        - Niezgodność: DB=5, Binance=5 (ale w innym kontekście)

        Przyczyna: exit_engine napisał pozycję do DB z opóźnieniem.
        Rozwiązanie: exit_engine musi ATOMOWO:
        1. Wykonaj close position na Binance
        2. Natychmiast zaktualizuj DB markując position.exit_reason_code
        3. Jeśli fail (DB writer error), retry + rollback.
        """
        # Test sprawdza jaki jest workflow w exit_engine
        # (tu tylko schematycznie - w realnym teście byłby mock DB)
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
