# TRADING_METRICS_SPEC.md — RLdC Trading BOT

**Wersja:** v0.7 beta | **Data:** 2 kwietnia 2026
**Cel:** Definicje wszystkich metryk używanych przez bota. Każde obliczenie kosztowe musi być zgodne z tymi definicjami.

---

## 1. DEFINICJE KOSZTÓW

### 1.1 Opłaty transakcyjne
```
fee_rate = taker_fee_rate  # domyślnie 0.001 = 0.1%
maker_fee_rate = 0.001     # 0.1% (przy limit orderach)
taker_fee_rate  = 0.001    # 0.1% (przy market orderach)
```

### 1.2 Koszty wejścia
```
entry_fees        = entry_price × qty × taker_fee_rate
slippage_bps      = 5.0   # 0.05% (5 bps — wartość z runtime_settings)
spread_buffer_bps = 3.0   # 0.03% (3 bps — wartość z runtime_settings)
slippage_pct      = slippage_bps / 10000      # 0.0005
spread_pct        = spread_buffer_bps / 10000 # 0.0003
entry_total_cost_pct = taker_fee_rate + slippage_pct + spread_pct
```

### 1.3 Koszty całkowite (round-trip)
```
total_cost_ratio = 2 × (taker_fee_rate + slippage_pct + spread_pct)
                 = 2 × (0.001 + 0.0005 + 0.0003)
                 = 2 × 0.0018
                 = 0.0036   # 0.36% round-trip
```
*Implementacja: `collector.py` linia ~2874: `(2 * taker_fee_rate) + (2 * slippage_bps / 10000.0) + (2 * spread_buffer_bps / 10000.0)`*

---

## 2. DEFINICJE EDGE I EXPECTED MOVE

### 2.1 Expected Move Ratio (dla BUY signal)
```
expected_move = ATR × atr_take_mult       # np. ATR × 3.5
expected_move_ratio = expected_move / entry_price
```

### 2.2 Cost Gate
```
PASS gdy: expected_move_ratio ≥ total_cost_ratio × min_edge_multiplier
                             ≥ 0.0036 × 2.5
                             ≥ 0.009  (0.9% minimalne ATR-TP wymagane)
```

### 2.3 Edge Netto
```
edge_net_score = expected_move_ratio - total_cost_ratio
```
*Reprezentuje "zysk na wejściu" w procentach po odjęciu kosztów.*

### 2.4 Composite Score (ranking kandydatów)
```
composite_score = edge_net_score × confidence × (rating / 5.0)
```
*Uwzględnia: efektywność kosztową × jakość sygnału × potwierdzenia techniczne.*

---

## 3. DEFINICJE PnL

### 3.1 Gross PnL (przy zamknięciu)
```
Dla LONG:
gross_pnl = (exit_price - entry_price) × qty

Dla SELL:
gross_pnl = (entry_price - exit_price) × qty
```

### 3.2 Net PnL (po wszystkich kosztach)
```
total_fees = (entry_price × qty × taker_fee_rate)
           + (exit_price  × qty × taker_fee_rate)
est_slip_spread = (entry_price × qty + exit_price × qty) × (slippage_pct + spread_pct)
net_pnl = gross_pnl - total_fees - est_slip_spread
```

### 3.3 Fee Leakage
```
fee_leakage = total_fees + est_slip_spread
fee_leakage_pct = fee_leakage / (entry_price × qty)
```
*Wskaźnik overtrading: suma fee/leakage w stosunku do obrotu.*

---

## 4. EQUITY I PORTFOLIO

### 4.1 Total Equity
```
equity = available_cash + positions_value_mark_to_market
```

### 4.2 Positions Value (MTM)
```
positions_value = Σ (current_price_i × qty_i)  dla każdej otwartej pozycji i
```

### 4.3 Unrealized PnL
```
unrealized_pnl = Σ ((current_price_i - entry_price_i) × qty_i)
```

### 4.4 Realized PnL
```
realized_pnl = Σ net_pnl_j  dla wszystkich zamkniętych transakcji j
```

### 4.5 Equity Curve
- Snapshot co interwał (godzina, koniec dnia)
- Format: `{timestamp, equity, realized_pnl_cumul, unrealized_pnl, open_positions_count}`

---

## 5. METRYKI SKUTECZNOŚCI

### 5.1 Win Rate
```
win_rate = liczba_transakcji_zysk / całkowita_liczba_transakcji
```
*Cel: win_rate > 40% przy R/R ≥ 2.0 daje positive expectancy.*

### 5.2 Profit Factor
```
gross_profit = Σ net_pnl_j  dla j gdzie net_pnl_j > 0
gross_loss   = Σ |net_pnl_j| dla j gdzie net_pnl_j < 0
profit_factor = gross_profit / max(gross_loss, 1e-9)
```
*Cel: profit_factor > 1.5. Wartości < 1.0 = bot traci więcej niż zarabia.*

### 5.3 Expectancy (per trade)
```
avg_win  = gross_profit / n_wins
avg_loss = gross_loss   / n_losses
expectancy = (win_rate × avg_win) - ((1 - win_rate) × avg_loss)
```
*Cel: expectancy > 0 EUR per transakcję.*

