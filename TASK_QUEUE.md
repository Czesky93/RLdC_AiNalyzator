# TASK_QUEUE — RLdC Trading Bot

*Ostatnia aktualizacja: 2026-04-04 (Sesja 35 — schema fix + USDC cleanup + testy 210/210)*

## ZADANIA OTWARTE

### CRITICAL

*Brak otwartych zadań krytycznych.*

### HIGH

*Brak otwartych zadań HIGH.*

### MEDIUM

*Brak otwartych zadań.*

### LOW

*Brak otwartych zadań.*

### DONE (zamknięte)

| ID | Zadanie | Zamknięte | Commit |
|----|---------|----------|--------|
| BUG-SCHEMA-35 | **Brakujące kolumny pending_orders**: `exchange_order_id VARCHAR(80)`, `expires_at DATETIME`, `last_checked_at DATETIME` nie dodane przez `_ensure_schema()` przy starcie. Root cause: `inspector = inspect(engine)` tworzony RAZ, cache nie odświeża po ALTER TABLE → dla tabel wcześniej odwiedzonych w tej samej funkcji wynik jest stale. Fix: `_ensure_column()` teraz tworzy `fresh_inspector = inspect(engine)` per wywołanie. Kolumny dodane ręcznie przez ALTER TABLE do live DB. Weryfikacja: PRAGMA table_info — 22 kolumny ✅. 210/210 ✅. | 04.04 sesja 35 | bieżący |
| DEBT-01-T17 | **USDC spam WARNING co ~17 min**: 8 par USDC (BTCUSDC, ETHUSDC, SOLUSDC, BNBUSDC, WLFIUSDC, SHIBUSDC, ETCUSDC, SXTUSDC) było w `WATCHLIST` w `.env` mimo że system działa wyłącznie na EUR. Logger generował WARNING przy każdym `_load_watchlist()`. Fix: usunięto pary USDC z `WATCHLIST=BTC/EUR,ETH/EUR,SOL/EUR,BNB/EUR,WLFI/EUR,SHIB/EUR`. Collector restart → brak WARNINGs, scanner top-30 EUR działa ✅. 210/210 ✅. | 04.04 sesja 35 | bieżący |
| BUG-NPM-TYPES | **Brakujące pakiety npm @types/\***: @types/node, @types/react, @types/react-dom nie były zainstalowane. Fix: `npm install --save-dev`. TypeScript build: 0 błędów ✅. | 04.04 sesja 35 | bieżący |
| T-08-F2 | **LIMIT orders LIVE — Faza 2 (monitor + fallback)**: dodano `PendingOrder.exchange_order_id/expires_at/last_checked_at`, `BinanceClient.get_open_orders/get_order/cancel_order`, monitor `_monitor_limit_orders()` uruchamiany w cyklu collectora oraz poprawkę w `_execute_confirmed_pending_orders()`: `LIMIT BUY` ze statusem `NEW/PARTIALLY_FILLED` nie jest już błędnie zapisywany jako `FILLED`, tylko przechodzi do `OPEN`. Po `limit_order_timeout` następuje `cancel_order` i fallback do `MARKET`; częściowe fill są księgowane przed fallbackiem na pozostały wolumen. Guardy/UI traktują `OPEN` jako aktywny pending. `limit_order_timeout` dodano do runtime settings. | 04.04 sesja 34 | bieżący |
| CC-TERMINAL | **WebSocket PTY Terminal w Control Center (6. zakładka)**: `backend/routers/terminal.py` — WebSocket `/ws/terminal?token=..`, PTY+bash, auth via query param, protokół JSON (input/resize/ping/output/exit/pong), limit 4 sesji/1h. `app.py` — import i rejestracja. `ControlCenter.tsx` — 6. zakładka `'terminal'`, `TermLine` interfejs, `wsTermRef`, `stripAnsi`, auto-connect/disconnect, historia poleceń (↑↓), Ctrl+C/Ctrl+L. Build ✅, 196/196 ✅, WS handshake 101 ✅. | 03.04 sesja 33 | bieżący |
| BUG-COLLECTOR-STATUS | **Collector status zawsze "stopped" mimo że działał**: `system.py` sprawdzało `getattr(collector, "_running", False)` ale collector używa `self.running` (bez podkreślnika). Fix: `getattr(collector, "running", False) or getattr(collector, "_running", False)`. Weryfikacja: `collector: active \| watchlist: 30`. 196/196 ✅. | 03.04 sesja 33 | bieżący |
| BUG-REGIME-MISSING | **Brak reżimu rynku (`regime`) w statusie systemu**: GET `/api/system/status` nie zwracał pola `regime`. Pobieramy z `get_market_regime()` (cache 30 min). Dodano: `regime: {regime, buy_blocked, buy_confidence_adj, reason}`. ControlCenter.tsx: rozszerzono `SystemStatus` interfejs + badge reżimu w headerze (czerwony gdy buy_blocked). Weryfikacja: `regime: SIDEWAYS, buy_blocked: False`. 196/196 ✅. | 03.04 sesja 33 | bieżący |
| BUG-WEALTH-PNL | **Live wealth view `pnl_eur: 0.0` i `entry_price=current_price` hardkodowane** | 03.04 sesja 32 | bieżący | `pnl_eur: 0.0` i `entry_price=current_price` hardkodowane**: `GET /api/portfolio/wealth?mode=live` zastępowało pozycje Binance danymi spot ale hardkodowało `pnl_eur=0.0` i `entry_price=cur_price`. Fix: query do `Position` (mode=live, qty>0) → mapping `asset → Position`; `pnl_eur=position.unrealized_pnl`, `entry_price=position.entry_price`, `opened_at=position.opened_at`. Dust balances (BNB/BTC) poprawnie `pnl=0.0`. `total_pnl=-1.48 EUR`. 196/196 OK. | 03.04 sesja 32 | bieżący |
| BUG-LUPNL | **Live summary `unrealized_pnl: 0.0` hardkodowane**: `GET /api/account/summary?mode=live` zwracało zawsze `unrealized_pnl: 0.0` i brak `realized_pnl_24h`. Fix: dodano query do `Position` (mode=live, qty>0) → suma `unrealized_pnl`. Dodano query do `Order` (mode=live, SELL, FILLED, last 24h) → `realized_pnl_24h`. Weryfikacja: `-1.4775 EUR` unrealized (ARBEUR+RENDEREUR+VETEUR), `+2.6441 EUR` realized_pnl_24h. 196/196 OK. | 03.04 sesja 32 | bieżący | **Audyt systemu — system_logs, REJECTED pending orders, LTCEUR/LINKEUR warnings, ARBEUR SL monitoring**: (1) Zbadano 57756 rekordów `system_logs` po restarcie 12:19 — znaleziono 2 typy ostrzeżeń: `Brak tickera dla LTCEUR/LINKEUR` (przejściowe błędy API, nie bug) oraz `Gemini HTTP 429` (rate limit AI, fallback aktywny). (2) 21 REJECTED pending (12 live, 9 demo) — wszystkie historyczne, wynikające z NameError `name 'symbol' is not defined` w pre-BUG-25 kodzie; każdy REJECTED ma odpowiadający FILLED order w tej samej chwili — pozycje zamknięte prawidłowo. Po restarcie 12:19: 0 `pending_execution_error`. (3) ARBEUR [live] SL monitoring: cena=0.0804, SL=0.080356, buf=0.055% — system monitoruje poprawnie co ~3 min. (4) Live realized PnL 24h: +2.6441 EUR. SCANNER tier dla ARBEUR zweryfikowany (min_conf=0.07, risk_scale=0.5). **0 nowych bugów znalezionych.** 196/196 OK. | 03.04 sesja 31 | bieżący |
| DEBT-03 | **ADMIN_TOKEN + live_ready=True**: Ustawiono `ADMIN_TOKEN` w `.env` (32-bajtowy `secrets.token_urlsafe`). `live_guard_issues: []`, `live_ready: True`. Dodano sekcję tokenu w `ControlCenter.tsx`: Input + zapis do `localStorage` (SessionStorage nie wymagany — localStorage bezpieczny dla lokalnej aplikacji). Auth: bez tokenu → 401 Unauthorized, z tokenem → 200 OK. Badge `🔑 auth / 🔒 brak tokenu` w headerze. 196/196 OK. | 03.04 sesja 30 | bieżący |
| CC-01 | **Control Center + Publiczny dostęp**: Nowe moduły: `backend/public_url.py` (5-poziomowe wykrywanie URL), `backend/routers/system.py` (GET /api/system/status, /public-url, /events, /logs/stream SSE), `backend/routers/actions.py` (10 akcji POST + `/api/actions/ai/chat`). Frontend: `ControlCenter.tsx` (4 zakładki: Status, Akcje, Logi SSE, AI Chat) + Sidebar/MainContent integracja. Telegram: komenda `/ip`. `.env` + `next.config.js` rozszerzone o PUBLIC_*. `docs/PUBLIC_ACCESS.md`. Weryfikacja: 196/196 ✅, build ✅, wszystkie EP przez port 3000. | 03.04 sesja 29 | bieżący |
| BUG-25 | **activity_gate_day + tier_daily_trade_limit fałszywe blokady przez partial take-profit**: Partial TP generuje 3 SELL orders na 1 pozycję (25%+18.75%+56.25%). `compute_activity_snapshot.trades_24h` zliczał ALL orders → po 5 cyklach (20 orderów = 5 BUY + 15 SELL) system blokował WSZYSTKIE nowe wejścia przez `activity_gate_day` (limit=20). Analogicznie `tier_daily_trade_limit` w collector.py zliczał BUY+SELL → RENDEREUR SPECULATIVE (limit=3) był blokowany po 1 pełnym cyklu (1 BUY+3 SELL=4 orders ≥3). Fix: (1) `accounting.py compute_activity_snapshot` — `trades_24h` teraz liczy tylko `side=='BUY'`; (2) `collector.py sym_trades_today` — dodano `Order.side=='BUY'` do filtru. Efekt: demo entries_24h 22→9, live 20→7. `activity_gate_day` zniknął (652→0 w nowych cyklach). 196/196 OK. | 03.04 sesja 29 | bieżący |
| BUG-HEALTH-TS | **health endpoint zwracał hardkodowany timestamp `"2026-01-31T17:30:00Z"`**: `GET /health` przywoływał statyczny string zamiast dynamicznie obliczanego czasu. Wpływ: monitoring/dashboardy widziały błędny czas. Fix: dodano `from datetime import datetime, timezone` do `app.py`, zmieniono na `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`. 196/196 OK. | 03.04 sesja 29 | bieżący |
| PROFIT-FIX-04 | **min_edge_multiplier 2.5→4.0** — zbyt niski próg akceptował transakcje o niewystarczającym stosunku edge/koszty. Default w `runtime_settings.py` i override w DB: `4.0`. Sam edge musi być 4× kosztu round-trip przed wejściem. 196/196 OK. | 31.01 sesja 28 | bieżący |
| PROFIT-FIX-03 | **Nowy filtr `atr_below_min_pct` w collector.py** — blokuje wejście gdy ATR/cena < min_atr_pct (domyślnie 0.5%). Nowy SettingSpec `min_atr_pct` (default=0.005, env_var=MIN_ATR_PCT) dodany do `runtime_settings.py`. cost_gate_pass rozszerzony o `_atr_pct >= _min_atr_pct`. SL cooldown ulepszone: `max(base_cooldown, min(sl_cooldown, base_cooldown*4))` — gwarantuje min 2h cooldown po each SL hit. 196/196 OK. | 31.01 sesja 28 | bieżący |
| PROFIT-FIX-02 | **Parametry strategii — zbyt agresywne ustawienia powodowały straty** — wynik Apr1-3: WR=41.7%, net -5.3 EUR. Poprawki w DB: `bear_regime_min_conf` 0.52→0.70, `max_open_positions` 5→3, `loss_streak_limit` 7→3, `cooldown_after_loss_streak_minutes` 0→120, `trading_aggressiveness` aggressive→safe, `demo_min_signal_confidence` 0.50→0.62, `pending_order_cooldown_seconds` 0→300. Tier: CORE `max_trades_per_day` 10→4, ALTCOIN 3→2. Demo cooldown ETHEUR/WIFEUR aktywowany. 196/196 OK. | 31.01 sesja 28 | bieżący |
| PROFIT-FIX-01 | **ATR_STOP_MULT 1.2→2.0, ATR_TAKE_MULT 2.0→3.5 (RR=1.75)** — SL był za ciasny (1.2×ATR ≈ 0.6% dla WIF), szum rynkowy natychmiast hitował. Z fee 0.36% round-trip i WR=41.7%: stare RR=1.67 → ujemne EV (-24.7%). Nowe: RR=1.75, min wymagany WR=40.4%. Wartości wpisane do DB (RuntimeSetting), .env też zaktualizowane. `runtime_settings.py` defaults: atr_stop_mult=2.0, atr_take_mult=3.5. 196/196 OK. | 31.01 sesja 28 | bieżący |
| BUG-24-BACKFILL | **Backfill NULL PnL dla 17 SELL FILLED orderów** — BUG-23 przerywał `_execute_confirmed_pending_orders` PRZED `attach_costs_to_order` → 16 orderów bez fee/gross/net. Uzupełnione z CostLedger+ExitQuality: 16 orderów dostało fee+gross+net, 1 bez gross (brak EQ match). Dane historyczne naprawione. | 31.01 sesja 28 | bieżący |
| BUG-24 | **PEPEEUR [live] ExitQuality corruption** — `total_cost=9895.9 EUR` (zamiast ~0.108 EUR) przez ticker price sanity check bug (BUG-19). `net_pnl=-9896.01 EUR` zawyżało straty. Naprawione: `net_pnl=-0.2121 EUR`, `total_cost=0.108 EUR`. | 31.01 sesja 28 | bieżący |
| BUG-23 | **NameError: 'symbol' is not defined przy zamykaniu pozycji (pending_execution_error)**: W `_execute_confirmed_pending_orders`, gdy pozycja jest pełne zamknięta (qty≤0 lub dust<1 EUR), `logger.info(f"✅ Pozycja {symbol} zamknięta...")` używał niezdefiniowanej zmiennej `symbol` zamiast `pending.symbol`. Efekt: za każdym razem gdy SELL zamykał pozycję, wyrzucał `NameError` → błąd był łapany w zewnętrznym try/except → trace `pending_execution_error` z `{"error": "name 'symbol' is not defined"}` → zlecenie nie było oznaczane jako EXECUTED, pozycja mogła nie zostać poprawnie zamknięta w DB. Naprawiono: `{symbol}` → `{pending.symbol}`. 196/196 OK. | 03.04 sesja 27 | bieżący |
| BUG-22 | **RENDEREUR/PEPEEUR w SCANNER tier (max_trades=1/dzień)**: Oba symbole nie były przypisane do żadnego tieru → wpadały do "SCANNER" z `max_trades_per_day_per_symbol=1`. Po pierwszym wejściu danego dnia, bot blokował dalsze wejścia przez `tier_daily_trade_limit`. Naprawiono: dodano RENDEREUR/RENDERUSDC/PEPEEUR/PEPEUSDC do tieru SPECULATIVE w default config i DB override. `max_trades_per_day_per_symbol = 3` (było 2). 196/196 OK. | 02.04 sesja 26 | bieżący |
| BUG-21 | **live_balance_eur poza SettingSpec → get_runtime_config() zwracało None → drawdown_gate używało złej bazy**: `live_balance_eur` nie był w `_SETTINGS` dict. `get_runtime_config(db)` zwracało tylko klucze z `_SETTINGS` → `cfg.get("live_balance_eur") = None` → `evaluate_risk` obliczało drawdown_base = tylko `exposure` (~213 EUR) zamiast `live_balance + exposure` (~363 EUR). Naprawiono: dodano `live_balance_eur` do `_SETTINGS` z `default=0.0`, `env_var="LIVE_INITIAL_BALANCE"`, sekcja "risk". Weryfikacja: `get_runtime_config()` zwróciło `live_balance_eur: 90.1485`. Workaround w risk.py (direct DB query) pozostawiony jako safety net. 196/196 OK. | 02.04 sesja 26 | bieżący |
| BUG-20 | **min_notional_guard blokuje ETHEUR live przy saldzie 150 EUR + max_open=5**: `max_cash_pct_per_trade = 1/5 = 20%` → `max_cash_for_trade = 30 EUR < min_order_notional = 60 EUR` → ETHEUR live permanentnie blokowane mimo dostępnych 150 EUR. Naprawiono w collector.py: gdy `max_cash_for_trade < min_order_notional AND available_cash >= min_order_notional`, podniesiono `max_cash_for_trade = min_order_notional`. Warunek "raise ATR-qty" zmieniony z `max_affordable * price` na `max_cash_for_trade >= min_order_notional` (obsługuje prowizję). Sim: 150 EUR saldo → ETH notional=60.00 EUR → eligible=True. 196/196 OK. | 02.04 sesja 26 | bieżący |
| BUG-19 | **exec_price sanity check (kill switch fałszywy trigger)**: W trybie DEMO przy pobieraniu ceny z `get_ticker_price()`, jeśli ticker zwrócił błędną cenę (np. 0.95 EUR zamiast 2.89e-6 dla PEPE), `notional = qty × wrong_price` wychodził miliony EUR → `fee_cost = notional × 0.001 = 9895 EUR` → `daily_net_pnl = -9898 EUR` → `kill_switch_triggered=True` fałszywie → blokada wszystkich live wejść (PEPEEUR, RENDEREUR). Naprawiono: ticker price sanity check — jeśli `ticker_price / pending_price > 50` lub `pending_price / ticker_price > 50` (stosunek > 50×), użyj `pending.price` zamiast ticker + logger.warning `BUG-19`. Istniejący fix currency conversion (waluty bazowe PEPE/RENDER → przelicz przez exec_price) był już w kodzie z wcześniejszej sesji. 196/196 OK. | 02.04 sesja 25 | bieżący |
| BUG-18 | **exit_reason_code ustawiany na pozycji podczas CZĘŚCIOWEGO EXIT**: W `_execute_confirmed_pending_orders` linia `position.exit_reason_code = ...` była wykonywana PRZED sprawdzeniem czy partial czy full close. Efekt: pozycja RENDEREUR demo (qty=21.8) miała `exit_reason_code="tp_partial_keep_trend"` po 2 częściowych wyjściach → nie była monitorowana przez exit engine (filtrowana jako "zamknięta"). Naprawiono: `exit_reason_code` ustawiany TYLKO w gałęzi pełnego zamknięcia (`qty<=0 or dust < 1 EUR`). Naprawa DB: RENDEREUR `exit_reason_code=None`. 196/196 OK. | 02.04 sesja 23 | bieżący |
| P3-01 | **build_runtime_state brak klucza "config" → signals.py używało hardkodowanych fallbacków**: `build_runtime_state` nie zawierało `"config"` w zwracanym dict. Konsekwencja: `config = runtime_ctx.get("config", {})` w 3 miejscach signals.py zawsze dostawało pusty dict → wszystkie `config.get(...)` używały hardkodowanych defaults. Efekty: (1) `trading_aggressiveness="balanced"` zamiast `"aggressive"` → złe MIN_SCORE/MIN_CONFIDENCE; (2) `max_open_positions=3` zamiast `5` → blokowanie po 3 pozycjach w UI; (3) `bear_regime_min_conf=0.68` zamiast `0.62` → zły próg wyświetlany w UI. Naprawiono: dodano `"config": effective` do `build_runtime_state` return dict. Kolektor był nienaruszony (używał `get_runtime_config(db)` osobno). 196/196 OK. | 02.04 sesja 22 | bieżący |
| P2-01b | **P2-01 CICHA REGRESJA: limit=50 w get_live_context → zawsze None**: P2-01 wywoływało `get_live_context(db, symbol, timeframe="4h", limit=50)`, ale funkcja wymaga `len(df) >= 60` — z limit=50 zawsze zwracała None. Efekt: `htf_align_factor` zawsze=1.0 (neutralny), filtr 4h nigdy nieaktywny od czasu implementacji. Naprawiono: `limit=50 → limit=100` (mamy 106 klines 4h w DB). Weryfikacja: ema_20=58418, ema_50=58881 → 4h niedźwiedzi, filtr aktywny. 196/196 OK. | 02.04 sesja 21 | bieżący |
| P2-01 | **Multi-timeframe 4h HTF alignment (soft penalty/bonus)**: `_screen_entry_candidates` pobiera `get_live_context(db, sym, timeframe="4h")`. Gdy BUY + 4h EMA20>EMA50 → `htf_align_factor=1.10` (+10% `composite_score`). Gdy BUY + 4h EMA20<EMA50 → `htf_align_factor=0.80` (-20% `composite_score`). SELL odwrotnie. `htf_align_note` zapisywany do `signal_summary["htf_4h_align"]` i Telegram. Brak danych 4h = neutralne (factor=1.0). Soft penalty — NIE blokuje wejścia, tylko zmienia ranking kandydatów. Telegram pokazuje pole `HTF: 4h:bycze(+10%)`. 196/196 OK. | 02.04 sesja P2 | bieżący |
| P2-01b | **P2-01 CICHA REGRESJA: limit=50 w get_live_context → zawsze None**: P2-01 wywoływało `get_live_context(db, symbol, timeframe="4h", limit=50)`, ale funkcja wymaga `len(df) >= 60` — z limit=50 zawsze zwracała None. Efekt: `htf_align_factor` zawsze=1.0 (neutralny), filtr 4h nigdy nieaktywny od czasu implementacji. Weryfikacja: testowy wywołanie z limit=50 zwróciło AttributeError (None). Naprawiono: `limit=50 → limit=100` (mamy 106 klines 4h w DB). Weryfikacja po naprawie: `ema_20=58418.76, ema_50=58881.50` (4h niedźwiedzi) — filtr aktywny; BUY dostanie teraz penalty -20% composite_score. 196/196 OK. | 02.04 sesja P2 (kontynuacja) | bieżący |
| P2-02 | **Composite final_score ranking** — już zaimplementowany jako T-19 (sesja 16): `composite_score = edge × conf × (rating/5)`. Teraz rozszerzony o HTF alignment factor w P2-01. DONE. | skumulowany w P2-01 | bieżący |
| P2-03 | **SELL bez pozycji → cichy skip (eliminacja szumu SKIP trace)**: W `_screen_entry_candidates`: gdy `side==SELL AND position is None` → `continue` (brak `_trace_decision` SKIP). Eliminuje 90%+ szumu w `decision_traces` (było ~20k+ rekordów `sell_blocked_no_position`). reason_code zachowany jako komentarz w kodzie dla backwards compat. Test `test_p1_sell_without_position_blocked` zaktualizowany. 196/196 OK. | 02.04 sesja P2 | bieżący |
| P1-02b | **P1-02 REGRESJA: bear_regime_min_conf DB override = 0.68 nadpisywał nowy default 0.62**: P1-02 zmieniał `default=0.62` w `SettingSpec`, ale w DB był override `0.68` zapisany z poprzedniej sesji — efektywna wartość była nadal 0.68. Naprawiono: `upsert_overrides(db, {'bear_regime_min_conf': None})` — usunięto override; system używa nowego default=0.62. Zweryfikowano: `/api/control/state` → `bear_regime_min_conf: 0.62`. 196/196 OK. | 02.04 sesja P2 | bieżący |
| P1-01 | **BEAR DOUBLE-BLOCK FIX**: Sygnał przechodzący `bear_regime_min_conf` (0.62) był PONOWNIE blokowany przez `min_confidence + buy_confidence_adj` (0.55+0.10=0.65). Skutek: 0.63 conf → bot blokował mimo przejścia BEAR testu. Naprawiono: gdy `buy_blocked=True` i sygnał przeszedł explicit BEAR check → `min_confidence = min(min_confidence, effective_bear_min)` (nie dodawaj `buy_confidence_adj` na wierzch). 196/196 OK. | 02.04 sesja P1 | bieżący |
| P1-02 | **BEAR/BEAR_SOFT buy_confidence_adj za wysoki** — CRASH 0.20→0.15, BEAR 0.15→0.10, BEAR_SOFT 0.10→0.05 w `get_market_regime()`. `bear_regime_min_conf` default 0.68→0.62. Typowy sygnał heurystyczny (score=2) = 0.66 conf — teraz przechodzi w BEAR_SOFT (0.55+0.05=0.60) i BEAR z override (0.62). 190/190 OK. | 02.04 sesja P1 | bieżący |
| P1-03 | **PRZEDWCZESNE WYJŚCIE z pozycji (BTC rósł, bot zamknął za wcześnie)** — `trend_strong` w Warstwie 3 TP używał `40 < RSI < 75.0`. RSI=78 w bull runie = False → pełne zamknięcie zamiast partial+trailing. Naprawiono: próg 75→82 (`rsi < 82.0`). Dodano ADX gate: `EMA_bullish AND ADX>=25` → `trend_strong=True` niezależnie od RSI. Layer 4 reversal check: RSI>65→RSI>70 (normalny RSI w trendzie nie triggeruje exit). 190/190 OK. | 02.04 sesja P1 | bieżący |
| P1-04 | **ADX/Supertrend/VolumeRatio BRAK w get_live_context()** — Kod w `_screen_entry_candidates` i `_check_exits` usiłował `ctx.get("adx")` ale zawsze dostał None (nie było w dict). Naprawiono: `get_live_context()` teraz oblicza i zwraca `adx`, `supertrend_dir`, `volume_ratio` przez pandas-ta. Exit engine ma teraz dostęp do ADX. 190/190 OK. | 02.04 sesja P1 | bieżący |
| P1-05 | **Gemini/Groq 429 brak rozróżnienia** — 429 (rate limit) traktowany jak 400 (błąd), brak logu AI_PROVIDER_RATE_LIMITED. Naprawiono: `_gemini_ranges()` i `_groq_ranges()` logują `"AI_PROVIDER_RATE_LIMITED. FALLBACK_ANALYSIS_ACTIVE."` na poziomie WARNING przy status_code==429. 190/190 OK. | 02.04 sesja P1 | bieżący |
| BUG-17 | **SELL ERROR "insufficient balance" — qty DB > Binance free**: Po BUY fill Binance rounded qty nieznacznie (0.01828261 ETH vs DB 0.0183). `normalize_quantity()` floorem do step_size nie sprawdzał faktycznego free salda, więc SELL qty=0.0183 > Binance free=0.01828261 → "Account has insufficient balance". Naprawiono: w `_execute_confirmed_pending_orders` przed pętlą pobieramy `get_balances()` raz → dict `{asset: free}`. Dla każdego SELL live po `normalize_quantity`, jeśli qty >  Binance free, cap: `qty = normalize_quantity(symbol, binance_free)`. 181/181 OK. | 02.04 sesja 10 | bieżący |
| BUG-13 | **Order.ERROR brak error_reason**: Gdy Binance `place_order` zwraca `_error`, kod logował błąd i tworzył REJECTED PendingOrder, ale NIE zostawiał żadnego Order rekordu z powodem błędu. Diagnostyka błędów Binance była tylko w logu textowym. Naprawiono: dodano `error_reason = Column(Text)` do `Order` + migracja `_ensure_column` + tworzenie `Order(status="ERROR", error_reason=err_msg[:500])` w `_execute_confirmed_pending_orders` gdy `result._error`. 181/181 OK. | 02.04 sesja 8 | bieżący |
| BUG-15 | **Float precision notional 24.9999<25.0**: Gdy `qty = min_order_notional / price`, następnie `notional = qty * price` dawało `24.9999...` przez precyzję float, co powodowało `execution_check.eligible=False` (minor_notional_guard) mimo że notional był praktycznie równy limitowi. Naprawiono: `notional >= min_order_notional - 0.01` (tolerancja 1 grosz). Sprawdzone: nie wpływa na SHIBEUR (blokowany wcześniej przez cost_gate_failed). 181/181 OK. | 02.04 sesja 8 | bieżący |
| BUG-16 | **LIVE KILL SWITCH FALSE TRIGGER (2 fazy naprawy)** — **Faza 1** (sesja 8): Gdy brak otwartych pozycji `total_exposure=0` → baza = 1 EUR → próg = 3 centy → kill switch ALWAYS TRUE. Naprawiono: persistowanie `live_balance_eur` z Binance + fallback gdy `total_exposure=0`. Efekt: ETHEUR BUY LIVE FILLED @ 1806.44. **Faza 2** (sesja 9): Regresja — po otwarciu ETHEUR: `total_exposure=33 EUR` → stary kod używał `total_exposure` jako bazę → 3% = 0.99 EUR → drawdown -3.93 EUR >> próg → kill switch znowu True. Prawdziwy drawdown = 1.18% (3.93 / (298+33) = 364 EUR). Naprawiono: `accounting.py compute_risk_snapshot`: `initial_balance = max(1.0, free_eur + total_exposure)` — zawsze gotówka+pozycje; `risk.py evaluate_risk`: `_base = max(1.0, _live_balance + _exposure)` — identyczna logika. Zweryfikowano: kill_switch_triggered=False, drawdown=1.18%, brak kill_switch_gate po restarcie. 181/181 OK. | 02.04 sesja 8+9 | bieżący |
| BUG-8 | **WATCHLIST - 7 zamiast 14 symboli**: `_load_watchlist()` używał Binance balance jako primary → tylko BNB/BTC/SHIB/SXT=7 symboli. ETH/SOL/ETC/WLFI poza portfolio → niewidoczne. Naprawiono: `_load_watchlist` łączy balance-based Z ENV WATCHLIST przed filtrem SPOT allowlist. Po restarcie: 14 symboli (BNBEUR/USDC, BTCEUR/USDC, ETCUSDC, ETHEUR/USDC, SHIBEUR/USDC, SOLEUR/USDC, SXTUSDC, WLFIEUR/USDC). 181/181 OK. | 02.04 sesja 5 | bieżący |
| BUG-9 | **ENTRY SCORE SKALA - bot NIGDY nie wchodził**: `rating` (int 1-5) porównywany z `demo_min_entry_score=5.5` (skala wait-status 0-12+). `if rating < 5.5` → zawsze True → zero wejść. Naprawiono: konwersja skali: thresh<5→rating 1; thresh<6→2; thresh<8→3; thresh<10→4; thresh≥10→5. Z score=5.5→min_rating=2 (wymaga conf≥0.75). Po naprawie: SHIBEUR przeszedł score gate → osiągnął `cost_gate_failed`. 181/181 OK. | 02.04 sesja 5 | bieżący |
| BUG-10 | **RANGE MAP PARTIAL COVERAGE**: Heurystyczny fallback wyzwalany tylko gdy `not range_map OR ai_ranges_stale`. Blog z 7-symbolową watchlistą → range_map niepustą (7/14) → fallback NIE uruchamiany dla brakujących symboli. ETHEUR/SOLEUR/ETCUSDC/WLFIUSDC pomijane cicho (bez śladu). Naprawiono: fallback sprawdza `if not range_map OR ai_ranges_stale OR missing_syms` — uzupełnia brakujące symbole niezależnie od tego czy range_map jest pusta. SystemLog potwierdza: "Heurystyczne zakresy ATR dla 7 brakujących symboli." 181/181 OK. | 02.04 sesja 6 | bieżący |
| BUG-10b | **_trace_decision: brak obsługi flush error**: Oryginalny kod propagował `db.flush()` wyjątek przez cały stos. Naprawiono: try/except around save_decision_trace+flush z explicit rollback + return (nie propaguj). _trace_decision failure nie przerywa już cyklu trading. 181/181 OK. | 02.04 sesja 6 | bieżący |
| BUG-12 | **DUST LIVE POZYCJA PĘTLA EXIT**: Po zamknięciu pozycji live przez Binance, pozostawało ≤1 EUR dust (np. BTCEUR qty=5.2e-6). _check_exits tworzył PENDING SELL co cykl → `normalize_quantity()` → qty=0 → REJECTED → pętla w kółko. Naprawiono: gdy `normalized_qty<=0` i `side==SELL`, bot szuka powiązanej Position (live, symbol, qty>0) i ustawia qty=0, exit_reason=`dust_quantity`. Pętla zatrzymana. Naprawa DB: BTCEUR live qty→0. 181/181 OK. | 02.04 sesja 7 | bieżący |
| BUG-14 | **exit_reason_code zawsze "pending_confirmed_execution"**: Wszystkie wyjścia (SL, TP, trailing, reversal) miały `position.exit_reason_code="pending_confirmed_execution"` zamiast rzeczywistego powodu (stop_loss_hit, tp_full_reversal, trailing_lock_profit itd.). Naprawiono: dodano kolumnę `exit_reason_code` do PendingOrder + _ensure_schema + przekazywanie z _create_pending_order (4 warstwy exit) + użycie w _execute_confirmed_pending_orders dla position i Order. 181/181 OK. | 02.04 sesja 7 | bieżący |
| T-01 | LIVE CostLedger actual Binance fees | 02.04 sesja 2 | 9ac10b0 |
| T-02 | Periodyczny sync DB↔Binance | 02.04 sesja 2 | 9ac10b0 |
| T-03 | Telegram /confirm /reject | — | Już było zaimplementowane (false positive) |
| T-04 | Qty sizing: prowizja w alokacji | 02.04 sesja 2 | bieżący |
| T-05 | CORS allow_origins → localhost/LAN (z env CORS_ALLOWED_ORIGINS) | 01.04 sesja 3 | bieżący |
| T-06 | Persistuj demo_state do RuntimeSetting co cykl + ładuj przy starcie | 01.04 sesja 3 | bieżący |
| T-06_old | Telegram governance stubs | — | Już było zaimplementowane (false positive) |
| T-07 | Usuń martwy widget AccountSummary.tsx | 01.04 sesja 3 | bieżący |
| T-09 | **KRYTYCZNY**: 27 hardkodowanych `mode="demo"` w `_check_exits` + `_demo_trading` — Bot działał w trybie LIVE ale tworzył zlecenia exit/entry z `mode="demo"`. `_create_pending_order` i `_trace_decision` używały złego trybu → LIVE exits ignorowane, LIVE DB queries zwracały demo dane. Naprawiono: dodano `_exit_mode = tc.get("mode","demo")` w `_check_exits`, `_current_mode` w entry sekcji. 181/181 OK. | 01.04 sesja 3 | bieżący |
| T-10 | **KRYTYCZNY**: `_sync_binance_positions` logowało WARNING co 5 minut o niezgodności DB↔Binance, ale bot miał `active_position_count=0` dla LIVE — nie wiedział o WLFI/BTC/SHIB. Mógłby kupować posiadane już aktywa, equity było źle obliczane. Naprawiono: `_sync_binance_positions` teraz auto-importuje brakujące aktywa z Binance do DB Position (mode=live, entry=current_price, filtr: symbol w watchliście, notional >= 1 EUR), warning wyciszone po imporcie (max 1x/30min). Test: 3 pozycje zaimportowane (BTCEUR, SHIBEUR, WLFIEUR), spam zatrzymany. 181/181 OK. | 02.04 sesja 4 | bieżący |
| T-11 | **KRYTYCZNY**: `place_order` zwraca `{"_error": True, ...}` przy BinanceAPIException — stary kod `if not result:` nie wykrywał błędu (dict jest truthy). Skutek: SHIBEUR SELL z LOT_SIZE error (qty=297837.99, step=1) był fałszywie oznaczony jako FILLED, pozycja usunięta, a Binance nigdy nie wykonał transakcji. Naprawiono: `_execute_confirmed_pending_orders` sprawdza `result.get("_error")`, ustawia status=REJECTED z logiem. Dodano `normalize_quantity()` do BinanceClient (floor qty do step_size Binance). Korekta DB: Ordery 31, 32, 33 BTCEUR/SHIBEUR → ERROR. 181/181 OK. | 02.04 sesja 4 | bieżący |
| T-12 | **KRYTYCZNY**: Degenerate ATR w `_auto_set_position_goals` — dla SHIB (ATR≈0) tp=sl=entry_price → `_check_exits` natychmiast wyzwalał SELL. Dodano: (1) minimum distance guard: TP min +0.5%, SL min -0.3% od entry; (2) grace period 2h dla importowanych pozycji bez TP/SL (binance_import) — zapobiega ustawianiu TP/SL na podstawie starych danych zaraz po imporcie. WLFI SELL przeszedł przez Binance (LOT_SIZE OK dla 3260.45); BTC SELL był blokowany przez LOT_SIZE (0.0008452, step=0.00001). 181/181 OK. | 02.04 sesja 4 | bieżący |
| T-13 | **WYDAJNOŚĆ KRYTYCZNA**: Endpointy UI `final-decisions` (10s), `best-opportunity` (12.5s), `positions/analysis` (3.5s), `portfolio/wealth` (2s) — każde wywołanie UI wywoływało Binance API + 14× pandas-ta obliczenia. Rozwiązanie: (1) TTL cache 55s dla `get_live_context` w `analysis.py` (jeden moduł obsługuje całe repo); (2) TTL cache 55s dla `_build_live_signals` w `signals.py` (key=sorted symbole); (3) TTL cache 60s dla `_get_symbols_from_db_or_env` (krok 4 = Binance spot API = 3.6s!); (4) TTL cache 30s dla `_build_live_spot_portfolio` w `portfolio.py`. Wynik: warm cache ≤15ms dla wszystkich 5 endpointów. 181/181 OK (testy same przyspieszyły z 45s→25s). | 02.04 sesja 4 | bieżący |
| T-14 | **Promotion/Rollback flow — 2 root causes (naprawione)**. Sub1: `apply_runtime_updates` early return bez `"snapshot"` klucza gdy `changed_keys=[]` → `baseline_id=None` → cascade 422. Naprawiono: dodano `"snapshot": previous_snapshot` do early return. Sub2: `pending_order_cooldown_seconds` SettingSpec miał `validators=(_validate_positive(...),)` (wymaga >0), ale `.env` ma `PENDING_ORDER_COOLDOWN_SECONDS=0` (0=brak cooldownu). Każde wywołanie promotion apply_runtime_updates rzucało `"must be > 0"`. Naprawiono: `_validate_positive` → `_validate_non_negative`. Wynik: **181/181 testów** (było 161/181). | `runtime_settings.py` | Stabilność pipeline strategii | 02.04 sesja 14 |
| T-15 | **WAIT-STATUS BEAR REGIME**: `/api/signals/wait-status` oznaczał BUY sygnały jako READY mimo aktywnego reżimu CRASH/BEAR (buy_blocked=True). Naprawiono: endpoint pobiera `get_market_regime()`, dodaje warunek do `missing_conditions` gdy `buy_blocked AND conf < bear_min_conf`. Odpowiedź teraz zawiera pole `market_regime.name/buy_blocked/bear_min_conf/reason`. | `routers/signals.py` | Poprawność UI | 02.04 sesja 13 |
| T-16 | **EXIT_REASON_CODE IGNOROWANY**: `_execute_confirmed_pending_orders` hardkodował `exit_reason_code="pending_confirmed_execution"` dla wszystkich SELL orderów, ignorując wartość z `PendingOrder.exit_reason_code` (stop_loss_hit, tp_full_reversal, trailing_lock_profit itd.). Naprawiono: używa `pending.exit_reason_code or "pending_confirmed_execution"`. | `collector.py` L594 | Diagnostyka | 02.04 sesja 13 |
| UI-REGIME | **BADGE REŻIMU RYNKOWEGO W UI**: Dodano baner CRASH/BESSA/SŁABA BESSA w `CommandCenterView` (MainContent.tsx). Dane z `waitStatus.market_regime`. Pokazuje: nazwę reżimu, powód, minimalną pewność dla BUY. Niewidoczny dla BULL/SIDEWAYS. | `MainContent.tsx` | UX transparentność | 02.04 sesja 13 |
| CFG-01 | **SettingSpec default min_order_notional 25→60**: Domyślna wartość `min_order_notional` w SettingSpec wynosiła 25.0, ale DB override i `signals.py` fallback używają 60.0. Przy świeżym deploymencie (brak DB override) wartość byłaby zbyt niska dla większości tokenów. Naprawiono: SettingSpec default → 60.0, spójne z DB i `routers/signals.py`. 181/181 OK. | `runtime_settings.py` | Poprawność konfiguracji | 02.04 sesja 15 |
| CFG-02 | **bear_regime_min_conf nie w SettingSpec**: Klucz `bear_regime_min_conf` używany w `collector.py` i `signals.py` z wartością domyślną 0.82 hardkodowaną w `config.get(..., 0.82)`. Nie było możliwości zmiany przez API. Naprawiono: dodano `SettingSpec(default=0.82, section="execution", env_var="BEAR_REGIME_MIN_CONF", _validate_probability)` + wpis do `_LIVE_GUARD_KEYS`. 181/181 OK. | `runtime_settings.py` | Konfigurowalność | 02.04 sesja 15 |
| AI-ORDER | **AI fallback order**: Ollama (lokalne) było PIERWSZE w łańcuchu (`ollama→gemini→groq→openai→heuristic`). Zmieniono na `gemini→groq→openai→ollama→heuristic` — lokalne AI używane tylko gdy wszystkie chmurowe niedostępne. Zmiana w: `analysis.py` (auto chain) + `routers/account.py` (AI status chain). 181/181 OK. | `analysis.py` L1641, `routers/account.py` L514 | Jakość sygnałów | 02.04 sesja 16 |
| T-19 | **Composite ranking score**: `edge_net_score` zastąpiony przez `composite_score = edge_net_score × confidence × (rating/5.0)`. Bot teraz wybiera najwyższą jakość sygnału zamiast najwyższego surowego edge (ATR/price). Telegram message zaktualizowany — pokazuje oba (Edge + Q). 181/181 OK. | `collector.py` `_screen_entry_candidates` L2937 | Zysk: lepszy dobór symbolu przy wielu kandydatach | 02.04 sesja 16 |
| T-08-F1 | **LIMIT orders LIVE — Faza 1**: `_create_pending_order` przyjmuje `order_type` param; `_execute_confirmed_pending_orders` używa `pending.order_type` zamiast hardkodowanego MARKET. Nowy `SettingSpec`: `live_entry_order_type` (default=`"MARKET"`, env=`LIVE_ENTRY_ORDER_TYPE`). BUY entries LIVE mogą być LIMIT jeśli skonfigurowane; SELL exits zawsze MARKET. Koszt: taker 0.10% → maker 0.05% = -0.10% round-trip gdy LIMIT wypelni się. 181/181 OK. | `collector.py`, `runtime_settings.py` | Koszty: -0.10% round-trip gdy LIMIT wypelnią | 02.04 sesja 19 |
| ROLLBACK-LOOP-FIX | **ROLLBACK LOOP FIX (6 poprawek)**: (1) `POST_PROMOTION_MIN_TRADE_COUNT` default 2→**20**, `POST_PROMOTION_MIN_WINDOW_SECONDS` default 0→**7200** — system nie ocenia strategii za wcześnie; (2) to samo dla post-rollback: `POST_ROLLBACK_MIN_TRADE_COUNT` 2→20, `POST_ROLLBACK_MIN_WINDOW_SECONDS` 0→7200; (3) Composite strategy score (`strategy_score_baseline/observed/delta`) dodany do deviation_summary — operator widzi pełny obraz; (4) `notification_hooks.py`: rate limiter alertów Telegram (`ALERT_RATE_LIMIT_SECONDS=3600`) — max 1 alert per event_type per godzinę; (5) `reevaluation_worker.py`: delta-based queue alert — Telegram wysyłany tylko gdy critical_count WZROŚNIE (nie co 5 min); (6) Bug fix: `execution_status == "applied"` → `"executed"` w filtrze post-rollback monitoring workera — monitoringi po rollbacku były nigdy nie re-evaluowane. Cooldown: `ROLLBACK_COOLDOWN_SECONDS=3600` — blokuje cascade rollbacków po ostatnio wykonanym. Izolacja testów: `NOTIFICATIONS_ENABLED=false`, `ALERT_RATE_LIMIT_SECONDS=0`, min thresholds=2/0 w testach. 190/190 OK. | `post_promotion/rollback_monitoring.py`, `notification_hooks.py`, `reevaluation_worker.py`, `rollback_decision.py`, `tests/test_smoke.py` | Stabilność: stop pętli rollback, koniec Telegram spam | 02.04 sesja 20 |
| DOC-ORIGIN | **Range origin tracking**: Pole `origin` w range dicts — `"heuristic"` lub `"ai:{provider}"`. 分ebrane przez: `_heuristic_ranges()` (zwraca `"origin": "heuristic"`); `_parse_ranges_response()` (zwraca `"origin": "ai:{provider}"`). Persisted w `signals.indicators` jako `range_origin`, `range_buy_low`, `range_sell_low`. `decision_traces.payload.details.range_origin` przy `CREATE_PENDING_ENTRY`. Endpoint `GET /api/market/ranges` zwraca `origin`. Log diagnostyczny w `maybe_generate_insights_and_blog`: ile symboli AI vs heuristic. 181/181 OK. | `analysis.py`, `routers/market.py`, `collector.py` | Diagnostyka: pełna widoczność skąd pochodzi range | 02.04 sesja 19 |
| DOC-01 | **TRADING_METRICS_SPEC.md — błędne koszty round-trip**: Dokument używał `slippage_pct=0.001` (0.1%) i `spread_pct=0.0008` (0.08%), podczas gdy kod `collector.py` używa `slippage_bps=5.0` (0.05%) i `spread_buffer_bps=3.0` (0.03%). Skutek: dok. podawał 0.56% round-trip zamiast 0.36%; cost gate 1.4% zamiast 0.9%. Naprawiono: zaktualizowano sekcje 1.2, 1.3 i tabelę referencyjną (274–275). | `TRADING_METRICS_SPEC.md` | Spójność dokumentacji z kodem | 02.04 sesja 18 |
| T-17 | **USDC pairs resource waste**: Watchlist zawierał 31 symboli USDC + 32 EUR = 63 razem. Gdy `demo_quote_ccy=EUR`, USDC symbole były zbierane przez WebSocket + klines + market_data, ale filtrowane przy wejściu do `_screen_entry_candidates`. Naprawiono: `_load_watchlist()` używa teraz `get_demo_quote_ccy()` jako domyślny quote zamiast hardkodowanego "EUR,USDC". `PORTFOLIO_QUOTES` env nadal pozwala na override. Efekt: ~50% mniej symboli w watchliście → ~50% mniej klines/market_data pisanego do DB co cykl. 181/181 OK. | `collector.py` `_load_watchlist()` | Wydajność: ~50% mniej zapisów DB w trybie EUR | 02.04 sesja 17 |
| WAL-01 | **Auto WAL checkpoint w purge**: WAL narastał do 450+ MB przy aktywnym backendzie (każdy commit → WAL, checkpoint niemożliwy przy aktywnych readers). Naprawiono: `_purge_stale_data()` (co 1h) wywołuje teraz `PRAGMA wal_checkpoint(PASSIVE)` po VACUUM — nie blokuje reads, przenosi strony WAL → main DB. Log gdy wal>500 stron. Wcześniej: ręczny TRUNCATE co kilka dni. 181/181 OK. | `collector.py` `_purge_stale_data()` | Stabilność dysku — zapobiega narastaniu WAL | 02.04 sesja 17 |

