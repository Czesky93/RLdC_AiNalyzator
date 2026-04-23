from __future__ import annotations

from backend.quote_service import get_validated_quote, invalidate_quote_cache


class _Client:
    def __init__(self, price_map):
        self.price_map = price_map

    def get_ticker_price(self, symbol):
        value = self.price_map.get(symbol)
        if value is None:
            raise Exception("404")
        return {"symbol": symbol, "price": value}

    def get_orderbook(self, symbol, limit=5):
        value = self.price_map.get(symbol)
        if value is None:
            raise Exception("404")
        return {"bids": [[value, 1]], "asks": [[value + 1, 1]]}


def _registry():
    return {
        "metadata": {"BTCUSDC": {"symbol": "BTCUSDC"}},
        "quote_filtered_universe": ["BTCUSDC"],
        "tradable_universe": ["BTCUSDC"],
    }


def test_invalid_symbol_never_reaches_quote_lookup(monkeypatch):
    invalidate_quote_cache()
    monkeypatch.setattr("backend.quote_service.get_symbol_registry", lambda *args, **kwargs: _registry())
    quote = get_validated_quote("FAKESYMBOL", binance_client=_Client({"BTCUSDC": 50000.0}))
    assert quote["success"] is False
    assert quote["error"] == "invalid_symbol"


def test_quote_lookup_404_soft_fails_without_crash(monkeypatch):
    invalidate_quote_cache()
    monkeypatch.setattr("backend.quote_service.get_symbol_registry", lambda *args, **kwargs: _registry())
    quote = get_validated_quote("BTCUSDC", binance_client=_Client({}))
    assert quote["success"] is False
    assert quote["error"] == "quote_unavailable"
