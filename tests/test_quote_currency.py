import os
from unittest.mock import MagicMock, patch

import pytest

import backend.quote_currency as _qc
from backend.quote_currency import (
    build_symbol_set,
    convert_eur_amount_to_quote,
    enforce_final_min_quote_usdc,
    ensure_usdc_balance_for_order,
    execute_conversion_eur_to_usdc,
    expand_watchlist_for_mode,
    filter_symbols_by_quote_mode,
    fund_usdc_from_eur_if_needed,
    get_markets_for_asset,
    get_supported_base_assets,
    is_test_symbol,
    parse_nl_quote_command,
    preferred_symbol_for_asset,
    resolve_eur_usdc_rate,
    resolve_required_quote_usdc,
    should_convert_eur_to_usdc,
)
from backend.routers.control import _parse_symbol_from_text


@pytest.fixture(autouse=True)
def _reset_conversion_globals():
    """Resetuje moduł-poziomowy stan konwersji EUR→USDC między testami."""
    _qc._last_conversion_time = None
    _qc._conversion_timestamps = []
    yield
    _qc._last_conversion_time = None
    _qc._conversion_timestamps = []


def test_filter_symbols_mode_eur_only():
    symbols = ["BTCEUR", "BTCUSDC", "ETHEUR", "SOLUSDC"]
    filtered = filter_symbols_by_quote_mode(symbols, "EUR")
    assert filtered == ["BTCEUR", "ETHEUR"]


def test_filter_symbols_mode_usdc_only():
    symbols = ["BTCEUR", "BTCUSDC", "ETHEUR", "SOLUSDC"]
    filtered = filter_symbols_by_quote_mode(symbols, "USDC")
    assert filtered == ["BTCUSDC", "SOLUSDC"]


def test_filter_symbols_mode_both():
    symbols = ["BTCEUR", "BTCUSDC"]
    filtered = filter_symbols_by_quote_mode(symbols, "BOTH")
    assert filtered == symbols


def test_usdc_mode_requires_conversion_when_no_usdc_has_eur():
    should_convert, reason, amount = should_convert_eur_to_usdc(
        free_eur=120.0,
        free_usdc=2.0,
        target_usdc_buffer=50.0,
        min_eur_reserve=10.0,
        min_conversion_notional=20.0,
        conversion_cooldown_minutes=60,
        max_conversion_per_hour=3,
    )
    assert should_convert is True
    assert reason == "funding_conversion_required"
    assert amount >= 20.0


def test_usdc_mode_no_conversion_when_insufficient_eur():
    should_convert, reason, amount = should_convert_eur_to_usdc(
        free_eur=12.0,
        free_usdc=1.0,
        target_usdc_buffer=50.0,
        min_eur_reserve=10.0,
        min_conversion_notional=20.0,
        conversion_cooldown_minutes=60,
        max_conversion_per_hour=3,
    )
    assert should_convert is False
    assert reason in {
        "funding_conversion_insufficient",
        "funding_conversion_skipped_small",
    }
    assert amount == 0.0


def test_preferred_symbol_for_asset_by_mode():
    assert preferred_symbol_for_asset("BTC", "USDC", "USDC") == "BTCUSDC"
    assert preferred_symbol_for_asset("BTC", "EUR", "EUR") == "BTCEUR"
    assert preferred_symbol_for_asset("BTC", "BOTH", "USDC") == "BTCUSDC"


def test_nl_kup_btc_selects_symbol_by_quote_mode(monkeypatch):
    monkeypatch.setenv("QUOTE_CURRENCY_MODE", "USDC")
    monkeypatch.setenv("PRIMARY_QUOTE", "USDC")
    assert _parse_symbol_from_text("kup btc") == "BTCUSDC"

    monkeypatch.setenv("QUOTE_CURRENCY_MODE", "EUR")
    monkeypatch.setenv("PRIMARY_QUOTE", "EUR")
    assert _parse_symbol_from_text("kup btc") == "BTCEUR"


def test_parse_nl_quote_mode_commands():
    assert parse_nl_quote_command("handluj tylko na usdc") == {
        "action": "set_quote_mode",
        "mode": "USDC",
    }
    assert parse_nl_quote_command("uzywaj eur i usdc") == {
        "action": "set_quote_mode",
        "mode": "BOTH",
    }
    assert parse_nl_quote_command("zamien eur na usdc") == {
        "action": "convert_eur_to_usdc"
    }


# =============================================================================
# Nowe testy — wymagania A-G z wdrożenia dual-quote
# =============================================================================


