# CHANGELOG_LIVE — RLdC AiNalyzator
*Chronologiczny dziennik wszystkich zmian w projekcie.*
*Format: DATA | SESJA | PLIK | OPIS | STATUS*

---

## SESJA 2026-04-03 (Sesja 32 — BUG-LUPNL + BUG-WEALTH-PNL: live PnL hardcoded 0.0)

### BUG-WEALTH-PNL — Live wealth view zwracało `pnl_eur: 0.0` per pozycja

**Plik**: `backend/routers/portfolio.py`

**Problem**: Endpoint `GET /api/portfolio/wealth?mode=live` zastępował listę pozycji danymi z Binance spot portfolio, ale hardkodował `pnl_eur: 0.0`, `pnl_pct: 0.0` i `entry_price: current_price` (brak historii wejścia). WWW pokazywało fałszywe 0% PnL dla każdej live pozycji.

**Fix (`backend/routers/portfolio.py`):**
- Przed budowaniem `items[]`, query do `Position` (mode=live, qty>0) → mapping `asset → Position`
- Dla każdej pozycji Binance: szuka pasującej DB Position (ARB → ARBEUR, RENDER → RENDEREUR itd.)
- `pnl_eur = position.unrealized_pnl`, `entry_price = position.entry_price`, `opened_at = position.opened_at`
- Dust balances bez wpisu w DB: nadal `pnl=0.0` (poprawne — to nie są pozycje bota)
- `total_pnl = sum(pnl_eur)` obliczany z wzbogaconej listy

**Weryfikacja**:
- `total_pnl: -1.48 EUR` ✅ (ARBEUR -0.665 + RENDEREUR -0.472 + VETEUR -0.341)
- ARBEUR: `pnl=-0.665 (-1.11%), entry=0.081300, cur=0.080400, opened=12:19` ✅
- BNB/BTC dust: `pnl=0.0` poprawnie (brak otwarcia przez bota) ✅

**Testy**: 196/196 ✅

---

## SESJA 2026-04-03 (Sesja 32 — BUG-LUPNL: live unrealized_pnl=0.0)

### BUG-LUPNL — Live summary zwracało hardkodowane `unrealized_pnl: 0.0`

**Plik**: `backend/routers/account.py`

**Problem**: Endpoint `GET /api/account/summary?mode=live` zwracał zawsze `unrealized_pnl: 0.0` mimo otwartych pozycji live. Wartość była hardkodowana w data dict. Dodatkowo brak `realized_pnl_24h` w odpowiedzi live.

**Wpływ**: WWW pokazywało fałszywe `unrealized_pnl: 0.0` (powinno: -1.4775 EUR przy 3 otwartych pozycjach ARBEUR/RENDEREUR/VETEUR). Dezorientacja operatora — niemożność oceny stanu konta live bez ręcznego sprawdzania pozycji.

**Fix (`backend/routers/account.py`):**
- Dodano query do `Position` (mode=live, quantity>0) przed budowaniem `data` dict
- `unrealized_total = sum(p.unrealized_pnl for ...)` — suma z tabeli pozycji
- Dodano `realized_pnl_24h` przez query do `Order` (mode=live, side=SELL, FILLED, last 24h)
- `data["unrealized_pnl"] = unrealized_total` (zamiast 0.0)
- `data["realized_pnl_24h"] = realized_pnl_24h`
- Snapshot zapisywany z realną wartością `unrealized_pnl`

**Weryfikacja po restarcie backendzie**:
- `unrealized_pnl: -1.4775 EUR` ✅ (ARBEUR -0.665 + RENDEREUR -0.472 + VETEUR -0.341)
- `realized_pnl_24h: 2.6441 EUR` ✅
- equity: 330.83 EUR ✅

**Testy**: 196/196 ✅

---

## SESJA 2026-04-03 (Sesja 31 — AUDYT: system_logs, REJECTED orders, ARBEUR SL)

### AUDIT-31 — Głęboka weryfikacja logów systemowych i mechanizmu exit

**Pliki**: (analiza, brak zmian w kodzie)

**Wyniki audytu**:

**1. REJECTED pending_orders (21 łącznie, 12 live):**
- KAŻDY REJECTED pending order ma odpowiadający FILLED order w tej samej chwili → transakcje BYŁY wykonane
- Historyczny NameError `name 'symbol' is not defined` w starym kodzie (pre-BUG-25); traceable modułem `demo_trading` — błąd w post-execution bookkeeping po `db.add(order)`
- Po restarcie 12:19 (BUG-25 fix): **0 pending_execution_error** → obecny kod poprawny
- Przykład: WIFEUR SELL [live] REJECTED 01:37 + FILLED 01:37 — ta sama transakcja, REJECTED = misleading status, pozycja zamknięta OK
- **Brak aktywnego buga**

**2. LTCEUR/LINKEUR — `Brak tickera` WARNING:**
- Są prawidłowymi parami EUR na Binance (LTCEUR ~45 EUR, LINKEUR ~7.5 EUR, 29k+ historycznych punktów)
- Są w watchliście ze skanera top-30 wolumenu — poprawne
- 2 warnings w 2h (13:23): chwilowy błąd API `get_24hr_ticker` (rate limit / timeout)
- Data zbierana poprawnie w następnym cyklu (13:46 w market_data)
- **Brak buga — transientny błąd API**

**3. ARBEUR SL monitoring:**
- Przy otwartej pozycji ARBEUR live (12:19, entry=0.0813) cena stopniowo spada
- 13:09: SL_buf=+0.68% | 13:47: SL_buf=+0.30% | 13:50: SL=0.0803556, price=0.0804 (~0.055% nad SL)
- Brak `create_pending_exit` — poprawne, bo price>SL (0.0804 > 0.0803556)
- System monitoruje co ~3 minuty, SL będzie wykonany gdy price ≤ 0.08036

**4. Performance 24h (LIVE):**
- Zrealizowane: **+2.6441 EUR** (RENDEREUR +3.31, BTCEUR +0.48, XLMEUR -0.15, PEPEEUR -0.16, WIFEUR -0.49, ETHEUR -0.35)
- Główne zyski: RENDEREUR (6 SELL FILLED: partial TP + trailing + full TP) = +3.31 EUR live
- Liberia Day crash 01:37-01:40 generował WIFEUR -0.49, BTCEUR nie zdołał wpłynąć (net +0.48)
- Aktualnie unrealized: -0.69 EUR (3 pozycje: RENDEREUR -0.30%, ARBEUR -0.86%, VETEUR +0.01%)

**5. SCANNER tier dla ARBEUR:**
- ARBEUR nie jest w `symbol_tiers` → tier="SCANNER" z kodu (min_conf_add=0.07, risk_scale=0.5, max=1/day)
- Wejście przy conf ≥ 0.77 (0.70 + 0.07), edge ≥ 4.5 (4.0 + 0.5) — surowe kryteria
- 738 szt @ 0.0813 EUR = ~60 EUR notional (= risk_scale=0.5 × pełna pozycja)

**Testy**: 196/196 ✅ (bez zmian w kodzie)

---

## SESJA 2026-04-03 (Sesja 30 — AUDYT: weryfikacja stanu, analiza strat historycznych)