---

## HISTORIA CHECKPOINTÓW

### CHECKPOINT (1 kwietnia 2026, iteracja 4)

Bot aktywnie handluje w demo! 2 otwarte pozycje: BTCEUR + ETHEUR.
Tryb **AGGRESSIVE** — obniżone progi wejścia, max 5 pozycji.

**Iter4 — DEMO straty fix (diagnoza + 5 napraw):**
- **Diagnoza:** Bot tracił z powodu za ciasnych TP/SL (0.57-0.69% SL), za krótkiego cooldownu (120s), braku RSI filtra soft-buy, braku eskalacji po SL.
- **ATR multipliers:** stop 1.3→2.0, take 2.2→3.5, trail 1.0→1.5 (oba miejsca w collector.py)
- **SL cooldown eskalacja:** Po SL → loss_streak++, cooldown rośnie do 7200s, win_streak=0
- **TP win tracking:** Po TP → loss_streak=0, win_streak++, cooldown reset
- **Soft buy RSI filter:** Wejścia miękkie wymagają RSI < 55 (anty-overextension)
- **Profil aggressive:** confidence 0.45→0.50, score 4.0→4.5, cooldown 120→300s

**Iter3:** WAL mode + async→def threadpool fix + enabled_strategies kill-switch.
181/181 testów. 0 błędów TypeScript. 0 problemów krytycznych.

