# PROJECT_AUDIT_MASTER.md — RLdC Trading BOT
## AKTUALIZACJA: SESJA T-110 RECONCILE + SYSTEM DIAGNOSTICS + TELEGRAM UX (21-04-2026)

### STATUS
- zamknięto wdrożenie T-110 w warstwach: reconcile, diagnostics API, telegram operator UX, execution guard
- testy dedykowane T-110: **7/7 PASS**
- full suite: **404 passed, 55 failed** (otwarte jako T-111 — smoke/config snapshot + runtime_settings init)

### ZMIANY W KODZIE
1. `backend/database.py`
	- dodane modele audytu reconcile: `ReconciliationRun`, `ReconciliationEvent`, `ManualTradeDetection`
	- migracja online przez `_ensure_schema`; `reset_database` rozszerzony o nowe tabele
2. `backend/portfolio_reconcile.py` (NEW)
	- source of truth = Binance
	- reconcile pending/positions/balances
	- wykrywanie manualnych transakcji i automatyczna naprawa DB
	- audit trail + opcjonalny Telegram notify
3. `backend/routers/system.py` (NEW)
	- diagnostyka execution/reconcile/universe/ai/telegram/db-health/full-status
	- endpoint ręczny trigger: `POST /api/system/reconcile`
4. `backend/app.py`
	- rejestracja routera system
	- startup reconcile thread (live)
5. `backend/collector.py`
	- reconcile per-cycle
	- globalny execution kill switch (`execution_enabled=false`) z trace `execution_globally_disabled`
6. `telegram_bot/bot.py`
	- nowe komendy operatorskie i diagnostyczne: `/pending`, `/trade`, `/incident`, `/close_incident`, `/reconcile`, `/health`, `/execution`, `/universe`, `/quote`
	- disambiguacja `/confirm` i `/reject` gdy operator poda `incident_id` zamiast `trade_id`
7. testy
	- nowe pliki: `tests/test_reconcile.py`, `tests/test_telegram_disambiguation.py`, `tests/test_execution_guard.py`

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: mniej utraconych wejść/wyjść przez rozjazdy DB↔Binance po manualnych transakcjach
- **Ryzyko**: niższe ryzyko błędu operatorskiego (trade vs incident) i niezamierzonego execution przy globalnym disable
- **Koszt**: niższy koszt operacyjny (mniej ręcznych interwencji i mniej „ślepych” diagnoz)
- **Stabilność**: wyższa obserwowalność systemu i deterministyczny audit trail reconcile

## AKTUALIZACJA: SESJA T-109 EXECUTION GATES + TELEGRAM PENDING-ID HARDENING (21-04-2026)

### STATUS
- zamknięto **T-109**: execution gating i parser/operator flow dla pending execution
- potwierdzono brak regresji: `test_control_center + test_smoke` **257/257**

### ZMIANY W KODZIE
1. `backend/collector.py`
	- LIVE execution gate czyta runtime config (`allow_live_trading`, `trading_mode`) zamiast samego process env
	- nowa blokada: `p_mode=live` + `trading_mode!=live` => reject `live_execution_blocked_wrong_trading_mode`
2. `backend/routers/control.py`
	- naprawiony krytyczny status typo `PENDING_CREATED_CREATED` -> `PENDING_CREATED` w `sell_weakest`
3. `telegram_bot/bot.py`
	- `/confirm` i `/reject` walidują `PendingOrder.id` w aktywnym trybie (`PendingOrder.mode == TRADING_MODE`)
	- canonical confirm status: `PENDING_CONFIRMED`
	- `/status` liczy pending wg canonical active statuses

### RCA
- niespójność między runtime config a execution gate powodowała ryzyko wykonania LIVE poza zamierzonym trybem globalnym
- literówka statusu pending tworzyła rekordy niewykonywalne przez collector
- Telegram potwierdzał/odrzucał pending bez ograniczenia do aktywnego trybu, co zwiększało ryzyko błędnej operacji operatorskiej

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: mniej utraconych okazji przez martwe pending statusy
- **Ryzyko**: mniejsze ryzyko przypadkowego LIVE execution przy niezgodnym globalnym mode
- **Koszt**: mniej błędnych operacji i mniej noise operacyjnego
- **Stabilność**: spójniejsza ścieżka PendingOrder ID w Telegram ↔ execution

## AKTUALIZACJA: SESJA T-105 LIVE STABILITY HARDENING (20-04-2026)

### STATUS
- zamknięto **T-105**: hardening execution/sync pod duplikaty i qty<=0
- potwierdzono brak regresji: smoke **220/220**

### ZMIANY W KODZIE
1. `backend/collector.py`
	- dodane ACTIVE/EXECUTABLE pending statuses jako wspólna definicja
	- lock inflight per symbol/side/mode dla execution confirmed pending
	- twarda blokada `qty<=0` przed próbą `place_order`
	- deduplikacja `_create_pending_order` + idempotency token
	- sync guard i reserved-cash liczą pełne pending inflight (w tym `EXCHANGE_SUBMITTED`)
	- poprawiony LIVE screening dla `QUOTE_CURRENCY_MODE=BOTH`
2. `backend/routers/control.py`
	- deduplikacja manualnych BUY/SELL pending
	- FORCE BUY nie pozostawia `qty<=0` (placeholder > 0 + preflight execution)
3. `backend/routers/signals.py`
	- ujednolicone ACTIVE pending statuses w diagnostyce (`final-decisions`, `execution-trace`, `buy-trace`)
4. testy
	- nowe regresje: duplicate force pending, qty non-positive block

### RCA
- główna przyczyna spamu i rozjazdów: brak centralnego mechanizmu deduplikacji pending oraz niespójne listy statusów aktywnych między execution, sync i diagnostyką.
- wtórny problem: ścieżki force/manual mogły dopuścić pending wymagający dopiero późniejszego ratowania qty.

### WALIDACJA
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_live_execution_cash_management.py tests/test_control_center.py -q` → **49 passed**
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → **220 passed**

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: mniej utraconych cykli przez duplikaty i lock contention
- **Ryzyko**: niższe ryzyko overtradingu i niekontrolowanych wielokrotnych wejść na ten sam symbol
- **Koszt**: mniej niepotrzebnych prób execution i mniej false alertów sync
- **Stabilność**: wyższa spójność DB↔Binance↔API statusów

## AKTUALIZACJA: SESJA T-104 EXECUTION-CASH-HARDENING (20-04-2026)

### STATUS
- zamknięto **T-104**: naprawiona ścieżka execution/cash-management dla LIVE (confirmed pending + auto-confirmed)
- wdrożono minimalny zakup `>= 60 EUR` z automatycznym przeliczeniem na quote i obsługą EUR→USDC

### ZMIANY W KODZIE
1. `backend/runtime_settings.py`
	- nowy centralny runtime key `min_buy_eur` (default `60.0`)
2. `backend/collector.py`
	- preflight LIVE BUY: min_buy_eur, kurs EUR→USDC, auto-konwersja, walidacja salda quote, normalizacja qty i minNotional po rounding
	- reason codes: `cash_convert_failed`, `cash_insufficient_after_conversion_attempt`, `execution_rejected_by_exchange`, `temporary_execution_error`
	- pełne logowanie kroków execution i aktualizacji statusu pending
	- blokada `TEST*` symboli w LIVE execution + usuwanie z watchlisty live
	- fix sortowania `CONFIRMED` pending (deterministyczny timestamp)
3. `backend/quote_currency.py`
	- helpery `resolve_eur_usdc_rate`, `convert_eur_amount_to_quote`, `is_test_symbol`
4. `backend/routers/signals.py`
	- `ENTRY_BLOCKED_NO_CASH` uwzględnia `min_buy_eur`, kurs i możliwość auto-konwersji EUR→USDC
	- wycięcie `TEST*` z universe sygnałów/entry-readiness
5. `backend/routers/control.py`
	- manual BUY sizing respektuje minimalny zakup 60 EUR (lub równowartość USDC)
	- blokada symboli testowych w LIVE dla komend BUY
6. `backend/routers/account.py`
	- temporary execution/cash errors jako non-blocker (bez trwałego freeze)
	- etykiety nowych reason codes w statusie pipeline
7. testy
	- rozszerzono `tests/test_quote_currency.py`
	- dodano `tests/test_live_execution_cash_management.py`

### RCA
- przyczyna problemu: execution BUY LIVE nie miał centralnego preflightu zależnego od waluty quote i minimalnej wartości transakcji w EUR, przez co CONFIRMED pending mogły kończyć się rejectem lub fałszywym brakiem gotówki mimo dostępnego EUR.
- dodatkowo brakowało spójnego mapowania temporary errors na stan niekrytyczny, co powodowało efekt „pseudo-freeze” w diagnostyce.

### WALIDACJA
- `PYTHONPATH=. DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_quote_currency.py tests/test_live_execution_cash_management.py tests/test_control_center.py -q` → **71 passed**
- `PYTHONPATH=. DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → **220 passed**

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: mniej utraconych wejść BUY na parach USDC przy saldzie EUR
- **Ryzyko**: niższe ryzyko fałszywych wejść poniżej minimum i błędów notional/precision
- **Koszt**: wyższa kontrola kosztowa przez wymuszenie realnego minimum i bufora konwersji
- **Stabilność**: deterministyczna ścieżka confirmed pending -> conversion -> BUY -> status update

## AKTUALIZACJA: SESJA T-103 TELEGRAM-PARSER-FIX (19-04-2026)