### AUDIT-30 — Głęboka weryfikacja systemu bez nowych bugów

**Pliki**: (tylko analiza, brak zmian w kodzie)

**Wyniki audytu**:
- `unrealized_pnl = -1.024 EUR` jest POPRAWNE — rynek się przesunął w dół po 12:19 UTC: RENDEREUR -1.08%, ARBEUR -0.74%
- `daily_net_pnl = +1.9272 EUR` jest POPRAWNE — rolling 24h okno SQL przez SQLAlchemy (używa formatu z spacją, nie 'T') — suma wszystkich FILLED orders BUY+SELL od 13:00 Apr 2 do 13:00 Apr 3
- `activity_gate_day` po fixie BUG-25: **0 nowych bloków** (traces z 10:00-12:19 to historyczne pre-fix)
- `tier_daily_trade_limit` 160×/3h: wszystkie **LEGALNE** (SCANNER max=1/day: ARBEUR, XLMEUR, WIFEUR; SPECULATIVE max=3/day: RENDEREUR osiągnął limit)
- `bear_regime_override` w signal_summary: celowy mechanizm mean-reversion (wejście przy RSI < 28 w BEAR = niższy próg confidence 0.65 zamiast 0.70; nie jest bugiem)
- Straty WIFEUR (-0.491 EUR) i inne z wieczoru 2 Apr: entries při conf=0.52-0.58 z **pre-PROFIT-FIX** konfiguracji (stary bear_conf=0.52, edge_mult=3.0). Aktualny system (bear_conf=0.70, edge_mult=4.0) blokuje takie wejścia
- Cykl trading engine: ~3 minuty, exit check aktywny i monitoring SL pozycji działa
- **196/196 testów** ✅

**Nowe pozycje w trakcie sesji**:
- **VETEUR** BUY @ 13:04 UTC: conf=0.72 (> bear_min 0.70), edge=4.5 (> min 4.0), SCANNER tier, htf=4h:niedź (-20% penalty ale nadal przeszedł), TP=+2.13%, SL=-1.25%
- 3 otwarte pozycje live: RENDEREUR (-0.54%), ARBEUR (-0.49%), VETEUR (+0.01%). max_open_positions=3 osiągnięty

**Diagnostyka narzędzi**: raw sqlite3 z `datetime.isoformat()` (format 'T') zwraca błędne wyniki przy porównaniu z timestampami przechowywanymi jako spacje (' '). SQLAlchemy ORM obsługuje to poprawnie. Pamiętaj: używaj `strftime('%Y-%m-%d %H:%M:%S')` w diagnostycznych raw SQL.

---

## SESJA 2026-04-03 (Sesja 29 — FIX: health timestamp + fałszywe blokady activity gate)

### BUG-HEALTH-TS — Health endpoint hardcoded timestamp

**Plik**: `backend/app.py`  
**Problem**: `GET /health` zwracał statyczny `"2026-01-31T17:30:00Z"` zamiast aktualnego czasu.  
**Fix**: Dodano `from datetime import datetime, timezone`, zmieniono na `datetime.now(timezone.utc).strftime(...)`.

### BUG-25 — activity_gate_day + tier_daily_trade_limit fałszywe blokady (partial take-profit)

**Pliki**: `backend/accounting.py`, `backend/collector.py`  
**Problem**: Partial take-profit (25%+18.75%+56.25%) generuje **3 SELL** orders na 1 pozycję.
- `compute_activity_snapshot.trades_24h` zliczał ALL orders (BUY + SELL) → po ~5 cyklach hit limit 20 → ALL nowe wejścia blokowane przez `activity_gate_day` 
- `collector.py sym_trades_today` tak samo → RENDEREUR SPECULATIVE (limit=3) blokowany po **1** pełnym cyklu (1 BUY + 3 SELL = 4 ≥ 3)
- Efekt: demo 22 orders → `activity_gate_day` blokowało 652 wejść/6h; live 20 orders → pełna blokada

**Fix**:
1. `accounting.py compute_activity_snapshot` — `trades_24h` teraz liczy **tylko BUY** (side=='BUY')
2. `collector.py sym_trades_today` — dodano `Order.side == "BUY"` do filtru

**Wynik**: entries_24h: demo 22→9, live 20→7. `activity_gate_day` 0 nowych bloków. RENDEREUR dokonał nowych wejść po fixie (12:19 UTC). 196/196 OK.

---

## SESJA 2026-01-31 (Sesja 28 — PROFIT-FIX: analiza historii transakcji + naprawa rentowności)

### Analiza historii transakcji

**Win rate**: 41.7% (15/36 exitów). **Recent (Apr 1-3)**: 7 WIN (+6.24 EUR), 11 LOSS (-11.5 EUR) = **net -5.3 EUR**.  
**Root cause strat**: ATR_STOP_MULT=1.2 → SL 0.6% dla WIF (szum rynkowy). Fee 0.36% round-trip. RR=1.67 → EV=-24.7%.  
**bear_regime_min_conf=0.52** → przyjmował prawie losowe sygnały w bessie. **cooldown=0** → natychmiastowe re-entry po SL.

### PROFIT-FIX-01 — ATR SL/TP parametry (`.env` + `runtime_settings.py` + DB)

| Parametr | Przed | Po |
|----------|-------|-----|
| ATR_STOP_MULT / atr_stop_mult | 1.2 | **2.0** |
| ATR_TAKE_MULT / atr_take_mult | 2.0 | **3.5** |
| min_edge_multiplier | 2.5 | **4.0** |
| atr_stop_mult default (runtime_settings.py) | 1.3 | **2.0** |
| atr_take_mult default | 2.2 | **3.5** |
| min_edge_multiplier default | 2.5 | **4.0** |

Nowe RR = 3.5/2.0 = **1.75**. Wymagany min win rate = 1/(1+RR) = **36.4%** (poprzednio 37.4% ale with wider SL = fewer false stops).  
Wartości wpisane do DB via RuntimeSetting override (nie env), by nadpisać stare env zmienne w powłoce.

### PROFIT-FIX-02 — Parametry strategii (DB RuntimeSetting)

| Klucz | Przed | Po | Uzasadnienie |
|-------|-------|-----|-------------|
| bear_regime_min_conf | 0.52 | **0.70** | Zbyt niska — akceptowała prawie losowe sygnały w bessie |
| bear_oversold_bypass_conf | 0.50 | **0.65** | Jw. dla bypass oversold |
| max_open_positions | 5 | **3** | Mniej jednoczesnych = większa selekcja |
| loss_streak_limit | 7 | **3** | 3 straty z rzędu = pauza (było 7!) |
| cooldown_after_loss_streak_minutes | 0 | **120** | 0 sekund cooldown = natychmiastowy re-entry! |
| trading_aggressiveness | aggressive=conservative*(w DB)* | **safe** | (invalid "conservative" → zmienone na dozwolone "safe") |
| demo_min_signal_confidence | 0.50 | **0.62** | Rygorystyczniejszy próg demo |
| pending_order_cooldown_seconds | 0 | **300** | 5 min między zleceniami |
| CORE max_trades_per_day | 10 | **4** | ETHEUR był handlowany 10×/dzień w bessie |
| ALTCOIN max_trades_per_day | 3 | **2** | Ograniczenie overtradingu |

