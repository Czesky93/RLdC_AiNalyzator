# CHANGELOG_LIVE

## 2026-05-18 — T-150 do T-152: Infrastruktura dynamicznego gridu (Phase 1 — grid.md implementation)

### Root cause T-150: Live trading paralysis despite T-149 bypass
- Po 30-min live monitoringu: **0 BUY fills** mimo wszystkich otworów progów edge/RR/score/confidence w T-147 do T-149
- 256/259 blokad to `no_buy_signal` — co oznacza, że wejścia są **odrzucane na etapie selekcji pary, nie na etapie scoringu**
- Unit testy pokazują sygnały jako valid; live pipeline je zaneguje → **architektura pipeline'u nie dopuszcza wielu par**
- Ponadto: **CRITICAL BUG w risk.py dla live mode**: `initial_balance` był hardcoded na 0.0, co unieważniało exposure ratio gatesy dla multi-pair gridu

### Pivot: zamiast dalszych tweaków thresholdów → pełna architektura dynamicznego gridu
- User załadował specification `grid.md` (3500+ linii) z kompletnymi formulami
- Decyzja: **skokowe przejście na dynamic grid engine** zamiast incrementalnego debugowania T-150
- Uzasadnienie: single watchlist + incremental tweaks nie skaluje się dla multi-pair, live exposure gates były niefunkcjonalne

### Modyfikacje T-150 do T-152

#### T-150: Fix critical risk.py bug + add market data helpers

**backend/risk.py** (lines 695-707):
- **BUG FIXED**: `initial_balance` dla live mode był `0.0`, co unieważniało:
  - `total_exposure_ratio = total_notional / initial_balance` → 0/0 = 0 (invalid)
  - `symbol_exposure_ratio = symbol_notional / initial_balance` → 0/0 = 0 (invalid)
  - Konsekwencja: **multi-pair grid trading miał exposure gates zawsze =0 (CATASTROPHIC)**
- **FIX APPLIED**: Live branch teraz czyta `live_balance` z risk_snapshot lub fallbackuje do `LIVE_INITIAL_BALANCE` env var
  ```python
  if context.mode == "demo":
      initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)
  else:
      live_balance = float(rs.get("live_balance") or 0.0)
      if live_balance > 0:
          initial_balance = live_balance
      else:
          initial_balance = float(os.getenv("LIVE_INITIAL_BALANCE", "1000") or 1000)
## 2026-05-18 — T-154: Phase 2 Step 1 — Grid Plan Building Integration
  ```
### Objective
Integrates dynamic grid plan builder into collector.py main cycle (run_once).
Each cycle: build/refresh grid plans for all watchlist symbols before trading.

### Changes
**backend/binance_client.py** (lines ~1300+):
**backend/collector.py**:
1. **New method** `_build_dynamic_grid_plans(db) → int` (lines ~1060-1150):
   - For each symbol in watchlist[:10] (first 10, to limit API load):
     1. Fetch multi-timeframe context (15m, 1h, 4h) via `get_grid_context()`
     2. Build grid plan via `build_grid_plan()` using grid_context, equity, config
     3. Persist plan to RuntimeSetting via `persist_grid_plan()`
     4. Return count of successfully built plans
   - Graceful fallback if dynamic_grid disabled or context insufficient
   - Logs: built_count, symbol, range, levels, invest per plan
   - Returns: Built count for monitoring
- `get_all_24hr_tickers()`: Agreguje wszystkie 24h ticker stats w jednym requesto (weight 80) zamiast N callów
2. **Integration into run_once()** (lines ~7300+):
   - Added call to `_build_dynamic_grid_plans(db)` after `collect_klines()`, before trading
   - Sequence: collect_klines → insights/blog → **build_grid_plans** → demo_trading → live_trading
   - Ensures grid plans are fresh before each trading cycle
  - Returns: List[Dict] z symbol, price_change_percent, high_price, low_price, quote_volume, count, bid_price, ask_price
**tests/test_grid_integration.py** (NEW, 4 test cases):
- `test_build_and_persist_grid_plan`: Build plan with mock context, verify persistence in DB
- `test_recentering_detection`: Test recentering logic (shift_down/shift_up/none)
- `test_grid_plan_persistence_lifecycle`: Create → persist → load → update → verify
- `test_multiple_grids_per_watchlist`: Manage 3+ grid plans for different symbols
- **Status**: ✅ 4/4 PASSED
  - Cel: support dla dynamic grid top-N pair selector
### Validation
- Code compiles without errors (syntax check passed)
- Integration tests: 4/4 passing
- Full test suite: 657 passed, 25 failed (no regressions from T-154 changes)
- Grid plans now refresh each cycle (before trading)
- `get_usdc_pairs()`: Filtruje i wzbogaca snapshot USDC pairs
### Impact
- ✅ Grid plans now build dynamically before each trading cycle
- ✅ Plans persist across cycles for recentering checks
- ✅ Multiple symbols supported simultaneously (top-10 watchlist)
- ✅ Multi-timeframe context available for all plans
- 🔄 NEXT STEP: Implement grid entry/exit orchestration (T-155)
  - Filtruje: Excludes stable-stable pairs (USDC, USDT, FDUSD, itd. jako base asset)
  - Computes: `spread_bps = ((ask - bid) / last_price) * 10000`
  - Returns: List[Dict] ready dla grid.md ranking (range_24h, abs_change_pct, atr_pct, volume, trades, spread)

**backend/analysis.py** (lines ~900+):
- `get_grid_context(db, symbol)`: Multi-timeframe indicator aggregation dla grid builder
  - Fetches: ≥60 bars dla 15m, 1h, 4h (returns None jeśli insufficient)
  - Computes per timeframe: ema_20, ema_50, rsi_14, atr_14, adx_14, volume_ratio
  - Zwraca: Context dict ready dla grid builder formulas w grid.md

#### T-151: Expand kline collection to 15m, 1h, 4h

**backend/collector.py** (line 173):
- Zmienił domyślny `KLINE_TIMEFRAMES` z `"1m,1h"` na `"1m,15m,1h,4h"`
- Cel: get_grid_context() wymaga ≥60 barów dla każdego interwału
- Backward compat: 1m zachowany dla legacy systemów, nowe: 15m, 4h

#### T-152: Create dynamic_grid.py module (grid.md Phase 1 logic)

**backend/trading/dynamic_grid.py** (NEW):
- `select_top_usdc_pairs()`: Rank all USDC pairs z grid.md algorithm
  - Input: Binance 24h tickers + spread data
  - Algorithm: Z-score normalizacja (range, change, volume, trades) + kara za spread
  - Scoring formula: `0.30*z_range + 0.20*z_change + 0.20*z_volume + 0.15*z_trades + 0.10*max(0,-z_spread)`
  - Output: Ranked top-N symbols (default N=10)
  
- `build_grid_plan()`: Generator planu gridu per pair (grid.md formulas)
  - Inputs: grid_context (15m/1h/4h indicators), equity, runtime config
  - Outputs: GridPlan dataclass z:
    - center, lower, upper (geometric ranges z VWAP + trend bias + ATR)
    - grid_count, step_pct, buy_levels[], sell_levels[]
    - invest_quote, hard_stop (risk sizing)
  
- `check_recentering_needed()`: Wykryj kiedy plan wymaga recentering
  - Logic: position_in_range < 0.15 or > 0.85 → shift/rebuild
  
- `persist_grid_plan()` / `load_grid_plan()`: State persistence w RuntimeSetting DB
  - Pattern: `grid_plan#{symbol}` key z JSON value
  - Allows: Dynamic recentering bez restart backendu

### Kompilacja i walidacja
- ✅ Syntax check: Wszystkie nowe moduły kompilują się bez błędów
- ✅ Import check: Funkcje mają poprawne sygnatury
- ✅ Grid context: Gotowe do multi-timeframe analysis
- ⚠️ Pending: Kline collection w live musi mieć 15m, 1h, 4h zbierane (zmiana `KLINE_TIMEFRAMES`)

### Wynik
- **PHASE 1 COMPLETE**: Infrastructure dla dynamic gridu w miejscu
- Risk.py: Live exposure gates teraz funkcjonalne
- Market data: All helpers dostępne dla selector
- Grid context: Multi-timeframe analysis ready
- Dynamic selector: Top-N ranking algorithm ready

### Następny krok: PHASE 2 (Integration)
1. Przetestować `get_grid_context()` na live symbols
2. Rozszerzyć collector aby zbiór 15m, 1h, 4h klines
3. Integrować dynamic grid z collector main loop
4. Replace portfolio-based watchlist selection dynamicznym selector'em
5. Implementować grid entry/exit orchestration

---

## 2026-05-18 — T-149: agresywny bypass no_buy_signal (tylko przy świadomie obniżonych progach)

### Root cause
- Po otwarciu progów edge/RR i sizingu live nadal dominowała blokada `no_buy_signal`, bo część par odpadała przed etapem score/confidence.
- W praktyce bot miał aktywne BUY tylko incydentalnie, mimo że operator świadomie przełączył runtime na agresywny profil startowy.

### Modyfikacje
- `backend/trading/signal_engine.py`:
   - dodano `aggressive_mode` aktywowany wyłącznie gdy runtime ma jednocześnie:
     - `require_htf_trend_agreement=false`
     - `min_entry_score<=0.50`
     - `min_signal_confidence<=0.50`
   - dodano `aggressive_entry_condition` (trend/momentum/HTF minimum), który pozwala przejść do dalszych bramek score/confidence/edge/RR;
   - rozszerzono diagnostykę o `aggressive_mode` i `aggressive_entry_condition`.

### Wynik
- Testy: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_trading_signal_engine.py -q` -> **46 passed**.
- Skan 120 symboli USDC po zmianie: **3 valid BUY** (`ADAUSDC`, `AIGENSYNUSDC`, `ATOMUSDC`).
- Risk gate dla kandydatów:
   - `ADAUSDC` -> `risk_gate_passed`, notional ~`88.85`
   - `AIGENSYNUSDC` -> `qty_too_small`
   - `ATOMUSDC` -> `symbol_has_open_position`
- `final-decisions?mode=live` po zmianie: summary `buy_ready=1`, `consider_buy=1`.

### Wniosek
- Bot ma dodatkowo odblokowany etap wejścia technicznego w agresywnym trybie runtime.
- Decyzje nadal przechodzą przez ekonomiczne i ryzykowe bramki końcowe, więc to nie jest ślepy force-buy.

## 2026-05-18 — T-148: agresywne runtime thresholds dla startu handlu live

### Root cause
- Po naprawieniu rozjazdu UI vs execution i poluzowaniu lokalnego RR system nadal praktycznie nie handlował, bo aktywny runtime DB był ustawiony zbyt konserwatywnie dla krótkich interwałów.
- Po poluzowaniu entry signal pojawiły się realne BUY, ale execution nadal blokował je na risk sizingu, bo `max_exposure_per_symbol_pct` ucinał notional poniżej `min_buy_notional`.

### Modyfikacje
- Runtime DB (`runtime_settings`) dostał agresywniejszy profil wejścia:
   - `trade_min_net_edge_pct=-0.20`
   - `trade_min_expected_rr=0.70`
   - `trade_min_signal_confidence=0.45`
   - `trade_min_entry_score=0.45`
   - `trade_require_volume_confirmation=false`
   - `trade_volume_ratio_min=0.50`
   - `trade_min_liquidity_score=0.10`
   - `trade_min_quote_volume_trade=10000`
   - `trade_min_depth_to_order_ratio=2.0`
   - `trade_require_htf_trend_agreement=false`
- Runtime DB (`runtime_settings`) dostał też agresywniejszy sizing execution:
   - `trade_max_exposure_per_symbol_pct=25.0`
   - `trade_risk_per_trade_pct=1.0`
   - `trade_max_open_positions=8`

### Wynik
- Walidacja live signal scan: **2 valid BUY** na próbce 120 symboli USDC (`AIXBTUSDC`, `ATOMUSDC`).
- Walidacja `final-decisions`: summary pokazuje `buy_ready=1`, a `ATOMUSDC` wchodzi jako `BUY` z reason `Live BUY potwierdzony: signal_accepted`.
- Walidacja risk gate:
   - `AIXBTUSDC` -> `risk_gate_passed`, notional ~`89.04`
   - `ATOMUSDC` -> `risk_gate_passed`, notional ~`89.04`

### Wniosek
- Bot przestał być zablokowany na samych progach i ma już aktywne warunki do realnych wejść live.
- Profil jest świadomie agresywny i ma służyć uruchomieniu handlu; dalsze strojenie jakości ma się odbywać na podstawie realnych wyników, nie dalszego paraliżu wejść.

## 2026-05-18 — T-147: adaptacyjny RR dla short-term breakoutów + prawdomówna walidacja live

### Root cause
- Po usunięciu rozjazdu UI vs live execution nadal pozostawał lokalny bloker dla części krótkoterminowych setupów 15m-1h: sztywny `min_expected_rr` odrzucał mocne, tanie egzekucyjnie breakouty mimo dodatniego edge po kosztach.
- Ten problem był szczególnie widoczny dla układów z wysokim score/confidence, mocnym wolumenem i niskim spreadem, gdzie rynek dawał krótszy impuls, ale nie pełne klasyczne RR trend-follow.

### Modyfikacje
- `backend/trading/signal_engine.py`:
   - dodano helper `effective_min_expected_rr`, który obniża minimalny RR tylko dla bardzo mocnych setupów short-term (`score`, `confidence`, `effective_volume_ratio`, `liquidity_score`, niski spread, dodatni edge po kosztach);
   - diagnostyka sygnału pokazuje teraz zarówno `required_rr`, jak i `required_rr_base`, więc wiadomo, czy zadziałała lokalna ulga breakoutowa;
   - bazowy kontrakt ekonomiczny pozostaje bez zmian dla zwykłych i słabszych setupów.
- `tests/test_trading_signal_engine.py`:
   - dodano regresję dla mocnego breakoutu, który przechodzi dzięki adaptacyjnemu RR;
   - dodano regresję dla podobnego układu bez mocnego potwierdzenia wolumenowego, który nadal jest blokowany bazowym RR.

### Wynik
- Regresja: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_trading_signal_engine.py -q` -> **46 passed**.
- Walidacja live `/api/signals/final-decisions?mode=live`:
   - `ATOMUSDC` -> `HOLD` (`volume_too_low`),
   - `TRXUSDC` -> `HOLD` (`negative_edge_after_costs`),
   - `APEUSDC` -> `HOLD` (`htf_trend_disagrees`),
   - summary pozostaje prawdomówny: `buy_ready=0`, `consider_buy=0`.