### STATUS
- zamknięto **T-103**: parser komend Telegram/control działa w modelu trading-first
- usunięto kolizję symboli typu `SOLUSDC` z parserem konfiguracji quote-currency

### ZMIANY W KODZIE
1. `backend/routers/control.py`
	- dodano `_parse_command_intent(...)` z jednolitym wynikiem parsera
	- wdrożono priorytet: BUY/SELL/FORCE → symbol → config
	- dodano `sell_symbol` i flow `MANUAL` / `MANUAL_FORCE`
	- dodano `set_aggressive_mode` dla komendy `tryb agresywny`
	- rozszerzono logi o `parser_decision` i `execution_path`
2. `backend/quote_currency.py`
	- parser quote-currency ignoruje komendy tradingowe i pełne pary (`*USDC`, `*EUR`)
	- usunięto nadmiernie szerokie dopasowania fraz
3. `telegram_bot/bot.py`
	- odpowiedzi Telegram mapowane na nowe execution path (`manual_*_queued`)
4. `tests/test_control_center.py`
	- testy dla komend kup/sprzedaj/wymuś + `tryb agresywny`

### RCA
- źródłem błędu była niespójna klasyfikacja intencji: ścieżka config mogła zostać uruchomiona dla tekstów tradingowych zawierających tokeny quote.
- brak centralnego parsera typu komendy powodował konflikt między routingiem tradingu i konfiguracji.

### WALIDACJA
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_control_center.py -q` → **36 passed**
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → **220 passed**

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: wyższa skuteczność manualnych komend wejścia/wyjścia
- **Ryzyko**: kontrolowane; FORCE omija część filtrów wejścia, ale pozostaje pod risk/min_notional/kill-switch
- **Koszt**: neutralny
- **Stabilność**: wyższa spójność parsera i odpowiedzi Telegram

## AKTUALIZACJA: SESJA T-102 ENTRY-UNBLOCK-WAVE (19-04-2026)

### STATUS
- zamknięto **T-102**: usunięto część blokad decyzyjnych prowadzących do stanu 0 wejść
- wdrożono fallback relaksujący wejście i naprawiono parser komendy force buy

### ZMIANY W KODZIE
1. `backend/routers/control.py`
	- parser komend BUY obsługuje frazy `wymuś kup ...` jako `buy_symbol`
2. `backend/collector.py`
	- dodano tryb `relaxed_entry_mode` po N cyklach bez BUY i bez otwartych pozycji
	- relax obniża progi confidence/entry-score i poszerza buy-zone tolerance
	- rozszerzono universe do top-N symboli ze skanera (`collector_scanner_top_n`)
3. `backend/routers/signals.py`
	- buy-trace używa `buy_zone_tolerance_pct` (fallback do `price_tolerance`)
4. `backend/runtime_settings.py`
	- poluzowano profile balanced/aggressive i default `demo_min_entry_score`

### RCA
- bot odrzucał 100% kandydatów BUY głównie przez confidence/entry-score i zbyt wąskie strefy wejścia.
- dodatkowo część komend force BUY mogła być błędnie klasyfikowana jako chat, jeśli zaczynały się od `wymuś kup`.

### WALIDACJA
- `.venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: dodatni potencjał (więcej dopuszczonych setupów BUY)
- **Ryzyko**: umiarkowanie wyższe w trybie relax; ograniczone warunkiem aktywacji (brak wejść przez kilka cykli)
- **Koszt**: nieznacznie wyższy koszt obliczeń przez szerszy universe
- **Stabilność**: lepsza przewidywalność komend force i spójniejsza ścieżka decyzyjna

## AKTUALIZACJA: SESJA T-101 ENTRY-ENGINE-ACTIVATION (19-04-2026)

### STATUS
- zamknięto **T-101**: usunięto kluczowe ograniczenie "watchlist-only" w collectorze
- dodano pełną diagnostykę powodów odrzucenia BUY oraz testowy debug override risk

### ZMIANY W KODZIE
1. `backend/collector.py`
	- `_screen_entry_candidates(...)` buduje universe z watchlist + `market_scanner` (best/opportunities/rejected)
	- uzupełnia brakujące zakresy AI heurystyką dla symboli spoza watchlisty
	- fallback sygnału live on-demand (`_build_live_signals`) gdy brak `Signal` w DB
	- logi operacyjne `WHY_NOT_BUY ...` i `BUY_ALLOWED ...`
2. `backend/risk.py`
	- dodano ENV debug: `RISK_FORCE_ALLOW_ENTRY_DEBUG=true`
	- dla BUY: `allowed=True`, `action=force_allow_debug`, `reason_code=forced_entry_debug_override`

### RCA
- system był technicznie zdrowy, ale decyzje wejścia były zbyt często odcinane przez połączenie:
	- statycznego universe (watchlist-only),
	- braków sygnałów/range poza watchlistą,
	- słabej widoczności "dlaczego BUY odrzucony".

### WALIDACJA
- `.venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: potencjalnie dodatni (większe pokrycie rynku i szybsze znajdowanie kandydatów BUY)
- **Ryzyko**: kontrolowane (debug override wymaga jawnego ENV i jest domyślnie OFF)
- **Koszt**: lekko wyższy koszt CPU/API przez rozszerzony screening
- **Stabilność**: znacząco lepsza diagnostyka decyzji (WHY_NOT_BUY)

## AKTUALIZACJA: SESJA T-100 LIVE-KLINES-FETCH-ON-DEMAND (19-04-2026)

### STATUS
- zamknięto **T-100**: stale klines w live sygnałach nie są już obsługiwane wyłącznie przez skip
- dla stale symboli wdrożono bezpieczny refresh z Binance API przed decyzją o odrzuceniu

### ZMIANY W KODZIE
1. `backend/routers/signals.py`
	- dodano `_fetch_and_store_klines_ondemand(db, symbol, timeframe="1h", limit=120)`
	- helper pobiera klines przez `get_binance_client().get_klines(...)` i zapisuje brakujące rekordy `Kline` do DB
	- w `_build_live_signals(...)` przy `kline_age_h > MAX_KLINE_AGE_HOURS` wykonuje się refresh-on-demand
	- jeśli refresh się nie powiedzie, pozostaje bezpieczny skip symbolu (brak analizy na danych przestarzałych)

### RCA
- T-93 poprawnie blokował analizę stale klines, ale strategia "tylko skip" odcinała symbole z przeterminowanym lokalnym cache, nawet gdy Binance miał świeże dane.
- skutkiem była utrata potencjalnych sygnałów live dla części universe.

### WALIDACJA
- `.venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- brak nowych regresji funkcjonalnych w smoke.

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: potencjalnie dodatni (więcej symboli ma szansę przejść przez pełną analizę live)
- **Ryzyko**: kontrolowane (wciąż brak sygnału, gdy refresh nieudany; brak analizy na stale danych)
- **Koszt**: niewielki wzrost kosztu API tylko dla stale symboli
- **Stabilność**: wyższa odporność na luki w lokalnym cache klines

## AKTUALIZACJA: SESJA T-99 UTC-DEPRECATION-FIX (19-04-2026)

### STATUS
- zamknięto **T-99**: usunięto deprecację `datetime.utcnow()` w endpointach health
- smoke pozostaje zielony po zmianie

### ZMIANY W KODZIE
1. `backend/app.py`
	- zastąpiono `datetime.utcnow().isoformat() + "Z"` przez `datetime.now(timezone.utc).isoformat()`
	- dodano import `datetime, timezone`

### RCA
- ostrzeżenie deprecacji w Python 3.12 pochodziło z pola `timestamp` w `GET /health`.
- stary zapis był naive-UTC i zgłaszał warning podczas smoke.

### WALIDACJA
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- warning `datetime.utcnow()` usunięty; pozostał tylko warning TLS (`InsecureRequestWarning`) niezwiązany z timestamp.

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: pośrednio dodatni (czytelniejsze sygnały jakości pipeline)
- **Ryzyko**: niższe ryzyko przyszłych regresji po aktualizacjach Pythona
- **Koszt**: neutralny
- **Stabilność**: wyższa zgodność runtime z aktualnym standardem UTC

## AKTUALIZACJA: SESJA T-98 AUTH-ENV-REGRESSION-FIX (19-04-2026)

### STATUS
- zamknięto **T-98**: usunięto regresję 401/422 w smoke wynikającą z nadpisywania env testowego przez `.env`
- pipeline testowy wrócił do pełnej zieleni dla smoke

### ZMIANY W KODZIE
1. `backend/app.py`
	- zmieniono `load_dotenv(dotenv_path=_ENV_PATH, override=True)` na `override=False`
	- dodano komentarz operacyjny o ochronie env ustawianego przez środowisko/testy

### RCA
- testy ustawiają `ADMIN_TOKEN=""` przed importem aplikacji, ale bootstrap backendu nadpisywał to przez `.env` (`override=True`), aktywując auth i limity runtime spoza scenariusza testowego.
- skutkiem była kaskada błędów 401 na endpointach control/orders/positions oraz wtórne 422/KeyError w smoke.