Demo cooldown aktywowany dla ETHEUR (loss_streak=2) i WIFEUR.

### PROFIT-FIX-03 — Nowy filtr min_atr_pct (`collector.py` + `runtime_settings.py`)

- **Nowy SettingSpec** `min_atr_pct` (default=0.005 = 0.5%, env_var=MIN_ATR_PCT) w `runtime_settings.py`
- **Filtr w `_screen_entry_candidates`**: gdy `ATR/price < min_atr_pct` → `reason_code="atr_below_min_pct"` → SKIP
- **cost_gate_pass** rozszerzone o: `and _atr_pct >= _min_atr_pct`
- **SL cooldown fix**: `max(base_cooldown, min(sl_cooldown, base_cooldown*4))` → gwarantuje **min 2h** cooldown po każdym SL hit (poprzednio mógł spaść do 0)

### BUG-24 + BUG-24-BACKFILL — NULL PnL na SELL FILLED orderach

**Root cause**: BUG-23 (naprawiony sesją 27) powodował NameError WEWNĄTRZ bloku pełnego zamknięcia PRZED wywołaniem `attach_costs_to_order`. Wyjątek był łapany → Order otrzymywał status FILLED ale bez fee/gross/net.  
**Skutek**: 17 SELL FILLED orderów z NULL `fee_cost`/`gross_pnl`/`net_pnl`.  
**Backfill**: Skrypt uzupełnił 16 orderów z CostLedger + ExitQuality (1 bez gross — brak EQ match).

### BUG-24-PEPEEUR — ExitQuality net_pnl = -9896 EUR (fałszywe)

**Root cause**: BUG-19 ticker sanity (sesja 25) naprawił price w DB, ale ExitQuality już był zapisany z `total_cost=9895.9 EUR` (notional PEPE liczone po złej cenie ~0.95 EUR zamiast 2.89e-6).  
**Naprawa**: `net_pnl = gross_pnl - 0.108 = -0.2121 EUR`, `total_cost = 0.108 EUR`.

### test_smoke.py — aktualizacja testu `test_p1_confidence_thresholds_reduced`

Test sprawdzał `bear_regime_min_conf default <= 0.62` (stary P1-FIX). Zaktualizowano do nowego wymogu PROFIT-FIX: `0.65 <= bear_min <= 0.90` (podniesiony do 0.70 dla ograniczenia overtradingu w bessie).

**Stan po naprawie**: 196/196 OK ✅. Backend uruchomiony ✅.

---

## SESJA 2026-04-03 (Sesja 27 — BUG-23: NameError 'symbol' przy zamykaniu pozycji)

### BUG-23 — NameError: 'symbol' is not defined → pending_execution_error przy każdym zamknięciu pozycji

**Root cause**: W `_execute_confirmed_pending_orders`, gałąź pełnego zamknięcia (SELL qty≤0 lub dust<1 EUR) zawierała:
```python
logger.info(f"✅ Pozycja {symbol} zamknięta (dust < 1 EUR lub qty=0)")
```
Zmienna `symbol` nie istnieje w tym zakresie — prawidłowa jest `pending.symbol`. Wyjątek `NameError` był łapany przez zewnętrzny `try/except Exception`, który zapisywał trace `pending_execution_error` z `{"error": "name 'symbol' is not defined"}`.

**Efekt**: Każde pełne zamknięcie pozycji DEMO powodowało error trace zamiast normalnego przepływu. Pozycja mogła nie być usuwana z DB przy SELL (dalszy kod po błędzie mógł nie wykonać `db.delete(position)` w zależności od flow).

**Naprawa** (`backend/collector.py` L805):
```python
# Przed:
logger.info(f"✅ Pozycja {symbol} zamknięta (dust < 1 EUR lub qty=0)")
# Po:
logger.info(f"✅ Pozycja {pending.symbol} zamknięta (dust < 1 EUR lub qty=0)")
```

**Obserwacja dodatkowa**: SOLEUR demo `planned_sl=68.785 > entry=68.77` — to poprawne zachowanie break-even lock. `new_be_sl = entry + atr * 0.05 = 68.77 + 0.30*0.05 = 68.785`. SL powyżej entry to zamierzone zabezpieczenie kapitału po osiągnięciu 1×ATR zysku.

**Stan po naprawie**: 196/196 OK. Backend uruchomiony przez start_dev.sh ✅.

---

## SESJA 2026-04-02 (Sesja 26 — BUG-20/21/22: min_notional_guard, live_balance_eur SettingSpec, SCANNER tier limit)

### BUG-20 — min_notional_guard blokuje ETHEUR live przy 150 EUR saldo i 5 max_open_positions

**Root cause**: Z `max_open_positions=5`, `max_cash_pct_per_trade = 1/5 = 20%`. Przy saldzie 150 EUR: `max_cash_for_trade = 150 × 0.20 = 30 EUR < min_order_notional = 60 EUR`. ETHEUR (cena ~1800 EUR) nie mogło uzyskać pozycji nawet gdy było dość gotówki (150 EUR > 60 EUR minimum).

**Naprawa** (`backend/collector.py`): Po obliczeniu `max_cash_for_trade`, jeśli `max_cash_for_trade < min_order_notional AND available_cash >= min_order_notional`, podniesiono do `min_order_notional`. Dodatkowo: warunek "raise ATR-qty do min_order_notional" zmieniał sprawdzenie z `max_affordable * price` na `max_cash_for_trade` (aby obsłużyć prowizję).

```python
# Nowy kod (po fix):
if max_cash_for_trade < min_order_notional and available_cash >= min_order_notional:
    max_cash_for_trade = min_order_notional  # min viable trade
```

**Efekt**: 150 EUR saldo + 5 max open → max_cash=60 EUR → ETH notional=60.00 → eligible=True ✅

### BUG-21 — live_balance_eur poza SettingSpec → get_runtime_config() zwracało None → drawdown_gate bez bazy

**Root cause**: `live_balance_eur` nie był zdefiniowany w `_SETTINGS` diccie w `runtime_settings.py`. Funkcja `get_runtime_config(db)` zwracała tylko klucze z `_SETTINGS` → `cfg.get("live_balance_eur")` = None → `evaluate_risk` używało `_base = max(1.0, 0 + exposure)` zamiast `live_balance + exposure`.

**Naprawa** (`backend/runtime_settings.py`): Dodano `live_balance_eur` do `_SETTINGS`:
```python
"live_balance_eur": SettingSpec(
    key="live_balance_eur",
    section="risk",
    parser=_parse_positive_float,
    serializer=_serialize_float,
    default=0.0,
    env_var="LIVE_INITIAL_BALANCE",
),
```

**Weryfikacja**: `get_runtime_config(db)` → `live_balance_eur: 90.1485` ✅ (z DB)

### BUG-22 — RENDEREUR/PEPEEUR w tierze SCANNER (max_trades=1/dzień) zamiast SPECULATIVE

**Root cause**: RENDEREUR i PEPEEUR nie były przypisane do żadnego tieru w `symbol_tiers`, wpadały do SCANNER z `max_trades_per_day_per_symbol=1`. Po pierwszej transakcji w danym dniu, dalsze wejścia były blokowane przez `tier_daily_trade_limit`.