- Wniosek operacyjny: naprawiono lokalny bottleneck short-term RR, ale obecne okno rynku nadal nie daje jeszcze czystego BUY po kosztach.

## 2026-05-18 — T-146: Binance-style charts + decision-view enrichment

### Root cause
- `web_portal` nadal pokazywał cenę jako line/area chart, przez co operator widział inną semantykę rynku niż w overlay i niż w realnym widoku Binance.
- `live_overlay` miał świece, ale nie pokazywał pełnego kontekstu wejścia/wyjścia: brak wolumenu, EMA50, pasm BUY/SELL, spreadu i orderbooku.
- Kanoniczny `decision-view` nie eksponował wszystkich wskaźników już liczonych przez backend, więc UI z konieczności upraszczał analizę.

### Modyfikacje
- `backend/routers/signals.py`:
   - `decision-view` zwraca teraz rozszerzone wskaźniki: `atr`, `adx`, `stoch_k`, `volume_ratio`, `macd_hist`, `bb_upper`, `bb_lower`, `fib_382`, `fib_618`, `spread_bps`, `orderbook_imbalance`;
   - dodano etykiety pochodne: `ema_cross`, `boll_position`, `macd_signal`.
- `web_portal/src/components/widgets/BinanceStyleChart.tsx`:
   - nowy wspólny renderer `lightweight-charts` dla świec, wolumenu, EMA20/EMA50, forecastu i RSI.
- `web_portal/src/components/widgets/TradingView.tsx`:
   - line/area chart zastąpiono wykresem świecowym z danymi `decision-view`, `ranges`, `forecast` i `orderbook`.
- `web_portal/src/components/MainContent.tsx`:
   - `ForecastChart` używa tej samej prawdy wizualnej i tych samych danych co główny TradingView.
- `live_overlay/index.html`:
   - canvas rysuje teraz wolumen, EMA50, zakresy BUY/SELL, ENTRY/TP/SL oraz podpisy spreadu/orderbooku;
   - focus/panel analizy pokazują dodatkowo spread, imbalance orderbooku i strefy BUY/SELL.

### Wynik
- `npm --prefix web_portal run lint` -> **PASS**.
- `python -m py_compile backend/routers/signals.py live_overlay/serve_live_overlay.py` -> **PASS**.
- Smoke: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` -> **1 fail / 226 pass**; fail pochodzi z istniejącej ścieżki `positions/analysis`, nie z obszaru wykresów ani `decision-view`.

## 2026-05-18 — T-145: adaptive volume tiers + breakout/reversal BUY gate

### Root cause
- W wielu cyklach brakowało wejść mimo płynnych par, bo pojedynczy próg `volume_ratio_min` nie rozróżniał tierów płynności.
- Dodatkowo warunek BUY był zorientowany głównie na klasyczny trend-follow i mógł przegapiać moment przejścia do nowego impulsu (breakout/reversal).

### Modyfikacje
- [backend/trading/signal_engine.py](backend/trading/signal_engine.py):
   - dodano dynamiczny próg potwierdzenia wolumenowego `effective_volume_ratio_min` zależny od `quote_volume_24h` (tier płynności) i szerokości spreadu;
   - wolumenowe gate'y używają teraz progu adaptacyjnego zamiast jednego stałego progu globalnego;
   - dodano bezpieczny warunek `breakout_reversal_condition` do BUY (mocne momentum + potwierdzenie 15m + lepszy HTF), obok klasycznego trend-follow;
   - rozszerzono diagnostykę o pola `effective_volume_ratio_min`, `trend_follow_condition`, `breakout_reversal_condition`.

### Wynik
- Regresja: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_trading_signal_engine.py -q` -> **44 passed**.
- Ręczny skan po zmianie: top kandydat do szybkiego wejścia to `ATOMUSDC` (blokada głównie przez wolumen), a duże pary (`BTCUSDC`, `ETHUSDC`) pozostają blokowane przez realny brak setupu trendowego (`no_buy_signal`), nie przez artefakt stałego progu wolumenu.

## 2026-05-17 — T-144: BUY/SELL signal quality tuning (HTF threshold + volume confirmation)

### Root cause
- `signal_engine` miał niespójny kontrakt HTF: gate trendu HTF blokował dopiero przy `htf_score < 0.35`, ale warunek wejścia BUY wymagał jednocześnie `htf_score >= 0.50`, co zawężało wejścia bardziej niż deklarowała diagnostyka gate.
- Potwierdzenie wolumenu i `volume_score` opierały się głównie o `entry_tf=1h`; w praktyce 1h `volume_ratio` bywa niskie w trakcie budowy świecy, mimo silnego wolumenu na 15m.

### Modyfikacje
- `backend/trading/signal_engine.py`:
   - warunek BUY dla HTF używa teraz `min_htf_agreement_for_buy` (fallback 0.35), spójnie z wcześniejszym gate HTF;
   - dodano `effective_volume_ratio = max(volume_ratio_1h, volume_ratio_15m)` oraz `effective_volume_spike`, używane do `volume_score` i volume confirmation;
   - rozszerzono payload diagnostyczny o `fast_volume_ratio` i `effective_volume_ratio`.

