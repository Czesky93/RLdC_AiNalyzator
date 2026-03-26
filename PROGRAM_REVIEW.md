# PROGRAM REVIEW — Rdzeń tradingowy vs Warstwa kontrolna

**Data:** 2025-07  
**Wersja:** v0.7-beta  
**Commit bazowy:** `c0eac1f` (167 testów)  
**Autor przeglądu:** GitHub Copilot (Claude Opus 4.6)

---

## Cel dokumentu

Ocena dojrzałości **rdzenia tradingowego** (kolektor → sygnał → wejście → egzekucja → wyjście)
w stosunku do **warstwy kontrolnej** (governance, risk gates, experiments, tuning, rollback).

Pytania do odpowiedzi:
- A) Czy entry logic jest wystarczająco rozbudowana?
- B) Czy execution path pokrywa scenariusze live?
- C) Czy warstwa strategii jest wydzielona?
- D) Czy symbol selection ma jakościowy ranking?
- E) Czy runtime_settings obejmuje krytyczne parametry?
- F) Czy decision trace daje wystarczającą obserwabilność?

---

## SEKCJA 1 — Co jest świetnie domknięte ✅

### 1.1 Warstwa kontrolna i governance (ETAP 1-8)

System posiada **jeden z najbardziej rozbudowanych frameworków kontroli zmian** jaki można spotkać w botach tradingowych tej skali:

| Moduł | Linie | Co robi |
|---|---|---|
| `runtime_settings.py` | 817 | ~30 tunowalnych parametrów z walidacją, snapshotami, API |
| `risk.py` | 227 | 10 bram ryzyka (drawdown, exposure, loss streak, kill switch, leakage, expectancy) |
| `experiments.py` | 457 | A/B framework z metrykami, promocją, wycofywaniem |
| `candidate_validation.py` | 514 | Walidacja kandydatów zmian, detekcja konfliktów, pakowanie bundli |
| `tuning_insights.py` | 566 | Automatyczne kandydaty zmian z diagnostyki |
| `promotion_flow.py` | 209 | Promocja kandydatów z monitoring post-promotion |
| `rollback_flow.py` | 158 | Bezpieczne wycofanie zmian |
| `rollback_decision.py` | 246 | Heurystyka decyzji rollback |
| `post_promotion_monitoring.py` | 278 | Monitoring po promocji |
| `post_rollback_monitoring.py` | 278 | Monitoring po rollbacku |
| `review_flow.py` | 143 | Ścieżka recenzji zmian |
| `trading_effectiveness.py` | 716 | Diagnostyka: edge, overtrading, cost leakage, per-symbol/strategy |

**Łącznie ~4600 linii kodu kontrolnego.** To jest ~2.5x więcej niż sam rdzeń tradingowy.

### 1.2 Risk gates — dojrzałe i dobrze zintegrowane

`evaluate_risk()` sprawdza **10 bram** przed każdym wejściem:
1. Kill switch
2. Dzienny drawdown (max_daily_drawdown)
3. Seria strat (loss_streak_limit)
4. Max otwartych pozycji
5. Max transakcji / dzień
6. Max transakcji / godzinę / symbol
7. Całkowita ekspozycja
8. Ekspozycja na symbol
9. Cost leakage ratio
10. Net expectancy (symbol + strategia)

Każda brama generuje `reason_code`, zapisywany w DecisionTrace — można odtworzyć *dlaczego* transakcja została zablokowana.

### 1.3 Cost-aware accounting

`accounting.py` (547 linii) poprawnie modeluje:
- Gross PnL vs Net PnL (po fee, slippage, spread)
- Cost breakdown per order/position
- CostLedger z `expected_value` i `actual_value`
- Risk snapshot i activity snapshot do bram ryzyka

### 1.4 Decision Trace — struktura OK

Model `DecisionTrace` posiada:
- `signal_summary` — parametry sygnału w momencie decyzji
- `risk_gate_result` — wynik bram ryzyka
- `cost_gate_result` — wynik bramy kosztowej
- `execution_gate_result` — wynik bramy egzekucji
- `config_snapshot_id` — powiązanie z dokładną konfiguracją
- `strategy_name`, `reason_code`, `action_type`

Collector faktycznie zapisuje trace dla **zarówno odrzuconych jak i zaakceptowanych** decyzji (`_trace_decision()`).

