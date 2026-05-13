# STRATEGY_RULES

Data aktualizacji: 2026-04-14
Status: aktywny

## Zasady nadrzedne
- Bot nie moze wchodzic bez przewagi netto po kosztach.
- Bot nie moze duplikowac wejsc na ten sam symbol bez logiki.
- Bot nie moze handlowac na starych lub niespojnych danych.

## Entry gates (BUY/SELL)
- min_confidence gate
- min_score gate
- trend agreement gate
- expected_move_vs_cost gate
- min_notional gate
- symbol allowlist/tier gate
- cooldown gate
- max_open_positions gate
- capital_available gate

## Exit rules
- take_profit
- stop_loss
- trailing_stop
- break_even escalation
- reversal exit
- emergency exit
- time stop

## Position sizing
- limit kapitalu per trade
- limit ekspozycji per symbol
- limit ekspozycji portfela
- qty zgodne z Binance LOT_SIZE

## Mandatory reason codes (przyklady)
- insufficient_edge_after_costs
- symbol_not_in_live_watchlist
- cooldown_active
- max_positions_reached
- hold_mode_no_new_entries
- inconsistent_portfolio_sync
- price_data_stale
- missing_binance_price
- min_notional_guard
- sell_blocked_no_position
- no_trend_confirmation
- confidence_below_threshold

## Synchronizacja i spojnosc
- Stan pozycji/orderow/portfela ma byc spojny miedzy Binance, backend i WWW.
- Rozjazd synchronizacji musi dawac jawna blokade wejscia z reason_code.

## Uwagi operacyjne
- LIVE i DEMO sa obslugiwane rownolegle, ale metryki i raportowanie musza pozostawac rozdzielne.
- Kazda decyzja tradingowa musi zostawic slad diagnostyczny w execution trace.