# A. Watchlista logiczna — BTC ma oba rynki: BTCEUR i BTCUSDC
def test_A_build_symbol_set_both_markets_for_btc():
    syms = build_symbol_set(["BTC"], "BOTH")
    assert "BTCEUR" in syms, "BTCEUR musi być w BOTH"
    assert "BTCUSDC" in syms, "BTCUSDC musi być w BOTH"


def test_A_all_supported_base_assets_have_both_markets():
    for asset in get_supported_base_assets():
        markets = get_markets_for_asset(asset)
        assert "EUR" in markets, f"{asset}: brak rynku EUR"
        assert "USDC" in markets, f"{asset}: brak rynku USDC"
        assert markets["EUR"].endswith("EUR"), f"{asset}: nieprawidłowy symbol EUR"
        assert markets["USDC"].endswith("USDC"), f"{asset}: nieprawidłowy symbol USDC"


def test_A_expand_watchlist_eur_only_adds_usdc():
    """Istniejąca lista tylko EUR → expand BOTH → obie quote currencies dodane."""
    input_syms = ["BTCEUR", "ETHEUR", "SOLEUR"]
    expanded = expand_watchlist_for_mode(input_syms, "BOTH")
    assert "BTCEUR" in expanded
    assert "BTCUSDC" in expanded
    assert "ETHEUR" in expanded
    assert "ETHUSDC" in expanded
    assert "SOLEUR" in expanded
    assert "SOLUSDC" in expanded


def test_A_expand_watchlist_bare_base_assets():
    """Bare base assets jak 'BTC' są poprawnie ekspandowane."""
    expanded = expand_watchlist_for_mode(["BTC", "ETH"], "BOTH")
    assert "BTCEUR" in expanded
    assert "BTCUSDC" in expanded
    assert "ETHEUR" in expanded
    assert "ETHUSDC" in expanded


# B. Tryb EUR — analiza zawiera tylko pary EUR
def test_B_mode_eur_only_eur_symbols():
    syms = build_symbol_set(["BTC", "ETH", "SOL", "BNB", "SHIB"], "EUR")
    for s in syms:
        assert s.endswith("EUR"), f"Tryb EUR: {s} nie kończy się na EUR"
    assert not any(s.endswith("USDC") for s in syms)


def test_B_expand_mode_eur_returns_only_eur():
    result = expand_watchlist_for_mode(["BTCEUR", "BTCUSDC", "ETHEUR"], "EUR")
    assert all(s.endswith("EUR") for s in result)
    assert "BTCUSDC" not in result


# C. Tryb USDC — analiza zawiera tylko pary USDC
def test_C_mode_usdc_only_usdc_symbols():
    syms = build_symbol_set(["BTC", "ETH", "SOL", "BNB", "SHIB"], "USDC")
    for s in syms:
        assert s.endswith("USDC"), f"Tryb USDC: {s} nie kończy się na USDC"
    assert not any(s.endswith("EUR") for s in syms)


def test_C_expand_mode_usdc_from_eur_list():
    """Nawet jeśli wejście to same EUR, tryb USDC zwraca tylko USDC."""
    result = expand_watchlist_for_mode(["BTCEUR", "ETHEUR", "SOLEUR"], "USDC")
    assert all(s.endswith("USDC") for s in result)
    assert "BTCEUR" not in result


# D. Tryb BOTH — oba rynki dla tych samych aktywów
def test_D_mode_both_both_markets_per_asset():
    syms = build_symbol_set(["BTC", "ETH", "BNB"], "BOTH")
    assert "BTCEUR" in syms and "BTCUSDC" in syms
    assert "ETHEUR" in syms and "ETHUSDC" in syms
    assert "BNBEUR" in syms and "BNBUSDC" in syms


def test_D_filter_symbols_by_quote_mode_both_keeps_all():
    symbols = ["BTCEUR", "BTCUSDC", "ETHEUR", "ETHUSDC"]
    assert filter_symbols_by_quote_mode(symbols, "BOTH") == symbols


# E. Ranking BOTH — preferred_symbol wybiera lepszy z dwóch rynków
def test_E_preferred_symbol_usdc_primary():
    assert preferred_symbol_for_asset("BTC", "BOTH", "USDC") == "BTCUSDC"
    assert preferred_symbol_for_asset("ETH", "BOTH", "USDC") == "ETHUSDC"


def test_E_preferred_symbol_eur_primary():
    assert preferred_symbol_for_asset("BTC", "BOTH", "EUR") == "BTCEUR"
    assert preferred_symbol_for_asset("ETH", "BOTH", "EUR") == "ETHEUR"