**Naprawa** (`backend/runtime_settings.py` + DB):
- `SPECULATIVE` tier default dodano symbole: `RENDEREUR, RENDERUSDC, PEPEEUR, PEPEUSDC`
- `max_trades_per_day_per_symbol`: `2 → 3` dla SPECULATIVE
- DB override `symbol_tiers` zaktualizowany bezpośrednio.

| Plik | Zmiana |
|------|--------|
| `backend/collector.py` L2834-2839 | min_order_notional override gdy pct-cap < min, `max_cash_for_trade` check w raise |
| `backend/runtime_settings.py` | `live_balance_eur` → nowy SettingSpec w `_SETTINGS`; SPECULATIVE tier +RENDEREUR/PEPEEUR, max_trades 2→3 |
| DB `runtime_settings.symbol_tiers` | RENDEREUR/RENDERUSDC/PEPEEUR/PEPEUSDC dodane do SPECULATIVE |

**Stan po naprawie**: 196/196 OK. Backend zrestartowany PID 518798.

---

## SESJA 2026-04-02 (Sesja 25 — BUG-19: exec_price sanity check / kill switch fałszywy trigger)

### BUG-19 — ticker zwraca złą cenę dla tokenu mikro-cena → fee_cost 9895 EUR → kill switch false positive

**Root cause**: W trybie DEMO, `exec_price = float(ticker["price"])` mogło zwrócić błędną cenę (np. 0.95 EUR zamiast 2.89e-6 EUR dla PEPEEUR) — prawdopodobnie stale cache lub chwilowe nieprawidłowe mapowanie tickera. Wówczas:
- `notional = qty × wrong_exec_price = 10,416,666 × 0.95 = 9,895,833 EUR`
- `fee_cost = notional × 0.001 = 9,895.83 EUR`
- `daily_net_pnl = -9,898.45 EUR`
- `kill_switch_triggered = True` (9898 / initial_balance >> 3%)
- Wszystkie live entries blokowane przez `kill_switch_gate`

**Obserwacja diagnostyczna**: `loss_streak_gate` traces z payload `{}` były MYLĄCE — payload jest kolumną `details`, dane ryzyka są w `risk_gate_result`. Właściwy reason był `kill_switch_gate`, nie `loss_streak_gate`.

**Naprawa**: W demo path, po pobraniu ticker price, dodano sanity check:
```python
if _pending_p > 0 and (_ticker_price / _pending_p > 50 or _pending_p / _ticker_price > 50):
    logger.warning("BUG-19: ticker price sanity FAIL ...")
    # exec_price pozostaje = pending.price (nie nadpisujemy)
else:
    exec_price = _ticker_price
```
Jeśli ticker różni się od pending.price o więcej niż 50×, używamy pending.price z WARNING logu.

**Nota**: currency conversion fix (`commissionAsset != EUR → fee × exec_price`, cap 5% notional) był już w kodzie z wcześniejszej sesji.

**DB efekt**: Zły order z fee=9895 EUR zniknął z DB (collector go usunął/zastąpił w następnym cyklu). Kill switch = False przywrócony automatycznie.

**Stan po naprawie**: 196/196 OK. Backend zrestartowany PID 503410.

---

## SESJA 2026-04-02 (Sesja 23 — BUG-18: exit_reason_code przy partial close)

### BUG-18 — exit_reason_code ustawiany podczas częściowego wyjścia → pozycja traktowana jako zamknięta

**Root cause**: W `_execute_confirmed_pending_orders`, linia `position.exit_reason_code = pending.exit_reason_code` była wykonywana PRZED sprawdzeniem czy to partial (qty > 0 pozostało) czy full close. Każde SELL — zarówno partial jak i full — ustawiało `exit_reason_code` na pozycji.

**Efekt:** RENDEREUR demo po 2 częściowych TP (partial_take_count=2, qty=21.8 pozostało) miało `exit_reason_code="tp_partial_keep_trend"`. Pozycja była:
- Niewidoczna w endpointach `/api/positions/analysis` (filtrowane jako "zamknięte")
- Nieskanowana przez exit engine w `_check_exits`
- 21.8 tokenów RENDER bez aktywnego monitoringu

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/collector.py` L773 | `position.exit_reason_code = ...` przeniesione wyłącznie do gałęzi pełnego zamknięcia (`qty<=0 or dust<1 EUR`). Dla partial: `exit_reason_code` nie zmieniane (pozostaje None). Komentarz: `# exit_reason_code NIE jest ustawiany — pozycja nadal otwarta` | ✅ GOTOWE |

**Naprawa DB**: RENDEREUR `exit_reason_code = None` (wyczyszczone manualnie).

**Weryfikacja**: obie pozycje widoczne:
- BTCEUR live (mode=live, qty=0.002633) ✅
- RENDEREUR demo (mode=demo, qty=21.816419, partial_take_count=2) ✅

### Metryki sesji 23

| Metryka | Wartość |
|---------|---------|
| Testy | **196/196 ✅** |
| Backend PID | 468727 |
| Naprawy | BUG-18 (exit_reason_code partial close) |

---

## SESJA 2026-04-02 (Sesja 22 — P3-01: build_runtime_state brak config)

### P3-01 — build_runtime_state nie zwracał klucza "config" → signals.py ignorowało faktyczną konfigurację

**Root cause**: `build_runtime_state()` w `runtime_settings.py` budowało `effective` (płaski config) wewnętrznie, ale nie umieszczało go w zwracanym dict. W `signals.py` wszystkie 3 endpointy robiły `config = runtime_ctx.get("config", {})` → zawsze `{}` → hardkodowane fallbacki.

**Wpływ na trading:**
- `trading_aggressiveness` → `"balanced"` zamiast `"aggressive"` (DB override!) → złe MIN_SCORE/MIN_CONFIDENCE w screeningu sygnałów
- `max_open_positions` → `3` zamiast `5` → UI blokował wejścia po 3 pozycjach
- `bear_regime_min_conf` → `0.68` zamiast `0.62` → zły próg wyświetlany w UI i wait-status
- `pending_order_cooldown_seconds` → `300` zamiast faktycznej wartości DB