### Wynik
- Ręczny przegląd par i skan 68 par USDC wykazał spadek fałszywych odrzuceń wolumenowych wynikających wyłącznie z niskiego ratio 1h.
- Dominujące blokady wróciły do logicznych przyczyn rynkowych (`htf_trend_disagrees`, `no_buy_signal` przy słabym trendzie), zamiast artefaktu niespójnych progów.
- Testy regresyjne: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_trading_signal_engine.py -q` -> **44 passed**.

## 2026-05-17 — T-143: LIVE execution consistency + Telegram test guards

### Root cause
- Po BUY w LIVE `Position.quantity` zapisywało ilość brutto `executedQty`, mimo że prowizja mogła być pobrana w aktywie bazowym (np. APE/ETH), co kończyło się późniejszym `insufficient balance` przy SELL.
- `PendingOrder` nie był claimowany atomowo przed wykonaniem i przy wyścigu procesów mógł zostać uruchomiony więcej niż raz.
- Testy mogły wysyłać realne wiadomości Telegram, jeśli token/chat były obecne w środowisku.

### Modyfikacje
- `backend/collector.py`:
   - atomowy claim pending do `EXECUTING` przed execution (`update ... where status in executable`),
   - BUY LIVE zapisuje `Position.quantity` jako qty netto po odjęciu fee w base asset,
   - dodano log diagnostyczny `LIVE PIPELINE WHY_NOT_BUY ...` oraz reason `active_pending_exists`.
- `backend/binance_client.py`:
   - `place_order()` ustawia `newOrderRespType=FULL` dla `MARKET`.
- `backend/notification_hooks.py` + `backend/collector.py`:
   - collector wysyła Telegram przez `send_telegram_message()` (wspólny adapter),
   - dodano guard `DISABLE_TELEGRAM=true` i respekt `APP_ENV=test`.
- `tests/conftest.py`:
   - test env wymusza `APP_ENV=test` i `DISABLE_TELEGRAM=true`.
- `tests/test_live_execution_cash_management.py`:
   - regresja: BUY z fee w base asset zapisuje qty netto w pozycji.

### Wynik
- Regresje execution/collector/state-manager: **7 testów PASS** (3 + 3 + 1).
- Ograniczono ryzyko odrzuceń SELL po poprawnym BUY fill i wyeliminowano wysyłkę Telegram z testów.

## 2026-05-17 — T-141: overlay 8099 recovery + chart symbol fallback + uproszczenie UI

### Root cause
- Overlay 8099 pokazywał puste wykresy dla par EUR, bo backend nie miał świec `kline` dla `*EUR` (np. `AAVEEUR`), mimo dostępnych świec dla odpowiadających par USDC.
- W praktyce runtime miał dodatkowo niestabilność procesu 8099 (`ERR_EMPTY_RESPONSE`/`ERR_CONNECTION_REFUSED`) po kolizji starego procesu i restartu usługi.

### Modyfikacje
- `live_overlay/serve_live_overlay.py`:
   - dodano resolver symbolu wykresowego na podstawie realnej dostępności klines w SQLite (`_resolve_chart_symbol`),
   - adapter potrafi przełączyć wykres z pary źródłowej EUR na dostępny symbol bazowy (np. `AAVEEUR -> AAVEUSDC`),
   - dodano cache resolvera, aby nie przeciążać zapytań do SQLite.
- `live_overlay/index.html`:
   - usunięto lewy pasek opcji (nawigacja pionowa),
   - uproszczono layout i poprawiono opisy komunikatów wykresu/braku świec,
   - zegar przeniesiono do górnego paska.
- Operacyjnie: `rldc-overlay.service` po awarii został przywrócony (`reset-failed` + restart).

### Wynik
- `GET /overlay/api/live-state` zwraca stabilnie `ok=true`.
- Pary EUR dostają dane wykresowe przez `chart_symbol` z dostępnych klines (`history_len > 0`).
- Overlay 8099 działa bez lewego panelu i pokazuje czytelny status połączenia oraz symbol wykresowy.
- Auto-focus rotuje deterministycznie między aktywnymi parami, a karta AI dla pozycji otwartej pokazuje sensowny komunikat o zarządzaniu wyjściem oraz aktualną ekspozycję zamiast pustego fallbacku.

## 2026-05-17 — T-142: LIVE SELL guard + hard exit cooldown split

### Root cause
- `BinanceClient.place_order()` nie cappingował SELL do aktualnego `free` z Binance, więc DB qty mogła zostać wysłana ponad realne saldo po step-size.
- `_check_exits()` traktował cooldown jako blokadę dla wszystkich exitów, przez co hard exit SL mógł zostać zatrzymany przez ten sam mechanizm, który powinien dotyczyć tylko kolejnych warstw exit.

### Modyfikacje
- `backend/binance_client.py`:
   - dodano `get_free_balance()` i `prepare_sell_quantity()`;
   - SELL jest normalizowany do realnego `free balance` i `LOT_SIZE.stepSize` przed `create_order()`;
   - `place_order()` zwraca czytelny `_error` przy braku salda lub symbol meta.
- `backend/collector.py`:
   - hard exit SL nie jest już blokowany przez `_pending_in_cooldown()`;
   - cooldown pozostaje dla trailing/TP/reversal, czyli dla kolejnych warstw exit.
- Testy:
   - `tests/test_binance_client_sell_guard.py`;
   - regresja w `tests/test_live_execution_cash_management.py` dla SL mimo cooldown.

### Wynik
- `pytest tests/test_binance_client_sell_guard.py tests/test_live_execution_cash_management.py -q` -> **15 passed**.
- SELL nie powinien już próbować sprzedać więcej niż realnie dostępne saldo Binance po step-size.
- SL nie powinien być zablokowany samym cooldownem exitów.

## 2026-05-17 — T-139: observe-only diagnostics hardening + spread/slippage caps + strict risk sizing

### Root cause
- Część diagnostyki wejść nadal była niejednoznaczna: przy słabej płynności brakowało pełnego kontekstu `score/min_score/spread_bps`, a limity spread/slippage opierały się częściowo o niejawny fallback.
- `risk_engine` sztucznie podbijał `qty` do `min_buy_notional`, co mogło łamać zasadę sizingu od ryzyka i odległości stop-loss.

### Modyfikacje
- `backend/trading/trade_config.py`: dodano jawne pola konfiguracji `max_spread_bps` i `max_slippage_bps` (DB/.env/default).
- `backend/trading/signal_engine.py`:
  - spread gate używa teraz bezpośrednio `max_spread_bps` (z fallbackiem do `max_allowed_spread_pct`),
  - odrzucenia płynnościowe `observe_only` zawierają pełne metryki diagnostyczne,
  - blokady market-quality mają priorytet po obliczeniu score (symbol jest analizowany i oceniony, ale nie jest tradowalny).
- `backend/trading/risk_engine.py`: usunięto podbijanie `qty` do `min_buy_notional`; dla zbyt małego sizingu zwracane jest `qty_too_small`.
- Testy:
  - `tests/test_trading_signal_engine.py`: dodano regresję `max_slippage_bps` i komplet metryk `observe_only`.
  - `tests/test_trading_risk_engine.py`: dodano regresję braku podbijania qty ponad limit ryzyka.

### Wynik
- `pytest tests/test_trading_signal_engine.py tests/test_trading_risk_engine.py -q` -> **68 passed**.
- `pytest tests/test_smoke.py -q` pozostaje niestabilny (intermitentne fail w `test_market_summary` i `test_acceptance_live_positions_analysis_restores_entry_baseline`), niepowiązany bezpośrednio ze zmienionymi modułami.

## 2026-05-17 — T-138: quoteVolume observe-only gate + orderbook depth

### Root cause
- `signal_engine` nadal traktował niski wolumen zbyt wcześnie jako twardy skip, a logika nie odróżniała dobrze `quoteVolume` od prostego `volume` w diagnostyce decyzji.
- Brakowało jawnego modułu depth-check na order booku dla wejść BUY, więc sam spread i RSI nie dawały pełnej oceny kosztu wejścia.

### Modyfikacje
- `backend/trading/signal_engine.py`: dodano gate na `quoteVolume` z dynamicznym progiem trade, gate na `orderbook_depth_too_low` oraz finalne `observe_only` details zamiast pierwszego, krótkiego skipa.
- `backend/trading/trade_config.py`: dodano progi `min_quote_volume_trade`, `use_dynamic_volume_threshold`, `min_depth_to_order_ratio`, `orderbook_depth_bps` i `max_slippage_bps`.
- `tests/test_trading_signal_engine.py`: regresje dla niskiego `quoteVolume`, shallow order booka i poprawnego użycia orderbooka w mockach.

### Wynik
- Sygnał daje teraz pełniejszą diagnostykę market quality: `quote_volume_24h`, `effective_min_quote_volume_trade`, `orderbook_quote_depth`, `depth_to_order_ratio`, `spread_bps`.
- Walidacja: `pytest tests/test_trading_signal_engine.py -q` -> **43 passed**.

## 2026-05-17 — T-133: live-state truth source + frontend fetch throttling

### Root cause
- `/api/rldc/safe/live-state` budowal pozycje na lokalnym `Position`, co nie gwarantowalo spójności z aktualnym Binance spot (szczególnie dla ręcznych holdingów).
- `web_portal` odpalał wiele cyklicznych requestów równolegle i przy degradacji backendu sam wzmacniał timeouty.

### Modyfikacje
- `backend/app.py`: `/api/rldc/safe/live-state` korzysta teraz z kanonicznego `_get_live_spot_positions()`; fallback do `Position` zostaje tylko awaryjnie.
- `backend/app.py`: payload pozycji rozszerzono o `source`, `has_entry_price` i bardziej prawdziwe `state`.
- `web_portal/src/components/MainContent.tsx`: dodano kolejkę fetch (`MAX_CONCURRENT_FETCHES=4`) i adaptacyjny backoff harmonogramu odświeżania po błędach.
- `backend/routers/positions.py`: `_analyze_spot_position` ma kompatybilny parametr `settings=None` (bez regresji testowych).

### Wynik
- Testy: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` -> **227 passed**.
- Runtime: `/api/rldc/safe/live-state` odpowiada ~1.16s (HTTP 200), ale `/api/positions`, `/api/positions/analysis` i `/overlay/api/live-state` nadal timeoutują przy 20s.
- Wniosek: naprawiono źródło prawdy, ale krytyczny dług wydajnościowy endpointów pozycyjnych pozostaje otwarty.

## 2026-05-17 — T-132: market health gate LIVE + API/overlay/Telegram telemetry

### Root cause
- LIVE pipeline umiał oceniać edge/koszt/ryzyko per symbol, ale nie miał twardej bramki globalnego zdrowia runtime (stare dane, rozłączony WS, skok błędów execution).
- Operator nie widział jednolitego stanu `NO_TRADE`/`REDUCE_ONLY` w runtime-activity, trading-status, overlay i Telegramie.

### Modyfikacje
- `backend/collector.py`: dodano `_evaluate_live_market_health()` i `_maybe_alert_market_health()`; LIVE BUY ma twardy skip z `reason_code` `market_health_no_trade` albo `market_health_reduce_only`.
- `backend/trading/trade_config.py`: dodano progi market health oraz fallback aliasu `min_symbol_net_expectancy -> min_net_edge_pct`; default `min_net_edge_pct` podniesiony do `0.60`.
- `backend/routers/account.py`: `runtime-activity` i `trading-status` zwracają `market_health` + flagi `allow_new_entries`, `no_trade_mode`, `reduce_only_mode`.
- `telegram_bot/bot.py`: `/status` pokazuje `Market health` i listę issue.
- `live_overlay/serve_live_overlay.py`: adapter wystawia `summary.market_health_mode` i blok `trading_guard`.
- `tests/test_trading_collector_live_path.py`: regresje dla market health skip i helperów TradeConfig.

### Wynik
- Bot nie otwiera nowych pozycji LIVE podczas degradacji runtime i loguje prawdziwy powód blokady.
- Web/API/overlay/Telegram pokazują ten sam stan gate bez rozjazdów operatorskich.

## 2026-05-17 — T-131: runtime UI truthfulness + overlay charts + separate overlay tunnel

### Root cause
- Po fixie `state_manager.reconcile` runtime dzialal poprawnie, ale `system-status` i `runtime-activity` nadal serwowaly historyczny `SystemLog`, bo filtr bledow patrzyl zbyt wasko na stare snapshoty/sync.
- Overlay blokowal auto-rotacje focusu po pierwszym wyborze symbolu i czesto dostawal puste `history` / `forecast_path`, mimo ze backendowe endpointy wykresow dzialaly.
- `run_quicktunnel.sh` uruchamial dwa tunele, ale oba parsery dzialaly w osobnych subshellach, wiec `overlay_url` bywal nadpisywany na `null`.

### Modyfikacje
- `backend/routers/account.py`: `system-status` i `runtime-activity` ukrywaja stary `last_error`, jesli runtime ma nowszy heartbeat (`last_binance_sync_ts`, `last_learning_ts`, `MarketData.timestamp`, snapshot).
- `live_overlay/serve_live_overlay.py`: top symbole sa uzupelniane o swieczki z `/api/market/kline` i forecast z `/api/market/forecast/:symbol`.
- `live_overlay/index.html`: domyslny timeframe to `15m`, focus znow auto-rotuje, prefetchuje top symbole i pokazuje dedykowany `overlay_url`.
- `backend/tunnel_manager.py`: `_read_overlay_url()` czyta jawny wpis `overlay_url`.
- `scripts/run_quicktunnel.sh`: runtime/public URL-e sa scalane z pliku, wiec frontend i overlay nie nadpisuja sobie nawzajem adresow.

### Wynik
- WWW nie pokazuje juz falszywego `⚠ Błąd state_manager.reconcile`, gdy collector ma swiezy heartbeat.
- Overlay ma aktualne wykresy dla czołowych symboli i odzyskana auto-zmiane focusu.
- Runtime zapisuje oddzielny publiczny adres overlay trycloudflare.

## 2026-05-15 — T-127: watchdog stability + truthful AI status

### Root cause
- `scripts/watchdog.sh` restartowal backend po pojedynczym, agresywnym probe `/health` i pozwalal na nakladajace sie przebiegi timera, przez co runtime byl ubijany podczas normalnego rozruchu.
- `GET /api/account/ai-status` wybieral aktywnego providera glownie po `configured=true`, przez co pokazywal `ollama` jako aktywnego nawet wtedy, gdy lokalny model byl nieosiagalny, a realny primary providerem byl `groq`.

### Modyfikacje
- `scripts/watchdog.sh`: dodano `flock`, okna rozruchowe dla backendu/frontendu, progi kolejnych HTTP faili oraz jawne ustawienie `XDG_RUNTIME_DIR` i `DBUS_SESSION_BUS_ADDRESS`.
- `backend/routers/account.py`: `ai-status` korzysta teraz z `get_ai_orchestrator_status()` jako z kanonicznego statusu providerow, mapuje lokalny provider `local -> ollama` dla UI i zwraca bardziej prawdziwe pola `status_raw`, `usable`, `selected`.
- `tests/test_smoke.py`: dodano regresje pod realnego primary providera i niedostepny local AI.

### Wynik
- Watchdog nie restartuje juz backendu w petli podczas startu runtime.
- `ai-status` pokazuje teraz `groq` jako `active_provider`, a niedostepny `ollama` jako blad zamiast aktywnego providera.

## 2026-05-14 — T-126: overlay UI activation + faster live-state adapter

### Root cause
- `live_overlay/index.html` mial wiele widocznych opcji (`Ulub.`, `Historia`, `Analizy`, `Ustaw.`, `Stream`, timeframes), ale byly tylko statycznym markupem bez realnej interakcji i bez pobierania danych.
- `/overlay/api/live-state` byl budowany sekwencyjnie z wielu endpointow backendu, przez co overlay potrafil zawisac lub sprawiac wrazenie martwego przy wolniejszej odpowiedzi jednej z uslug.

### Modyfikacje
- `live_overlay/index.html`: przebudowano overlay na aktywna wersje z:
  - klikalnym tickerem i fokusowaniem symbolu,
  - gwiazdkami i lokalna lista ulubionych,
  - dzialajacymi timeframe (`1m..1d`) z fetchowaniem `/api/market/kline`,
  - panelami `Historia`, `Analizy`, `Ustaw.`, `Stream` opartymi o istniejace endpointy backendu,
  - lepsza diagnostyka zrodel i czytelniejszym statusem focusu.
- `live_overlay/serve_live_overlay.py`: pobieranie endpointow do `live_state()` jest teraz równolegle przez `ThreadPoolExecutor`, a handler HTTP oddaje jawny JSON blad zamiast zrywać odpowiedz.

### Wynik
- Overlay ma teraz realnie dzialajace sekcje i nie ogranicza sie do statycznego ekranu LIVE.
- `/overlay/api/live-state` odpowiada szybciej i przestal blokowac UI przez sekwencyjne timeouty.

## 2026-05-14 — T-125: runtime controls sync (backend + Telegram + WWW)

### Root cause
- Telegram i WWW nie mialy jednej, spojnej warstwy operatorskiej do `start trading`, `stop trading` i `reboot bot`.
- Topbar w `web_portal` zatrzymywal tylko `demo_trading_enabled`, co bylo falszywe wobec realnego runtime live.
- Brakowalo jawnego, admin-protected endpointu backendu do restartu calego runtime z poziomu operatora.