### 1.5 Provider fallback (AI_PROVIDER=auto)

`analysis.py` posiada **trzy ścieżki** generowania price ranges:
1. `openai` — GPT via API (domyślne)
2. `heuristic` — ATR + Bollinger bands (darmowe, bez API)
3. `auto` — OpenAI z fallbackiem na heurystykę

Heurystyka (`_heuristic_ranges`) jest solidna: ATR-based widths, alignment z Bollinger bands, korekty RSI, korekta trendu. System **nie jest 100% zależny od OpenAI** — ma darmowy fallback.

### 1.6 Kalibracja na historii

`_learn_from_history()` co 1h kalkuluje per-symbol:
- `min_confidence` — dynamicznie na bazie zmienności
- `risk_scale` — skalowanie pozycji wg vol
- `volatility`, `trend_strength`

To prosty ale działający mechanizm adaptacji.

---

## SEKCJA 2 — Co jest średnie lub niezweryfikowane ⚠️

### 2.1 Monolityczna `_demo_trading()` — ~700 linii w jednej metodzie

**Problem:** Cała logika tradingowa (wyjścia TP/SL, filtrowanie sygnałów, position sizing, cost gate, risk gate, pending order) jest w jednej metodzie `_demo_trading()` w `collector.py`.

**Konsekwencje:**
- Nie da się testować fragmentów w izolacji
- Każda zmiana w entry logic dotyka tego samego 700-liniowego bloku
- Ryzyko efektów ubocznych przy refactorze

**Rekomendacja:** Wydzielić do osobnych metod:
- `_screen_entry_signals()` → filtrowanie i rating
- `_compute_position_size()` → sizing
- `_check_exits()` → TP/SL/trailing
- `_create_pending_entry()` → tworzenie pending order

### 2.2 Jedna strategia: "demo_collector"

**Problem:** `strategy_name` istnieje w DecisionTrace i PendingOrder, ale **zawsze** ma wartość `"demo_collector"`. Nie ma mechanizmu:
- definiowania innych strategii
- porównania strategii (poza retrospektywnym `trading_effectiveness`)
- wyłączenia jednej strategii bez wyłączenia całego tradingu

**Konsekwencje:**
- `enabled_strategies` w runtime_settings istnieje, ale nigdzie nie jest sprawdzane w `_demo_trading()`
- `compute_strategy_performance()` zwraca zawsze jedną strategię
- Experiments framework jest gotowy na multi-strategy, ale silnik nie

**Rekomendacja:** Minimum viable: choćby dwa warianty entry logic (np. "conservative" vs "aggressive") z różnymi progami extreme_min_conf / rating.

### 2.3 ~20 env vars w collector NIE przeniesione do runtime_settings

**Stan obecny:** `collector.py` czyta ~20 parametrów z `os.getenv()` zamiast z `runtime_settings`:

| Env var | Domyślna | Powinien być w runtime_settings? |
|---|---|---|
| `DEMO_ORDER_QTY` | 0.01 | ✅ TAK — krytyczny |
| `DEMO_MIN_SIGNAL_CONFIDENCE` | 0.75 | ✅ TAK — krytyczny |
| `DEMO_MAX_SIGNAL_AGE_SECONDS` | 3600 | ✅ TAK |
| `DEMO_MIN_KLINES` | 60 | Opcjonalnie |
| `ATR_STOP_MULT` | 1.3 | ✅ TAK — krytyczny |
| `ATR_TAKE_MULT` | 2.2 | ✅ TAK — krytyczny |
| `ATR_TRAIL_MULT` | 1.0 | ✅ TAK — krytyczny |
| `EXTREME_RANGE_MARGIN_PCT` | 0.02 | ✅ TAK |
| `EXTREME_MIN_CONFIDENCE` | 0.85 | ✅ TAK |
| `EXTREME_MIN_RATING` | 4 | ✅ TAK |
| `CRASH_WINDOW_MINUTES` | 60 | Opcjonalnie |
| `CRASH_DROP_PERCENT` | 6.0 | Opcjonalnie |
| `CRASH_COOLDOWN_SECONDS` | 7200 | Opcjonalnie |
| `CRASH_MIN_CONFIDENCE` | 0.85 | Opcjonalnie |
| `PENDING_ORDER_COOLDOWN_SECONDS` | 3600 | ✅ TAK |
| `MAX_AI_INSIGHTS_AGE_SECONDS` | 7200 | ✅ TAK |
| `DEMO_MAX_POSITION_QTY` | 1.0 | ✅ TAK |
| `DEMO_MIN_POSITION_QTY` | 0.001 | ✅ TAK |
| `DEMO_INITIAL_BALANCE` | 10000 | Opcjonalnie |

