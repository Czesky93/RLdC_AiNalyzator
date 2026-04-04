# STRATEGY_RULES.md — RLdC Trading BOT

**Wersja:** v0.7 beta | **Data:** 2 kwietnia 2026
**Autorytet:** Kod jest źródłem prawdy. Ten dokument opisuje AKTUALNIE ZAIMPLEMENTOWANE reguły.

---

## ZASADA NADRZĘDNA

Bot nie ma przewidywać rynku idealnie.
Bot ma działać jak **zdyscyplinowany operator przewagi**:
- wchodzi tylko gdy edge netto > 0 po kosztach,
- preferuje jakość sygnału nad częstotliwość transakcji,
- szybko ucina złe wejścia,
- nie handluje bez planu wyjścia,
- raportuje KAŻDĄ blokadę z konkretnym powodem.

---

## 1. WARUNKI OTWARCIA POZYCJI (BUY)

Wszystkie niżej wymienione muszą być prawdziwe jednocześnie:

### 1.1 Sygnał bazowy
- `signal_type = BUY`
- `confidence ≥ base_min_confidence` (domyślnie 0.55 dla balanced)
- `signal_age < 3600s`

### 1.2 Reżim rynkowy
- `market_regime ≠ CRASH` i `market_regime ≠ BEAR` (czyli `buy_blocked = False`)
- **WYJĄTEK (mean-reversion override):**
  - `RSI < extreme_oversold_rsi_threshold` (domyślnie 28)
  - `confidence ≥ bear_oversold_bypass_conf` (domyślnie 0.55)
  - Pozycja skalowana do 25% (crash_sizing)
  - Sygnał oznaczany jako `mean_reversion_entry`

### 1.3 Filtry techniczne (przynajmniej jedno z dwóch)
Cena w strefie BUY (AI/heuristic) LUB soft entry:

**Normalne wejście (AI range):**
- `buy_low ≤ cena ≤ buy_high` (z 3% tolerancją)
- `trend_up = True` (EMA20 > EMA50 OR Supertrend > 0)
- `RSI ≤ rsi_buy_gate` (domyślnie 65)

**Soft entry (brak zakresu AI):**
- `trend_up = True`
- `RSI < 55` (bez overextension)
- Wejście fallback przez wskaźniki (Supertrend + EMA + RSI)

### 1.4 Quality gates
- `rating ≥ min_rating` (domyślnie 2/5)
  - Rating z: confidence + EMA + Supertrend + RSI + ADX + wolumen
- `cost_gate_pass = True`: `expected_move_ratio ≥ total_cost_ratio × 2.5`
  - `expected_move_ratio = ATR × atr_take_mult / price`
  - `total_cost_ratio = 2×taker_fee + 2×slippage + 2×spread`
- `R/R ≥ 1.5`: `atr_take_mult / atr_stop_mult ≥ min_expected_rr`

### 1.5 Risk gates
- `max_open_positions` nie przekroczony (domyślnie 5)
- `daily_drawdown < max_daily_loss_pct` (domyślnie 3%)
- `kill_switch = False`
- Brak istniejącej pozycji w tym symbolu
- Brak aktywnego pending order
- Cooldown po ostatnim order NIE aktywny

### 1.6 Notional guard
- `qty × price ≥ min_order_notional` (domyślnie 60 EUR)
- `available_cash ≥ min_order_notional`

---

## 2. WARUNKI ZAMKNIĘCIA POZYCJI (EXIT)

Przetwarzane w kolejności priorytetu — pierwsza spełniona warunkuje exit:

### WARSTWA 1: Stop Loss
- `cena ≤ entry_price - ATR × atr_stop_mult` (domyślnie 2.0)
- Lub `cena ≤ planned_sl` (z momentu wejścia)
- **Exit type:** `stop_loss_hit`
- **Telegram:** 🔴 `STOP LOSS — limit straty osiągnięty`

### WARSTWA 1b: Break-even upgrade
- Gdy `cena ≥ entry_price + ATR × break_even_atr_trigger` (domyślnie 1.0)
- Przesuń SL do `entry_price` (chroni przed stratą, pozycja "na zero")
- Nie zamyka pozycji — zmienia tylko poziom SL