### WALIDACJA
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q --tb=short` → **220 passed**

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: pośrednio dodatni (szybsza i pewniejsza iteracja zmian bez fałszywych regresji)
- **Ryzyko**: niższe ryzyko błędnych decyzji na bazie przekłamanych wyników testów
- **Koszt**: niższy koszt operacyjny debugowania (eliminacja masowych false-fail)
- **Stabilność**: spójny bootstrap konfiguracji między testami i runtime

## AKTUALIZACJA: SESJA T-97 TELEGRAM-SINGLETON-SYSTEMD (19-04-2026)

### STATUS
- zamknięto **T-97**: usunięto konflikt `service + local duplicate` dla `telegram_bot.bot`
- runtime po cleanupie raportuje pojedynczy proces Telegram zgodny z `rldc-telegram.service MainPID`

### ZMIANY W KODZIE
1. `scripts/start_dev.sh`
	- dodano ścieżkę preferującą systemd (`rldc-telegram.service`) gdy service jest `enabled`,
	- zablokowano lokalny spawn Telegram w tej ścieżce,
	- dodano cleanup lokalnych PID-ów niezgodnych z `MainPID` serwisu,
	- `telegram.pid` synchronizowany z PID serwisu.
2. `scripts/stop_dev.sh`
	- dodano jawne zatrzymanie `rldc-telegram.service` przed fallback `pkill`.
3. `scripts/status_dev.sh`
	- dodano diagnostykę źródła procesu (systemd PID),
	- warning duplikacji rozróżnia przypadek `service + lokalny`.

### WALIDACJA
- `bash -n scripts/start_dev.sh scripts/stop_dev.sh scripts/status_dev.sh` → PASS
- `status_dev.sh` → Telegram: DZIAŁA, źródło `systemd rldc-telegram.service`
- `pgrep -af "telegram_bot.bot"` → 1 proces (PID serwisu)

### WPŁYW (ZYSK / RYZYKO / KOSZT / STABILNOŚĆ)
- **Zysk**: pośredni wzrost jakości operacyjnej (brak podwójnych odpowiedzi/akcji Telegram)
- **Ryzyko**: redukcja ryzyka konfliktu komend i niespójnego stanu runtime
- **Koszt**: brak dodatkowych kosztów transakcyjnych; mniejszy koszt operacyjny (mniej ręcznych interwencji)
- **Stabilność**: wyższa przewidywalność start/stop/status przy aktywnym systemd

## AKTUALIZACJA: SESJA T-96 CONFIDENCE-RUNTIME-FIX (19-04-2026)

### Co zmieniono
- zamknięto **T-96**: krytyczny fix blokerów `signal_confidence_too_low` przy degradacji AI
- `backend/collector.py`:
	- dodano fallback confidence liczony z indikatorów (RSI/EMA/volume/momentum)
	- dodano detekcję runtime AI failure (`_is_ai_failed_runtime`)
	- dodano dynamiczny próg confidence: **0.4 (AI fallback)** / **0.6 (AI OK)**
	- dodano debug operacyjny: `CONFIDENCE`, `AI_USED`, `AI_FAILED`
	- `avg_confidence` w heartbeat nie jest już stałym 0.0 (fallback do średniej z `Signal`)
- `backend/analysis.py`:
	- AI ranges dostają jawny payload rynkowy (`price`, `candles`, `rsi`, `ema20`, `ema50`, `volume`, `trend`)
	- insighty zawierają teraz `candles` (30 close) i `trend`
- `backend/routers/control.py`:
	- AI chat dostaje realny kontekst collectora/sygnałów (`market_scan_snapshot`, `top_opportunities`, status providera)

### Co przetestowano
- `python -m pytest tests/test_confidence_runtime_fix.py -q` → **4 passed**
- `python -m pytest tests/test_control_center.py tests/test_smoke.py -q` → **246 passed**
- runtime sanity po zmianie:
	- backend/frontend/telegram: UP
	- `GET /api/signals/entry-readiness` odpowiada poprawnie; obecna główna blokada wejść to nadal `ENTRY_BLOCKED_DATA_TOO_OLD`

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: dodatni potencjał — mniej fałszywych odrzuceń z confidence=0 przy chwilowej degradacji AI
- Ryzyko: niższe — fallback confidence opiera się o realne wskaźniki zamiast zera
- Koszty: neutralne bezpośrednio; pośrednio niższe koszty utraconych okazji
- Stabilność: wyższa diagnostycznie (jawny provider/failure/confidence w runtime)

## AKTUALIZACJA: SESJA T-95 TELEGRAM-SINGLETON-RUNTIME (19-04-2026)

### Co zmieniono
- zamknięto **T-95**: usunięto konflikt podwójnych procesów Telegram bota
- `scripts/start_dev.sh`:
	- dodano lock równoległego uruchomienia (`flock` na `logs/dev/.start_dev.lock`)
	- dodano normalizację singletona `telegram_bot.bot` (autoczyszczenie duplikatów >1 + odświeżenie `telegram.pid` gdy proces już działa)

### Co przetestowano
- `bash -n scripts/start_dev.sh scripts/stop_dev.sh scripts/status_dev.sh` → **PASS**
- runtime restart + status: **1 proces Telegram**, backend/frontend/telegram **UP**, endpointy HTTP **200**
- `GET /api/account/trading-status?mode=live` → `trading_enabled=true`, `available_to_trade=true`, `collector_running=true`, `blockers=0`

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: pośrednio dodatni (mniej konfliktów sterowania i mniejsze ryzyko utraty okazji przez race conditions)
- Ryzyko: niższe (brak podwójnego wykonania komend Telegram)
- Koszty: neutralne
- Stabilność: wyższa deterministyczność startu runtime

## AKTUALIZACJA: SESJA T-94 COST-METRICS-WIDGETS (19-04-2026)

### Co zmieniono
- zamknięto **T-94**: dashboardowe metryki kosztowe jako stałe widgety UI
- `backend/reporting.py::performance_overview` rozszerzono o:
	- `overtrading_score`
	- `overtrading_activity_blocks`
	- `gross_to_net_retention_ratio`
	- `gross_net_gap`
	- `closed_orders`
- `web_portal/src/components/MainContent.tsx`:
	- `DashboardV2View`: stały pas KPI kosztowych (retencja brutto→netto, leakage kosztowe, overtrading score)
	- `EconomicsSubView`: rozszerzone KPI o nowe metryki kosztowe

### Co przetestowano
- `PYTHONPATH=. python3 -m pytest tests/test_reporting_metrics.py -q --tb=short` → **6 passed**
- `PYTHONPATH=. python3 -m pytest tests/test_reporting_metrics.py tests/test_signals_router.py -q --tb=short` → **8 passed**
- `npm --prefix web_portal run build` → **PASS**

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: pośrednio dodatni (szybsza identyfikacja degradacji brutto→netto)
- Ryzyko: niższe ryzyko overtradingu dzięki stałej widoczności `overtrading_score`
- Koszty: bezpośrednio lepszy monitoring fee leakage i ubytku PnL po kosztach
- Stabilność: wyższa spójność backend↔frontend dla metryk ekonomicznych

## AKTUALIZACJA: SESJA T-93 STALE-KLINES-GUARD (19-04-2026)

### Co zmieniono
- zamknięto **T-93** w `backend/routers/signals.py::_build_live_signals`
- dodano guard świeżości klines 1h (`MAX_KLINE_AGE_HOURS`, domyślnie 4h)
- symbole z przeterminowanymi klines są pomijane przed analizą wskaźnikową, co eliminuje misleading live fallback dla orphaned symboli (ARBUSDC/EGLDUSDC)

### Co przetestowano
- `PYTHONPATH=. python3 -m pytest tests/test_signals_router.py tests/test_market_scanner.py -q --tb=short` → **43 passed**
- runtime sanity: `entry-readiness?mode=live` nie zwraca ARB/EGLD z live_analysis opartą o stare klines

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: pośrednio dodatni (mniej błędnych wskazań diagnostycznych dla wejść)
- Ryzyko: niższe ryzyko podejmowania decyzji na przeterminowanych danych
- Koszty: neutralne
- Stabilność: wyższa spójność jakości danych między fallback i gate'ami staleness

## AKTUALIZACJA: SESJA KILL-SWITCH-FEE-CORRUPTION-FIX (17-04-2026)

### Co zmieniono
- **BUG KRYTYCZNY**: CostLedger order #81 (BNBEUR SELL) miał taker_fee actual=30.73 EUR (zamiast 0.068 EUR), co powodowało `daily_net_pnl=-29 EUR` → `kill_switch_triggered=True` → wszystkie wejścia LIVE zablokowane od ~16.04 wieczorem
- naprawiono dane: CostLedger #81 actual 30.73→0.068 EUR; Order #81 net_pnl -28.98→+1.68 EUR
- naprawiono `backend/collector.py _convert_fee_to_quote`: dodano sanity cap 2% notional; przekroczenie powoduje log WARNING + fallback do szacunkowej prowizji; dodano parametr `notional`
- naprawiono `backend/accounting.py compute_risk_snapshot` (LIVE): `initial_balance` teraz używa `AccountSnapshot.equity` (total konto ~340 EUR) zamiast `total_exposure` (tylko aktywne pozycje ~68 EUR) — próg kill_switch 3% teraz ~10 EUR zamiast 2 EUR
- naprawiono `compute_risk_snapshot`: filtruje tylko pozycje `exit_reason_code IS NULL AND quantity > 0` — `open_positions_count` zmienił się z 4 na 1 (eliminuje stale zapisy z qty=0)
- naprawiono `backend/routers/signals.py entry-readiness`: kill_switch sprawdza OBIE ścieżki: `config.kill_switch_active` OR `risk_snapshot.kill_switch_triggered` — poprzednio entry-readiness pokazywał FALSE mimo że collector blokował (niespójność)

### Co przetestowano
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/ -q --tb=short` → **262 passed**
- `curl /api/signals/entry-readiness?mode=live` → `can_enter_now: true, kill_switch_active: false, open_positions: 1`
- `bash scripts/status_dev.sh` → backend/frontend/telegram UP

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: bezpośrednio pozytywny — bot przestał być zablokowany przez fałszywy kill switch, może ponownie wchodzić w pozycje
- Ryzyko: niższe — kill switch threshold teraz bazuje na pełnym kapitale (340 EUR) a nie tylko otwartych pozycjach; cap prowizji 2% chroni przed kolejnymi koruplami danych
- Koszty: corrected daily net_pnl = +1.53 EUR (zamiast -29 EUR); eliminuje błędne liczenie fee leakage
- Stabilność: wyższa — entry-readiness i collector są teraz spójne w ocenie kill switch