**Wpływ:** Te parametry **nie mogą być zmieniane bez restartu bota**. Runtime settings + experiments pipeline ich nie widzi. Tuning insights nie może generować dla nich kandydatów zmian.

### 2.4 Model kosztowy — szacunkowy, nie zmierzony

**Problem:** `cost_gate_result` w DecisionTrace zawiera `expected` koszty:
- `taker_fee` = `notional × taker_fee_rate`
- `slippage` = `notional × slippage_bps / 10000`
- `spread` = `notional × spread_buffer_bps / 10000`

Ale **nigdy nie mierzy faktycznych kosztów** — bo w trybie DEMO nie ma realnych egzekucji. `CostLedger` ma pola `expected_value` i `actual_value`, ale `actual_value` jest zawsze NULL w trybie demo.

**Konsekwencje:**
- `cost_leakage_ratio` w diagnostyce trading_effectiveness bazuje na szacunkach
- Nie wiadomo, czy `slippage_bps=5` jest realistyczne
- Przejście na live ujawni rozbieżności

**Rekomendacja:** Przy wejściu live — natychmiast dodać pomiar `actual_value` z Binance fills i porównanie expected vs actual.

### 2.5 Symbol selection — brak rankingu/scoringu

**Obecna logika:**
1. Pobierz balanse z Binance → wyciągnij aktywa z `free > 0`
2. Dołącz `USDT` do każdego → powstaje watchlist
3. Możliwość override z runtime_settings

**Brakuje:**
- Rankingu symboli wg siły trendu / momentum / volatility
- Filtrowania symboli o niskim wolumenie / spreadzie
- Dynamicznego dodawania/usuwania symboli na bazie screenerów
- Priorytetyzacji (symbol z lepszym edge powinien mieć wyższy priorytet)

**Rekomendacja:** Minimum viable: filtruj po wolumenie 24h i przesortuj watchlist wg ATR/price (normalized volatility).

### 2.6 Brak live execution path

**Problem:** `binance_client.py` (426 linii) nie posiada:
- `place_order(symbol, side, qty, price)` — nawet jako stub
- `cancel_order()`
- `get_order_status()`
- Logiki market/limit order

Cały flow jest DEMO:
```
Signal → PendingOrder → Telegram /confirm → collector writes Order/Position to DB
```

Nie ma żadnego kodu, który **wysyła zlecenie na Binance**. Przejście na live wymaga napisania execution layer od zera.

**Rekomendacja:** Dodać minimalny execution module:
- `execute_market_order(symbol, side, qty)` z Binance API
- `get_order_fills(order_id)` dla pomiaru actual costs
- Circuit breaker (max N orders per minute)

---

## SEKCJA 3 — Co ma największy wpływ na wynik bota 💰

Poniżej posortowane od **największego** do **najmniejszego** wpływu na PnL:

### 🏆 3.1 Entry timing i quality (KRYTYCZNY)

**Obecny flow:**
```
Signal (confidence ≥ 0.75)
→ EMA20 > EMA50 (trend filter)
→ RSI ≤ rsi_buy (oversold filter)
→ Cena w buy_low–buy_high range (AI/heuristic)
→ Extreme entry filter (cena na krawędzi zakresu, margin 2%)
→ Rating ≥ 4/5 AND confidence ≥ 0.85
→ Cost gate (expected_move > required_move)
→ Risk gate (10 bram)
→ PendingOrder → Telegram → confirm
```

**Ocena:** Entry logic jest **rygorystyczna** — 7 warstw filtrowania. To chroni przed złymi wejściami, ale może też powodować **zbyt mało transakcji**. Brak danych o hit rate, frequency, missed opportunities.

**Klucz do poprawy PnL:**
- Zmierzyć jak często bot **pomija** dobre okazje (false negatives)
- A/B test: strict vs relaxed extreme_margin_pct
- Dodać alternatywny entry mode (np. momentum-based bez wymogu AI ranges)

