"""
Testy dla symbol_universe.py

Scenariusze:
- fetch_exchange_symbols: pobieranie symboli z Binance
- filter USDC: tylko BTCUSDC, ETHUSDC, itp
- filter EUR: tylko BTCEUR, ETHEUR, itp
- filter test symbols: test/dev usuwa się
- merge universes: priority + eligible
"""

from unittest.mock import MagicMock

import pytest

from backend.symbol_universe import (
    TEST_SYMBOLS,
    _is_test_or_dev_symbol,
    build_priority_symbols_from_watchlist,
    fetch_exchange_symbols,
    get_rotating_universe_slice,
    get_symbol_universe_stats,
    merge_universes,
    validate_symbol,
)


class TestIsTestOrDevSymbol:
    """Test detekcji test/dev symboli."""

    def test_test_symbols_detected(self):
        """Test symbole z listy TEST_SYMBOLS."""
        for sym in ["TESTUSDC", "DEMOBTC", "DEVEUR"]:
            assert _is_test_or_dev_symbol(sym) is True

    def test_dev_in_name(self):
        """Test symbole z DEV w nazwie."""
        assert _is_test_or_dev_symbol("DEVETHUSD") is True
        assert _is_test_or_dev_symbol("TESTBTC") is True

    def test_normal_symbols_not_detected(self):
        """Test normalne symbole."""
        assert _is_test_or_dev_symbol("BTCUSDC") is False
        assert _is_test_or_dev_symbol("ETHEUR") is False
        assert _is_test_or_dev_symbol("SOLUSDC") is False


class TestFetchExchangeSymbols:
    """Test pobierania symboli z Binance."""

    def _make_mock_exchange_info(self, symbols_list):
        """Tworzy mock exchange info."""
        symbols = []
        for sym in symbols_list:
            symbols.append(
                {
                    "symbol": sym,
                    "status": "TRADING",
                    "filters": [{"filterType": "NOTIONAL"}],
                }
            )
        return {"symbols": symbols}

    def test_fetch_usdc_only(self):
        """Test pobierania tylko USDC symboli."""
        mock_client = MagicMock()
        mock_client.get_exchange_info.return_value = self._make_mock_exchange_info(
            ["BTCUSDC", "ETHUSDC", "SOLUSDC", "ETHEUR", "SOLEUR"]
        )

        symbols, rejected, diag = fetch_exchange_symbols(mock_client, "USDC")

        assert "BTCUSDC" in symbols
        assert "ETHUSDC" in symbols
        assert "SOLUSDC" in symbols
        assert "ETHEUR" not in symbols
        assert "SOLEUR" not in symbols
        assert diag["final_count"] == 3

    def test_fetch_eur_only(self):
        """Test pobierania tylko EUR symboli."""
        mock_client = MagicMock()
        mock_client.get_exchange_info.return_value = self._make_mock_exchange_info(
            ["BTCUSDC", "ETHUSDC", "ETHEUR", "SOLEUR"]
        )

        symbols, rejected, diag = fetch_exchange_symbols(mock_client, "EUR")

        assert "ETHEUR" in symbols
        assert "SOLEUR" in symbols
        assert "BTCUSDC" not in symbols
        assert diag["final_count"] == 2

    def test_fetch_both_modes(self):
        """Test pobierania EUR+USDC symboli."""
        mock_client = MagicMock()
        mock_client.get_exchange_info.return_value = self._make_mock_exchange_info(
            ["BTCUSDC", "BTCEUR", "ETHUSDC", "ETHEUR"]
        )

        symbols, rejected, diag = fetch_exchange_symbols(mock_client, "BOTH")

        assert len(symbols) == 4
        assert all(s in symbols for s in ["BTCUSDC", "BTCEUR", "ETHUSDC", "ETHEUR"])

    def test_reject_test_symbols(self):
        """Test że symbole testowe są odrzucane."""
        mock_client = MagicMock()
        mock_client.get_exchange_info.return_value = self._make_mock_exchange_info(
            ["BTCUSDC", "TESTUSDC", "ETHUSDC", "DEMOBTC"]
        )

        symbols, rejected, diag = fetch_exchange_symbols(mock_client, "USDC")

        assert "TESTUSDC" not in symbols
        assert "DEMOBTC" not in symbols
        assert "BTCUSDC" in symbols
        assert diag["test_symbols"] >= 2

    def test_reject_non_trading_status(self):
        """Test że symbole z status != TRADING są odrzucane."""
        mock_client = MagicMock()
        mock_client.get_exchange_info.return_value = {
            "symbols": [
                {
                    "symbol": "BTCUSDC",
                    "status": "TRADING",
                    "filters": [{"filterType": "NOTIONAL"}],
                },
                {
                    "symbol": "ETHUSDC",
                    "status": "HALT",
                    "filters": [{"filterType": "NOTIONAL"}],
                },
                {
                    "symbol": "SOLUSDC",
                    "status": "PENDING_TRADING",
                    "filters": [{"filterType": "NOTIONAL"}],
                },
            ]
        }

        symbols, rejected, diag = fetch_exchange_symbols(mock_client, "USDC")

        assert "BTCUSDC" in symbols
        assert "ETHUSDC" not in symbols
        assert "SOLUSDC" not in symbols
        assert diag["inactive_symbols"] >= 2

    def test_diagnostics_counters(self):
        """Test że diagnostyka zawiera poprawne liczniki."""
        mock_client = MagicMock()
        mock_client.get_exchange_info.return_value = self._make_mock_exchange_info(
            ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
        )

        symbols, rejected, diag = fetch_exchange_symbols(mock_client, "USDC")

        assert diag["total_symbols"] == 3
        assert diag["final_count"] == 3
        assert diag["test_symbols"] == 0
        assert diag["inactive_symbols"] == 0