## AKTUALIZACJA: SESJA LIVE-RUNTIME-UNSTICK-AND-RECONCILE (16-04-2026)

### Co zmieniono
- wykonano twardy audyt runtime: aktywne procesy LIVE to backend `uvicorn backend.app:app` i `telegram_bot.bot`, oba uruchomione z bieżącego repozytorium
- naprawiono pętlę rejected SELL / fake Telegram activity w `backend/collector.py`:
	- partial SELL nie ustawia już `position.exit_reason_code = pending_confirmed_execution`
	- partial TP respektuje `min_order_notional` i nie tworzy mikrozleceń odrzucanych przez Binance `NOTIONAL`
	- rejected SELL odblokowuje pozycję i resynchronizuje `quantity` z Binance; jeśli aktywo nie istnieje już na giełdzie, rekord DB jest zamykany
	- slot counting ignoruje pozycje będące w trakcie zamknięcia
	- alerty Telegram dla trailing stop są deduplikowane
- naprawiono sync monitor DB↔Binance:
	- BNB jest liczone w mapie realnych aktywów, więc nie generuje już fałszywego mismatch
	- pozycje LIVE nieistniejące już na Binance są auto-zamykane zamiast tylko raportowane
- wykonano ręczny cleanup `trading_bot.db` zgodny z realnym stanem Binance:
	- zamknięto martwe rekordy `ETHEUR`, `SHIBEUR`, `SOLEUR`
	- pozostawiono tylko realne pozycje LIVE: `BTCEUR`, `BNBEUR` (+ dust `WLFI` jako read-only residual)

### Co przetestowano
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py --tb=short -q` -> **220 passed**
- restart runtime: `./scripts/stop_dev.sh && ./scripts/start_dev.sh` -> backend/frontend/telegram **UP**
- `GET /api/signals/entry-readiness?mode=live` -> `can_enter_now=true`, `open_positions=2`, `max_open_positions=5`, `cash_available=203.8`
- `GET /api/positions/analysis?mode=live` -> tylko 2 realne pozycje LIVE + dust residual

### Wplyw na zysk/ryzyko/koszty/stabilnosc
- Zysk: dodatni — wolne EUR wróciło do obiegu, bo sloty przestały być blokowane przez martwe pozycje
- Ryzyko: niższe — bot nie próbuje już w nieskończoność sprzedawać aktywów, których nie ma na Binance
- Koszty: niższe — koniec odrzuconych SELL i fałszywych prób wyjścia poniżej `min_notional`
- Stabilnosc: wyższa — WWW/Telegram/DB są zsynchronizowane z realnym stanem giełdy

## AKTUALIZACJA: SESJA CONTROL-CENTER-IP-AI-TELEGRAM-WEB (16-04-2026)

### Co zmieniono
- dodano centralny orchestrator AI multi-provider: `backend/ai_orchestrator.py`
	- local/free-first routing (local -> groq/gemini -> openai -> heuristic)
	- diagnostyka paid/unpaid dla OpenAI i maskowanie sekretow
	- status task-routing dla analysis/prediction/chat/command parsing
- rozbudowano backend API:
	- `GET /api/account/ip-diagnostics` (local IP, public egress IP, domain DNS, cloudflare/proxy/tunnel classification)
	- `GET /api/account/ai-orchestrator-status` (pelna diagnostyka primary/fallback/providers/task routing)
	- `GET/POST /api/control/env*` (get/set/diff/backup/rollback/reload) z whitelista i audit logiem
	- `POST /api/control/command/execute` (shared command brain dla Telegram + Web)
	- `POST /api/control/terminal/exec` + `GET /api/control/terminal/permissions` (guarded online terminal)
- przepieto Telegram na wspolna warstwe sterowania:
	- `/ip` korzysta z `ip-diagnostics` zamiast samego DNS extraction
	- `/ai` korzysta z `ai-orchestrator-status`
	- `/status` rozszerzony o collector/ws/exchange/ai/fallback/open/pending/last error/governance
	- `/portfolio` formatowanie PnL (wartosc + procent), ranking, best/worst, green/red count
	- dodano `/env` i `/config` (env/config manager)
	- dodano natural language chat -> shared command brain (jedno zrodlo prawdy dla Telegram i Web)
- rozbudowano web diagnostyke: `DiagTerminalTab` ma teraz panel AI command/chat + online terminal execute (backend-guarded)
- dodano nowe testy: `tests/test_control_center.py`

### Co przetestowano
- `python3 -m pytest tests/test_control_center.py -q --tb=short` -> **6 passed**
- `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**
- `cd web_portal && npm run build` -> **PASS**

### Wplyw na zysk/ryzyko/koszty/stabilnosc
- Zysk: szybsze i bardziej trafne decyzje operacyjne (jedna warstwa command brain dla Telegram/Web)
- Ryzyko: obnizone ryzyko blind spots diagnostycznych (`/ip`, `/ai`) i single point of failure OpenAI
- Koszty: local/free-first policy redukuje zaleznosc od platnych providerow
- Stabilnosc: wyzsza kontrola runtime przez bezpieczne `/env` i guarded terminal + audit trail

## AKTUALIZACJA: SESJA CONTROL-DOCS-ROOT-RESTORE (14-04-2026)

### Co zmieniono
- odtworzono wymagane pliki kontrolne w katalogu glownym projektu:
	- `ARCHITECTURE_DECISIONS.md`
	- `TRADING_METRICS_SPEC.md`
	- `STRATEGY_RULES.md`
	- `CURRENT_STATE.md`
	- `OPEN_GAPS.md`
	- `CHANGELOG_LIVE.md`
- zsynchronizowano tresc z aktualnym stanem runtime (build root PASS, smoke 220 passed, endpointy LIVE 200)
- pozostawiono archiwalna historie zmian w `docs/archive/CHANGELOG_LIVE.md`

### Co przetestowano
- `npm run build` (root) -> PASS
- `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**

### Wplyw na zysk/ryzyko/koszty/stabilnosc
- Zysk: posrednio dodatni (szybszy i bardziej powtarzalny onboarding/audyt)
- Ryzyko: nizsze ryzyko blednych decyzji wynikajacych z brakow dokumentacji kontrolnej
- Koszty: neutralne
- Stabilnosc: wyzsza spojnosc procesu operacyjnego i audytowego

## AKTUALIZACJA: SESJA RUNTIME-AUDIT-AND-FIX (14-04-2026)

### Co zmieniono
- wykonano audyt runtime usług przez `scripts/status_dev.sh` i sanity-check kluczowych endpointów LIVE:
	- backend/frontend/telegram: UP
	- `/health`, `/api/account/system-status`, `/api/account/trading-status?mode=live`, `/api/account/runtime-activity?mode=live`, `/api/account/capital-snapshot?mode=live`, `/api/signals/entry-readiness?mode=live`, `/api/signals/execution-trace?mode=live` -> 200
- zidentyfikowano i naprawiono bloker operacyjny narzędziowy:
	- rootowe `npm run build` kończyło się `Missing script: "build"` z powodu braku sekcji `scripts` w `package.json`
	- dodano skrypty delegujące do `web_portal` (`dev`, `build`, `start`, `lint`)

### Co przetestowano
- runtime status: `bash scripts/status_dev.sh` -> backend/frontend/telegram działają, endpointy 200
- build root: `npm run build` -> OK (delegacja do `web_portal`, Next.js build zakończony sukcesem)
- smoke: `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: pośrednio dodatni (mniejsze ryzyko awarii operacyjnej podczas deploy/build)
- Ryzyko: niższe ryzyko false alarmów i przerwania pipeline przez brak skryptów npm
- Koszty: neutralne
- Stabilność: wyższa przewidywalność uruchomień i build flow (root -> web_portal)

### Uwaga audytowa (pliki kontrolne)
- brakujace pliki kontrolne z tej sekcji zostaly uzupelnione w sesji `CONTROL-DOCS-ROOT-RESTORE` (14-04-2026)

## AKTUALIZACJA: SESJA PYTEST-TELEGRAM-SPAM-RCA (14-04-2026)

### Co zmieniono
- wykonano RCA dla spamu Telegram podczas `pytest`: testy governance/notification uruchamiały realny `dispatch_notification`, a przy aktywnym `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID` wysyłały wiadomości na produkcyjny chat
- dodano bezpiecznik testowy w `backend/notification_hooks.py`:
	- `_get_config()` rozpoznaje kontekst pytest przez `PYTEST_CURRENT_TEST`
	- w kontekście pytest automatycznie wyłącza outbound Telegram (`enabled=False`), chyba że jawnie ustawiono `ALLOW_TEST_TELEGRAM=true`
	- `send_telegram_message()` ma dodatkowy guard testowy (brak outbound HTTP w pytest)
- zachowano pełną ścieżkę biznesową: `dispatch_notification` nadal zapisuje log do DB (`channels.log=True`), więc testy dalej weryfikują logikę incydentów/policy bez efektów ubocznych na zewnętrznym kanale

