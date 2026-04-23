# CURRENT_STATE

Data: 2026-04-22
Status dokumentu: aktualny

## Sesja 37 — zmiany (T-112 RECONCILIATION FIX)
- Wykryto: reconcile od >12h failował z error=binance_unavailable — _get_binance_balances() wywoływał client.get_account() (nieistniejącą metodę), zamiast client.get_balances().
- FIX #1: _get_binance_balances() używa teraz client.get_balances() (zwraca [{asset, free, locked, total}]).
- FIX #2: sekcja manual_trades_detection sprawdza base_asset (nie tylko exact symbol) przy wykrywaniu istniejących pozycji DB — eliminuje pętlę BTCEUR → create BTCUSDC → close BTCUSDC → repeat.
- FIX #3: dodano post-check deduplikacji pozycji w _reconcile_positions: zamyka duplikaty (kilka DB pozycji dla tego samego base_asset) z exit_reason_code=reconcile_duplicate_base_asset, zachowując pozycję z najlepszym dopasowaniem qty do salda Binance.
- Efekt operacyjny: WLFIUSDC (id=5, orphaned) zamknięty; open_positions LIVE: 5→4; can_enter_now: False→True.
- Pełny suite: 459/459 passed po zmianach.

## Sesja 37 — zmiany (T-111 FULL SUITE STABILIZATION)
- Pełne test suite ustabilizowane: **459 passed, 0 failed** (z 55 failów przed sesją).
- Root cause #1: RuntimeSetting nie był czyszczony między runami → symbol_cooldown_gate zamiast loss_streak_gate. FIX: dodano RuntimeSetting do cleanup w ensure_db_initialized (test_smoke.py).
- Root cause #2: CostLedger i 14 innych tabel (ExitQuality, DecisionTrace, Experiment itp.) nie były czyszczone → stary stan IDs → błędne aggregate wartości. FIX: pełny cleanup tabel w ensure_db_initialized.
- Root cause #3: conftest.py używał setdefault dla DATABASE_URL i ADMIN_TOKEN → testy używały produkcyjnej bazy i real ADMIN_TOKEN. FIX: bezwzględne os.environ["KEY"] = val; zawsze tworzona izolowana temp DB.
- Root cause #4: TTL cache 60s w ai_orchestrator ignorował monkeypatch OPENAI_UNPAID. FIX: dodano ?force=true do żądania w test_control_center.py.
- Root cause #5: telegram_bot/bot.py load_dotenv(override=True) podczas pytest collection phase nadpisywał ADMIN_TOKEN="" → 401 w test_smoke i test_control_center. FIX: zmieniono na override=False.
- Root cause #6: mock _runtime_context w test_live_execution_cash_management bez trading_mode/allow_live_trading → wszystkie live orders dostawały REJECTED. FIX: dodano trading_mode="live", allow_live_trading=True, execution_enabled=True do mock config.
- Root cause #7: _last_conversion_time global w quote_currency.py zanieczyszczał test_quote_currency gdy uruchamiane po test_live_execution. FIX: autouse fixture resetująca globals w test_quote_currency.py.

## Sesja 36 — zmiany
- T-110: wdrożono reconcile DB↔Binance (auto self-heal) z audit trail (`ReconciliationRun`, `ReconciliationEvent`, `ManualTradeDetection`) oraz nowy moduł `backend/portfolio_reconcile.py`.
- T-110: dodano router diagnostyczny `/api/system/*` (`execution-status`, `reconciliation-status`, `reconcile`, `universe-status`, `ai-consensus-status`, `telegram-status`, `db-health`, `full-status`).
- T-110: startup reconcile (thread po starcie app) + reconcile w każdym cyklu collectora (`run_reconcile_cycle`).
- T-110: Telegram UX rozszerzony o komendy operatorskie: `/pending`, `/trade`, `/incident`, `/close_incident`, `/reconcile`, `/health`, `/execution`, `/universe`, `/quote`.
- T-110: `/confirm` i `/reject` mają disambiguację incident_id vs trade_id (czytelne komunikaty operatorskie, bez mylenia kolejek).
- T-110: globalny execution guard w collectorze: `execution_enabled=false` blokuje ALL execution i zapisuje trace `reason_code=execution_globally_disabled`.
- T-110: nowe testy: `tests/test_reconcile.py`, `tests/test_telegram_disambiguation.py`, `tests/test_execution_guard.py` → **7/7 PASS**.
- pełny suite po zmianach: **404 passed, 55 failed** (głównie smoke: `runtime_settings` init i rozjazd agregacji `exit_quality_report`) — otwarte jako T-111.