---

## ZASADA GŁÓWNA

> WLFI to osobna pozycja HOLD. Demo i rozwój tradingu na ETH/SOL/BTC/BNB działają cały czas niezależnie.

---

## 3 RÓWNOLEGŁE TORY

### TOR A — WLFI (HOLD)

- **Trzymamy.** Nie sprzedajemy wcześniej.
- **Jedyny warunek:** całość WLFI warta minimum **300 EUR.**
- Bot nie robi: SL/TP, alarmy drawdown, nowe wejścia.
- Bot robi: sprawdza wartość co cykl → alert gdy >= 300 EUR → `/confirm`.
- Stan: ~3 260 szt × ~0.09 EUR ≈ 292 EUR. Cel blisko.

### TOR B — DEMO (AKTYWNY)

- **500 EUR wirtualnych** — BTCEUR (58878 EUR) + ETHEUR (1820 EUR) otwarte.
- Bot: zbiera dane, wchodzi w pozycje auto-potwierdzone, zarządza TP/SL.
- Diagnostyka dostępna: `/api/signals/execution-trace` + widok UI "Diagnostyka".

### TOR C — REAL TRADING (czeka na kapitał)

- Przygotowany logicznie (te same zasady co demo).
- Ruszy kiedy pojawi się EUR: po sprzedaży WLFI lub po wpłacie.
- Zasady: max 1 pozycja, max 2 trade'y/dzień, /confirm na każdym.

