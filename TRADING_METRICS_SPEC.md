# TRADING_METRICS_SPEC

Data aktualizacji: 2026-04-14
Status: aktywny

## Cel
Zdefiniowac metryki tradingowe i ich znaczenie operacyjne.
Wszystkie metryki musza byc liczone w sposob audytowalny i porownywalny miedzy DEMO/LIVE.

## Metryki podstawowe
- gross_pnl: PnL przed kosztami
- fee_total: suma oplat (maker/taker + konwersje)
- slippage_cost: koszt poslizgu
- spread_cost: koszt spreadu
- net_pnl: gross_pnl - fee_total - slippage_cost - spread_cost
- equity: free_cash + market_value_open_positions

## Metryki skutecznosci
- win_rate = liczba_zyskownych / liczba_zamknietych
- expectancy = sredni_zysk_na_trade
- profit_factor = suma_zyskow / suma_strat_bezwzgledna
- avg_r_multiple = srednia wartosc R

## Metryki kosztowe
- fee_leakage = fee_total / max(1, gross_positive_pnl)
- cost_to_edge_ratio = (fee+spread+slippage) / expected_move

## Metryki ryzyka
- max_drawdown
- daily_drawdown
- open_risk_exposure (na symbol i portfel)
- overtrading_score (za czeste wejscia lub duzy churn)

## Metryki diagnostyczne decyzji
- entry_block_rate (ile sygnalow zablokowanych)
- top_rejection_reasons (ranking reason_code)
- stale_data_blocks
- inconsistent_sync_blocks

## Zasady obliczen
- Wszystkie wartosci PnL raportowac w walucie quote (domyslnie EUR).
- Brak kosztow w analizie okazji = blad krytyczny.
- Brak danych wymaganych do net_pnl = blokada decyzji wejscia.

## Minimalny zestaw endpointow kontrolnych
- /api/portfolio/wealth?mode=...
- /api/account/trading-status?mode=...
- /api/signals/execution-trace?mode=...