def test_E_preferred_symbol_strict_mode():
    """Tryb EUR/USDC ignoruje primary_quote — tryb ma pierwszeństwo."""
    assert preferred_symbol_for_asset("BTC", "EUR", "USDC") == "BTCEUR"
    assert preferred_symbol_for_asset("BTC", "USDC", "EUR") == "BTCUSDC"


# F. Account valuation — niezależnie od trybu handlu, konto liczone w EUR
# (account valuation jest obliczana w portfolio_engine.py — tu testujemy
#  że quote_currency nie zmienia stronę waluty raportowania)
def test_F_get_markets_for_asset_structure():
    """get_markets_for_asset zwraca oba rynki, EUR jako raportowany."""
    for asset in ["BTC", "ETH", "SOL", "BNB"]:
        m = get_markets_for_asset(asset)
        assert "EUR" in m, f"{asset}: brak klucza EUR"
        assert "USDC" in m, f"{asset}: brak klucza USDC"


def test_F_expand_usdc_mode_does_not_remove_eur_key_from_map():
    """Mapa aktywów zawsze zawiera EUR — nawet gdy tryb to USDC."""
    for asset in get_supported_base_assets():
        m = get_markets_for_asset(asset)
        assert "EUR" in m, f"Mapa {asset}: brak EUR (potrzebne do account valuation)"


# G. Default config — domyślnie system startuje z USDC
def test_G_default_quote_mode_env_is_usdc(monkeypatch):
    """Bez override env, domyślny tryb to USDC."""
    monkeypatch.delenv("QUOTE_CURRENCY_MODE", raising=False)
    monkeypatch.delenv("PRIMARY_QUOTE", raising=False)
    from backend.runtime_settings import _SETTINGS

    qcm_spec = _SETTINGS.get("quote_currency_mode")
    pq_spec = _SETTINGS.get("primary_quote")
    assert qcm_spec is not None
    assert pq_spec is not None
    assert (
        qcm_spec.default == "USDC"
    ), f"Domyślny quote_currency_mode = {qcm_spec.default!r} (oczekiwano USDC)"
    assert (
        pq_spec.default == "USDC"
    ), f"Domyślny primary_quote = {pq_spec.default!r} (oczekiwano USDC)"


def test_G_preferred_symbol_default_usdc_mode():
    """W trybie USDC, preferred_symbol zwraca USDC wariant."""
    # Symuluje zachowanie systemu z QUOTE_CURRENCY_MODE=USDC
    assert preferred_symbol_for_asset("BTC", "USDC", "USDC") == "BTCUSDC"
    assert preferred_symbol_for_asset("WLFI", "USDC", "USDC") == "WLFIUSDC"
    assert preferred_symbol_for_asset("SHIB", "USDC", "USDC") == "SHIBUSDC"


# H. Konwersja EUR→USDC — kierunek i parametry zlecenia
def test_H_conversion_uses_sell_direction():
    """execute_conversion_eur_to_usdc MUSI używać side=SELL (sprzedaj EUR, kup USDC).
    BUG HISTORY: wcześniej błędnie używało side=BUY (kupowało EUR za USDC — odwrotny kierunek).
    """
    mock_client = MagicMock()
    mock_client.get_allowed_symbols.return_value = {
        "EURUSDC": {
            "base_asset": "EUR",
            "quote_asset": "USDC",
            "min_qty": 0.1,
            "step_size": 0.1,
            "min_notional": 5.0,
        }
    }
    mock_client.place_order.return_value = {
        "orderId": 12345,
        "executedQty": "50.0",
        "status": "FILLED",
    }

    result = execute_conversion_eur_to_usdc(mock_client, amount_eur=50.0)

    assert result["executed"] is True
    call_kwargs = mock_client.place_order.call_args
    # Sprawdź kierunek — SELL, nie BUY
    assert call_kwargs.kwargs.get("side") == "SELL" or (
        len(call_kwargs.args) >= 2 and call_kwargs.args[1] == "SELL"
    ), f"Błędny side: {call_kwargs} — powinno być SELL (sprzedaj EUR i kup USDC)"
    # Sprawdź że używa quantity, nie quote_qty
    qty_arg = call_kwargs.kwargs.get("quantity")
    assert (
        qty_arg is not None and qty_arg > 0
    ), f"Konwersja powinna używać quantity=amount_eur, nie quote_qty. kwargs={call_kwargs.kwargs}"


def test_min_buy_eur_to_usdc_conversion_uses_rate():
    amount = convert_eur_amount_to_quote(60.0, "USDC", eur_usdc_rate=1.12)
    assert amount == pytest.approx(67.2, rel=1e-6)