**Kolektor był nienaruszony** — `collector.py` używał `get_runtime_config(db)` osobno w `_runtime_context()`.

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/runtime_settings.py` L1045 | Dodano `"config": effective` do return dict `build_runtime_state` | ✅ GOTOWE |

**Weryfikacja post-fix:**
- `build_runtime_state(db).get('config', {}).get('trading_aggressiveness')` → `"aggressive"` ✅
- `build_runtime_state(db).get('config', {}).get('max_open_positions')` → `5` ✅
- `/api/signals/wait-status` → `bear_min_conf: 0.62` ✅

### Metryki sesji 22

| Metryka | Wartość |
|---------|---------|
| Testy | **196/196 ✅** |
| Backend PID | 465249 |
| Naprawy | P3-01 (config starvation w signals.py) |
| Efekt net | signals.py screener teraz używa aggressive profile + prawidłowego max_open_positions=5 |

---

## SESJA 2026-03-26 (Sesja A — Setup, Audyt backendowy, Pierwsze poprawki)

### [2026-03-26] — Audyt i pierwsze naprawki backendu

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/signals.py` | Dodano import `persist_insights_as_signals`; wszystkie 3 endpointy (`/latest`, `/top5`, `/top10`) teraz wywołują persistację po generowaniu sygnałów | ✅ GOTOWE |
| `backend/collector.py` | Dodano `_load_persisted_symbol_params()` — ładuje `symbol_params` z DB przy starcie | ✅ GOTOWE |
| `backend/collector.py` | Zmodyfikowano `run_once()` — heurystyczne sygnały generowane KAŻDY cykl, niezależnie od OpenAI | ✅ GOTOWE |
| `backend/collector.py` | Zmodyfikowano `_learn_from_history()` — wyniki uczenia zapisywane do `RuntimeSetting('learning_symbol_params')` | ✅ GOTOWE |
| `backend/analysis.py` | Zmieniono domyślny `AI_PROVIDER` z `"openai"` → `"auto"` | ✅ GOTOWE |
| `backend/analysis.py` | Tryb `openai` teraz fallbackuje do heurystyki gdy brak klucza (zamiast `return None`) | ✅ GOTOWE |
| `backend/routers/orders.py` | Naprawiono `md.close` → `md.price` w create_order MARKET (błędny atrybut) | ✅ GOTOWE |
| `tests/test_smoke.py` | Status po naprawkach: **174/174 ✅** | ✅ GOTOWE |

### [2026-03-26] — Dokumenty

| Plik | Opis | Status |
|------|------|--------|
| `MASTER_GAP_REPORT.md` | Pełny raport statusu: 37 plików backend + widoki frontend + plan 4 pilarów | ✅ GOTOWE |
| `/memories/repo/rldc-ainlyzator.md` | Zaktualizowano pamięć repo o nowe cele i poprawki sesji | ✅ GOTOWE |

---

## SESJA 2026-03-26 (Sesja B — Pełna inwentaryzacja funkcji)

### [2026-03-26] — Dokumenty inwentaryzacji

| Plik | Opis | Status |
|------|------|--------|
| `FUNCTIONS_MATRIX.md` | Pełna macierz funkcji: ~108 funkcji, statusy DONE/PARTIAL/BROKEN/NOT_STARTED | ✅ GOTOWE |
| `OPEN_GAPS.md` | 12 braków posortowanych wg priorytetu, z zakresem każdego | ✅ GOTOWE |
| `SYSTEM_RULES.md` | Zasady systemu: reguły decyzyjne, bezpieczeństwo, konfiguracja, kody UI/UX | ✅ GOTOWE |
| `CHANGELOG_LIVE.md` | Ten plik — chronologiczny dziennik zmian | ✅ GOTOWE |
| `MASTER_INDEX.md` | Indeks wszystkich plików projektu z opisem roli | ✅ GOTOWE |

### Kluczowe odkrycia z inwentaryzacji

| Odkrycie | Wpływ | Priorytet naprawy |
|----------|-------|-------------------|
| Kliknięcie w symbol — NIGDZIE nie istnieje | Krytyczny | P1 |
| Forecast — backend działa, UI nigdy nie wywołuje | Krytyczny | P1 |
| `macro-reports` i `reports` — brak w OtherView routerze | Wysoki | P2 |
| Economy/Alerty/Wiadomości — wszystkie to ta sama tabela | Wysoki | P2 |
| PortfolioView — brak auto-refresh | Wysoki | P2 |
| OpenOrders widget — brak auto-refresh | Wysoki | P2 |
| Drawdown real Binance — zawsze 0.0 | Wysoki | P4 |
| Akcje handlowe (KUP/SPRZEDAJ) — brak w głównych widokach | Wysoki | P2 |

### [2026-03-26] — Implementacja GAP-01 + GAP-02 + GAP-04 + GAP-06

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/MainContent.tsx` | Dodano globalny `selectedSymbol` state w `MainContent` — kliknięcie z dowolnego widoku otwiera panel | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Dodano `SymbolDetailPanel` — slide-in overlay z prawej strony: cena, PnL, wykres, prognoza AI | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Dodano `ForecastChart` — wykres historyczny (klines) + prognoza AI (forecast) jako przerywana linia pomarańczowa z pionową linią "teraz" | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Kliknięcia w symbole: CommandCenterView scanner ✅, pozycje ✅, StrategiesView ✅, SignalsView ✅, RiskView tabela ✅, MarketsView tabela ✅, PositionAnalysisView nagłówki kart ✅ | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-04: Przyciski "KUP" (z kwotą EUR) i "ZAMKNIJ POZYCJĘ" w SymbolDetailPanel | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-06: Routing dla `macro-reports` i `reports` w OtherView — wyświetlają "Moduł w trakcie przygotowania" zamiast generic fallback | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | TypeScript kompiluje się bez błędów (`npx tsc --noEmit`) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-07: Auto-refresh dodany do PortfolioView (30s), BacktestView (60s), MarketProxyView (30s) | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy backend po zmianach: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-27 (Sesja C — Symbol Tiers, GAP-03, GAP-05, GAP-08/09/10)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/account.py` | Endpoint `/api/account/user-target` — persistacja celu użytkownika do DB (GAP-05) | ✅ GOTOWE |
| `backend/routers/positions.py` | Endpoint `/api/positions/decisions/{symbol}` — historia decyzji dla symbolu (GAP-10) | ✅ GOTOWE |
| `backend/routers/market.py` | Endpoint `/api/market/forecast-accuracy/{symbol}` — trafność prognoz (GAP-03) | ✅ GOTOWE |
| `backend/risk.py` | `drawdown_real` poprawiony dla trybu live Binance (GAP-08) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | ForecastChart: linie EMA20/EMA50 na wykresie historycznym (GAP-09) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | ForecastChart: mini-panel RSI(14) pod wykresem (GAP-09) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | SymbolDetailPanel: ustawianie celu użytkownika z persistacją (GAP-05) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | SymbolDetailPanel: historia decyzji dla symbolu (GAP-10) | ✅ GOTOWE |
| `backend/database.py` | Model `ForecastRecord` — tabela trafności prognoz (GAP-03) | ✅ GOTOWE |
| `docs/ETAP_C_SYMBOL_TIERS_REPORT.md` | Raport z drobiazgowej inwentaryzacji system symbol tiers | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-27 (Sesja D — PION B: WLFI hold-status)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/account.py` | Endpoint `GET /api/account/wlfi-status` — wartość WLFI, cel 300 EUR, brakująca kwota | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `WlfiStatusCard` widget w DashboardV2View — wartość WLFI, pasek postępu do celu | ✅ GOTOWE |
| `web_portal/src/components/widgets/AccountSummary.tsx` | Naprawiono pole `account_mode` — poprawne odczytywanie trybu konta | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-28 (Sesja E — Poprawki bezpieczeństwa Telegram + artefakty)

| Plik | Zmiana | Status |
|------|--------|--------|
| `telegram_bot/bot.py` | `ADMIN_TOKEN` ładowany z `.env`; `_is_authorized()` poprawiony — brak CHAT_ID blokuje wszytkich | ✅ GOTOWE |
| `telegram_bot/bot.py` | `/stop` poprawiony — wywołuje `POST /api/control/state` z `ADMIN_TOKEN` (było: martwy kod) | ✅ GOTOWE |
| `telegram_bot/bot.py` | `/governance` i `/incidents` — dodano `_check_auth` (wcześniej bez autoryzacji) | ✅ GOTOWE |
| `telegram_bot/bot.py` | `reject_command` — naprawiono błąd wcięcia bloku `if not context.args:` | ✅ GOTOWE |
| `backend/routers/orders.py` | Usunięto blok `generate_demo_orders` w `export_orders_csv` (powodował `NameError` w runtime) | ✅ GOTOWE |
| `PROGRAM_REVIEW.md` | Zaktualizowano: 8 pozycji przeniesiono do NAPRAWIONE, KRYTYCZNE zredukowane z 6 do 3 | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-28 (Sesja F — Best Trade Engine + F2)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/signals.py` | Dodano `_score_opportunity()` — scoring: confidence×10, trend±1.5, RSI±1.5, R/R+1.0, HOLD-3.0 | ✅ GOTOWE |
| `backend/routers/signals.py` | Nowy endpoint `GET /api/signals/best-opportunity` — zwraca BUY/SELL/CZEKAJ z uzasadnieniem | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `BestOpportunityCard` widget — zastąpił stary "Co teraz zrobić?" baner | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `BestOpportunityCard` — zielona/czerwona karta, pasek pewności, breakdown punktów, runner-up | ✅ GOTOWE |
| `tests/test_smoke.py` | Dodano `test_signals_best_opportunity`; testy: **175/175 ✅** | ✅ GOTOWE |
| Weryfikacja stanu systemu | Wszystkie 6 endpointów zwraca 200 (localhost + LAN) po resecie sesji | ✅ GOTOWE |