### WARSTWA 2: Trailing Stop
- Aktywuje się po pierwszym Partial TP (25%)
- `trailing_stop = max(price - ATR × trail_mult, poprzedni_trailing)` (domyślnie 1.5)
- Gdy `cena ≤ trailing_stop` → exit
- **Exit type:** `trailing_lock_profit`
- **Telegram:** 🟠 `TRAILING STOP — zabezpieczenie zysku`

### WARSTWA 3: Take Profit (częściowy)
- Gdy `cena ≥ take_profit (entry + ATR × atr_take_mult)` i trend nadal trwa
- Zamknij **25%** pozycji, zostaw resztę
- Aktywuje Trailing Stop na resztcie
- **Exit type:** `tp_partial_keep_trend`
- **Telegram:** 🟢 `CZĘŚCIOWE TP (25%) — trend trwa`

### WARSTWA 4: Take Profit (pełny) lub Reversal
- Gdy `cena ≥ take_profit` i trend słabnie (EMA cross lub ST odwrócenie)
- Lub gdy `partial_take_count > 0` i trend odwrócił się
- Zamknij 100% pozycji
- **Exit type:** `tp_full_reversal` lub `weak_trend_after_tp`
- **Telegram:** 🟡 `ZAMKNIĘCIE — trend słabnie`

---

## 3. WARUNKI BRAKU DZIAŁANIA (HOLD)

Bot NIE handluje gdy:

| Kod | Warunek |
|-----|---------|
| `market_regime_buy_blocked` | F&G ≤ 20 + MCap < -1% → BEAR/CRASH |
| `signal_confidence_too_low` | confidence < min_confidence |
| `signal_too_old` | sygnał starszy niż 3600s |
| `signal_filters_not_met` | cena poza strefą + brak trendu + RSI |
| `cost_gate_failed` | expected_move < 2.5 × koszty |
| `min_notional_guard` | notional < 60 EUR |
| `active_pending_exists` | jest nierozliczony pending order |
| `pending_cooldown_active` | < 300s od ostatniego pending |
| `symbol_cooldown_active` | cooldown po loss_streak aktywny |
| `tier_daily_trade_limit` | limit dziennych transakcji na symbol |
| `buy_blocked_existing_position` | już mamy pozycję w tym symbolu |
| `sell_blocked_no_position` | SELL sygnał, brak pozycji (nie shortujemy) |
| `max_open_positions_reached` | maksymalna liczba pozycji otwarta |
| `daily_loss_gate` | dzienna strata > 3% |
| `kill_switch_gate` | kill_switch aktywny |

---

## 4. POSITION SIZING

### Formuła bazowa
```
risk_amount = equity × risk_per_trade_pct
stop_distance = ATR × atr_stop_mult
qty_base = risk_amount / stop_distance
```

### Skalowania
| Czynnik | Efekt |
|---------|-------|
| `tier_risk_scale` | CORE=1.0, ALTCOIN=0.7, SPECULATIVE=0.3, SCANNER=0.5 |
| `loss_streak` | qty × (1 - loss_streak × 0.15) — max redukcja do 0.2× |
| `win_streak` | qty × (1 + min(win_streak × 0.05, 0.20)) |
| crash mode | qty × 0.25 |
| `position_size_multiplier` | z evaluate_risk() — dodatkowe ryzyko |

### Limity
- `min_qty = 0.001`
- `max_qty = 1.0`
- `max_cash_per_trade = equity / max_open_positions`
- `min_order_notional = 60 EUR`

---

## 5. CANDIDATE RANKING

Gdy przejdzie wiele symboli przez wszystkie filtry, priorytet ustalany jest przez:

```
composite_score = edge_net_score × confidence × (rating / 5.0)
```

gdzie:
```
edge_net_score = (ATR × atr_take_mult / price) - (2×fee + 2×slippage + 2×spread)
```

- **Wyższy edge_net_score** = większy expected return vs koszty (ATR/price)
- **Wyższy confidence** = silniejszy sygnał (multi-TF, wskaźniki, F&G)
- **Wyższy rating** = więcej potwierdzeń technicznych (EMA+ST+RSI+ADX+Vol)

**Bierzemy max N kandydatów** gdzie `N = max_open_positions - aktualnie_otwarte`.