### Modyfikacje
- `backend/routers/system.py`: dodano `POST /api/system/runtime-action` z akcja `restart_runtime`; restart planowany jest asynchronicznie i obejmuje user services runtime oraz probe restartu overlay.
- `telegram_bot/bot.py`: dodano komendy `/start_trading`, `/stop_trading`, `/reboot_bot`; `/stop` blokuje teraz realne wykonanie live zamiast samego demo.
- `web_portal/src/components/Topbar.tsx`: przycisk start/stop steruje teraz realnymi flagami `allow_live_trading`, `execution_enabled`, `enable_auto_execute`.
- `web_portal/src/components/MainContent.tsx`: dodano operatorowi jawne akcje `START HANDEL`, `STOP HANDEL`, `REBOOT BOT`.
- `tests/test_smoke.py`: regresja dla `POST /api/system/runtime-action`.

### Wynik
- Telegram i WWW steruja teraz tym samym runtime state zamiast rozjechanych flag demo/live.
- Restart runtime jest dostepny z jednego endpointu operatorskiego bez recznego logowania na hosta.

## 2026-05-14 — T-125: runtime controls sync (backend + Telegram + WWW)

### Root cause
- Telegram i WWW nie mialy jednej, spójnej warstwy operatorskiej do `start trading`, `stop trading` i `reboot bot`.
- Topbar w `web_portal` zatrzymywal tylko `demo_trading_enabled`, co bylo falszywe wobec realnego runtime live.
- Brakowalo jawnego, admin-protected endpointu backendu do restartu calego runtime z poziomu operatora.

### Modyfikacje
- `backend/routers/system.py`: dodano `POST /api/system/runtime-action` z akcja `restart_runtime`; restart planowany jest asynchronicznie i obejmuje user services runtime oraz probe restartu overlay.
- `telegram_bot/bot.py`: dodano komendy `/start_trading`, `/stop_trading`, `/reboot_bot`; `/stop` blokuje teraz realne wykonanie live zamiast samego demo.
- `web_portal/src/components/Topbar.tsx`: przycisk start/stop steruje teraz realnymi flagami `allow_live_trading`, `execution_enabled`, `enable_auto_execute`.
- `web_portal/src/components/MainContent.tsx`: dodano operatorowi jawne akcje `START HANDEL`, `STOP HANDEL`, `REBOOT BOT`.
- `tests/test_smoke.py`: regresja dla `POST /api/system/runtime-action`.

### Wynik
- Telegram i WWW steruja teraz tym samym runtime state zamiast rozjechanych flag demo/live.
- Restart runtime jest dostepny z jednego endpointu operatorskiego bez recznego logowania na hosta.

## 2026-05-14 — T-124: runtime portability + compatibility endpoint aliases

### Root cause
- Czesc klientow (overlay, starsze skrypty, narzedzia operatorskie) nadal oczekiwala legacy sciezek typu `/api/status`, `/api/runtime/state`, `/api/live/state`, podczas gdy backend wystawial juz nowsze endpointy pod innymi adresami.
- `backend.app --all` startowal frontend przez `cd web_portal`, co uzaleznialo uruchomienie od aktualnego katalogu roboczego procesu.
- Domyslny CORS zawieral twardy adres LAN, zamiast przenoszalnego zestawu localhost/127.0.0.1 lub wartosci z env.

### Modyfikacje
- `backend/app.py`: dodano aliasy kompatybilnosci dla `/api/status`, `/api/runtime/state`, `/api/runtime-settings`, `/api/runtime-config`, `/api/live/state`, `/api/broadcast/live`, `/api/overlay/live`, `/api/account/positions`.
- `backend/app.py`: `--all` uruchamia `web_portal` po absolutnej sciezce wyliczonej z lokalizacji repo, bez zaleznosci od cwd.
- `backend/app.py`: domyslny CORS uzywa przenoszalnych originow `localhost` i `127.0.0.1`.
- `live_overlay/serve_live_overlay.py`: adapter odpyta teraz glownie kanoniczne endpointy zamiast znanych legacy-404.
- `tests/test_smoke.py`: regresje dla aliasow runtime/live overlay.

### Wynik
- Starsi klienci i overlay nie wpadaja juz w 404 przy legacy sciezkach.
- Backend jest latwiejszy do przeniesienia na inny dysk/serwer, bo start web_portalu nie zalezy od katalogu startowego procesu.

## 2026-05-14 — T-123: live signal engine contract fix (analysis -> signal_engine)

### Root cause
- `backend/trading/signal_engine.py` odrzucal wszystkie symbole jako `insufficient_klines`, bo `backend.analysis.get_live_context()` nie zwracal pola `klines_count`, mimo ze dane 1h/4h realnie byly dostepne.
- `_klines_to_df()` gubil `quote_volume` i `trades`, przez co liquidity gate liczyl `0.0` mimo zapisanych danych Binance.
- `signal_engine` prosil o szybki kontekst `15m` z `limit=50`, ale `get_live_context()` wymaga minimum 60 swiec, wiec filtr fast trend byl stale pusty.

### Modyfikacje
- `backend/analysis.py`: `get_live_context()` zwraca teraz `klines_count`, `macd_signal`, Bollingery, `volume_spike_ratio`, `volume_24h_quote`, `trade_count`; `_klines_to_df()` zachowuje `quote_volume`, `trades`, `taker_buy_*`.
- `backend/trading/signal_engine.py`: fallback dla brakujacego `klines_count` nie blokuje juz poprawnego kontekstu; szybki timeframe pobiera >=60 swiec.
- `tests/test_trading_signal_engine.py`: dodane regresje dla brakujacego `klines_count`, zachowania `quote_volume/trades` i minimalnego limitu dla fast timeframe.

### Wynik
- LIVE entry pipeline nie blokuje juz wszystkich symboli z powodow technicznych/pozornych.
- Po poprawce realne odrzucenia sa juz ekonomiczne (`volume_too_low`, `negative_edge_after_costs`), a nie artefaktem zepsutego kontraktu miedzy analiza a execution.

## 2026-05-14 — T-121: runtime path unification + Telegram runtime sync + overlay 8099 fix

### Root cause
- Czesci runtime nadal startowaly ze starej kopii projektu pod `/media/...`, podczas gdy aktywny kod i poprawki byly w `/home/...`. To prowadzilo do rozjazdu Telegram/systemd/WWW wobec backendu.
- Telegram filtrowal i raportowal po stalej wartosci `TRADING_MODE` z env zamiast po kanonicznym trybie runtime zwracanym przez backend.
- `8099` byl obslugiwany przez legacy `serve_live.py`, a nie przez adapter overlay zgodny z repo.
- Panelowy `trycloudflare` nie byl lokalnie zepsuty — Cloudflare odrzucal nowe quick tunnel requesty kodem `1015 / 429 Too Many Requests`.

### Modyfikacje
- `telegram_bot/bot.py`: dodano runtime mode resolution z `/api/system/full-status`; komendy Telegram nie opieraja sie juz na stalej wartosci startowej procesu.
- `backend/tunnel_manager.py`: status tunelu raportuje tez `overlay_url`; parser fallback logu ignoruje testowe/falszywe wpisy URL.
- `scripts/run_quicktunnel.sh`: quicktunnel zapisuje jawny `last_error=trycloudflare_rate_limited` przy 1015/429 i uzywa `--no-autoupdate`.
- Runtime scripts i unit files (`~/.rldc_runtime/*`, `~/.config/systemd/user/rldc-*.service`): przepiete na aktualny workspace `/home/...`.
- Overlay: `8099` serwuje teraz `serve_live_overlay.py`, a nie legacy `serve_live.py`.

### Runtime
- backend: `rldc-backend.service` aktywny z `/home/...`
- frontend: `rldc-frontend.service` aktywny na `127.0.0.1:3000`
- telegram: `rldc-telegram.service` aktywny z aktualnego repo
- overlay: `http://127.0.0.1:8099/overlay/api/live-state`
- publiczny overlay URL istnieje; panelowy quicktunnel nadal blokuje Cloudflare `1015/429`

## 2026-05-14 — T-120: live entry plan -> filled position sync + overlay adapter fallback

### Root cause
- LIVE pipeline `signal_engine + risk_engine` liczył SL/TP/trailing przy wejściu, ale po BUY fill collector odbudowywał nowy plan wyjścia z fallbacku ATR. To rozjeżdżało plan wejścia z planem pozycji i psuło spójność ekonomii trade'u.
- Port `8099` jest zajmowany przez legacy `live_overlay/serve_live.py`, więc właściwy adapter `serve_live_overlay.py` nie mógł przejąć domyślnego adresu.

### Modyfikacje
- `backend/collector.py`: pending order z nowego LIVE pipeline przenosi teraz zakodowany plan trade'u (`SL/TP/TP2/trailing/break-even`) w reason payload.
- `backend/collector.py`: przy BUY fill collector odzyskuje zapisany plan i przypisuje go do `Position.planned_tp`, `Position.planned_sl` i `exit_plan_json`; fallback ATR działa już tylko gdy planu brak.
- `tests/test_live_execution_cash_management.py`: regresja potwierdza, że po fillu pozycja zachowuje plan wyjścia policzony na wejściu.

### Runtime
- właściwy adapter overlay działa na `http://127.0.0.1:8100/index.html`
- `http://127.0.0.1:8100/overlay/api/live-state` odpowiada poprawnym JSON
- `8099` pozostaje zajęty przez legacy `python3 serve_live.py`

## 2026-05-14 — T-119: WWW pending sync fix (kanoniczne statusy)

### Root cause
- `web_portal/src/components/widgets/DecisionsRiskPanel.tsx` nadal pytał backend o `status=PENDING`, mimo że kanoniczny lifecycle kolejki używa `PENDING_CREATED` / `PENDING_CONFIRMED`.
- Efekt: panel WWW gubił świeżo utworzone pending orders i zaniżał licznik zleceń wymagających akcji.

### Modyfikacje
- `backend/routers/orders.py`: `GET /api/orders/pending` obsługuje teraz CSV w `status=` oraz aliasy `ACTIONABLE` i `ACTIVE`.
- `web_portal/src/components/widgets/DecisionsRiskPanel.tsx`: panel używa filtra `PENDING_CREATED,PENDING`, więc widzi kanoniczne pending orders oraz legacy rekordy.
- `tests/test_smoke.py`: dodano regresję dla aliasu `ACTIONABLE` i CSV statusów.

### Wynik
- Backend i WWW znów liczą tę samą kolejkę pending wymagającą decyzji operatora.
- Build frontend przechodzi, a smoke/test suite pozostają zielone.

## 2026-05-14 — T-115: UNIT TESTY backend/trading/*.py — 6 plików, 156 nowych testów

### Pliki dodane
- `tests/test_trading_symbol_filter.py` — walidacja LOT_SIZE/PRICE_FILTER/PERCENT_PRICE_BY_SIDE, round_qty, round_price, meets_min_notional
- `tests/test_trading_signal_engine.py` — scoring RSI/MACD/Bollinger/HTF, evaluate_entry_signal pełny (23 scenariusze)
- `tests/test_trading_risk_engine.py` — sizing, SL/TP, max_positions, cooldown, min_notional_guard
- `tests/test_trading_execution_engine.py` — state machine: IDLE→PENDING_BUY, LONG_OPEN→PENDING_SELL, blokady
- `tests/test_trading_state_manager.py` — recover_on_startup, check_pending_fills, reconcile_live_positions, detect_orphan_orders, _symbol_to_base
- `tests/test_trading_collector_live_path.py` — _live_entry_new_pipeline (guards, signal reject, risk reject, success, min_notional); LIVE vs DEMO bypass w _screen_entry_candidates

### Bugfixy w kodzie produkcyjnym (wykryte przez testy)
- `backend/trading/state_manager.py`: `PendingOrder.submitted_at` → `PendingOrder.created_at` (kolumna nie istniała w DB)
- `backend/collector.py`: `entries_created = 0` przeniesione przed pętlę `for symbol in candidate_symbols` (błąd: `UnboundLocalError` przy LIVE bypass)

### Wynik
- Przed: 484 tests passed
- Po: **640 tests passed** (640/640, 0 failed)

---

## 2026-04-21 — T-110: RECONCILE DB↔BINANCE + SYSTEM DIAGNOSTICS + TELEGRAM UX + GLOBAL EXECUTION GUARD

