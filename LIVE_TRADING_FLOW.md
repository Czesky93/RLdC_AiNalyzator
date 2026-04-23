# LIVE_TRADING_FLOW

## Przepływ end-to-end (LIVE)
1. Collector pobiera dane rynkowe (REST/WS) i zapisuje MarketData/Kline.
2. Analysis + collector budują sygnały i oceniają kandydatów.
3. Risk gates i cost gates filtrują wejścia (edge po kosztach, limity, cooldown, notional).
4. Decyzje są logowane w DecisionTrace z reason_code.
5. Wejście/wyjście realizowane przez:
   - auto flow collectora, lub
   - manual flow UI (POST /api/orders, close position, pending + confirm/reject).
6. Zlecenia LIVE trafiają do Binance (MARKET), wynik zapisywany do Order.
7. Portfolio/positions/account snapshot odświeżane i prezentowane w WWW.
8. Diagnostyka w UI pokazuje blockers, last decision, last order, freshness.

## Główne reason_code blokad wejścia
- insufficient_edge_after_costs
- symbol_not_in_live_watchlist
- cooldown_active
- max_positions_reached
- hold_mode_no_new_entries
- price_data_stale
- missing_binance_price
- min_notional_guard
- no_trend_confirmation
- confidence_below_threshold

## Główne endpointy operacyjne
- /api/account/trading-status
- /api/account/runtime-activity
- /api/account/capital-snapshot
- /api/orders (POST)
- /api/positions/{id}/close
- /api/positions/close-all

## Co zostało poprawione w sesji
- Runtime heartbeat endpoint dla panelu "co bot robi teraz".
- Live-only dostępność akcji pending/close w UI.
- Usunięcie demo-only guardów blokujących działania w LIVE.