---

## 6. SYMBOL TIERS — PARAMETRY

| Tier | Symbole | min_conf_add | risk_scale | max/dzień |
|------|---------|-------------|-----------|-----------|
| CORE | BTC, ETH, SOL, BNB (EUR+USDC) | +0.00 | 1.0 | 10 |
| ALTCOIN | ETC, SHIB, SXT (USDC) | +0.05 | 0.7 | 3 |
| SPECULATIVE | WLFI (EUR+USDC) | +0.10 | 0.3 | 2 |
| SCANNER | nowe (top-30 wolumen) | +0.07 | 0.5 | 1 |

---

## 7. MARKET REGIME — PROGI

| Regime | Warunek | buy_blocked | buy_conf_adj |
|--------|---------|-------------|-------------|
| CRASH | F&G ≤ 15 + MCap < -2.5% | ✓ True | +0.20 |
| BEAR | F&G ≤ 20 + MCap < -1.0% | ✓ True | +0.15 |
| BEAR_SOFT | F&G ≤ 30 + MCap < 0% | ✗ False | +0.10 |
| SIDEWAYS | inne | ✗ False | 0.00 |
| BULL | F&G ≥ 75 + MCap > 2.0% | ✗ False | -0.05 |
| UNKNOWN | brak danych F&G | ✗ False | 0.00 |

---

## 8. ZASADY AUTONOMII BOTA

1. Bot **sam** skanuje rynek co 60s — bez interwencji użytkownika
2. Bot **sam** generuje sygnały i zakresy (heuristic co cykl, AI co 1h)
3. Bot **sam** filtruje kandydatów przez 19 warstw filtrów
4. Bot **sam** rankuje kandydatów po jakości (composite_score)
5. Bot **sam** kalkuluje rozmiar pozycji
6. Bot **sam** zarządza TP/SL/trailing bez interwencji
7. Bot **sam** wykrywa CRASH i blokuje BUY
8. Bot **sam** informuje o każdej blokadzie (Telegram idle alert co 30 min)
9. Bot NIE potrzebuje ręcznego potwierdzenia transakcji (`demo_require_manual_confirm = False`)
10. Bot **zawsze** loguje przyczynę każdej decyzji do DecisionTrace

---

## 9. CZEGO BOT NIE ROBI

- **NIE shortuje** (SELL tylko gdy ma otwartą pozycję LONG)
- **NIE scaluje** bez sygnału (nie dokłada bez nowego sygnału)
- **NIE wchodzi** gdy edge < koszty
- **NIE handluje** w trybie CRASH bez mean-reversion override
- **NIE otwiera** duplikatów (jedna pozycja per symbol)
- **NIE ignoruje** cooldownów
- **NIE ukrywa** blokad — każda ma reason_code i reason_pl
- **NIE obiecuje** braku strat (SL jest zawsze aktywny)

---

## 10. PARAMETRY DOMYŚLNE (profil balanced)

| Parametr | Wartość | Opis |
|----------|---------|------|
| `demo_min_signal_confidence` | 0.55 | Min pewność sygnału |
| `atr_stop_mult` | 2.0 | Stop loss: entry - 2×ATR |
| `atr_take_mult` | 3.5 | Take profit: entry + 3.5×ATR |
| `atr_trail_mult` | 1.5 | Trailing: highest - 1.5×ATR |
| `min_edge_multiplier` | 2.5 | Expected move / koszty min |
| `min_expected_rr` | 1.5 | Min R/R ratio |
| `min_order_notional` | 60 EUR | Min wielkość zlecenia |
| `max_open_positions` | 5 | Max otwartych naraz |
| `risk_per_trade` | 0.01 | 1% kapitału na ryzyko |
| `pending_order_cooldown_seconds` | 300 | 5 min między pending |
| `max_daily_drawdown` | 0.03 | 3% max dzienna strata |
| `max_weekly_drawdown` | 0.07 | 7% max tygodniowa strata |
| `bear_regime_min_conf` | 0.82 | Min conf w BEAR/CRASH |
| `extreme_oversold_rsi_threshold` | 28.0 | RSI do mean-reversion override |
| `break_even_atr_trigger` | 1.0 | ATR do break-even upgrade |