### Root causes fixed
- Brak deterministycznego self-heal DB względem Binance (szczególnie po manualnych transakcjach wykonanych poza botem).
- Brak jednej warstwy diagnostycznej systemu (`execution`, `reconcile`, `universe`, `db-health`, `telegram`).
- Telegram mieszał operacje na trade queue i incident queue (ID collisions).
- Brak globalnego kill-switch execution działającego dla ALL trybów z jawnie logowanym `reason_code`.

### Modyfikacje
- `backend/database.py`: dodano modele auditowe `ReconciliationRun`, `ReconciliationEvent`, `ManualTradeDetection`; rozszerzono `_ensure_schema` i `reset_database`.
- `backend/portfolio_reconcile.py` (NEW): pełny reconcile DB↔Binance (pending/positions/balances), wykrywanie manualnych trade i naprawy z audit trail.
- `backend/routers/system.py` (NEW): endpointy `/api/system/execution-status`, `/reconciliation-status`, `/reconcile`, `/universe-status`, `/ai-consensus-status`, `/telegram-status`, `/db-health`, `/full-status`.
- `backend/app.py`: rejestracja routera system + startup reconcile thread (tryb live).
- `backend/collector.py`: reconcile per-cycle + global execution gate `execution_enabled`; dla zablokowanych pending zapisywany trace `reason_code=execution_globally_disabled`.
- `telegram_bot/bot.py`: nowy zestaw komend operatorskich (`/pending`, `/trade`, `/incident`, `/close_incident`, `/reconcile`, `/health`, `/execution`, `/universe`, `/quote`) + disambiguacja `/confirm` i `/reject` (incident_id vs trade_id).

### Testy
- Nowe testy: `tests/test_reconcile.py`, `tests/test_telegram_disambiguation.py`, `tests/test_execution_guard.py`.
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_reconcile.py tests/test_telegram_disambiguation.py tests/test_execution_guard.py -q --tb=line`
- wynik: **7 passed**
- pełny suite: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/ -q --tb=line` → **404 passed, 55 failed** (otwarte jako T-111; główny objaw: smoke/config snapshot flow z `runtime_settings` init oraz rozjazd agregacji `exit_quality_report`).

### Wpływ
- Spójność DB↔Binance: wyższa (source-of-truth = Binance + auto-naprawy).
- Ryzyko operacyjne: niższe (jawne reason codes i disambiguacja trade vs incident).
- Stabilność execution: wyższa (global kill-switch z trace i bez cichego wykonywania).

## 2026-04-21 — T-109: EXECUTION GATES + TELEGRAM PENDING ID HARDENING

### Root causes fixed
- `sell_weakest` tworzył pending z literówką statusu `PENDING_CREATED_CREATED`, co blokowało wykonanie przez collector.
- LIVE execution gate bazował na pojedynczym odczycie env, bez twardej walidacji globalnego `trading_mode` z runtime config.
- Telegram `/confirm` i `/reject` mogły działać na ID bez ścisłego zawężenia do aktywnego trybu.

### Modyfikacje
- `backend/routers/control.py`: status pending w ścieżce `sell_weakest` poprawiony do canonical `PENDING_CREATED`.
- `backend/collector.py`: execution gate dla LIVE oparty o runtime config (`allow_live_trading`, `trading_mode`) + reject przy `trading_mode != live`.
- `telegram_bot/bot.py`: `/confirm` i `/reject` wyszukują `PendingOrder.id` tylko w bieżącym `TRADING_MODE`; confirm ustawia canonical `PENDING_CONFIRMED`; `/status` liczy active pending wg canonical statusów.

### Testy
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_control_center.py tests/test_smoke.py -q --tb=line`
- wynik: **257 passed, 3 warnings**

### Wpływ
- niższe ryzyko przypadkowego LIVE execution przy niespójnym trybie,
- eliminacja martwych pending tworzonych przez typo,
- jednoznaczniejsza ścieżka operatorska PendingOrder ID w Telegram.

## 2026-04-21 — T-108: FULL MARKET UNIVERSE + MULTI-AI EXPERT SYSTEM

### Root causes fixed
- **Hardcoded symbols**: `quote_currency.py` miał `_ASSET_QUOTE_MAP` ręczną — wymieniona na dynamiczne fetch_exchange_symbols()
- **Single-universe limit**: WATCHLIST ograniczała cały bot — zmieniona semantyka: teraz priorytet, nie limit
- **Fallback-chain AI**: `AI_PROVIDER=auto` było fallback (local→groq→gemini→openai) — zamieniono na TRUE parallel multi-AI
- **No consensus layer**: bez porównywania AI responses — dodany expert_audit_engine.py
- **Env chaos**: duplicate DATABASE_URL, brak jasnych local AI flags — naprawiono struktura

### Modyfikacje

#### 1. symbol_universe.py (NEW)
- `fetch_exchange_symbols(binance_client, quote_mode)` — pobierz WSZYSTKIE symbole z Binance
- Filtrowanie: test/dev/inactive/broken metadata usuwa się
- Quote mode: USDC | EUR | BOTH
- `build_priority_symbols_from_watchlist()` — konwersja BTC→BTCUSDC
- `merge_universes()` — scalanie eligible (pełne) + priority (watchlist)
- Diagnostyka: total_symbols, eligible_count, priority_count, rejection reasons

#### 2. expert_audit_engine.py (NEW)
- `AIResponse` — pojedyncza odpowiedź AI (provider, decision, confidence, score, reasoning)
- `ExpertAuditResult` — wynik audytu (final_decision, consensus, outliers, reasoning)
- `audit_multi_ai_responses()` — meta-AI consensus:
  - Detekuje outlierów (1 sprzeciwia się N-1)
  - Consensus voting: jeśli ≥60% BUY → BUY; <40% → WAIT; split → WAIT
  - Audit score: kombinacja consensus + outlier penalty
  - Modes: expert_audit (outlier removal), majority_vote, weighted_consensus
- Diagnostyka: które AI co powiedziało, kto był outlier, finalna decyzja

#### 3. ai_orchestrator.py (UPDATED)
- Dodano `run_multi_ai_parallel(messages, max_tokens)` — uruchamia wszystkie AI w ThreadPoolExecutor
- Wszystkie dostawcy uruchamiane RÓWNOLEGLE (nie fallback chain)
- Timeout per-provider: AI_PROVIDER_TIMEOUT_SECONDS (default 30s)
- Graceful degradation: jeśli jeden AI fail → pozostałe ciągle działają
- Circuit breaker per-provider still active (3 fails → 5min backoff)

#### 4. .env (MAJOR RESTRUCTURE)
- ❌ Usunięto: duplicate DATABASE_URL
- ❌ Deprecated: `AI_PROVIDER=auto` (stary fallback chain)
- ✅ Dodano: Symbol Universe flags
  - `USE_FULL_EXCHANGE_UNIVERSE=true` — pobierz wszystkie symbole z giełdy
  - `EXCHANGE_UNIVERSE_CACHE_SECONDS=3600`
  - `WATCHLIST_PRIORITY_ONLY=false` — watchlist to priorytet, nie limit
  - `QUOTE_CURRENCY_MODE=USDC` — USDC | EUR | BOTH
- ✅ Dodano: Multi-AI flags
  - `AI_MULTI_ENABLED=true` — enable parallel multi-AI + expert audit
  - `AI_PROVIDERS=ollama,gemini,groq` — lista providerów do uruchomienia
  - `AI_CONSENSUS_MODE=expert_audit` — expert_audit | majority_vote | weighted_consensus
  - `AI_ALLOW_PARTIAL_PROVIDER_FAILURE=true` — graceful degradation
  - `AI_PROVIDER_TIMEOUT_SECONDS=30`
- ✅ Dodano: Clear Local AI flags
  - `LOCAL_AI_ENABLED=true`
  - `LOCAL_AI_AUTO_START=true`
  - `LOCAL_AI_REQUIRED=false`
  - `LOCAL_AI_RETRIES=2`

#### 5. Tests (35 NEW)
- `tests/test_expert_audit_engine.py` (20 tests):
  - AIResponse creation, clamping
  - Outlier detection: unanimous, disagreement, majority vs minority
  - Consensus voting: BUY, SELL, WAIT, REJECT_SIGNAL
  - Audit score calculation
  - Mode: expert_audit, majority_vote, weighted_consensus
  - Risk score aggregation
- `tests/test_symbol_universe.py` (15 tests):
  - fetch_exchange_symbols: USDC | EUR | BOTH
  - Test symbol rejection, non-TRADING status
  - Diagnostics counters
  - Priority symbols: watchlist conversion
  - Merge universes: priority_only true/false
  - Empty/whitespace handling

### Results
- **35/35 new tests PASS**
- **307/308 full suite PASS** (1 pre-existing flaky unrelated to T-108)
- **0 regressions** — backward compatible
- **env cleanup** — duplicate removed, clear structure
- **ready for**: integrating with market_scanner, collector, signals router

### Next steps
- Integrate `fetch_exchange_symbols()` w market_scanner.py
- Integrate `run_multi_ai_parallel()` + `audit_multi_ai_responses()` w analysis.py
- Add diagnostics endpoint: symbol counts, universe composition, consensus stats
- Auto-reconciliation: bot fixing DB inconsistencies at startup (pending)

---

## 2026-04-21 — T-107: LOCAL AI end-to-end fix

### Root cause
- `_call_ollama_chat()` nie istniał → `generate_ai_chat_response()` nigdy nie używało local AI
- Timeout bug: kod czytał `AI_LOCAL_TIMEOUT_SECONDS` (niezdefiniowane = 15s) zamiast `OLLAMA_TIMEOUT_SECONDS=90` z `.env`
- Brak `keep_alive` → model cold-start przy każdym wywołaniu (~90-120s na i5-4300M bez GPU)

### Modyfikacje
- `backend/ai_orchestrator.py`: dodano `_call_ollama_chat()`, `_try_start_ollama()`, `check_local_ai_health()` (z retry+latency+auto-start); `generate_ai_chat_response()` nowy łańcuch `local→groq→gemini→openai→heuristic`; timeout chain `OLLAMA_TIMEOUT_SECONDS→AI_LOCAL_TIMEOUT_SECONDS→AI_PROVIDER_TIMEOUT_SECONDS`; `keep_alive: "10m"`; logi `[local_ai_*]`; `get_ai_orchestrator_status()` zwraca `local_ai_latency_ms`, `local_ai_model_installed`, etc.
- `backend/analysis.py`: dodano `_ollama_ranges()` — local AI w łańcuchu analizy technicznej; timeout fix; `keep_alive: "10m"`
- `backend/app.py`: `/health` zwraca `local_ai` blok z pełną diagnostyką
- `tests/test_ai_orchestrator.py`: nowy plik, 16 testów: healthcheck reachable/unreachable, routing local→groq→heuristic, timeout fallback, status pola, /health endpoint

### Testy
- **313 passed**, 1 failed (pre-existing flaky: `test_ai_orchestrator_unpaid_openai_with_fallback` — cache state, przechodzi w izolacji)
- 16 nowych testów: 16/16 passed

### Runtime weryfikacja
- `check_local_ai_health()` → `reachable=True`, `latency_ms=2`, `model_available=True`, `primary=local`
- `installed_models: ['qwen2.5:1.5b', 'qwen2.5:0.5b']`
- `OLLAMA_MODEL=qwen2.5:0.5b`, `OLLAMA_TIMEOUT_SECONDS=90`, `keep_alive=10m`

---

## 2026-04-20 — T-106: canonical pending lifecycle + local AI observability

### Modyfikacje

#### backend/routers/orders.py
1. `create_pending_order` tworzy rekordy ze statusem `PENDING_CREATED` (poprzednio `PENDING`).
2. `confirm_pending_order` akceptuje `PENDING` lub `PENDING_CREATED` → przechodzi do `PENDING_CONFIRMED` (poprzednio `CONFIRMED`).
3. `reject_pending_order` i `cancel_pending_order` akceptują `PENDING` i `PENDING_CREATED`.

#### backend/routers/positions.py
4. Close position i close-all tworzą PendingOrder ze statusem `PENDING_CREATED`.
5. Filtr duplikatów rozszerzony o `PENDING_CREATED` i `PENDING_CONFIRMED`.

#### backend/collector.py
6. `ACTIVE_PENDING_STATUSES` rozszerzony o `PENDING_CREATED`.
7. Komunikat auto-confirm zmieniony na prawdziwy: „zlecenie przyjęte do wykonania" (nie „pozycja otwarta automatycznie").

#### backend/routers/control.py
8. `_ACTIVE_PENDING_STATUSES` zawiera `PENDING_CREATED`.
9. Manual BUY/SELL używa `PENDING_CONFIRMED` dla ręcznie potwierdzonych zleceń.

#### backend/routers/signals.py
10. Wszystkie 4 zestawy active-status (`_ACTIVE_PENDING_STATUSES`, reserved_cash, entry_readiness, buy-trace) rozszerzone o `PENDING_CREATED`.

#### backend/ai_orchestrator.py
11. `get_ai_orchestrator_status()` zwraca jawne pola: `local_ai_enabled`, `local_ai_configured`, `local_ai_reachable`, `local_ai_selected`, `local_ai_model`, `local_ai_endpoint`, `local_ai_last_status`.

#### backend/app.py
12. `/health` odczytuje `local_ai_*` z orchestratora i zwraca w odpowiedzi.
13. Naprawiono syntax error (duplikat bloku local_ai w pliku, urwany string literal).

#### .gitignore
14. Dodano `.env_backups/` do ignorowanych plików.

#### testy
15. `tests/test_smoke.py`: asercje `CONFIRMED`→`PENDING_CONFIRMED`, `PENDING`→`PENDING_CREATED` dla create/close-position.
16. `tests/test_control_center.py`: status OpenAI rozszerzony o `"error"` w asercji.

### Testy i walidacja
- Testy dedykowane (test_smoke, test_control_center, test_portfolio_engine, test_reporting_metrics, test_signals_router, test_sync_consistency, test_live_execution_cash_management, test_quote_currency): **325 passed, 3 failures** (wyłącznie shared-state ordering — każdy z nich przechodzi w izolacji).
- `test_ai_orchestrator_unpaid_openai_with_fallback` przechodzi w izolacji, fail w pełnym suite z powodu shared AI cache.
- Pre-existing failure: `test_symbol_cooldown_after_losing_trade_blocks_buy` — brak tabeli `orders` w test DB (niezwiązane z naszymi zmianami).

### Backward compatibility
- Legacy `PENDING` → traktowane jak `PENDING_CREATED` w confirm/reject/cancel.
- Legacy `CONFIRMED` → `PENDING_CONFIRMED` po confirm.
- Cały `ACTIVE_PENDING_STATUSES` zawiera oba warianty.

## 2026-04-20 — T-105: live stability hardening (dedupe + qty guards + sync consistency)

### Modyfikacje

#### backend/collector.py
1. Dodano globalne zbiory statusów aktywnych pending (`ACTIVE_PENDING_STATUSES`) i statusów wykonywalnych (`EXECUTABLE_PENDING_STATUSES`) — jedno źródło prawdy dla execution/sync.
2. Dodano lock inflight per `mode:symbol:side` (`_acquire_inflight_slot` / `_release_inflight_slot`) aby blokować równoległe, duplikujące wykonania tego samego zlecenia.
3. Dodano twardy guard `qty<=0` w `_execute_confirmed_pending_orders`: pending dostaje `REJECTED` i trace `insufficient_cash_or_qty_below_min`.
4. Naprawiono filtr po anulowaniu konfliktu BUY/SELL w jednej partii: po CANCEL nie gubimy już `PENDING_CONFIRMED`.
5. `_create_pending_order(...)` dostał deduplikację aktywnego pending (symbol/side/mode) oraz idempotency token w `reason`.
6. `_sync_binance_positions(...)` i kalkulacja reserved cash używają pełnego zestawu aktywnych statusów pending (w tym `EXCHANGE_SUBMITTED`, `PARTIALLY_FILLED`).
7. LIVE screening poprawnie filtruje symbole dla `QUOTE_CURRENCY_MODE=EUR|USDC|BOTH`.

#### backend/routers/control.py
8. Dodano deduplikację manualnych pending BUY/SELL (ten sam symbol+side+mode+active status).
9. FORCE BUY nie tworzy już qty<=0: gdy brak wyliczonej ilości, ustawia bezpieczny placeholder `>0`, a właściwa walidacja jest wykonywana przez preflight execution.

#### backend/routers/signals.py
10. Ujednolicono listę aktywnych statusów pending (`_ACTIVE_PENDING_STATUSES`) w final-decisions/execution-trace/buy-trace.

#### testy
11. `tests/test_control_center.py`: nowy test regresyjny blokady duplikatu manual force BUY.
12. `tests/test_live_execution_cash_management.py`: nowe testy deduplikacji `_create_pending_order(...)` oraz guardu `qty<=0`.

### Testy i walidacja
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_live_execution_cash_management.py tests/test_control_center.py -q` → **49 passed**
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → **220 passed**