- T-109: execution safety gate uszczelniony. `_execute_confirmed_pending_orders` korzysta z runtime config (`allow_live_trading`, `trading_mode`) zamiast samego process env i odrzuca pending LIVE gdy `trading_mode != live` (`reason_code=live_execution_blocked_wrong_trading_mode`).
- T-109: naprawiono krytyczny bug parsera komend kontrolnych: `sell_weakest` tworzył `PendingOrder.status=PENDING_CREATED_CREATED` (niewykonywalne). Status poprawiony na `PENDING_CREATED`.
- T-109: Telegram `/confirm` i `/reject` walidują teraz `PendingOrder.id` w kontekście aktywnego trybu (`PendingOrder.mode == TRADING_MODE`), komunikaty jawnie mówią o PendingOrder ID i używają canonical `PENDING_CONFIRMED`.
- T-109: `/status` w Telegram liczy pending na canonical active statuses (`PENDING_CREATED`, `PENDING`, `CONFIRMED`, `PENDING_CONFIRMED`) zamiast legacy-only.
- testy regresji: `tests/test_control_center.py` + `tests/test_smoke.py` → **257/257 PASS**.

## Sesja 34 — zmiany
- T-104: execution/cash-management hardening dla LIVE: centralne minimum zakupu `min_buy_eur=60.0`, przeliczenie EUR→USDC po kursie (`EURUSDC`/`USDCEUR` fallback), auto-konwersja przed BUY i walidacja salda quote.
- T-104: confirmed pending BUY (manual i auto-confirmed) przechodzi przez deterministyczny preflight: min notional po zaokrągleniu step-size, minNotional po rounding i reason codes przy odrzuceniu (`cash_convert_failed`, `cash_insufficient_after_conversion_attempt`, `execution_rejected_by_exchange`, `temporary_execution_error`).
- T-104: w LIVE zablokowano symbole testowe (`TEST*`) w command parser, universe sygnałów i execution pipeline.
- T-104: `ENTRY_BLOCKED_NO_CASH` nie jest już zgłaszane fałszywie, gdy konto ma EUR i może pokryć wymagane USDC przez auto-konwersję.
- T-104: status tradingowy nie utrzymuje pseudo-freeze po pojedynczym błędzie wykonania (tymczasowe reason codes traktowane jako non-blocker).
- testy: 71/71 dla pakietu execution/cash/control + smoke 220/220 PASS.

## Runtime
- backend: UP (PID z backend.pid)
- frontend: UP
- telegram bot: UP
- health endpoint: 200

## Sesja 33 — zmiany
- T-103: wdrożono parser trading-first dla komend Telegram/control z jednolitym wynikiem `{type, side, symbol, force, config_key, config_value}`.
- T-103: komendy `wymuś kup solusdc` i analogiczne nie wpadają już w ścieżkę config quote-currency; trading ma priorytet nad config.
- T-103: dodano execution flow `MANUAL` i `MANUAL_FORCE` oraz wsparcie `sell_symbol` dla komend `sprzedaj ...` / `wymuś sprzedaj ...`.
- T-103: dodano komendę runtime `tryb agresywny` (z zachowaniem zabezpieczeń risk/min_notional/kill-switch).
- T-103: odpowiedzi Telegrama są mapowane do faktycznie wykonanej akcji (`manual_pending_confirmed_queued`, `manual_force_pending_confirmed_queued`).
- T-103: testy parsera/control: `tests/test_control_center.py` → 36/36 PASS; smoke: 220/220 PASS.
- T-102: parser NL komend BUY obsługuje teraz poprawnie frazy typu `wymuś kup ...` jako realny `buy_symbol` (execute path).
- T-102: collector ma fallback relaksowany po N cyklach bez BUY (domyślnie 3): niższy confidence floor, niższy entry-score threshold i szersza tolerancja BUY zone.
- T-102: candidate universe rozszerzony o top-N symboli z market_scanner (`collector_scanner_top_n`, domyślnie 50).
- T-102: buy-trace używa `buy_zone_tolerance_pct` (fallback `price_tolerance`) z domyślną tolerancją 2%.
- T-102: profile i defaulty wejścia poluzowane (`demo_min_entry_score` i aggressive confidence).
- smoke po zmianie: 220/220 PASS.

## Sesja 32 — zmiany
- T-101: `backend/collector.py` rozszerza screening symbolami z `market_scanner` (nie tylko watchlista), uzupełnia range dla nowych symboli i fallbackuje live sygnał on-demand gdy brak sygnału w DB.
- T-101: dodano operacyjne logi decyzji wejścia: `WHY_NOT_BUY ...` oraz `BUY_ALLOWED ...`.
- T-101: `backend/risk.py` ma testowy debug override `RISK_FORCE_ALLOW_ENTRY_DEBUG=true` (BUY `allowed=True`, `reason_code=forced_entry_debug_override`).
- smoke po zmianie: 220/220 PASS.

## Sesja 31 — zmiany
- T-100: `backend/routers/signals.py` dostał fetch-on-demand dla stale klines w `_build_live_signals` — zamiast natychmiastowego skip stale symbol próbuje odświeżyć klines 1h z Binance i zapisać je do DB.
- smoke po zmianie: 220/220 PASS; bez regresji funkcjonalnej.

## Sesja 30 — zmiany
- T-99: usunięto deprecację czasu UTC w health API (`backend/app.py`) — `datetime.utcnow()` zastąpione `datetime.now(timezone.utc)`
- smoke po zmianie: 220/220 PASS; warning deprecacji zniknął (pozostał tylko `InsecureRequestWarning` z probe tunelu)

