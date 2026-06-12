# TRADING_METRICS_SPEC.md — RLdC Trading BOT

## Cel
Ustalić twarde KPI „best bot” oparte o realny wynik netto po kosztach i spójność danych.

## KPI główne (source-of-truth)

1. **net_pnl_after_costs**  
   - Definicja: suma `net_pnl` dla zamkniętych transakcji (po fee/slippage/spread).  
   - Źródło: `backend/accounting.py` + `backend/reporting.py`.

2. **max_drawdown_net**  
   - Definicja: bieżący dzienny drawdown netto portfela.  
   - Źródło: `compute_risk_snapshot()` (`daily_net_drawdown`).

3. **profit_factor_net**  
   - Definicja: relacja zysków netto do strat netto dla zamkniętych transakcji.  
   - Źródło: `summarize_orders()` / `performance_overview()`.

4. **overtrading_score**  
   - Definicja: skala 0..1 oparta o nadmiar transakcji vs target 24h i presję blokad aktywności/cooldown.  
   - Źródło: `performance_overview()` (`trades_24h`, `target_trades_24h`, `activity_blocks_24h`).

5. **sync_stability**  
   - Definicja: stabilność zgodności symboli pozycji Binance spot vs lokalna tabela `Position` (LIVE).  
   - Źródło: `performance_overview()` → `_live_sync_stability()`.

## Endpoint referencyjny KPI

- **GET `/api/account/analytics/best-bot-kpi?mode=demo|live`**
- Zwraca:
  - `net_pnl_after_costs`
  - `max_drawdown_net`
  - `profit_factor_net`
  - `overtrading_score`
  - `sync_stability`
  - metryki pomocnicze 24h (`trades_24h`, `target_trades_24h`, `activity_blocks_24h`, `cost_leakage_ratio`)

## Progi operacyjne (v0.7)

- `overtrading_score <= 0.35` → bezpiecznie  
- `0.35 < overtrading_score <= 0.60` → ostrzeżenie  
- `overtrading_score > 0.60` → wymagane zaostrzenie filtrów wejścia

- `sync_stability.score >= 0.95` → spójność bardzo dobra  
- `0.70 <= score < 0.95` → częściowa niespójność, monitorować  
- `score < 0.70` lub `status=inconsistent` → blokada nowych wejść LIVE do czasu diagnostyki