### Co przetestowano
- targeted notification suite: `python3 -m pytest tests/test_smoke.py -q -k "notification" --tb=short` -> **13 passed**
- pełny smoke: `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**
- test manualny guardu: przy ustawionym tokenie/chat i `PYTEST_CURRENT_TEST` wynik `dispatch_notification(..., priority="high")` zwraca `channels.telegram=None` (wysyłka pominięta), `channels.log=True`

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: neutralny
- Ryzyko: istotnie niższe ryzyko operacyjne (pytest nie wysyła już wiadomości na produkcyjny Telegram)
- Koszty: niższe koszty operacyjne i noise (brak spamu testowego na kanale alertowym)
- Stabilność: wyższa deterministyczność testów i czystsza separacja test/prod

## AKTUALIZACJA: SESJA CONFIDENCE-GATE-ROOTCAUSE (14-04-2026)

### Co zmieniono
- diagnoza: `signal_confidence_too_low` 64/60m utrzymywało się pomimo T-56 (tolerancja 0.01 za mała — gap był 0.05-0.07)
- root cause: `_learn_from_history` miał hardkodowany `base_conf = 0.55` — nadpisywał reset DB przy każdym restarcie, `learned_conf` wracało do 0.556-0.617
- naprawa: zmieniono `base_conf = 0.55` na `_base_conf_cfg = float(get_runtime_config(db).get("demo_min_signal_confidence", 0.48))`
- przeniesiono `get_runtime_config(db)` poza pętlę `for symbol in self.watchlist` (efektywność, 1 read/cykl zamiast N)
- obniżono `demo_min_signal_confidence` w DB: `0.55` → `0.48`
- zresetowano `learning_symbol_params` min_confidence z 0.556-0.617 → 0.48 dla wszystkich 20 symboli
- zmieniono cap formuły: `min(0.72, base+0.12+...)` → `min(base+0.20, base+0.10+...)` (proporcjonalny do nowej bazy)

### Co przetestowano
- smoke: `220 passed in 60.23s` ✅
- restart stacka (wymagany do przeładowania symbol_params w pamięci)
- telemetry 5min po restarcie: **0 `signal_confidence_too_low`** (was 64/60m)
- nowe `learning_symbol_params` po reinicjalizacji: ETHEUR=0.492, PEPEEUR=0.497, WLFIEUR=0.500 ✓
- ETHEUR/PEPEEUR poprawnie blokowane przez `signal_filters_not_met` (HOLD signal, RSI 40-45 < buy_gate 65) — prawidłowe zachowanie

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: znacząca poprawa — confidence gate przestał blokować wszystkie heurystyczne sygnały
- Ryzyko: kontrolowane — inne bramki (RSI, cost gate, entry score) nadal aktywne
- Koszty: neutralne
- Stabilność: system poprawnie kalibruje progi do aktualnego modelu (heurystyka zamiast OpenAI)


## AKTUALIZACJA: SESJA CONFIDENCE-GATE-TOLERANCE (14-04-2026)

### Co zmieniono
- przeanalizowano `decision_traces` LIVE (60m): duża część `signal_confidence_too_low` była na granicy `confidence=0.50` przy progu `min_confidence≈0.51`
- w collectorze dodano warunkową mikrotolerancję dla BUY:
	- `buy_confidence_tolerance` (domyślnie `0.01`)
	- odrzucenie następuje dopiero gdy `confidence + tolerance < min_confidence`
	- do trace dopisano `confidence_tolerance` w `risk_check`
- nie zmieniano globalnych progów confidence ani scoringu

### Co przetestowano
- smoke po zmianie: `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**
- restart stacka: `scripts/stop_dev.sh` + `scripts/start_dev.sh`
- sanity endpointów po restarcie: `/api/signals/best-opportunity`, `/api/positions/analysis` -> 200
- telemetry LIVE (10m po restarcie):
	- `symbol_cooldown_active`: 20
	- `signal_confidence_too_low`: 10
	- brak dominacji cost gate w krótkim oknie po wdrożeniu

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: mniej fałszywych odrzuceń na granicy progu
- Ryzyko: minimalny wzrost (tylko BUY, tylko margines 0.01)
- Koszty: neutralne
- Stabilność: wyższa przewidywalność bramki confidence

## AKTUALIZACJA: SESJA ENTRY-GATE-NORMALIZATION (14-04-2026)

### Co zmieniono
- usunięto niespójność skali w collectorze: `demo_min_entry_score` (docelowo 0-100) był porównywany z `rating` (0-5), co zwiększało liczbę `entry_score_below_min`
- dodano normalizację progu wejścia:
	- kompatybilność legacy: jeśli próg <= 10, traktowany jako stara skala i mnożony x10
	- nowa skala: `signal_score` porównywany do `entry_score_threshold` (0-100)
	- `rating` oceniany niezależnie przez `min_rating_gate` (domyślnie 3.0)
- dopracowano `validate_long_entry` w `risk.py`:
	- dla mocnych sygnałów w `TREND_UP` zastosowano warunkowo łagodniejsze `required_move_mult` (1.2 zamiast 1.3)
	- dla mocnych sygnałów w `TREND_UP` podniesiono warunkowo maksymalny udział kosztów z 50% do 55% expected move
	- dla słabszych setupów i innych reżimów bramki pozostają bez zmian

### Co przetestowano
- smoke po zmianach: `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**
- restart stacka: `scripts/stop_dev.sh` + `scripts/start_dev.sh` -> backend/frontend/telegram online
- sanity endpointów po restarcie:
	- `GET /api/signals/best-opportunity?mode=live` -> 200
	- `GET /api/account/trading-status?mode=live` -> 200
	- `GET /api/account/runtime-activity?mode=live` -> 200

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: większa przepustowość dla jakościowych setupów bez otwierania słabych wejść
- Ryzyko: ograniczone, bo relax działa tylko dla `TREND_UP` i wysokiego `signal_score`
- Koszty: mniej fałszywych odrzuceń przy poprawnym edge, brak globalnego wyłączenia cost gate
- Stabilność: wyższa spójność logiki i trace (`min_rating_gate` + `signal_score_min`)

## AKTUALIZACJA: SESJA LIVE-ENTRY-UNBLOCK (14-04-2026)

### Co zmieniono
- przeprowadzono diagnostykę `decision_traces`/`runtime-activity`: bot działał, ale większość wejść była blokowana przez `cost_gate_failed` z powodem `Range regime requires a stronger edge; default is NO_TRADE`
- skorygowano bramki wejścia w collectorze:
	- `signal_score` cutoff: 72.0 -> 50.0
	- `min_rr` dla `validate_long_entry`: `max(2.0, min_expected_rr)` -> `max(1.6, min_expected_rr)`
	- usunięto twardą blokadę wejść w `RANGE` na etapie collectora (`allow_range=True`)
- skorygowano bramkę kosztową w `risk.py`:
	- udział kosztów vs expected move: 35% -> 50%
	- `required_move` mnożnik: `total_cost_pct * 1.8` -> `total_cost_pct * 1.3`

### Co przetestowano
- smoke po zmianach: `DISABLE_COLLECTOR=true python -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**
- restart stacka: `scripts/stop_dev.sh` + `scripts/start_dev.sh` -> backend/frontend/telegram online
- runtime heartbeat: `GET /api/account/runtime-activity` pokazuje nowe wykonania LIVE
- w DB potwierdzono sekwencję:
	- `create_pending_entry` -> `execute_pending` -> `orders.status=FILLED`
	- nowe BUY LIVE dla: `SOLEUR`, `WLFIEUR`, `BTCEUR`, `BNBEUR`

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: dodatni potencjał (bot przestał być zamrożony i wrócił do wykonywania wejść)
- Ryzyko: umiarkowanie wyższe (szersza przepustowość wejść w regime `RANGE`)
- Koszty: nadal kontrolowane przez cost gate i min-notional guard
- Stabilność: wyższa transparentność; diagnostyka API/DB spójnie potwierdza decyzje i wykonania

## AKTUALIZACJA: SESJA STARTUP-FORENSICS (14-04-2026)

### Co zmieniono
- wykonano twardy audyt ścieżek uruchomieniowych: `scripts/start_dev.sh`, `scripts/stop_dev.sh`, `scripts/status_dev.sh`, `backend/app.py`, `.env`, `README.md`, `docs/QUICK_START.md`, `docs/archive/START_HERE.md`, `MASTER_INDEX.md`
- wykonano git archaeology dla rootowego `package.json`
- przywrócono rootowy `package.json` do historycznej funkcji 1:1: dependency-only (`next`) bez wrapperowych `scripts`

### Co ustalono
- działający runtime NIE używa rootowego `npm run ...`
- aktywne ścieżki startu to:
	- `bash scripts/start_dev.sh`
	- `python -m backend.app`
	- `python -m backend.app --all`
	- `cd web_portal && npm run dev|build|start`
	- `python -m telegram_bot.bot`
- backend sam uruchamia collector i `reevaluation_worker` w lifespanie aplikacji
- historyczny rootowy `package.json` został dodany jednorazowo w commicie checkpointowym i zawierał wyłącznie `dependencies.next`, bez `scripts`
- w repo nie znaleziono alternatywnych launcherów typu `docker-compose*`, `Dockerfile*`, `Makefile`, `systemd`, `pm2`, `supervisor`

