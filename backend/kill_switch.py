"""
Globalny kill switch RLdC — sprawdzanie flag BOT_ENABLED, TELEGRAM_ENABLED, TRADING_ENABLED, EXECUTION_ENABLED
"""
import os
from backend.runtime_settings import _SETTINGS, _parse_bool

def is_bot_enabled() -> bool:
    v = os.getenv("BOT_ENABLED", "true")
    return _parse_bool(v) is True

def is_telegram_enabled() -> bool:
    v = os.getenv("TELEGRAM_ENABLED", "true")
    return _parse_bool(v) is True

def is_trading_enabled() -> bool:
    v = os.getenv("TRADING_ENABLED", "true")
    return _parse_bool(v) is True

def is_execution_enabled() -> bool:
    v = os.getenv("EXECUTION_ENABLED", "true")
    return _parse_bool(v) is True

# Można rozszerzyć o odczyt z DB jeśli wymagane