---

## CO BOT ROBI W KODZIE — STAN PO NAPRAWACH

| Funkcja | Status |
|---------|--------|
| Demo trading enabled (DB) | ✅ |
| Auto-confirm pending orders w demo | ✅ NAPRAWIONE |
| Position sizing z max_cash_pct_per_trade | ✅ NAPRAWIONE |
| is_extreme gate — tylko bonus, nie blokada | ✅ NAPRAWIONE |
| Router nie zatruwa sygnałów w DB | ✅ NAPRAWIONE |
| Symbol tiers: CORE (BTC/ETH/SOL/BNB) + ALTCOIN | ✅ |
| HOLD tier (WLFI): blokuje nowe wejścia | ✅ |
| RSI gate permisywny (65 kupno / 35 sprzedaż) | ✅ NAPRAWIONE (31.03) |
| Tolerancja cenowa 3% do zakresu AI | ✅ |
| Heuristic ranges (List→Dict fix) | ✅ NAPRAWIONE (31.03) |
| Leakage gate min 5 trade'ów | ✅ NAPRAWIONE (31.03) |
| Expectancy gate min 5 trade'ów | ✅ NAPRAWIONE (31.03) |
| Retencja DB batch + VACUUM | ✅ NAPRAWIONE (31.03) |
| trading_aggressiveness (safe/balanced/aggressive) | ✅ NOWE (01.04) |
| max_open_positions = 5 (aggressive) | ✅ NOWE (01.04) |
| KANDYDAT_DO_WEJŚCIA / WEJŚCIE_AKTYWNE UI labels | ✅ NOWE (01.04) |
| Dynamiczne progi best-opportunity z profilu | ✅ NOWE (01.04) |
| Telegram idle alert co 30 min | ✅ NOWE (01.04) |
| RuntimeSetting description crash fix | ✅ NAPRAWIONE (01.04) |
| enabled_strategies kill-switch w collectorze | ✅ NOWE (01.04) |
| strategy_name=default w DecisionTrace | ✅ NOWE (01.04) |
| Konsolidacja 13 plików MD → docs/archive/ | ✅ NOWE (01.04) |
| titleOverride "Market" → "Wykres rynku" | ✅ NOWE (01.04) |
| ATR stop 1.3→2.0, take 2.2→3.5, trail 1.0→1.5 | ✅ NAPRAWIONE (01.04 iter4) |
| SL cooldown eskalacja (loss_streak→7200s) | ✅ NOWE (01.04 iter4) |
| TP win tracking (loss_streak=0, win_streak++) | ✅ NOWE (01.04 iter4) |
| Soft buy RSI<55 filter (anty-overextension) | ✅ NOWE (01.04 iter4) |
| Profil aggressive: conf 0.50, score 4.5, cd 300s | ✅ NAPRAWIONE (01.04 iter4) |
| execution-trace endpoint | ✅ NOWE |
| UI panel Diagnostyka | ✅ NOWE |