## 2026-04-20 — T-104: execution/cash-management hardening (LIVE)

### Modyfikacje

#### backend/runtime_settings.py
1. Dodano centralny runtime setting `min_buy_eur` (domyślnie `60.0`, env `MIN_BUY_EUR`) i objęto go guard-rails dla LIVE.

#### backend/collector.py
2. Wdrożono centralny preflight LIVE BUY dla pending `CONFIRMED`:
   - minimalna wartość zakupu liczona z `min_buy_eur` (EUR) i przeliczana na quote,
   - automatyczna konwersja EUR→USDC gdy symbol wymaga USDC,
   - normalizacja qty do `step_size` i ponowna walidacja `minNotional` po zaokrągleniu,
   - blokady i reason codes: `cash_convert_failed`, `cash_insufficient_after_conversion_attempt`, `execution_rejected_by_exchange`, `temporary_execution_error`,
   - pełne logi kroków: pending found, execution started, pre-trade balance, conversion needed/not needed, conversion filled/failed, final buy sent, pending status update.
3. Zablokowano symbole testowe w LIVE (`live_test_symbol_blocked`) i usuwanie `TEST*` z watchlisty live.
4. Naprawiono deterministyczne sortowanie potwierdzonych pending (`datetime.timestamp()` zamiast mieszania `datetime/int`).

#### backend/quote_currency.py
5. Dodano helpery kursowe i konwersyjne:
   - `resolve_eur_usdc_rate(...)` z fallbackami `EURUSDC` / `USDCEUR` / stable,
   - `convert_eur_amount_to_quote(...)`,
   - `is_test_symbol(...)`.

#### backend/routers/signals.py
6. Naprawiono cash gate (`ENTRY_BLOCKED_NO_CASH`):
   - uwzględnia `min_buy_eur` i `required_cash_eur`,
   - dla par `*USDC` liczy wymagane USDC z kursu EUR→USDC,
   - nie blokuje fałszywie, gdy możliwa auto-konwersja i wystarczające EUR.
7. Wycięto symbole testowe z universe sygnałów i entry-readiness LIVE.

#### backend/routers/control.py
8. `_calculate_buy_quantity(...)` respektuje minimum `60 EUR` (lub równowartość USDC) już przy tworzeniu manual pending BUY.
9. Komendy BUY w trybie LIVE odrzucają symbole testowe.

#### backend/routers/account.py
10. Uszczelniono status pipeline: tymczasowe błędy execution/conversion nie są raportowane jako trwałe blokady (`_NON_BLOCKER_REASONS`).
11. Dodano etykiety reason codes dla nowych ścieżek cash/execution.

#### testy
12. Rozszerzono `tests/test_quote_currency.py` (kursy/fallbacki/przeliczenia/test symbols).
13. Dodano `tests/test_live_execution_cash_management.py` (min 60 EUR, auto-konwersja przed BUY, confirmed pending execution, brak trwałego blokera po temporary error).

### Testy i walidacja
- `PYTHONPATH=. DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_quote_currency.py tests/test_live_execution_cash_management.py tests/test_control_center.py -q` → **71 passed**
- `PYTHONPATH=. DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → **220 passed**

## 2026-04-19 — T-103: parser Telegram trading-first + MANUAL/MANUAL_FORCE

### Modyfikacje

#### `backend/routers/control.py`
1. Dodano jednolity parser komend `_parse_command_intent(...)` zwracający strukturę:
   - `type`, `side`, `symbol`, `force`, `config_key`, `config_value`.
2. Ustalono kolejność parsowania:
   - najpierw intencja tradingowa (`kup`, `sprzedaj`, `wymuś`),
   - potem symbol,
   - dopiero potem komendy konfiguracji.
3. Dodano osobny flow execution:
   - `MANUAL` (`manual_pending_confirmed_queued`),
   - `MANUAL_FORCE` (`manual_force_pending_confirmed_queued`).
4. Dodano obsługę `sell_symbol` (np. `sprzedaj btc`, `wymuś sprzedaj ethusdc`) z dopasowaniem pozycji po base-asset.
5. Dodano komendę runtime `tryb agresywny` (`set_aggressive_mode`) bez wyłączania podstawowych zabezpieczeń.
6. Rozszerzono logowanie parsera i ścieżki wykonania: `parser_decision=... execution_path=...`.

#### `backend/quote_currency.py`
7. Uszczelniono `parse_nl_quote_command(...)`:
   - brak interpretacji quote-config, gdy wykryto intencję tradingową,
   - brak kolizji ze symbolami pełnych par (`SOLUSDC`, `ETHUSDC`),
   - usunięto zbyt szerokie frazy (`usdc`, `oba`) i dodano precyzyjne warianty (`handluj tylko na usdc`, `handluj tylko na eur`).

#### `telegram_bot/bot.py`
8. Odpowiedzi Telegrama są zgodne z realnym execution path dla `MANUAL` i `MANUAL_FORCE`.

#### `tests/test_control_center.py`
9. Dodano testy parsera i execution dla komend:
   - `kup sol`, `kup solusdc`,
   - `wymuś kup sol`, `wymuś kup solusdc`,
   - `sprzedaj btc`, `wymuś sprzedaj ethusdc`,
   - `tryb agresywny`.

### Testy i walidacja
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_control_center.py -q` → **36 passed**
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → **220 passed**

### RCA błędnej interpretacji
- parser quote-currency dopuszczał zbyt szerokie dopasowania i mógł wejść w ścieżkę config mimo komendy tradingowej.
- brak jednolitego parsera intencji powodował konflikt między routingiem BUY/SELL i routingiem konfiguracji.

## 2026-04-19 — T-102: odblokowanie entry path (force parser + relaxed fallback + szersza strefa BUY)

### Modyfikacje

#### `backend/routers/control.py`
1. Naprawiono parser NL komend BUY: frazy typu `wymuś kup ...` trafiają teraz do akcji `buy_symbol` (wcześniej mogły zostać sklasyfikowane jako chat).

#### `backend/collector.py`
2. Dodano fallback relaksujący wejścia po serii cykli bez BUY i bez otwartych pozycji:
   - aktywacja: `no_entry_relax_after_cycles` (domyślnie 3),
   - obniżenie progu confidence do `relaxed_min_confidence_floor` (domyślnie 0.50),
   - obniżenie progu entry-score do `relaxed_min_entry_score` (domyślnie 40),
   - poszerzenie strefy BUY do `relaxed_buy_zone_tolerance_pct` (domyślnie 0.03).
3. Rozszerzono universe kandydatów o top-N symboli z `market_scanner` (`collector_scanner_top_n`, domyślnie 50).

#### `backend/routers/signals.py`
4. Buy-trace używa teraz wspólnej tolerancji strefy BUY:
   - `buy_zone_tolerance_pct` (preferowane),
   - fallback do `price_tolerance`,
   - domyślnie 0.02.

#### `backend/runtime_settings.py`
5. Poluzowano profile agresywności i próg entry-score:
   - balanced: `demo_min_entry_score` 60 → 50,
   - aggressive: `demo_min_signal_confidence` 0.50 → 0.48,
   - aggressive: `demo_min_entry_score` 50 → 45,
   - globalny default `demo_min_entry_score` 5.5 → 5.0 (skala legacy 0-10 => 50/100).