class TestBuildPrioritySymbols:
    """Test budowania priority universe z WATCHLIST."""

    def test_watchlist_to_usdc_symbols(self):
        """Test konwersji BTC,ETH → BTCUSDC, ETHUSDC."""
        symbols = build_priority_symbols_from_watchlist("BTC,ETH,SOL", "USDC")

        assert "BTCUSDC" in symbols
        assert "ETHUSDC" in symbols
        assert "SOLUSDC" in symbols
        assert len(symbols) == 3

    def test_watchlist_to_eur_symbols(self):
        """Test konwersji do EUR symboli."""
        symbols = build_priority_symbols_from_watchlist("BTC,ETH", "EUR")

        assert "BTCEUR" in symbols
        assert "ETHEUR" in symbols
        assert len(symbols) == 2

    def test_watchlist_both_mode(self):
        """Test mode BOTH tworzy EUR i USDC."""
        symbols = build_priority_symbols_from_watchlist("BTC,ETH", "BOTH")

        assert "BTCUSDC" in symbols
        assert "BTCEUR" in symbols
        assert "ETHUSDC" in symbols
        assert "ETHEUR" in symbols
        assert len(symbols) == 4

    def test_empty_watchlist(self):
        """Test że pusta watchlist zwraca []."""
        symbols = build_priority_symbols_from_watchlist("", "USDC")
        assert symbols == []

        symbols2 = build_priority_symbols_from_watchlist(None, "USDC")
        assert symbols2 == []

    def test_whitespace_handling(self):
        """Test że spacje są ignorowane."""
        symbols = build_priority_symbols_from_watchlist("BTC , ETH , SOL", "USDC")

        assert "BTCUSDC" in symbols
        assert "ETHUSDC" in symbols
        assert len(symbols) == 3


class TestMergeUniverses:
    """Test scalania eligible + priority universes."""

    def test_merge_priority_only_false(self):
        """Test merge bez PRIORITY_ONLY: zwraca eligible + priority."""
        eligible = ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
        priority = ["BTCUSDC", "ETHUSDC"]

        final, eligible_only, priority_set = merge_universes(
            eligible, priority, priority_only=False
        )


def test_validate_symbol_rejects_fake_symbol():
    registry = {
        "metadata": {"BTCUSDC": {"symbol": "BTCUSDC"}},
        "quote_filtered_universe": ["BTCUSDC"],
        "tradable_universe": ["BTCUSDC"],
    }
    result = validate_symbol("OPERATORUSDC", registry=registry)
    assert result["valid"] is False
    assert result["reason"] == "not_in_exchange"


def test_rotating_universe_slice_chunks_symbols():
    registry = {
        "quote_filtered_universe": ["AUSDC", "BUSDC", "CUSDC", "DUSDC", "EUSDC"]
    }
    first, next_offset = get_rotating_universe_slice(registry=registry, limit=2, offset=0)
    second, _ = get_rotating_universe_slice(registry=registry, limit=2, offset=next_offset)
    assert first == ["AUSDC", "BUSDC"]
    assert second == ["CUSDC", "DUSDC"]


def test_universe_stats_return_required_counts(monkeypatch):
    monkeypatch.setattr(
        "backend.symbol_universe.get_symbol_registry",
        lambda *args, **kwargs: {
            "full_universe": ["BTCUSDC", "ETHUSDC", "BTCEUR"],
            "tradable_universe": ["BTCUSDC", "ETHUSDC", "BTCEUR"],
            "quote_filtered_universe": ["BTCUSDC", "ETHUSDC"],
            "user_watchlist": ["BTCUSDC"],
            "allowed_quotes": ["USDC", "EUR"],
            "error": None,
        },
    )
    stats = get_symbol_universe_stats()
    assert stats["full_count"] == 3
    assert stats["tradable_count"] == 3
    assert stats["filtered_count"] == 2

        assert len(final) == 3  # eligible_only + priority (bez duplikacji)
        assert "SOLUSDC" in eligible_only  # symbole spoza priority
        assert "BTCUSDC" in priority_set

    def test_merge_priority_only_true(self):
        """Test PRIORITY_ONLY=true: zwraca tylko przecięcie priority ∩ eligible."""
        eligible = ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
        priority = ["BTCUSDC", "ETHUSDC", "AVAXUSDC"]  # AVAXUSDC nie jest w eligible

        final, eligible_only, priority_set = merge_universes(
            eligible, priority, priority_only=True
        )

        assert "BTCUSDC" in final
        assert "ETHUSDC" in final
        assert "AVAXUSDC" not in final  # nie ma w eligible
        assert len(final) == 2  # tylko intersect

    def test_priority_sorted_first(self):
        """Test że priority symbole są na czoło (gdy priority_only=False)."""
        eligible = ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
        priority = ["SOLUSDC", "ETHUSDC"]

        final, _, _ = merge_universes(eligible, priority, priority_only=False)

        # priority na czoło (sorted priority + remaining eligible)
        priority_indices = [i for i, s in enumerate(final) if s in priority]
        assert len(priority_indices) > 0

    def test_empty_eligible(self):
        """Test że puste eligible zwraca []."""
        final, eligible_only, priority_set = merge_universes(
            [], ["BTCUSDC"], priority_only=True
        )

        assert len(final) == 0
        assert len(priority_set) == 1

    def test_empty_priority(self):
        """Test że pusta priority nie psuje eligible."""
        eligible = ["BTCUSDC", "ETHUSDC"]
        final, eligible_only, priority_set = merge_universes(
            eligible, [], priority_only=False
        )

        assert len(final) == 2
        assert len(priority_set) == 0
        assert set(final) == set(eligible)