### 🥈 3.2 Exit logic — TP/SL/trailing (WAŻNY)

**Obecny flow:**
- **Stop Loss:** `entry_price - ATR × 1.3` (long), `entry_price + ATR × 1.3` (short)
- **Take Profit:** `entry_price + ATR × 2.2` (long), `entry_price - ATR × 2.2` (short)
- **Trailing stop:** Gdy EMA20 > EMA50, SL podąża za ceną (`price - ATR × trail_mult`)
- Sprawdzenie: co cykl (`COLLECTION_INTERVAL_SECONDS=60s`)

**Problemy:**
- TP/SL nie są dynamiczne po wejściu — ATR z momentu entry, nie aktualizowany
- Brak partial exits (np. sprzedaj 50% na TP1, 50% na TP2)
- Trailing stop aktywuje się tylko przy trend confirmation (EMA20 > EMA50) — w ranging market TP/SL są statyczne
- Sprawdzanie co 60s = w szybkim rynku mogą być duże slippage na exit

**Klucz do poprawy PnL:**
- Partial exits mogą znacząco poprawić Sharpe ratio
- Dynamiczny trailing (time-based + ATR decay)
- WS tick-by-tick exit checking zamiast polling co 60s

### 🥉 3.3 Position sizing (WAŻNY)

**Obecny flow:**
```python
risk_amount = equity × risk_per_trade           # np. 10000 × 0.015 = 150
stop_distance = ATR × atr_stop_mult             # np. 500 × 1.3 = 650
qty = risk_amount / (stop_distance × price)     # 150 / (650 × 60000) = 0.0000038
```

Plus skalowanie:
- Loss streak: `qty × max(0.3, 1 - streak × 0.15)`
- Win streak: `qty × min(2.0, 1 + streak × 0.1)`
- Risk gate: `qty × position_size_multiplier` (redukowany przy exposure blisko limitu)
- Symbol-level risk_scale z `_learn_from_history`
- Max/min qty clamp

**Ocena:** Solidna logika — ATR-based sizing z wieloma modyfikatorami. **Lepsze niż 90% botów** na tym etapie rozwoju.

**Potencjał poprawy:**
- Kelly criterion zamiast fixed fractional
- Volatility-normalized position sizing (w _learn_from_history jest podstawa, ale nie jest w pełni wykorzystana)

### 3.4 AI ranges quality (ŚREDNI wpływ)

**Problem:** Jakość ranges zależy od:
- openai: GPT-generated ranges — brak walidacji dokładności
- heuristic: ATR + Bollinger — rozsądne, ale nie uwzględnia fundamentów

**Brak backtestingu ranges:** System nie sprawdza, czy ranges z 6h temu były trafne. Nie kalkuluje hit rate zakresów.

**Rekomendacja:** Dodać tabelę `range_accuracy` — po X godzinach sprawdź, czy cena trafiła w buy/sell range. To da metrykę jakości AI vs heuristic.

### 3.5 Overtrading protection (NIŻSZY, ale ważny)

**Status:** Risk gates pokrywają to dobrze (max_trades_per_day, per_hour_per_symbol, exposure limits). Plus daily loss hamulec i crash detection.

---

## PODSUMOWANIE DOJRZAŁOŚCI

| Warstwa | Dojrzałość | Komentarz |
|---|---|---|
| **Governance / control plane** | ⭐⭐⭐⭐⭐ | Kompletna — experiments, rollback, monitoring, tuning insights |
| **Risk management** | ⭐⭐⭐⭐ | 10 bram, cost-aware, kill switch. Brakuje: risk-of-ruin, portfolio-level VaR |
| **Entry logic** | ⭐⭐⭐ | Rygorystyczna, ale monolityczna. Jedna strategia. Brak alternatywnych entry modes |
| **Exit logic** | ⭐⭐⭐ | ATR-based TP/SL + trailing. Brak partial exits, brak dynamicznego ATR update |
| **Position sizing** | ⭐⭐⭐⭐ | ATR-based + multi-modifier. Solidna |
| **Execution layer** | ⭐ | DEMO only. Zero kodu live execution. Brak order management |
| **Symbol selection** | ⭐⭐ | Portfolio-based watchlist. Brak rankingu / scoringu |
| **Observability** | ⭐⭐⭐⭐ | DecisionTrace + CostLedger + ConfigSnapshot. Brak dashboardu trace |
| **Cost model** | ⭐⭐ | Szacunkowy (expected only). Brak actual measurement |
| **Multi-strategy** | ⭐ | Pole istnieje. Logika nie. Jedna strategia "demo_collector" |
| **Wskaźniki techniczne** | ⭐⭐⭐⭐ | EMA, RSI, MACD, Bollinger, ATR — pandas_ta. Poprawne |
| **Data pipeline** | ⭐⭐⭐⭐ | REST + WebSocket, multi-timeframe klines, market data. Solid |