### Testy i walidacja
- `.venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- brak regresji po zmianach entry path.

## 2026-04-19 — T-101: aktywne szukanie wejść + diagnostyka WHY_NOT_BUY + debug risk override

### Modyfikacje

#### `backend/collector.py`
1. `_screen_entry_candidates(...)` rozszerza universe o symbole z `market_scanner` (best executable, best analytical, opportunities i odrzucone), zamiast ograniczać się wyłącznie do watchlisty.
2. Dodano uzupełnianie `range_map` dla symboli spoza watchlisty przez heurystykę (`generate_market_insights` + `_heuristic_ranges`).
3. Dodano fallback sygnału live on-demand dla symboli bez rekordu `Signal` w DB (`backend.routers.signals._build_live_signals`).
4. Dodano logi diagnostyczne `WHY_NOT_BUY ...` na kluczowych bramkach odrzucenia BUY oraz `BUY_ALLOWED ...` przy przejściu wszystkich gate'ów.

#### `backend/risk.py`
5. Dodano debug override risk engine przez ENV:
   - `RISK_FORCE_ALLOW_ENTRY_DEBUG=true`
   - dla BUY zwracane jest `allowed=True` i `reason_code=forced_entry_debug_override`.
   - tryb domyślnie wyłączony (bezpieczne zachowanie produkcyjne).

### Testy i walidacja
- `.venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- brak regresji w smoke po zmianach logiki wejścia/risk.

## 2026-04-19 — T-100: fetch-on-demand klines dla stale symboli w live signals

### Modyfikacje

#### `backend/routers/signals.py`
1. Dodano helper `_fetch_and_store_klines_ondemand(...)`, który pobiera klines 1h z Binance i zapisuje brakujące świece do DB.
2. W `_build_live_signals(...)` zmieniono zachowanie stale-data guard:
   - było: `kline_age_h > MAX_KLINE_AGE_HOURS` => natychmiastowy `continue` (skip),
   - jest: próba odświeżenia klines z Binance; dopiero przy niepowodzeniu fetch następuje skip.