### Co przetestowano
- `bash scripts/status_dev.sh` -> backend/frontend/telegram działają, HTTP 200
- snapshot procesów -> frontend działa jako `npm exec next start ...` z `web_portal`, backend jako `uvicorn backend.app:app`, telegram jako `python -m telegram_bot.bot`
- potwierdzono w kodzie `backend/app.py`, że ścieżka `--all` uruchamia frontend przez `cd web_portal && npm run dev`

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: neutralny
- Ryzyko: niższe ryzyko uszkodzenia realnej ścieżki startowej przez pozorny wrapper rootowy
- Koszty: neutralne
- Stabilność: wyższa zgodność repo z realnym, udokumentowanym sposobem uruchamiania

## AKTUALIZACJA: SESJA ROOT-BUILD-RECOVERY (14-04-2026)

### Co zmieniono
- `package.json` w katalogu głównym:
	- usunięto przypadkowy artefakt w formacie lockfile, który nie zawierał `scripts`
	- dodano minimalny manifest narzędziowy delegujący `build/dev/start/lint` do `web_portal`

### Co przetestowano
- Git archaeology: na `main` rootowy `package.json` nie istnieje, więc plik nie był częścią bazowej architektury
- Build root: `npm run build` z katalogu głównego -> delegacja do `web_portal`

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: neutralny
- Ryzyko: niższe ryzyko błędnego uruchomienia narzędzi operatorskich z root repo
- Koszty: neutralne
- Stabilność: wyższa przewidywalność build flow dla frontendowego review i deploy sanity

## AKTUALIZACJA: SESJA LIVE-DOC-CONSISTENCY (14-04-2026)

### Co zmieniono
- `README.md`:
	- usunięto sprzeczny zapis „Handel działa wyłącznie w trybie DEMO (LIVE wyłączony)”
	- zaktualizowano przykład control-plane na `allow_live_trading`
	- doprecyzowano endpoint `wealth` pod LIVE (`mode=live`, demo jako tryb wspierany)

### Co przetestowano
- Smoke: `DISABLE_COLLECTOR=true .venv/bin/python -m pytest tests/test_smoke.py -q --tb=short` → **220 passed**
- TypeScript: `./node_modules/.bin/tsc --noEmit` → OK

### Wpływ na zysk/ryzyko/koszty/stabilność
- Zysk: pośrednio dodatni (mniejsze ryzyko błędnej operacji przez operatora)
- Ryzyko: obniżone (brak mylącej instrukcji demo-only przy aktywnym LIVE)
- Koszty: neutralne
- Stabilność: wyższa spójność operacyjna backend ↔ WWW ↔ dokumentacja

## AKTUALIZACJA: SESJA LIVE-ONLY (14-04-2026)

### Co zmieniono
- Frontend:
	- usunięto demo-only guardy blokujące akcje w LIVE (zamykanie pozycji, akcje pending, statusy i etykiety)
	- dodano panel runtime heartbeat w Command Center (`RuntimeActivityPanel`)
	- Topbar i Settings czytają stan live (`live_trading_enabled` / `allow_live_trading`)
- Backend:
	- dodano endpoint `GET /api/account/runtime-activity`
	- `control/state` zwraca aliasy: `live_trading_enabled`, `trading_enabled`
	- `orders.py`: pending orders działają dla `mode=live` i `mode=demo`
	- `positions.py`: `close-all` działa dla LIVE i DEMO

### Co przetestowano
- TypeScript: `node_modules/.bin/tsc --noEmit` -> OK
- Smoke: `python3 -m pytest tests/test_smoke.py -q --tb=short` -> **220 passed**

### Otwarte ryzyka po sesji
- Niskie: dokumentacja README nadal ma historyczne fragmenty DEMO poza sekcjami krytycznymi flow LIVE.
- Niskie: część typów frontendu nadal używa union `mode: 'demo' | 'live'` dla kompatybilności.

**Data audytu:** 5 kwietnia 2026 (aktualizacja: sesja 10)
**Wersja:** v0.7 beta
**Testy:** 182 PASSED / 0 FAILED / 0 SKIPPED (`tests/test_smoke.py`, sesja 10)
**TypeScript:** 0 błędów
**Tryb:** TRADING_MODE=live, ALLOW_LIVE_TRADING=true, AI_PROVIDER=heuristic

---

## 1. Aktualny stan projektu

Bot jest funkcjonalny w trybie DEMO (500 EUR) i częściowo w trybie LIVE.
Architektura jest spójna — brak aspiracyjnych katalogów, brak martwego kodu.
Wszystkie 4 piony (A-D) są w znacznym stopniu domknięte.

**Co działa prawidłowo:**
- Pobieranie danych rynkowych (REST + WebSocket)
- Generowanie sygnałów (24 wskaźników, scoring 1-5)
- Filtry wejścia (13+ filtrów incl. edge-after-costs)
- Filtry wyjścia (4 warstwy: SL, Trailing, TP partial/full, Reversal)
- Koszty (maker/taker fee, slippage, spread) w CostLedger
- Equity, free cash, realized/unrealized PnL
- Decision trace z 20+ reason_codes (po polsku)
- WWW — 18 widoków, wszystkie endpointy OK
- Telegram — **20 komend** (incl. `/ip`, `/ai`), alerty entry+exit, portfolio, pozycje, sygnały
- _learn_from_history z persistencją do RuntimeSetting
- LIVE place_order → Binance API (MARKET)
- Daily drawdown gate (DEMO + LIVE)

---

## 2. Mapa modułów

### Backend (`backend/`)

| Plik | Rola | Stan | Linie |
|------|------|------|-------|
| `app.py` | Startpoint FastAPI, mount routerów | ✅ DZIAŁA | ~200 |
| `database.py` | Modele ORM (30+), init_db, _ensure_schema | ✅ DZIAŁA | ~1800 |
| `collector.py` | Główna pętla: dane, sygnały, entry/exit, execution | ✅ DZIAŁA | ~3127 |
| `analysis.py` | Analiza techniczna, AI ranges, blog | ✅ DZIAŁA | ~1577 |
| `accounting.py` | Equity, PnL, koszty, cost summary | ✅ DZIAŁA | ~600 |
| `risk.py` | Risk gates, drawdown, position limits | ✅ DZIAŁA | ~300 |
| `runtime_settings.py` | Konfiguracja runtime, symbol tiers | ✅ DZIAŁA | ~700 |
| `binance_client.py` | API Binance: spot, earn, futures, orders | ✅ DZIAŁA | ~700 |
| `auth.py` | Autoryzacja endpoint (API key) | ✅ DZIAŁA | ~50 |
| `system_logger.py` | Centralny logging do SystemLog | ✅ DZIAŁA | ~80 |
| `operator_console.py` | Read-only diagnostyka | ✅ DZIAŁA | ~150 |
| `reporting.py` | Raporty, metryki, statystyki | ✅ DZIAŁA | ~400 |
| `trading_effectiveness.py` | Efektywność: win rate, profit factor | ✅ DZIAŁA | ~300 |
| `experiments.py` | Eksperymenty konfiguracyjne | ✅ DZIAŁA | ~200 |
| `recommendations.py` | Rekomendacje zmian konfiguracji | ✅ DZIAŁA | ~200 |
| `review_flow.py` | Review pipeline rekomendacji | ✅ DZIAŁA | ~150 |
| `promotion_flow.py` | Promocja recommended→active | ✅ DZIAŁA | ~150 |
| `post_promotion_monitoring.py` | Monitoring po promocji | ✅ DZIAŁA | ~150 |
| `rollback_decision.py` | Decyzja o rollbacku | ✅ DZIAŁA | ~150 |
| `rollback_flow.py` | Wykonanie rollbacku | ✅ DZIAŁA | ~150 |
| `post_rollback_monitoring.py` | Monitoring po rollbacku | ✅ DZIAŁA | ~100 |
| `policy_layer.py` | Warstwa polityk: verdict→action | ✅ DZIAŁA | ~200 |
| `governance.py` | Freeze, incydenty, SLA | ✅ DZIAŁA | ~300 |
| `notification_hooks.py` | Hooki dla powiadomień | ✅ DZIAŁA | ~100 |
| `candidate_validation.py` | Walidacja kandydatów entry | ✅ DZIAŁA | ~100 |
| `correlation.py` | Korelacja między symbolami | ✅ DZIAŁA | ~150 |
| `reevaluation_worker.py` | Reewaluacja pozycji | ✅ DZIAŁA | ~100 |
| `tuning_insights.py` | Insighty z tuningu | ✅ DZIAŁA | ~100 |

### Routery (`backend/routers/`)

| Plik | Endpointy | Stan | Linie |
|------|-----------|------|-------|
| `account.py` | ~90 EP: account summary, governance, analytics, AI status, aliasy runtime-config | ✅ DZIAŁA | 2064+ |
| `signals.py` | Sygnały, analiza, execution-trace, decision trace + root alias `/api/signals/` | ✅ DZIAŁA | 1808+ |
| `positions.py` | Pozycje, analiza pozycji | ✅ DZIAŁA | 1910 |
| `orders.py` | Zlecenia DEMO+LIVE, create_order, pending | ✅ DZIAŁA | 633 |
| `market.py` | Dane rynkowe, Klines, kontekst | ✅ DZIAŁA | 817 |
| `portfolio.py` | Portfel, wealth, forecast, equity | ✅ DZIAŁA | 569 |
| `control.py` | Sterowanie: demo ON/OFF, WS, watchlist + alias `/operator-queue` | ✅ DZIAŁA | 185+ |
| `blog.py` | Blog AI insights | ✅ DZIAŁA | 67 |
| `debug.py` | Diagnostyka dev + alias `/logs` | ✅ DZIAŁA | 278+ |
| `telegram_intel.py` | Intel Telegram | ✅ DZIAŁA | 145 |

### Frontend (`web_portal/`)