---

## OTWARTE ZADANIA

| ID | Zadanie | Priorytet |
|----|---------|-----------|
| B | Unifikacja logiki kolektor↔UI (final-decisions) | ŚREDNI |
| - | ETAP F: pełny test kontrolowany (czekamy na 1 cykl TP/SL) | INFO |

---

## CZEGO NIE ROBIMY

- Nie dodajemy nowych modułów
- Nie ruszamy governance/policy/worker/console
- Nie mieszamy WLFI z demo/tradingiem
- Nie panikujemy przy spadkach WLFI

---

## CHECKPOINT (sesja 2 — pełna spójność frontendu API)

### Co zrobiono
- Przepisano hook `useFetch` w `MainContent.tsx`: URL budowany lazily w `useEffect`, prawdziwe komunikaty błędów (HTTP 404, brak połączenia, itp.)
- Podmieniono wszystkie 31 wywołań `useFetch` z `${API_BASE}/api/...` → `/api/...` (ścieżka relatywna)
- Naprawiono bezpośrednie wywołania `fetch('/api/...')` i `new URL('/api/...')` w handlerach akcji → `${getApiBase()}/api/...`
- `API_BASE` całkowicie wyeliminowane z frontendu: `EquityCurve.tsx`, `OpenOrders.tsx`, `Topbar.tsx`, `DecisionsRiskPanel.tsx`, `MainContent.tsx`
- Dodano brakujący komponent `RiskView` (sidebar miał link do widoku `risk`, ale handler nie istniał)
- `DecisionsView`: EUR zamiast `$`, kolorowanie PnL (zielony/czerwony)
- TypeScript: **brak błędów**, testy: **174/174 PASSED**