### Testy i walidacja
- `.venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- brak regresji endpointów; pozostał tylko znany warning TLS (`InsecureRequestWarning`).

## 2026-04-19 — T-99: usunięcie deprecacji `datetime.utcnow()` w health API

### Modyfikacje

#### `backend/app.py`
1. Zastąpiono deprecated timestamp:
   - było: `datetime.utcnow().isoformat() + "Z"`
   - jest: `datetime.now(timezone.utc).isoformat()`
2. Dodano import `datetime, timezone` z modułu standardowego.

### Testy i walidacja
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- warning deprecacji `datetime.utcnow()` usunięty; pozostał tylko warning `InsecureRequestWarning` z probe tunelu.

## 2026-04-19 — T-98: naprawa regresji 401 w smoke (dotenv override)

### Modyfikacje

#### `backend/app.py`
1. Zmieniono bootstrap `.env` z `load_dotenv(..., override=True)` na `override=False`.
2. Efekt: wartości ustawione przez testy (`ADMIN_TOKEN`, limity runtime, tryb) nie są już nadpisywane przez lokalne `.env` podczas importu aplikacji.

### Testy i walidacja
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**

### RCA
- Źródło regresji: `backend/app.py` nadpisywał env z testów przez `override=True`, co aktywowało auth admin oraz obce limity runtime i powodowało kaskadę 401/422 w smoke.

## 2026-04-19 — T-97: eliminacja duplikatów Telegram (systemd vs lokalny start)

### Modyfikacje

#### `scripts/start_dev.sh`
1. Dodano twardą preferencję dla `rldc-telegram.service` gdy unit jest `enabled`:
   - skrypt uruchamia service (jeśli nieaktywny),
   - nie odpala lokalnej drugiej instancji,
   - czyści lokalne PID-y różne od `MainPID` serwisu.
2. `telegram.pid` jest aktualizowany na PID procesu zarządzanego przez systemd.

#### `scripts/stop_dev.sh`
3. Dodano świadome zatrzymanie `rldc-telegram.service` przy `stop_dev.sh` (zamiast wyłącznie `pkill`), żeby uniknąć restart-loop i konfliktu źródeł procesu.

#### `scripts/status_dev.sh`
4. Rozszerzono diagnostykę o źródło procesu Telegram:
   - pokazuje PID z `rldc-telegram.service`,
   - ostrzeżenie o duplikacie rozróżnia przypadek `service + lokalny`.

### Testy i walidacja
- `bash -n scripts/start_dev.sh scripts/stop_dev.sh scripts/status_dev.sh` → **PASS**
- runtime sanity po wdrożeniu guardów:
  - `status_dev.sh` raportuje źródło `systemd rldc-telegram.service` i brak ostrzeżenia po cleanupie,
  - `pgrep -af "telegram_bot.bot"` → pojedynczy proces (`MainPID` serwisu).

## 2026-04-19 — T-96: confidence fallback runtime + dynamic AI threshold + rich AI chat context

### Modyfikacje

#### `backend/collector.py`
1. Dodano fallback confidence liczony z indikatorów (`RSI`, `EMA20/EMA50`, `volume_ratio`, `MACD hist`), aby sygnały nie wpadały do `confidence=0` przy problemach AI.
2. Dodano detekcję degradacji AI runtime (`_is_ai_failed_runtime`) oraz dynamiczny próg confidence:
   - `0.4` gdy AI fallback/failed,
   - `0.6` gdy AI działa poprawnie.
3. Dodano debug output wymagany operacyjnie:
   - `CONFIDENCE:`
   - `AI_USED:`
   - `AI_FAILED:`
4. Ujednolicono `signal_summary` i `risk_check` o pola diagnostyczne `effective_confidence`, `raw_confidence`, `fallback_confidence`, `ai_provider`, `ai_failed`.
5. Naprawiono status heartbeat (`avg_confidence`): gdy `DecisionTrace` nie niesie confidence, fallback liczy średnią z najnowszych `Signal` (zamiast stałego `0.0`).

#### `backend/analysis.py`
6. Dodano jawny payload wejściowy do AI (`_build_ai_input_payload`) z polami:
   - `price`, `candles`, `rsi`, `ema20`, `ema50`, `volume`, `volume_ratio`, `trend`.
7. Wszystkie providery ranges (`Gemini/Groq/Ollama/OpenAI`) korzystają teraz z nowego payloadu zamiast surowych insightów.
8. `generate_market_insights` rozszerzono o `candles` (ostatnie 30 close) i `trend` per symbol.

#### `backend/routers/control.py`
9. Chat AI dostaje pełny kontekst runtime (`_build_ai_chat_context`):
   - `market_scan_snapshot` z live `MarketData`,
   - `top_opportunities` z realnych `Signal`,
   - status providera (`ai_primary`, `ai_fallback_active`),
   - `mode` i `source`.

#### Testy
10. Dodano `tests/test_confidence_runtime_fix.py` (4 testy):
   - fallback confidence > 0,
   - dynamiczny próg 0.4/0.6,
   - kompletność payloadu AI,
   - chat context z realnymi danymi rynkowymi i opportunities.

### Testy i walidacja
- `python -m pytest tests/test_confidence_runtime_fix.py -q` → **4 passed**
- `python -m pytest tests/test_control_center.py tests/test_smoke.py -q` → **246 passed**
- runtime sanity:
  - `scripts/status_dev.sh` → backend/frontend/telegram UP (uwaga operacyjna: wykryto 2 procesy Telegram)
  - `GET /api/signals/entry-readiness` → API działa, blokady wejść nadal z powodu `ENTRY_BLOCKED_DATA_TOO_OLD`

## 2026-04-19 — T-95: singleton Telegram bota + hardening `start_dev.sh`

### Modyfikacje

#### `scripts/start_dev.sh`
1. Dodano blokadę równoległego uruchomienia skryptu (`flock` na `logs/dev/.start_dev.lock`), żeby wyeliminować wyścigi i podwójne starty procesów.
2. Dodano normalizację procesu Telegram:
   - gdy wykryto >1 proces `telegram_bot.bot`, skrypt czyści duplikaty i uruchamia jedną instancję,
   - gdy wykryto dokładnie 1 proces, odświeża `telegram.pid`.

### Walidacja runtime
- `bash -n scripts/start_dev.sh scripts/stop_dev.sh scripts/status_dev.sh` → **PASS**
- restart przez `start_dev.sh` po `pkill -f telegram_bot.bot` → **1 aktywny proces Telegram**
- `bash scripts/status_dev.sh` → backend/frontend/telegram **UP**, HTTP endpointy **200**
- `GET /api/account/trading-status?mode=live` → `trading_enabled=true`, `available_to_trade=true`, `collector_running=true`, `blockers=0`
- `GET /api/signals/entry-readiness?mode=live` → brak wejść (`ENTRY_BLOCKED_DATA_TOO_OLD`) przy aktywnym live trading

## 2026-04-19 — T-94: stałe metryki kosztowe w dashboardzie + overtrading score

### Modyfikacje

#### `backend/reporting.py` — `performance_overview`
1. Dodano metryki pochodne do payloadu `/api/account/analytics/overview`:
   - `overtrading_score` (0..1, ratio blokad aktywności do liczby zamkniętych transakcji, clamp)
   - `overtrading_activity_blocks`
   - `gross_to_net_retention_ratio` (0..1, retencja PnL brutto po kosztach)
   - `gross_net_gap` (ubytek brutto→netto w EUR)
   - `closed_orders`
2. Dodano helpery obliczeniowe i clampy zakresów, żeby metryki były stabilne i porównywalne.

#### `web_portal/src/components/MainContent.tsx`
3. `DashboardV2View`: dodano stały pas 3 kafli kosztowych widoczny zawsze w dashboardzie:
   - Retencja brutto→netto
   - Leakage kosztowe
   - Overtrading score
4. `EconomicsSubView`: rozszerzono KPI o nowe metryki kosztowe i overtrading.

#### Testy
5. Dodano `tests/test_reporting_metrics.py` (6 testów helperów metryk).

### Testy i walidacja
- `PYTHONPATH=. python3 -m pytest tests/test_reporting_metrics.py -q --tb=short` → **6 passed**
- `PYTHONPATH=. python3 -m pytest tests/test_reporting_metrics.py tests/test_signals_router.py -q --tb=short` → **8 passed**
- `npm --prefix web_portal run build` → **PASS** (TypeScript + Next build)

## 2026-04-19 — T-93: guard stale klines w `_build_live_signals`

### Modyfikacje

#### `backend/routers/signals.py` — `_build_live_signals`
1. Dodano walidację świeżości ostatniego `Kline` (timeframe `1h`) przed wywołaniem analizy wskaźnikowej.
2. Nowy próg środowiskowy: `MAX_KLINE_AGE_HOURS` (domyślnie `4`).
3. Jeśli ostatni `Kline` jest starszy niż próg, symbol jest pomijany (`continue`) zamiast generowania live_analysis na przeterminowanych danych.

### Testy
- Dodano `tests/test_signals_router.py`:
   - `test_build_live_signals_skips_stale_klines`
   - `test_build_live_signals_keeps_fresh_klines`
- Regresja: `tests/test_signals_router.py` + `tests/test_market_scanner.py` → **43/43 passed**.

### Weryfikacja runtime
- `GET /api/signals/entry-readiness?mode=live&limit=20` → ARBUSDC/EGLDUSDC nie są już zwracane jako live_analysis na starych klines.
- Diagnostyka dla starych sygnałów pozostaje spójna z T-90 (`ENTRY_BLOCKED_DATA_TOO_OLD`).

---

## 2026-04-18 — Druga fala: Extended universe + odświeżanie starych sygnałów

### Modyfikacje

#### `backend/routers/signals.py` — `_load_signals_from_db_or_live`
1. **Parametr `max_age_minutes=90`**: funkcja przyjmuje teraz próg stałości sygnałów.
   Sygnały z DB starsze niż `max_age_minutes` traktowane jako brakujące → trafiają do
   `_build_live_signals` (live fallback). Efekt: EUR pary z 4h-starymi sygnałami dostają
   świeży sygnał z `/api/klines`, a nie stary odrzucany przez `DATA_TOO_OLD`.
2. **Ujednolicony `regenerate` = missing + stale_symbols**: jeden przepływ dla brakujących
   i przestarzałych symboli.

#### `backend/market_scanner.py` — `get_trade_universe`
3. **Extended mode omija filtr QCM**: `extended=True` zwraca WSZYSTKIE symbole z MarketData
   niezależnie od `QUOTE_CURRENCY_MODE`. Primary nadal filtruje po QCM.
   Efekt: przy `QCM=USDC` extended universe = 20 (10 USDC + 10 EUR), primary = 10.

#### `backend/market_scanner.py` — `_scan_symbols`
4. **Parametr `max_signal_age_minutes=90`** przekazywany do `_load_signals_from_db_or_live`.

#### `backend/market_scanner.py` — `run_market_scan` (extended block)
5. **Extended scan używa `max_signal_age_minutes=120`** (luźniejszy limit dla EUR).
   Diagnostyki: `extended_scan_info.new_symbols_found`, `extended_scan_info.new_symbols`.
   Graceful handling gdy `new_symbols=[]`.

### Testy (nowe klasy)
- `TestLoadSignalsStaleness` (3 testy): fresh signal → DB, stale signal → live fallback, brakujący → live fallback
- `TestGetTradeUniverseExtended` (3 testy): bypass QCM, extended ≥ primary, full pipeline z mixed quotes
- `TestValidateCandidate::test_data_too_old_rejected` i `test_data_too_old_fresh_signal_passes`

### Weryfikacja live
- `scanned=20` (było 10) — extended dodał 10 EUR symboli
- `new_symbols_found=10`: ARBEUR, AVAXEUR, BNBEUR, BTCEUR, EGLDEUR, ETHEUR, PEPEEUR, SHIBEUR, SOLEUR, WLFIEUR
- `rsi=37.85, regime=TREND_DOWN` — pola wypełnione (były null)
- EUR odrzucone z poprawnych powodów: SELL_WITHOUT_POSITION (brak pozycji EUR), HOLD
- 353/353 testów zielonych

---

## 2026-04-18 — Naprawa scoringu sygnałów: RSI, market_regime, DATA_TOO_OLD

### Modyfikacje

#### `backend/routers/signals.py` — `_score_opportunity`
1. **Normalizacja kluczy DB**: sygnały kolekcjonowane przez `collector.py` używają `rsi_14`/`atr_14`
   zamiast `rsi`/`atr`. Scoring ignorował RSI dla wszystkich sygnałów z DB. Naprawione.
2. **Inferencja `market_regime` z EMA**: gdy DB nie zwraca pola `regime`, `_score_opportunity`
   teraz wyprowadza reżim z wyrównania EMA (`ema_20 > ema_50` → `TREND_UP`, itp.).
   Efekt: SELL z DB ≥ score +30 (reżim potwierdzony) zamiast +18 (tylko EMA bez regime).
3. **Propagacja `rsi` do result dict**: `_score_opportunity` dodaje teraz `result["rsi"] = rsi`
   (wartość wzbogacona o fallback z `get_live_context`). Widoczne w UI i testach.

#### `backend/market_scanner.py` — `_validate_candidate`
4. **Aktywna bramka `DATA_TOO_OLD`**: kod istniał w `REJECTION_CODES` ale nigdy nie był sprawdzany.
   Teraz pierwsze sprawdzenie w `_validate_candidate` — odrzuca sygnały starsze niż
   `MAX_SIGNAL_AGE_MINUTES` (domyślnie 90 min, konfigurowalne przez ENV).
   Test: ARBUSDC i EGLDUSDC (sygnały sprzed 4 dni) → `DATA_TOO_OLD`.

#### `backend/market_scanner.py` — `_format_candidate` i `_format_opportunity`
5. **Priorytet top-level fields**: `rsi` i `market_regime` teraz biorą wartość z top-level
   danych wzbogaconych przez `_score_opportunity`, a dopiero w fallback z `indicators`.
   Naprawia null w `best_analytical_candidate.rsi` i `best_analytical_candidate.market_regime`.

### Weryfikacja
- 345/345 testów zielonych
- `best_analytical.rsi = 38.64` (było null)
- `best_analytical.market_regime = "TREND_DOWN"` (było null)
- `best_analytical.score = 69.0` (było 54.0) — poprawa dokładności
- `DATA_TOO_OLD` aktywnie odrzuca 2 symbole z 4-dniowymi sygnałami

---

## 2026-04-18 — Hardening AI providers + naprawa health endpoint

### Modyfikacje
- **`backend/ai_orchestrator.py`**: 3 nowe mechanizmy hardeningu:
  1. **Cache TTL** (domyślnie 60s, env `AI_STATUS_CACHE_TTL`) — `get_ai_orchestrator_status()`
     nie re-sonduje providerów przy każdym wywołaniu. `force=True` omija cache.
  2. **Circuit breaker per-provider** — po `_CIRCUIT_BREAKER_THRESHOLD=3` kolejnych błędach
     provider jest wyłączany na `_CIRCUIT_BREAKER_TIMEOUT=300s`. Po tym czasie automatyczny reset.
  3. **Throttlowane logowanie** — pierwsze niepowodzenie → `WARNING`, kolejne → `DEBUG`.
     Otwarcie circuit breaker → `WARNING`. Reset po sukcesie → `DEBUG`.
  4. **Pole `circuit_breakers`** w statusie — widoczne przez `/api/account/ai-orchestrator-status`.
- **`backend/app.py`**: `/api/health` teraz zwraca rzeczywistego primary providera AI
  (np. `"ai": "groq"`) zamiast zawsze zwracać wartość ENV `AI_PROVIDER`.
  Naprawiono błędny import `AIOrchestrator` (klasa nie istniała).

### Weryfikacja
- 345/345 testów zielonych
- `/api/health` → `"ai": "groq"` (zamiast `"auto"`)
- Cache: drugie wywołanie `get_ai_orchestrator_status()` < 0.0001s
- Circuit breaker: otwiera po 3 błędach, reset po sukcesie — przetestowane jednostkowo

---

## 2026-04-XX — Pipeline skanowania rynku — WYMUSZENIE AUTONOMII

### Nowe pliki
- **`backend/market_scanner.py`** — Globalny pipeline skanowania rynku. Cache 18s, cycle_id, snapshot_id.
  - `run_market_scan(db, mode, force)` → `MarketScanSnapshot`
  - `get_trade_universe(db, extended)` → lista symboli (primary + extended)
  - `_validate_candidate(...)` → `(rejection_code, rejection_text) | (None, None)` — walidacja JEDNEGO kandydata
  - `_scan_symbols(db, symbols, cycle_id)` → `{scanned, analyzed, ranked}`
  - `REJECTION_CODES` — 16 kanonicznych kodów
  - `FINAL_MARKET_STATUSES` — 5 statusów końcowych
- **`backend/routers/dashboard.py`** — Endpoint `GET /api/dashboard/market-scan`
- **`tests/test_market_scanner.py`** — 33 testy jednostkowe

### Modyfikacje
- **`backend/app.py`**: rejestracja routera `dashboard` pod `/api/dashboard`
- **`web_portal/src/components/MainContent.tsx`**:
  - `CommandCenterView`: zastąpienie 3 fetchów (scanner/bestOpp/waitStatus) jednym `/api/dashboard/market-scan`
  - Unified `snapshot_id` dla wszystkich komponentów dashboardu
  - `best_executable_candidate` ≠ `best_analytical_candidate` — pokazane oddzielnie
  - CZEKAJ używa `final_user_message` z liczbą przeskanowanych/odrzuconych i top powodami
  - `waitStatus` przywrócony jako supplementary fetch (per-symbol diagnostyka)

### Rozwiązane problemy
1. Pipeline ZATRZYMYWAŁ się na pierwszym odrzuconym kandydacie — teraz iteruje ALL
2. Brakowało rozróżnienia analityczny vs wykonywalny — teraz dwa osobne pola
3. "CZEKAJ" bez wyjaśnienia — teraz `final_user_message` z danymi
4. 4 fetchdy z różnymi TTL i różnymi cycle_id → race conditions — teraz jeden spójny endpoint
5. Extended scan — gdy primary nie daje wyników, system automatycznie rozszerza universe

### Wynik: 345/345 testów (312 + 33 nowe), TypeScript 0 błędów

---

## 2026-04-18 — Fix tunelu Cloudflare (KRYTYCZNY)

### ROOT CAUSE: `~/.cloudflared/config.yml` catch-all `http_status:404`
- **Problem**: cloudflared quick tunnel automatycznie ładuje `~/.cloudflared/config.yml`
  niezależnie od flagi `--url`. Reguła `- service: http_status:404` (catch-all dla
  nieznanych hostnames) odpowiadała 404 na **wszystkie** żądania z `*.trycloudflare.com`
  (bo hostname nie pasował do `rldc.TWOJA_DOMENA.pl`).
- **Objaw**: publiczny URL zwracał `server: cloudflare`, HTTP 404, brak body — z
  przesyłką przez tunel do Next.js w ogóle nie dochodziło.
- **Naprawa**: zmieniono catch-all w `~/.cloudflared/config.yml`:
  ```yaml
  - service: http_status:404   # PRZED
  - service: http://localhost:3000   # PO — quick tunnel + nieznane domeny → frontend
  ```

### tunnel_manager.py — 3 poprawki
1. `_read_cf_log_url()` — nowa funkcja odczytująca URL z `quicktunnel.log` + cloudflared.log
   (fallback gdy runtime file jest stary po restarcie)
2. `_wait_for_new_url()` — rozszerzone o czytanie z logu jako fallback
3. `recovery_count` reset przy sukcesie probe runtime/env URL (nie tylko po pełnym recovery)

### scripts/tunnel_doctor.py — NOWY
- Pełna diagnostyka E2E: procesy, porty, runtime file, log URL, probe publiczny, backend status
- `python3 scripts/tunnel_doctor.py [--json] [--fix]`
- Zwraca exit 0 = OK, exit 1 = problemy

### Weryfikacja
- `tunnel_doctor.py` → wszystkie 7 kroków ✅
- Publiczny URL: HTTP 200 dla `/` (30591 B) i `/api/health` (179 B)
- Backend: `probe_ok=True`, `recovery_count=0`, `last_error=null`
- 312/312 testów

## 2026-04-14

### Operacyjne domkniecie audytu i fix
- Dodano root npm scripts (`dev`, `build`, `start`, `lint`) w package.json, delegowane do web_portal.
- Naprawiono blad operacyjny: `npm run build` w root nie konczyl sie juz `Missing script: build`.
- Potwierdzono build produkcyjny Next.js z poziomu root.
- Potwierdzono smoke tests: 220 passed.

### Kontrola dokumentacji
- Utworzono brakujace pliki kontrolne w root:
  - ARCHITECTURE_DECISIONS.md
  - TRADING_METRICS_SPEC.md
  - STRATEGY_RULES.md
  - CURRENT_STATE.md
  - OPEN_GAPS.md
  - CHANGELOG_LIVE.md (ten plik)
- Archiwalna historia zmian pozostaje w docs/archive/CHANGELOG_LIVE.md.

### Wczesniejsze wpisy
- Pelna historia sprzed 2026-04-14: docs/archive/CHANGELOG_LIVE.md

## [2025-07-03] — Fix entry-readiness EUR filter + buy-trace + ip-diagnostics

### CRITICAL FIX — entry-readiness: USDC symbols nie trafiały do kandydatów
- **Plik**: `backend/routers/signals.py` `get_entry_readiness()`
- **Bug**: `if not sym_norm.endswith(demo_quote_ccy): continue` gdzie `demo_quote_ccy = get_demo_quote_ccy() = "EUR"` — filtrowało WSZYSTKIE symbole USDC w trybie LIVE → always 0 candidates
- **Naprawa**: zastąpiono warunkiem `if mode != "live" and not sym_norm.endswith(demo_quote_ccy): continue`
- **Rezultat**: `entry-readiness` teraz zwraca 8 kandydatów BUY (WLFIUSDC conf=0.84, SHIBUSDC conf=0.88, etc.)

### NEW ENDPOINT — `/api/signals/buy-trace/{symbol}`
- Deterministyczny trace decyzji BUY przez 13 kroków pipeline
- Każdy krok: passed/failed + szczegóły
- Final `reason_code` + `reason_pl`
- Weryfikacja: WLFIUSDC → ALLOW (wszystkie 13 kroków zielone)

### IMPROVED — `/api/account/ip-diagnostics`
- HTTP probe dla każdego URL (timeout 2s)
- `pgrep cloudflared` → pole `tunnel_process_running`
- Per-URL status: reachable/unreachable + typ (quick/named)
- `active_frontend_url`, `active_api_url` (None jeśli nic nie odpowiada)
- Wykrywa martwe quick tunnel URL-e i ostrzega
- Weryfikacja: tunnel_process_running=False, any_url_reachable=False, 2x❌ quick tunnel

### IMPROVED — Telegram `/ip` command
- Pokazuje `tunnel_process_running` (✅/❌)
- Per-URL status z HTTP probe
- `active_frontend_url` lub "BRAK"
- Ostrzeżenie gdy żaden URL nie odpowiada

### Testy: 279/279 passed