| Plik | Rola | Stan |
|------|------|------|
| `MainContent.tsx` | 18 widoków, główna logika UI | ✅ DZIAŁA (5764L) |
| `Sidebar.tsx` | Nawigacja 18 pozycji | ✅ DZIAŁA |
| `Topbar.tsx` | Nagłówek + status | ✅ DZIAŁA |
| `Dashboard.tsx` | Dashboard wrapper | ✅ DZIAŁA |
| `widgets/*.tsx` | 11 widgetów (AccountMetrics, EquityCurve, etc.) | ✅ DZIAŁA |
| `lib/api.ts` | getApiBase() helper | ✅ DZIAŁA |

### Telegram (`telegram_bot/`)

| Plik | Rola | Stan |
|------|------|------|
| `bot.py` | 18 komend Telegram: /status /portfolio /risk /confirm /reject /governance /freeze /incidents | ✅ DZIAŁA |

### Testy (`tests/`)

| Plik | Testy | Stan |
|------|-------|------|
| `test_smoke.py` | 182 testy (176 smoke + 6 akceptacyjnych v0.7) | ✅ WSZYSTKIE PRZECHODZĄ |

### Inne

| Katalog/Plik | Rola | Stan |
|--------------|------|------|
| `scripts/` | start_dev.sh, stop_dev.sh, status_dev.sh | ✅ DZIAŁA |
| `docs/` | Dokumentacja: checkpointy, design system | ✅ AKTUALNE |
| `logs/` | Logi runtime | ✅ DZIAŁA |

---

## 3. Źródła prawdy danych

| Domena | Moduł | Tabela DB |
|--------|-------|-----------|
| Konfiguracja | `runtime_settings.py` | `RuntimeSetting` |
| Ekonomia (PnL, equity) | `accounting.py` | `Order`, `CostLedger`, `Position` |
| Ochrona kapitału | `risk.py` | `RiskLog` |
| Dane rynkowe | `database.py` | `MarketData`, `Kline` |
| Sygnały | `analysis.py` → `collector.py` | `Signal` |
| Decyzje | `collector.py` | `DecisionTrace` |
| Zlecenia | `routers/orders.py` + `collector.py` | `Order`, `PendingOrder` |
| Koszty | `accounting.py` | `CostLedger` |
| Pozycje | `collector.py` | `Position` |
| Exit quality | `collector.py` | `ExitQualityRecord` |
| AI forecasts | `analysis.py` | `ForecastRecord` |
| Blog | `analysis.py` | `BlogPost` |
| Logi systemowe | `system_logger.py` | `SystemLog` |
| Incydenty | `governance.py` | `Incident` |
| Eksperymenty | `experiments.py` | `Experiment`, `ExperimentResult` |

---

## 4. Blokery krytyczne

### CRITICAL-1: LIVE — koszty z Binance-fills nie są zapisywane do CostLedger
- **Plik:** `backend/collector.py` L408-470 (`_execute_confirmed_pending_orders`, ścieżka LIVE)
- **Problem:** Po place_order na Binance, kod parsuje fills i wyciąga `exec_price`, ale **koszty** (fee_cost, slippage_cost, spread_cost) są nadal szacowane identycznie jak dla DEMO — `notional * taker_fee_rate`. Rzeczywista prowizja z `fills[].commission` jest ignorowana.
- **Wpływ:** Net PnL w LIVE może być niedokładny o kilka % (Binance fees mogą być mniejsze jeśli BNB jest używany do płacenia opłat, albo inne jeśli jest zero-fee promo).
- **Fix:** Użyć `sum(float(f.get("commission", 0)) for f in fills)` jako `actual_value` w CostLedger.

### CRITICAL-2: Brak periodycznego sync pozycji DB ↔ Binance
- **Plik:** brak odpowiedniej funkcji
- **Problem:** Pozycje w DB są aktualizowane tylko przy execution (BUY/SELL). Jeśli użytkownik dokona transakcji bezpośrednio na Binance (poza botem), DB się rozjedzie.
- **Wpływ:** Portfolio w WWW może nie odzwierciedlać rzeczywistego stanu konta Binance.
- **Fix:** Dodać `_sync_binance_positions()` wywoływany co N cykli w kolektorze.

---

## 5. Długi techniczne

| ID | Opis | Plik | Priorytet |
|----|------|------|-----------|
| ~~DEBT-1~~ | ~~Telegram: /confirm i /reject~~ | `telegram_bot/bot.py` | ✅ ZAMKNIĘTY — już zaimplementowane (L371-424) |
| ~~DEBT-2~~ | ~~Telegram: /governance /freeze /incidents /logs /report~~ | `telegram_bot/bot.py` | ✅ ZAMKNIĘTY — już zaimplementowane (L427-560) |
| DEBT-3 | CORS: allow_origins=["*"] | `backend/app.py` | LOW |
| ~~DEBT-4~~ | ~~Qty sizing nie odejmuje prowizji~~ | `backend/collector.py` | ✅ NAPRAWIONY — max_cash_after_fees = max_cash/(1+fee) |
| DEBT-5 | Brak LIMIT orders w LIVE (tylko MARKET) | `backend/routers/orders.py` L383 | LOW |
| DEBT-6 | AccountSummary widget w frontend nieużywany | `web_portal/src/components/widgets/` | LOW |

---

## 6. Martwy kod

**Brak martwego kodu.** W iter7 przeprowadzono pełne czyszczenie:
- Aspiracyjne katalogi usunięte (hft_engine, quantum_optimization, etc.)
- Nieużywane importy usunięte
- DemoOrderGenerator usunięty
- Duplikaty funkcji usunięte

---

## 7. Niespójności backend ↔ frontend ↔ DB ↔ Telegram ↔ Binance

| Problem | Stan |
|---------|------|
| WWW equity vs DB equity | ✅ Spójne — accounting.py liczy z Order history |
| WWW pozycje vs DB pozycje | ✅ Spójne — Position table |
| DB pozycje vs Binance pozycje | ⚠️ Brak periodycznego sync (CRITICAL-2) |
| Telegram alerty vs WWW dane | ✅ Spójne — ten sam source (DB) |
| LIVE fees vs CostLedger | ⚠️ Estimated zamiast actual (CRITICAL-1) |
| Decision trace WWW | ✅ Spójne — endpoint `/api/signals/execution-trace` |

---

## 8. Lista zadań otwartych

| ID | Zadanie | Priorytet | Plik/Moduł | Wpływ |
|----|---------|-----------|------------|-------|
| ~~TASK-01~~ | ~~LIVE CostLedger: actual Binance commission~~ | ~~CRITICAL~~ | `collector.py` | ✅ DONE (sesja 2, commit 9ac10b0) |
| ~~TASK-02~~ | ~~Periodyczny sync pozycji DB ↔ Binance~~ | ~~CRITICAL~~ | `collector.py` | ✅ DONE (sesja 2, commit 9ac10b0) |
| ~~TASK-03~~ | ~~Telegram /confirm i /reject~~ | ~~HIGH~~ | `telegram_bot/bot.py` | ✅ już zaimplementowane (false positive) |
| ~~TASK-04~~ | ~~Qty sizing: odejmij prowizję~~ | ~~MEDIUM~~ | `collector.py` | ✅ DONE (sesja 2) |
| TASK-05 | CORS allow_origins → proper domains | LOW | `app.py` | Bezpieczeństwo |

---

## 9. Lista zadań zamkniętych (ostatnie sesje)

| Data | Co | Rezultat |
|------|-----|----------|
| 01.04 iter8 | Dodano Gemini + Groq AI providers | ✅ auto fallback chain |
| 01.04 iter8 | /api/account/ai-status endpoint | ✅ diagnostyka AI |
| 01.04 iter8 | Collector nigdy nie blokuje bota bez AI key | ✅ heuristic fallback |
| 01.04 iter7 | HOLD→SPECULATIVE, WLFI odblokowany | ✅ |
| 01.04 iter7 | Watchlist 14 symboli | ✅ |
| 01.04 iter6 | 18 widoków WWW, sidebar PL | ✅ |
| 01.04 iter5 | Portfolio wealth + equity curve + forecast | ✅ |
| 01.04 iter4 | ATR multipliers, SL cooldown, soft RSI | ✅ |
| 31.03 iter3 | WAL mode, async fix, 181 testów | ✅ |

---

## 10. Decyzje architektoniczne

| Data | Decyzja | Powód |
|------|---------|-------|
| 01.04 | AI_PROVIDER=heuristic domyślnie | Instant, bez external dependency, stabilny |
| 01.04 | Auto fallback chain: Ollama→Gemini→Groq→OpenAI→Heuristic | Resilience, user may not have all keys |
| 31.03 | SQLite WAL mode | Concurrent reads w asynch web + collector |
| 31.03 | Thin routers — zero logiki biznesowej | Łatwa mutowalność, testability |
| 31.03 | Single source of truth per domena | Brak duplikacji, konsystencja |
| 26.03 | MARKET only w LIVE (na start) | Bezpieczeństwo, prostota |
| 26.03 | PendingOrder + manual confirm (LIVE) | Safety gate przed real execution |

---

## 11. Ostatnia sesja — 2 kwietnia 2026

### Co zmieniono
- Przeprowadzono pełny audyt LIVE trading paths
- Stworzono PROJECT_AUDIT_MASTER.md (ten plik)
- Zidentyfikowano 2 blokery krytyczne: LIVE fees accounting, Binance position sync
- Zidentyfikowano 4 długi techniczne

### Co przetestowano
- 181/181 smoke testów ✅ (ostatni run: sesja 01.04)

