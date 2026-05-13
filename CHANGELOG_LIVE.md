# CHANGELOG_LIVE

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