def test_resolve_eur_usdc_rate_uses_inverse_pair_when_needed():
    mock_client = MagicMock()
    mock_client.get_ticker_price.side_effect = [
        None,
        {"symbol": "USDCEUR", "price": 0.9},
    ]
    rate, source = resolve_eur_usdc_rate(mock_client)
    assert rate == pytest.approx(1.111111, rel=1e-5)
    assert source == "usdceur_inverse"


def test_is_test_symbol_detects_live_forbidden_symbols():
    assert is_test_symbol("TESTUSDC") is True
    assert is_test_symbol("btcusdc") is False


def test_H2_conversion_applies_step_size():
    """execute_conversion_eur_to_usdc musi dostosować quantity do step_size.
    BUG HISTORY: 101.08 EUR z step_size=0.1 dawało LOT_SIZE error (101.08 nie jest wielokrotnością 0.1).
    """
    mock_client = MagicMock()
    mock_client.get_allowed_symbols.return_value = {
        "EURUSDC": {
            "base_asset": "EUR",
            "quote_asset": "USDC",
            "min_qty": 0.1,
            "step_size": 0.1,
            "min_notional": 5.0,
        }
    }
    mock_client.place_order.return_value = {
        "orderId": 99,
        "executedQty": "101.0",
        "status": "FILLED",
    }

    result = execute_conversion_eur_to_usdc(mock_client, amount_eur=101.08)

    assert result["executed"] is True
    call_kwargs = mock_client.place_order.call_args
    qty = call_kwargs.kwargs.get("quantity")
    # 101.08 zaokrąglone do step 0.1 = 101.0
    assert qty == pytest.approx(101.0, abs=0.001), f"Oczekiwano 101.0, dostałem {qty}"


def test_H3_conversion_error_not_marked_executed():
    """execute_conversion_eur_to_usdc NIE MOŻE logować executed=True gdy Binance zwraca _error.
    BUG HISTORY: order.get("_error") był ignorowany, więc orderId=None i balance nie rosło.
    """
    mock_client = MagicMock()
    mock_client.get_allowed_symbols.return_value = {
        "EURUSDC": {
            "base_asset": "EUR",
            "quote_asset": "USDC",
            "min_qty": 0.1,
            "step_size": 0.1,
            "min_notional": 5.0,
        }
    }
    mock_client.place_order.return_value = {
        "_error": True,
        "error_code": 400,
        "error_message": "LOT_SIZE filter failure",
    }

    result = execute_conversion_eur_to_usdc(mock_client, amount_eur=50.0)

    assert (
        result.get("executed") is not True
    ), "Konwersja nie powinna być oznaczona jako executed gdy Binance zwrócił _error"
    assert result.get("reason_code") == "funding_conversion_failed"


# =============================================================================
# T-104 v2: USDC-first canonical helpers
# =============================================================================


def test_resolve_required_quote_usdc_converts_reference_eur():
    """resolve_required_quote_usdc przelicza min_buy_reference_eur na USDC."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.12"}
    required_usdc, meta = resolve_required_quote_usdc(60.0, mock_client)
    assert required_usdc == pytest.approx(67.2, rel=1e-4)
    assert meta["quote_asset"] == "USDC"
    assert meta["min_buy_reference_eur"] == 60.0
    assert meta["eur_usdc_rate"] == pytest.approx(1.12, rel=1e-4)
    assert meta["required_quote_usdc"] == pytest.approx(67.2, rel=1e-4)


def test_resolve_required_quote_usdc_respects_exchange_min_notional():
    """exchange_min_notional jest brany pod uwagę jako dolna granica."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.0"}
    # 60 EUR * 1.0 = 60 USDC, ale exchange_min = 100
    required_usdc, meta = resolve_required_quote_usdc(
        60.0, mock_client, exchange_min_notional=100.0
    )
    assert required_usdc == pytest.approx(100.0, rel=1e-4)
    assert meta["exchange_min_notional"] == 100.0