### Co zostało
- TASK-05: CORS allow_origins (LOW) — przed produkcją
- DEBT-5: LIMIT orders w LIVE (LOW)
- DEBT-6: AccountSummary widget cleanup (LOW)
- Żadnych blokerów krytycznych ani ważnych

---

## 12. Ostatnia sesja — 4 kwietnia 2026 (sesja 4)

### Co zmieniono
- Dodano aliasy kompatybilnosci endpointow eliminujace obserwowane 404 z runtime:
	- `GET /api/account/runtime-settings`
	- `GET /api/account/runtime-config`
	- `GET /api/account/config`
	- `GET /api/control/operator-queue`
	- `GET /api/debug/logs`
	- `GET /api/signals/`
- Wykonano pelny reset srodowiska: `./scripts/stop_dev.sh` -> `./scripts/start_dev.sh`.
- Potwierdzono status uslug: backend/frontend/telegram dzialaja.

### Co przetestowano
- Sanity endpointow po restarcie: wszystkie ww. endpointy zwracaja `200`.
- `./scripts/status_dev.sh`: wszystkie uslugi zdrowe, API krytyczne `200`.
- `pytest tests/test_smoke.py -q`: 161 passed, 19 failed, 1 skipped.

### Co zostalo
- Do naprawy pozostaja testy governance/promotion/rollback (19 fail), niezwiazane bezposrednio z aliasami endpointow.

---

## 13. Ostatnia sesja — 4 kwietnia 2026 (sesja 5)

### Co zmieniono
- `backend/collector.py`: stabilizacja odswiezania watchlisty.
	- Fallback do `WATCHLIST` z `.env` jest uzywany tylko przy bootstrapie (gdy brak aktywnej listy).
	- Przy okresowym refreshu, gdy lista juz istnieje, tymczasowy timeout Binance nie przelacza watchlisty na fallback.
- `backend/collector.py`: throttling powtarzalnych alertow `Niezgodność pozycji DB↔Binance`.
	- Identyczne mismatch'e sa logowane maksymalnie raz na `BINANCE_MISMATCH_LOG_COOLDOWN_SECONDS` (domyslnie 1800s).
- Wykonano restart runtime po zmianie (`stop_dev` -> `start_dev`) i potwierdzono zdrowie uslug (`status_dev`).

### Co przetestowano
- Walidacja skladni: `python -m py_compile backend/collector.py`.
- Status uslug po restarcie: backend/frontend/telegram aktywne, endpointy health `200`.

---

## 14. Ostatnia sesja — 4 kwietnia 2026 (sesja 6)

### Co zmieniono
- `backend/routers/positions.py`: LIVE spot positions przestaly zwracac sztuczne `entry_price=None` dla wszystkich aktywow.
	- Priorytet 1: jesli istnieje lokalna pozycja LIVE z poprawnym baseline, router uzywa jej jako zrodla kosztu wejscia.
	- Priorytet 2: jesli baseline w DB nie istnieje, router odtwarza sredni koszt aktualnie trzymanej pozycji z historii `Binance myTrades`.
	- Jesli baseline da sie policzyc wiarygodnie, brakujaca pozycja LIVE jest dopisywana / odswiezana w lokalnej tabeli `Position` z `entry_reason_code=synced_from_binance`.
- `backend/routers/positions.py`: `/api/positions?mode=live` i `/api/positions/analysis?mode=live` zwracaja teraz `entry_price`, `cost_eur`, `pnl_eur`, `pnl_pct` wszedzie tam, gdzie historia Binance na to pozwala.
- `tests/test_smoke.py`: dodano test regresyjny potwierdzajacy odbudowe baseline LIVE i zapis synchronizowanej pozycji do DB.

### Wplyw
- WWW przestaje pokazywac `brak danych` dla kosztu wejscia i PnL w pozycjach LIVE, gdy Binance ma historie transakcji dla symbolu.
- Zmniejsza sie niespojnosc Binance ↔ DB dla pozycji, ktore dotad istnialy tylko jako saldo spot bez lokalnego baseline.
- Operator dostaje realny punkt odniesienia do decyzji zamkniecia / trzymania pozycji LIVE zamiast samej wartosci rynkowej.

### Co przetestowano
- Celowany smoke: `pytest tests/test_smoke.py -q -k 'live_positions_analysis_restores_entry_baseline or acceptance_live_positions_returns_source_field or acceptance_demo_positions_from_local_db'` -> `3 passed`.
- Pelny smoke: `pytest tests/test_smoke.py -q` -> `162 passed, 19 failed, 1 skipped`.
- Potwierdzenie: liczba faili nie wzrosla; otwarte porazki pozostaja w obszarze governance/promotion/rollback.

### Co zostalo
- Dla aktywow nabytych poza para `ASSET/EUR` lub bez historii `myTrades`, baseline moze pozostac nieznany — wtedy UI nadal uczciwie pokazuje brak kosztu wejscia.

---

## 15. Ostatnia sesja — 4 kwietnia 2026 (sesja 7)

### Co zmieniono
- `backend/runtime_settings.py`: `apply_runtime_updates(...)` zwraca teraz zawsze pole `snapshot` rowniez w sciezce no-op (brak realnej zmiany), co stabilizuje przeplyw eksperyment -> rekomendacja -> promocja.
- `backend/promotion_flow.py`: promocja aplikuje tylko roznice miedzy snapshotem zrodlowym i docelowym zamiast calego payloadu snapshotu.
- `backend/rollback_flow.py`: rollback aplikuje tylko roznice miedzy `from_snapshot` i `rollback_snapshot`, analogicznie do promocji.

### Wplyw
- Usunieto krytyczny powod porazek governance/promotion/rollback: reaplikacja calych snapshotow wymuszala walidacje niezmienianych legacy kluczy (np. `pending_order_cooldown_seconds`).
- Pipeline promocji i rollbacku stal sie deterministyczny: dotyka tylko faktycznie promowanych/rollbackowanych parametrow.

### Co przetestowano
- Celowany smoke (promotion + rollback decision): `5 passed`.
- Celowany smoke (rollback_flow + post_rollback_monitoring): `9 passed, 1 failed` przy uruchomieniu niepelnego podzbioru (fail wynikajacy z braku fixture chain), bez regresji funkcjonalnej.
- Pelny smoke: `pytest tests/test_smoke.py -q` -> `182 passed`.

### Co zostalo
- Brak otwartych faili smoke.

---

## 16. Sesja 10 — 5 kwietnia 2026

### Co zmieniono

**T-16 — `backend/collector.py` `_load_watchlist`:**
- Przed naprawą: `WATCHLIST` z `.env` był używany TYLKO jako fallback gdy saldo Binance nie zwróciło żadnych symboli. Ponieważ konto ma AVAX/ARB/EGLD/PEPE (dust), `resolved` był non-empty → env WATCHLIST był całkowicie ignorowany → ETH/SOL/WLFI/SHIB EUR nigdy nie trafiały do watchlisty.
- Po naprawie: env WATCHLIST jest ZAWSZE scalany z balance-derived. Wyjątek: `allow_env_fallback=False` AND `resolved=[]` (tymczasowy timeout Binance) → zwraca [] → refresh code zachowuje starą watchlistę.
- Nowa watchlista: ARBEUR, AVAXEUR, BNBEUR, BTCEUR, EGLDEUR, ETHEUR, PEPEEUR, SHIBEUR, SOLEUR, WLFIEUR

**T-17 — `backend/collector.py` `_load_trading_config` range_map supplement:**
- Przed naprawą: heurystyka ATR była generowana TYLKO gdy `not range_map or ai_ranges_stale`. Nowe symbole (ETH/SOL/SHIB/WLFI) dodane do watchlisty nie miały zakresów → ciche `if not r: continue` w `_screen_entry_candidates` bez logu.
- Po naprawie: heurystyka uzupełnia BRAKUJĄCE symbole watchlisty (`missing_in_range`) nawet gdy range_map ma już wpisy dla innych symboli. Log: „Heurystyczne zakresy ATR uzupełnione dla: ETHEUR, SHIBEUR, SOLEUR, WLFIEUR."

### Wynik weryfikacji

Collector decisions po naprawie:
- ETHEUR(live): SKIP → sell_blocked_no_position ✅ (SELL bez pozycji — poprawne na SPOT)
- SOLEUR(live): SKIP → sell_blocked_no_position ✅
- SHIBEUR(live): SKIP → sell_blocked_no_position ✅
- WLFIEUR(live): SKIP → sell_blocked_no_position ✅
- BNBEUR(live): SKIP → signal_confidence_too_low (learned=0.56 > heuristic=0.55, delta 0.01 — learning poprawne)
- BTCEUR(live): SKIP → entry_score_below_min (ma już pozycję 157 EUR)
- ARB/AVAX/EGLD/PEPE EUR: SKIP → symbol_not_in_any_tier (dust balance artifacts, nie w tier config)

### Co przetestowano
- `pytest tests/test_smoke.py -q` → **182 passed** ✅
- Logi collectora potwierdzają poprawne flow dla ETHEUR/SOLEUR/SHIBEUR/WLFIEUR
- Wszystkie current decisions mają ekonomicznie poprawne uzasadnienie

### Co zostało
- Bot będzie automatycznie próbował wejść do pozycji gdy:
  - ETHEUR, SOLEUR, SHIBEUR lub WLFIEUR wygenerują BUY signal z conf >= learned_threshold
  - BNBEUR wygeneruje BUY signal z conf >= 0.56 (jeden tick powyżej aktualnego 0.55)
- Brak otwartych blokerów