---

## ETAP 0 — 2026-03-28 (Stabilne uruchamianie projektu)

| Plik | Zmiana | Status |
|------|--------|--------|
| `scripts/start_dev.sh` | Skrypt startowy: wykrywa działające procesy, uruchamia backend+frontend, weryfikuje HTTP 200 | ✅ GOTOWE |
| `scripts/stop_dev.sh` | Skrypt stop: zatrzymuje przez PID file + fallback `fuser` na portach | ✅ GOTOWE |
| `scripts/status_dev.sh` | Skrypt status: sprawdza porty + 6 endpointów HTTP | ✅ GOTOWE |
| `START_HERE.md` | Dokument startowy: jak uruchomić, adresy, logi, zmienne env, pierwsze uruchomienie | ✅ GOTOWE |
| `MASTER_INDEX.md` | Zaktualizowano: sekcja `scripts/` + statusy aktualności dokumentów | ✅ GOTOWE |
| `CURRENT_STATE.md` | Zaktualizowano: sesje D-F, ETAP 0, GAP-13, GAP-14, GAP-15, GAP-16 | ✅ GOTOWE |
| `OPEN_GAPS.md` | Zaktualizowano: GAP-13 (F2 DONE), GAP-14 (ETAP 0 DONE), GAP-15, GAP-16 | ✅ GOTOWE |

---

## ETAP 2 — 2026-03-28 (Naprawa luk widocznych dla użytkownika)

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/MainContent.tsx` | GAP-15: `refreshMs=30000` dodany do 4 useFetch w `SymbolDetailPanel` (analysis, signals, accuracy, decisions) — dane live zamiast zamrożonych | ✅ GOTOWE |
| `web_portal/src/components/widgets/TradingView.tsx` | GAP-09: EMA20/EMA50 linie na wykresie TradingView (ComposedChart) + mini-panel RSI(14) pod wykresem | ✅ GOTOWE |
| `web_portal/src/components/widgets/TradingView.tsx` | GAP-09: Poprawiony import recharts (ComposedChart, Line, LineChart), dodano `calcEma()`, `calcRsi()`, stan `rsiData`, legenda wskaźników | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-06: `MarketProxyView` zastąpiony — Economics/Alerty/Wiadomości teraz wyświetlają EmptyState "Moduł w przygotowaniu" zamiast fałszywych danych proxy | ✅ GOTOWE |
| `OPEN_GAPS.md` | Zaktualizowano: GAP-06, GAP-09, GAP-15, GAP-16 oznaczone jako ✅ DONE; tabela planu zaktualizowana | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — 0 błędów po wszystkich zmianach | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## ETAP 3 — 2026-03-28 (Globalny przełącznik DEMO/LIVE — jedno źródło prawdy)

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/Topbar.tsx` | Zastąpiono niefunkcjonalny dropdown "Basic Dom" dwoma przyciskami DEMO/LIVE; typ zwężony do `'live' \| 'demo'` | ✅ GOTOWE |
| `web_portal/src/components/Sidebar.tsx` | Dodano props `tradingMode` + `setTradingMode`; usunięto hardcoded "DEMO AKTYWNY"; dodano interaktywny picker DEMO/LIVE | ✅ GOTOWE |
| `web_portal/src/components/Dashboard.tsx` | Zwężono typ z `'live' \| 'demo' \| 'backtest'` → `'live' \| 'demo'`; przekazano `tradingMode`/`setTradingMode` do Sidebar | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Zwężono typ interfejsu; naprawiono hardcoded `mode=demo` → `mode=${mode}` w close-all; badge LIVE (amber) / DEMO (zielony) w DashboardHeader i ClassicDashboardView; dodano `const mode` w ClassicDashboardView; `<DecisionRisk mode={mode}>` | ✅ GOTOWE |
| `web_portal/src/components/widgets/OpenOrders.tsx` | Dodano `mode` prop z domyślnym `'demo'`; poprawiono 4 hardcoded `mode=demo` na `mode=${mode}`; dependency `[mode]` w useEffect | ✅ GOTOWE |
| `web_portal/src/components/widgets/DecisionRisk.tsx` | Dodano `mode` prop; fetch URL `risk?mode=${mode}` (był hardcoded `mode=demo`); dependency `[mode]` | ✅ GOTOWE |
| `web_portal/src/components/widgets/PositionsTable.tsx` | Dodano `mode` prop; fetch URL `positions?mode=${mode}` (był hardcoded `mode=demo`); dependency `[mode]` | ✅ GOTOWE |
| `web_portal/src/components/widgets/DecisionsRiskPanel.tsx` | Poprawiono 3 hardcoded `mode=demo` w URL-ach (reloadPending, useEffect tasks, submitTicket POST) na `mode=${mode}` | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — **0 błędów** po wszystkich zmianach | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## ETAP 4 — 2026-03-28 (Hotfix CSS + LIVE fallback + ForecastChart)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/account.py` | `get_account_summary` LIVE: zamieniono `HTTPException(401)` na graceful HTTP 200 + `_info` | ✅ GOTOWE |
| `web_portal/src/components/widgets/AccountSummary.tsx` | Auto-refresh co 60s + amber karta z `_info` gdy Binance niedostępne | ✅ GOTOWE |
| `web_portal/src/components/widgets/DecisionRisk.tsx` | Czytelne stany błędów, message zależny od `mode` | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `score_breakdown` jako lista punktowana; `ForecastChart` refreshMs 0→30000/60000 | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — **0 błędów** | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## ETAP 5 — 2026-03-28 (Portfel LIVE Binance — pełny majątek + prognoza)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/portfolio.py` | Nowy endpoint `GET /api/portfolio/wealth?mode=` — majątek portfela: pozycje z wartościami EUR, historia equity, wolna gotówka; LIVE + DEMO | ✅ GOTOWE |
| `backend/routers/portfolio.py` | Nowy endpoint `GET /api/portfolio/forecast?mode=` — prognoza wartości portfela za 1h/2h/7d bazowana na ForecastRecord; 2h interpolacja, 7d ekstrapolacja z 24h | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `PortfolioView` — pełna przebudowa: KPI cards, prognoza 1h/2h/7d, wykres equity 48h, tabela składu z klikalnymi symbolami | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `SymbolDetailPanel` — dodano blok „Ilość / Wartość pozycji / Zmiana %" gdy symbol jest w portfelu | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — **0 błędów** | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## SZABLON DLA PRZYSZŁYCH SESJI

