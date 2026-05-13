# CONFIG_AUDIT

## Single source of truth
- Runtime config: backend/runtime_settings.py + tabela RuntimeSetting
- Odczyt stanu: GET /api/control/state
- Aliasy stanu live:
  - live_trading_enabled (alias allow_live_trading)
  - trading_enabled (live mode + allow_live_trading)

## Kluczowe flagi runtime
- trading_mode: live/demo
- allow_live_trading: true/false
- demo_trading_enabled: true/false
- ws_enabled: true/false
- max_certainty_mode: true/false
- watchlist, symbol_tiers
- max_open_positions, max_trades_per_day
- maker_fee_rate, taker_fee_rate, slippage_bps, spread_buffer_bps
- min_edge_multiplier, min_expected_rr, min_order_notional

## Kluczowe ENV (operacyjne)
- BINANCE_API_KEY
- BINANCE_API_SECRET
- TRADING_MODE
- ALLOW_LIVE_TRADING
- WS_ENABLED
- ADMIN_TOKEN
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

## Wynik audytu sesji
- Control state jest spójny z frontendem LIVE.
- Frontend czyta live_trading_enabled (z fallbackiem).
- Runtime status i trading status raportują rzeczywiste blokery i świeżość danych.

## Ryzyka konfiguracyjne
- Błędny ADMIN_TOKEN zablokuje akcje mutujące.
- Brak kluczy Binance = brak realnego place_order w LIVE.
- WS_ENABLED=false zwiększa ryzyko danych nieświeżych.