def test_fund_usdc_from_eur_if_needed_sufficient_usdc():
    """Gdy USDC wystarczy — brak konwersji, ok=True."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}
    result = fund_usdc_from_eur_if_needed(
        mock_client,
        required_usdc=50.0,
        available_usdc=80.0,
        available_eur=0.0,
    )
    assert result["ok"] is True
    assert result["converted"] is False
    assert result["reason_code"] == "usdc_balance_sufficient"
    assert result["missing_usdc"] == 0.0
    mock_client.place_order.assert_not_called()


def test_fund_usdc_from_eur_if_needed_converts_eur():
    """Gdy USDC za mało, ale EUR wystarczy — wykonuje konwersję i zwraca ok=True."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}
    mock_client.get_allowed_symbols.return_value = {
        "EURUSDC": {"step_size": "0.1", "min_qty": "0.1"}
    }
    mock_client.place_order.return_value = {
        "orderId": 555,
        "executedQty": "30.0",
        "status": "FILLED",
    }
    mock_client.get_balances.return_value = [
        {"asset": "USDC", "free": "80.0"},
        {"asset": "EUR", "free": "70.0"},
    ]
    result = fund_usdc_from_eur_if_needed(
        mock_client,
        required_usdc=70.0,
        available_usdc=30.0,
        available_eur=100.0,
    )
    assert result["ok"] is True
    assert result["converted"] is True
    assert result["reason_code"] == "funding_conversion_filled"
    mock_client.place_order.assert_called_once()
    # upewnij się że side=SELL
    call_kwargs = mock_client.place_order.call_args
    assert call_kwargs.kwargs.get("side") == "SELL"


def test_fund_usdc_from_eur_if_needed_insufficient_both():
    """Gdy brak USDC i EUR — zwraca ok=False z USDC-denominated message."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}
    result = fund_usdc_from_eur_if_needed(
        mock_client,
        required_usdc=200.0,
        available_usdc=10.0,
        available_eur=5.0,
    )
    assert result["ok"] is False
    assert result["reason_code"] == "insufficient_usdc_and_eur"
    assert result["missing_usdc"] > 0
    # Komunikat musi być w USDC
    assert "USDC" in result["message"]


def test_ensure_usdc_balance_for_order_usdc_pair():
    """ensure_usdc_balance_for_order dla BTCUSDC sprawdza USDC + konwersję EUR."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}
    mock_client.get_allowed_symbols.return_value = {
        "EURUSDC": {"step_size": "0.1", "min_qty": "0.1"}
    }
    mock_client.place_order.return_value = {
        "orderId": 888,
        "executedQty": "50.0",
        "status": "FILLED",
    }
    mock_client.get_balances.return_value = [
        {"asset": "USDC", "free": "100.0"},
        {"asset": "EUR", "free": "50.0"},
    ]
    result = ensure_usdc_balance_for_order(
        mock_client,
        symbol="BTCUSDC",
        required_usdc=90.0,
    )
    # USDC=20 + EUR=50 → konwersja powinna być wywołana (USDC=20 < 90)
    # mock zwraca 100 po konwersji
    assert result["ok"] is True


def test_ensure_usdc_balance_for_order_eur_pair_sufficient():
    """ensure_usdc_balance_for_order dla BTCEUR sprawdza EUR bez konwersji."""
    mock_client = MagicMock()
    mock_client.get_balances.return_value = [
        {"asset": "EUR", "free": "120.0"},
        {"asset": "USDC", "free": "0.0"},
    ]
    result = ensure_usdc_balance_for_order(
        mock_client,
        symbol="BTCEUR",
        required_usdc=60.0,  # w tym kontekście = required_eur dla par EUR
    )
    assert result["ok"] is True
    assert result["reason_code"] == "eur_balance_sufficient"


def test_fund_usdc_messages_use_usdc_not_eur():
    """Wiadomości dla USDC par muszą mówić o USDC, nie EUR."""
    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}
    result = fund_usdc_from_eur_if_needed(
        mock_client,
        required_usdc=500.0,
        available_usdc=5.0,
        available_eur=2.0,
    )
    assert result["ok"] is False
    # Wiadomość musi zawierać "USDC" a nie tylko "EUR"
    msg = result.get("message", "")
    assert "USDC" in msg, f"Wiadomość powinna zawierać 'USDC': {msg!r}"
    assert "5.0000 USDC" in msg or "5" in msg


def test_enforce_final_min_quote_usdc_bumps_qty_after_rounding_drop():
    # qty=0.033 * 2000 = 66, ale przy step=0.01 i qty=0.03 mamy 60 (za mało)
    qty, meta = enforce_final_min_quote_usdc(
        qty=0.03,
        price=2000.0,
        required_min_notional=66.0,
        step_size=0.01,
    )
    assert meta["bumped"] is True
    assert qty * 2000.0 >= 66.0


def test_enforce_final_min_quote_usdc_keeps_qty_when_already_sufficient():
    qty, meta = enforce_final_min_quote_usdc(
        qty=0.04,
        price=2000.0,
        required_min_notional=66.0,
        step_size=0.001,
    )
    assert meta["bumped"] is False
    assert qty == 0.04