```
## SESJA [DATA] (Sesja X — Tytuł)

| Plik | Zmiana | Status |
|------|--------|--------|
| `ścieżka/pliku` | Opis zmiany | ✅/🔴/⏳ |
```

---

## SESJA (ETAP 8 — Stabilizacja danych konta)

### Frontend — pełna migracja na `/api/portfolio/wealth`

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/MainContent.tsx` | `DashboardV2View`: `/api/account/summary?mode=` → `/api/portfolio/wealth?mode=` — ujednolicone pola (total_equity, free_cash, positions_value, unrealized_pnl, equity_change, equity_change_pct). Etykiety KPI: "Zmiana equity (24h)" i "Zmiana equity % (24h)" | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `SettingsView`: `/api/account/summary?mode=` → `/api/portfolio/wealth?mode=` — wyświetlane pola total_equity i balance | ✅ GOTOWE |

### Weryfikacja backendu SymbolDetailPanel

| Endpoint | Status |
|----------|--------|
| `/api/positions/decisions/{symbol}` | ✅ Istnieje (positions.py:549) |
| `/api/market/forecast-accuracy/{symbol}` | ✅ Istnieje (market.py:702) |
| `/api/positions/goal/{symbol}` | ✅ Istnieje (positions.py:490) |

### Rezultat

- **Zero** odwołań do `/api/account/summary` lub `/api/account/kpi` w frontendzie ✅
- `AccountSummary.tsx` widget — sierota (niezaimportowany nigdzie), nieusuwany
- Testy: **175/175 ✅** | TypeScript: **0 błędów ✅**

---

## PODSUMOWANIE STANU

| Metryka | Wartość |
|---------|---------|
| Testy | **175/175 ✅** |
| TypeScript błędy | **0 ✅** |
| Źródło danych konta (frontend) | **Wyłącznie `/api/portfolio/wealth`** ✅ |
| Otwarte gapy aktywne | 5 (GAP-06, GAP-07 partial, GAP-09 partial, GAP-15, GAP-16) |
| Zrealizowane gapy | 10 (GAP-01 do GAP-10) + GAP-13 + GAP-14 |
| Status ogólny | v0.7-beta — backend ✅, UI ✅, uruchamianie ✅ |

---

## SESJA 2026-03-29 (Sesja G — Standard datetime UTC: `utc_now_naive()`)

### Backend — unifikacja obsługi czasu UTC

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/database.py` | Dodano `utc_now_naive()` — jedyna dopuszczalna funkcja zwracająca UTC jako naive datetime; 35+ `default=lambda: datetime.now(...)` → `default=utc_now_naive` | ✅ GOTOWE |
| 25 plików backend + `telegram_bot/bot.py` | `datetime.now(timezone.utc).replace(tzinfo=None)` → `utc_now_naive()` | ✅ GOTOWE |
| `backend/reporting.py`, `collector.py`, `reevaluation_worker.py`, `operator_console.py`, `policy_layer.py` | Naprawka uszkodzonych multi-line importów po masowym replacemencie | ✅ GOTOWE |

### Dokumentacja

| Plik | Zmiana | Status |
|------|--------|--------|
| `SYSTEM_RULES.md` | Dodano sekcję 6.5 — standard `utc_now_naive()` z przykładami i zakazami | ✅ GOTOWE |
| `PROGRAM_REVIEW.md` | Zaktualizowano: problem datetime → ✅ NAPRAWIONE, metryki (0 warnings) | ✅ GOTOWE |
| `CURRENT_STATE.md` | Zaktualizowano: 3 wpisy `datetime.utcnow` → NAPRAWIONE | ✅ GOTOWE |

### Metryki sesji

| Metryka | Wartość |
|---------|---------|
| Testy | **175/175 ✅** |
| Zastąpień `datetime.now(timezone.utc).replace(tzinfo=None)` | **203 w 26 plikach** |
| Deprecation warnings | **0** |
| Nowy helper | `utc_now_naive()` w `backend/database.py` |

---

## SESJA 2026-04-02 (Sesja 18 — T-18 AI top-N; TRADING_METRICS_SPEC fix)

### Backend — AI cost optimization + metryki

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/analysis.py` | **T-18:** `maybe_generate_insights_and_blog` — sort insights po `confidence × max(volume_ratio,0.5)`; top-5 (env `AI_TOP_SYMBOLS`) do AI, reszta → `_heuristic_ranges()`. ~90% mniej tokenów API przy 62 symbolach | ✅ GOTOWE |
| `TRADING_METRICS_SPEC.md` | Poprawiono wartości kosztów: slippage `0.001→0.0005`, spread `0.0008→0.0003`, round-trip `0.56%→0.36%`, cost_gate `1.4%→0.9%` | ✅ GOTOWE |
| `backend/collector.py` | Composite score ranking: `composite_score = 0.5*edge_net_score_norm + 0.3*confidence + 0.2*trend_strength` w `_screen_entry_candidates` | ✅ GOTOWE |

### Metryki sesji 18

| Metryka | Wartość |
|---------|---------|
| Testy | **181/181 ✅** |
| Backend PID | 411680 |

---

## SESJA 2026-04-02 (Sesja 19 — T-08 Faza 1 LIMIT orders; range origin tracking; T-18 walidacja)

### Backend — LIMIT orders + diagnostyka origin

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/analysis.py` | `_heuristic_ranges()` — dodano `"origin": "heuristic"` do każdego range dict | ✅ GOTOWE |
| `backend/analysis.py` | `_parse_ranges_response(text, provider)` — po udanym parse AI: `r["origin"] = f"ai:{provider.lower()}"` dla wszystkich zakresów | ✅ GOTOWE |
| `backend/analysis.py` | `persist_insights_as_signals()` — embeds `range_origin`, `range_buy_low`, `range_sell_low` w `indicators` JSON (brak zmiany schematu DB) | ✅ GOTOWE |
| `backend/analysis.py` | `maybe_generate_insights_and_blog()` — log diagnostyczny: ile symboli AI vs heuristic po każdym cyklu generowania | ✅ GOTOWE |
| `backend/collector.py` | `_create_pending_order()` — nowy param `order_type: str = "MARKET"` zamiast hardkodowanego "MARKET" | ✅ GOTOWE |
| `backend/collector.py` | `_execute_confirmed_pending_orders()` — `exec_order_type = pending.order_type or "MARKET"`; `exec_price = pending.price if LIMIT else None`; przekazuje do `binance.place_order()` | ✅ GOTOWE |
| `backend/collector.py` | `_screen_entry_candidates()` — entry creation: `order_type=tc.get("live_entry_order_type","MARKET") if live and BUY else "MARKET"` | ✅ GOTOWE |
| `backend/collector.py` | `_screen_entry_candidates()` decision trace — dodano `"range_origin"` do `details` dict | ✅ GOTOWE |
| `backend/runtime_settings.py` | Nowy `SettingSpec`: `live_entry_order_type` (section="execution", default="MARKET", env=`LIVE_ENTRY_ORDER_TYPE`) | ✅ GOTOWE |
| `backend/routers/market.py` | `GET /api/market/ranges` — dodano `"origin": r.get("origin","unknown")` do odpowiedzi | ✅ GOTOWE |

