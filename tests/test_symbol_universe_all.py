import os
from backend.symbol_universe import validate_symbol

def test_symbol_universe_all(monkeypatch):
    monkeypatch.setenv("TRADE_ALL_SYMBOLS", "true")
    # symbol nie w tierach, ale istnieje w metadata i jest aktywny
    dummy_registry = {
        "metadata": {
            "SHIBEUR": {"symbol": "SHIBEUR", "active": True},
            "APEEUR": {"symbol": "APEEUR", "active": True},
        },
        "quote_filtered_universe": [],
        "tradable_universe": [],
    }
    res = validate_symbol("SHIBEUR", registry=dummy_registry)
    assert res["valid"]
    assert res["in_active_universe"]
    monkeypatch.delenv("TRADE_ALL_SYMBOLS", raising=False)
    # symbol_universe=ALL
    monkeypatch.setenv("SYMBOL_UNIVERSE", "ALL")
    res2 = validate_symbol("APEEUR", registry=dummy_registry)
    assert res2["valid"]
    assert res2["in_active_universe"]
    monkeypatch.delenv("SYMBOL_UNIVERSE", raising=False)