## Sesja 29 — zmiany
- T-98: naprawa regresji auth/env w testach — `backend/app.py` ładuje `.env` z `override=False`, więc env ustawione przez pytest (`ADMIN_TOKEN`, limity runtime) nie są nadpisywane przez lokalny `.env`
- T-98: smoke wrócił do pełnego PASS (`220/220`) bez 401 na endpointach kontrolnych

## Sesja 28 — zmiany
- `entry-readiness` staleness fix: ARBUSDC/EGLDUSDC pokazują `ENTRY_BLOCKED_DATA_TOO_OLD` (poprzednio mylące SELL_WITHOUT_POSITION)
- `_active_position_count` naprawiony: liczy tylko `exit_reason_code IS NULL` (previousy COUNT(*) = 2 zamiast 0)
- Extended universe scan: `new_symbols_found=10` (EUR pary), `scanned=20`
- RSI normalizacja + regime inference + DATA_TOO_OLD gate aktywne
- T-93: `_build_live_signals` pomija symbole ze starymi klines 1h (`MAX_KLINE_AGE_HOURS=4h`)
- T-94: dashboard i Ekonomia pokazują stałe KPI kosztowe (`overtrading_score`, `gross_to_net_retention_ratio`, `gross_net_gap`) z `/api/account/analytics/overview`
- T-95: `scripts/start_dev.sh` utwardzony o lock (`flock`) i singleton Telegram (auto-czyszczenie duplikatów + odświeżenie `telegram.pid`)
- T-97: domknięcie duplikacji Telegram przy aktywnym systemd: `start_dev.sh` preferuje `rldc-telegram.service` (enabled→active), czyści lokalne duplikaty i nie uruchamia drugiej instancji; `status_dev.sh` pokazuje źródło PID serwisu
- T-96: confidence gate dostał fallback indikatorowy + dynamiczny próg AI (`0.4` fallback / `0.6` AI OK), debug `CONFIDENCE/AI_USED/AI_FAILED`, oraz bogaty context dla AI chat (`market_scan_snapshot`, `top_opportunities`)
- T-96: payload AI ranges rozszerzony o `price/candles/rsi/ema20/ema50/volume/trend`; status heartbeat liczy `avg_confidence` z `Signal` gdy trace nie niesie confidence
- testy regresji zmiany: `tests/test_signals_router.py` + `tests/test_market_scanner.py` → 43/43 PASS
- testy T-94: `tests/test_reporting_metrics.py` → 6/6 PASS
- testy T-96: `tests/test_confidence_runtime_fix.py` → 4/4 PASS; regresja `tests/test_control_center.py` + `tests/test_smoke.py` → 246/246 PASS
- walidacja T-97: singleton Telegram po cleanupie (`pgrep -af telegram_bot.bot` = 1 PID, zgodny z `rldc-telegram.service MainPID`)

## Stan rynku (19-04-2026 ~00:20 UTC)
- Wszystkie 8 USDC symboli: SELL (rynek bearish, -2% do -5%)
- Brak otwartych pozycji, cash=340 EUR LIVE
- ARBUSDC/EGLDUSDC: stale signals od 14-04, DATA_TOO_OLD gate działa
- Extended scan: EUR pary regenerowane przez live fallback, też SELL (bear market)

## API sanity (LIVE)
- /api/signals/entry-readiness?mode=live -> 200, can_enter_now=false
- /api/signals/entry-readiness: ARB/EGLD → ENTRY_BLOCKED_DATA_TOO_OLD ✅
- /api/signals/entry-readiness: ARB/EGLD nie pojawiają się już z fake live_analysis opartą na starych klines ✅
- /api/control/state -> active_position_count=0 ✅
- /api/dashboard/market-scan -> scanned=20, extended_performed=true ✅
- /api/account/runtime-activity -> collector/ws alive ✅
- /api/account/trading-status?mode=live -> trading_enabled=true, available_to_trade=true, blockers=0 ✅
- /api/signals/entry-readiness -> endpoint działa, ale wejścia nadal blokuje staleness (`ENTRY_BLOCKED_DATA_TOO_OLD`) ✅

## Build i testy
- root npm build (web_portal): PASS (TS zero błędów)
- target pytest po T-98: `tests/test_smoke.py` → 220/220 passed
- target pytest po T-93: `tests/test_signals_router.py` + `tests/test_market_scanner.py` → 43/43 passed
- target pytest po T-94: `tests/test_reporting_metrics.py` → 6/6 passed

## Znane ograniczenia
- ARBUSDC/EGLDUSDC nie są w watchliście kolektora — mają stare MarketData/Klines i są pomijane przez T-93 guard (brak live wskaźników dla tych symboli).
- Dla symboli stale odświeżanie klines w live signals działa best-effort (zależne od dostępności Binance API/kluczy); przy nieudanym fetch nadal obowiązuje bezpieczny skip.

## Źródła prawdy
- kod + testy + endpointy + logi runtime
- dokument nadrzędny: PROJECT_AUDIT_MASTER.md