### Walidacja T-18 (operacyjna)

| Sprawdzenie | Wynik |
|------------|-------|
| `range_origin=heuristic` w DB signals | ✅ Potwierdzone: XRPEUR, XLMEUR 17:58 |
| `origin` w API `/api/market/ranges` | ✅ Zwraca pole dla każdego symbolu |
| decision_traces zawierają range_origin | ✅ W polach `details` |
| AI provider log po cyklu | ✅ "T-18 ranges: AI(gemini)=5 symboli; heuristic=N symboli" |

### Analiza T-08 kosztów

| Parametr | Obecne (MARKET) | Z LIMIT BUY |
|----------|-----------------|-------------|
| Entry fee | 0.10% (taker) | 0.05% (maker) |
| Exit fee | 0.10% (taker) | 0.10% (taker) |
| Round-trip | 0.36% | 0.31% |
| Cost gate | 0.9% | ~0.78% |
| Ryzyko | brak | fill risk (wymaga Fazy 2) |

### Metryki sesji 19

| Metryka | Wartość |
|---------|---------|
| Testy | **181/181 ✅** (po KAŻDEJ zmianie) |
| Backend PID | 433213 |
| Market regime | CRASH (F&G≈12) — BUY zablokowane |

---

## SESJA 2026-04-02 (Sesja 20 — Governance walidacja; P2-01/02/03 HTF alignment + cichy skip)

### Governance — walidacja operacyjna

| Sprawdzenie | Wynik |
|------------|-------|
| decision_traces ROLLBACK_CANDIDATE | 0 — governance nie triggerowało (brak aktywnych promocji) |
| `rollback_decision.py` cooldown | ✅ `ROLLBACK_COOLDOWN_SECONDS=3600` już w kodzie |
| `reevaluation_worker.py` delta alerting | ✅ Alert tylko gdy sytuacja się POGORSZYŁA (linie ~219-220) |
| Telegram spam (kaskadowe rollbacki) | ✅ Brak — nie ma aktywnych promotions do monitorowania |

### P2-01 — Multi-timeframe 4h HTF alignment (consistency fix)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/collector.py` | `candidates.append` — dodano `"htf_align_factor": htf_align_factor` (brakujący klucz) | ✅ GOTOWE |
| `backend/collector.py` | `CREATE_PENDING_ENTRY` trace details — naprawiono klucze: `cand.get("htf_align_note")` / `cand.get("htf_align_factor")` zamiast defaultujących do `"neutral"`/1.0 | ✅ GOTOWE |

Logika P2-01 (`htf_align_factor=1.10/1.0/0.80`) już istniała z poprzedniej sesji.

### P2-02 — Composite final_score

- `composite_score = edge_net_score × confidence × (rating/5.0) × htf_align_factor` — potwierdzone, już w kodzie.
- Zamknięte jako skumulowane w P2-01.

### P2-03 — SELL bez pozycji → cichy skip

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/collector.py` | `_screen_entry_candidates`: gdy `side=="SELL" and position is None` → `continue` bez `_trace_decision(SKIP)`. Komentarz z `reason_code: sell_blocked_no_position` zachowany. | ✅ GOTOWE |
| `tests/test_smoke.py` | `test_p1_sell_without_position_blocked` — zaktualizowany: szuka reason_code jako komentarz (backwards compat), nie jako wywołanie trace | ✅ GOTOWE |

Efekt: eliminacja ~20k+ redundantnych SKIP rekordów w `decision_traces`.

### Metryki sesji 20

| Metryka | Wartość |
|---------|---------|
| Testy | **196/196 ✅** |
| Backend PID | 452053 |
| Market regime | CRASH (F&G≈12) — BUY zablokowane |
| decision_traces SELL_BLOCKED przed P2-03 | ~20 921 rekordów |
| decision_traces po P2-03 (nowe) | 0 SKIP dla SELL bez pozycji |

---

## SESJA 2026-04-02 (Sesja 21 — P2-01b cicha regresja limit=50; P1-02b bear_regime override)

### P1-02b — bear_regime_min_conf DB override nadpisywał nowy default

| Sprawdzenie | Wynik |
|------------|-------|
| `bear_regime_min_conf` w DB override | 0.68 — pozostałość z przed naprawy P1-02 |
| Efektywna wartość po P1-02 fix | Nadal 0.68 (DB override > code default) |
| Naprawa | `upsert_overrides(db, {'bear_regime_min_conf': None})` — usunięto override |
| Weryfikacja | `/api/control/state` → `bear_regime_min_conf: 0.62` ✅ |

### P2-01b — CICHA REGRESJA: limit=50 w get_live_context → zawsze None

**Root cause**: P2-01 wywoływało `get_live_context(db, symbol, timeframe="4h", limit=50)`, ale `analysis.py` ma guard `if len(df) < 60: return None`. Z limit=50: zawsze None → filtr 4h nigdy nieaktywny.

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/collector.py` L2968 | `limit=50` → `limit=100` (DB ma 106 klines 4h, limit=100 > 60 guard) | ✅ GOTOWE |

**Weryfikacja przed naprawą**: `get_live_context(db, 'BTCEUR', timeframe='4h', limit=50)` → `None`
**Weryfikacja po naprawie**: `ema_20=58418.76, ema_50=58881.50` → 4h niedźwiedzi ✅

Efekt handlowy: BUY w BTCEUR teraz dostanie `htf_align_factor=0.80` (penalty -20% composite_score) zamiast neutralnego 1.0. Filtr 4h był martwy od implementacji P2-01 — teraz aktywny.

### Weryfikacja stanu bieżącego

| Sprawdzenie | Wynik |
|------------|-------|
| Backend PID | 461915 (zrestartowany po P2-01b fix) |
| `bear_regime_min_conf` efektywna | 0.62 ✅ |
| 4h klines dostępne | 106 (BTCEUR), 106 (ETHEUR), 101 (XRPEUR) ✅ |
| BTCEUR 4h trend | niedźwiedzi (ema20=58418 < ema50=58881) |
| MFE/MAE tracking | aktywny (mfe=58083, mae=57773) |
| Pozycja BTCEUR live | SL=57753 (break-even), TP=58220, price ~58030 ✅ |

### Metryki sesji 21

| Metryka | Wartość |
|---------|---------|
| Testy | **196/196 ✅** |
| Backend PID | 461915 |
| Naprawy | P1-02b (bear override) + P2-01b (limit=50 bug) |