### 5.4 Maximum Adverse Excursion (MAE)
```
MAE = entry_price - lowest_price_during_holding  # dla LONG
```
*Miara jak głęboko cena poszła przeciw nam zanim wyszła.*

### 5.5 Maximum Favorable Excursion (MFE)
```
MFE = highest_price_during_holding - entry_price  # dla LONG
```
*Jak wysoko cena mogła pójść — różnica MFE vs exit pokazuje efektywność TP.*

### 5.6 Edge Ratio
```
edge_ratio = avg_MFE / avg_MAE
```
*Cel: edge_ratio > 1.5. Poniżej 1.0 = bot trzyma stratnych dłużej niż zyskownych.*

---

## 6. METRYKI RYZYKA

### 6.1 Daily Drawdown
```
daily_drawdown = (equity_max_dzisiaj - equity_biezace) / equity_max_dzisiaj
```
*Blokada wejść gdy > 3% (max_daily_drawdown).*

### 6.2 Weekly Drawdown
```
weekly_drawdown = (equity_max_tydzien - equity_biezace) / equity_max_tydzien
```
*Blokada wejść gdy > 7% (max_weekly_drawdown).*

### 6.3 Max Drawdown All Time (MDD)
```
MDD = max((peak_i - trough_i) / peak_i)  dla wszystkich trough po każdym peak_i
```

### 6.4 Kelly Fraction (informacyjnie)
```
kelly = win_rate - (1 - win_rate) / (avg_win / avg_loss)
```
*Nie używany jako limiter — tylko referencyjna metryka.*

### 6.5 Daily Loss Alert
```
Telegram alert gdy: dzienna_strata > alert_daily_loss_pct (domyślnie 2%)
Blokada wejść gdy:  dzienna_strata > max_daily_drawdown (domyślnie 3%)
```

---

## 7. METRYKI OVERTRADING

### 7.1 Overtrading Score
```
overtrading_score = fee_leakage_total_7d / avg_equity_7d × 100
```
*Cel: < 3%. Powyżej 5% = bot "przejada" kapitał na kosztach.*

### 7.2 Trade Frequency vs Edge
```
avg_edge_per_trade = Σ edge_net_score_j / n_transakcji
```
*Cel: avg_edge > 0.02 (2% edge netto per trade).*

### 7.3 Fee Efficiency Ratio
```
fee_efficiency = Σ net_pnl / Σ fee_leakage
```
*Ile zarobiliśmy na każdy 1 EUR zapłacony w kosztach. Cel: > 2.0*

---

## 8. SIGNAL QUALITY METRICS

### 8.1 Signal Confidence
```
base_conf = 0.58 + min(0.30, |score| × 0.06)
multi_tf_adj    = ±0.04..0.05  (4h konfluencja)
sentiment_adj   = ±0.02..0.05  (F&G + CoinGecko)
confidence = clamp(base_conf + adjustments, 0.50, 0.95)
```

### 8.2 Signal Score (raw)
```
score = Σ wskaźniki_j  (j = RSI, EMA, MACD, Stoch, …, ~24 wskaźników)
Range: [-20, +20]
Próg BUY:  score ≥ +3
Próg SELL: score ≤ -3
```

### 8.3 Forecast Accuracy
```
accuracy = n_prawidlowe_prognozy / n_wszystkich_prognoz
Miara: czy sygnał BUY doprowadził do + po horizon_minutes?
```
*Target: accuracy > 55% przy horizon 4h.*

---

## 9. METRYKI PORTFOLIO

### 9.1 Sortino Ratio
```
downside_deviation = sqrt(Σ min(0, return_i)^2 / n)
sortino = avg_return / downside_deviation
```
*Lepsza miara niż Sharpe, ignoruje pozytywną zmienność.*

### 9.2 Calmar Ratio
```
calmar = roczna_zwrot_procentowy / MDD
```
*Cel: calmar > 1.0.*

---

## 10. AKTUALNE WARTOŚCI REFERENCYJNE

| Metryka | Bieżąca wartość | Cel |
|---------|-----------------|-----|
| Equity | 997.06 EUR (demo) | rosnące |
| Open positions | 0 | 0-5 |
| Win rate | brak danych (0 transakcji) | > 40% |
| Profit factor | brak danych | > 1.5 |
| Total cost ratio | ~0.36% round-trip | - |
| Min edge (cost gate) | 0.9% (2.5×) | - |
| Daily drawdown limit | 3% | - |
| Market regime | CRASH (F&G=12) | SIDEWAYS/BULL |
| buy_blocked | True | False |

---

## UWAGI O IMPLEMENTACJI

1. `accounting.py` — SINGLE SOURCE OF TRUTH dla PnL, equity, fee_leakage
2. `risk.py` — SINGLE SOURCE OF TRUTH dla drawdown gates, kill_switch
3. `collector.py` — liczy koszty per-candidate w `_screen_entry_candidates()`
4. `reporting.py` — agreguje i prezentuje metryki z accounting.py
5. **Każde nowe miejsce kalkulacji kosztów** musi być zsynchronizowane z sekcją 1.3 tego dokumentu
6. **Nie wolno** mieć rozbieżnych definicji fee_rate w różnych modułach