### Wynik
Portal w pełni spójny. Wszystkie widoki pobierają dane przez `getApiBase()`. Telefon/LAN działa.

### Przetestuj na telefonie
Otwórz `http://192.168.0.109:3000` i sprawdź: **Ryzyko, Rynki, Portfel, Strategie, AI Sygnały, Backtest**

---

## OSTATNI CHECKPOINT (26 marca 2026 — weryfikacja portalu)

### Co zrobiono
- Przediagnozowano wszystkie endpointy API używane przez frontend (20 URL-i).
- Wszystkie endpointy zwracają 200 i realne dane z bazy.
- Naprawiono `PositionsTable.tsx`:
  - `data.positions` → `data.data` (poprawne pole z API)
  - `API_BASE` → `getApiBase()` (bezpieczne dla LAN/telefonu)
  - `pnl` → `unrealized_pnl` (poprawna nazwa pola)
  - Usunięto twardo wpisane mocki w USD — teraz pokazuje realne pozycje DEMO
  - EUR zamiast $, `fmtPrice()` z dynamic precision dla małych kwot
- Naprawiono `positions.py` (`_analyze_position` + summary):
  - `round(value, 2)` → dynamiczna precyzja (6 dla  < 1 EUR, 4 dla < 100 EUR, 2 dla reszty)
  - Wyniki analizy WLFI (0.01 szt × 0.085 EUR) teraz pokazują 0.000849 EUR zamiast 0.0
- Testy: **174/174 PASSED**, TypeScript: brak błędów.

### Aktualny stan widoków portalu
| Widok | Status |
|-------|--------|
| Panel (Dashboard) | ✅ dane live, pozycje poprawne |
| Decyzje (position-analysis) | ✅ karta decyzyjna WLFI z powodami |
| Handel (trade-desk) | ✅ zlecenia + pozycje |
| Portfel | ✅ |
| AI Sygnały | ✅ |
| Rynki | ✅ |

### Następny krok (do wyboru)
1. Dopracować widok `PositionAnalysisView` — WLFI ma 0.01 szt; podsumowanie portfela powinno uwzględniać REAL (3260 szt WLFI).
2. Dodać nową demo-pozycję BTCEUR z aktualną ceną zakupu i sprawdzić, czy analiza sugeruje decyzję poprawnie.
3. Poprawić DashboardV2View — tabela "Positions" ma angielskie nagłówki (`Symbol`, `Side`, `Qty`).