---

## TOP 5 AKCJI — posortowane wg wpływu na PnL

| # | Akcja | Wpływ PnL | Pracochłonność |
|---|---|---|---|
| 1 | **Migracja env vars → runtime_settings** (ATR_*, EXTREME_*, cooldowns) | 🔴 Wysoki | Niska (rejestracja + `effective_float`) |
| 2 | **Wydzielenie _demo_trading() na metody** (screen, size, exit, entry) | 🟡 Średni (umożliwia testing/A-B) | Średnia |
| 3 | **Partial exits** (TP1 / TP2 split) | 🔴 Wysoki | Średnia |
| 4 | **Range accuracy tracking** (hit rate AI vs heuristic) | 🟡 Średni | Niska |
| 5 | **Execution layer stub** (live order + fill measurement) | 🔴 Wysoki (dla live) | Wysoka |

---

## ODPOWIEDZI NA PYTANIA A–F

### A) Czy entry logic jest wystarczająco rozbudowana?

**TAK, ale monolitycznie.** 7 warstw filtrów to dużo. Problem nie w brakach, tylko w architekturze — wszystko w jednej metodzie, jedna strategia. Rozbudowa wymaga refaktoru.

### B) Czy execution path pokrywa scenariusze live?

**NIE.** Execution layer nie istnieje. `binance_client.py` ma READ-ONLY API (tickers, balances, klines). Brak place_order, cancel_order, get_fills. Przejście na live wymaga nowego modułu.

### C) Czy warstwa strategii jest wydzielona?

**NIE.** Pole `strategy_name` istnieje, ale logika nie. Zawsze "demo_collector". Runtime setting `enabled_strategies` nie jest sprawdzana w `_demo_trading()`. Experiments framework jest gotowy na multi-strategy, ale sam silnik nie.

### D) Czy symbol selection ma jakościowy ranking?

**NIE.** Watchlist = aktywa z portfela Binance + USDT. Brak filtrowania po wolumenie, spreadzie, sile trendu. Brak priorytetyzacji.

### E) Czy runtime_settings obejmuje krytyczne parametry?

**CZĘŚCIOWO.** runtime_settings pokrywa ~30 parametrów (głównie risk/cost), ale ~15 krytycznych parametrów tradingowych (ATR mults, extreme filters, cooldowns) wciąż jest w `os.getenv()` — niewidoczne dla tuning insights i experiments pipeline.

### F) Czy decision trace daje wystarczającą obserwabilność?

**TAK, na poziomie danych.** DecisionTrace zapisuje signal_summary, risk_gate_result, cost_gate_result, config_snapshot_id. Brakuje: dashboardu do przeglądania trace'ów (obecnie tylko surowy JSON w DB) i alertów na anomalie w trace patterns.

---

## WNIOSEK KOŃCOWY

> **Warstwa kontrolna (governance, risk, experiments) jest ~2x bardziej dojrzała niż rdzeń tradingowy.**
>
> Rdzeń tradingowy *działa* i ma solidne filtry wejściowe + position sizing, ale jest architektonicznie monolityczny (jedna metoda, jedna strategia, brak live execution).
>
> **Najważniejsza kolejność działań:**
> 1. Migracja env vars → runtime_settings (niski koszt, duży wpływ — odblokuje tuning pipeline)
> 2. Refaktor _demo_trading() na osobne metody (odblokuje testing i multi-strategy)
> 3. Partial exits (bezpośredni wpływ na PnL)
> 4. Range accuracy tracking (meta-diagnostyka jakości AI)
> 5. Live execution stub (prereq dla prawdziwego tradingu)

---

*Dokument wygenerowany jako checkpoint v0.7-beta. Nie zawiera nowego kodu — tylko diagnostykę i rekomendacje.*
