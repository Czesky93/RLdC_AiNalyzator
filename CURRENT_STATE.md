# CURRENT_STATE

Data: 2026-04-22
Status dokumentu: aktualny

## Sesja 2026-05-17 — domkniecie runtime WWW/overlay po fixie reconcile
- Wykryto, ze sam fix `backend/trading/state_manager.py` nie wystarczal operatorowi, bo WWW i overlay nadal widzialy stary `SystemLog` oraz stare procesy runtime.
- FIX #1: `backend/routers/account.py` filtruje teraz `last_error` po nowszym heartbeat runtime (`last_binance_sync_ts`, `last_learning_ts`, `MarketData.timestamp`, snapshot), wiec `system-status` i `runtime-activity` przestaja pokazywac historyczny `Błąd state_manager.reconcile`, gdy collector juz pracuje poprawnie.
- FIX #2: `live_overlay/serve_live_overlay.py` wzbogaca top symbole o `history` z `/api/market/kline` i `forecast_path` z `/api/market/forecast/:symbol`, a `live_overlay/index.html` wraca do auto-rotacji focusu, domyslnego `15m` i uzywa publicznego `overlay_url` zamiast lokalnego origin.
- FIX #3: `backend/tunnel_manager.py` czyta jawny `overlay_url`, a `scripts/run_quicktunnel.sh` wystawia osobny quick tunnel dla overlay i zapisuje oba URL-e bez utraty danych przy równoleglych parserach.
- Walidacja: `bash -n scripts/run_quicktunnel.sh` -> PASS; `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_trading_state_manager.py -q` -> 28 passed; smoke `curl` potwierdza `last_error_msg=null`, `last_error=null`, obecne `history/forecast_path/chart_tf` w `/overlay/api/live-state` i osobny `overlay_url` w `/api/account/tunnel-status`.

## Sesja 2026-05-17 — fix state_manager.reconcile
- Wykryto runtime bloker w supplemental reconcile collectora LIVE: `StateManager` czytał `cfg.sync_interval_sec`, ale kanoniczny `TradeConfig` ma pole `reconcile_interval_sec`.
- FIX #1: `backend/trading/state_manager.py` używa teraz `reconcile_interval_sec` z fallbackiem do legacy `sync_interval_sec`, więc błąd nie powstaje już przed wejściem do `try` w `reconcile_live_positions()`.
- FIX #2: moduł przeszedł z `datetime.utcnow()` na `utc_now_naive()` dla zapisów/porównań czasu w DB.
- FIX #3: dodano regresję dla domyślnego `TradeConfig()` w `tests/test_trading_state_manager.py`.
- Walidacja: `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_trading_state_manager.py -q` -> 28 passed.

## Sesja 2026-05-17 — audyt instrukcji i Binance live
- Odczytano instrukcje: AGENTS.md, `.github/instructions/*`, `instrukcje.txt`, README, LIVE_TRADING_FLOW, STRATEGY_RULES, CONFIG_AUDIT, OPEN_GAPS, TASK_QUEUE.
- Efektywny runtime DB/.env: `trading_mode=live`, `allow_live_trading=true`, `execution_enabled=true`, `ws_enabled=true`, `quote_currency_mode=USDC`, `live_guard_issues=[]`.
- Binance public data działa: `BTCUSDC`, `ETHUSDC`, `SOLUSDC` zwracają ticker.
- Endpointy live sanity zwracają 200: `/api/system/full-status`, `/api/account/trading-status`, `/api/account/runtime-activity`, `/api/account/capital-snapshot`, `/api/signals/entry-readiness`, `/api/positions`, `/api/orders`.
- Wdrożone poprawki spójności: health ma pole `status`, full-status nie zwraca starego cache, pytest zbiera tylko kanoniczne testy, lint frontendu działa z Next 16.
- Walidacja: `.venv/bin/python -m pytest -q` -> 650 passed; `npm --prefix web_portal run lint` -> PASS; `npm --prefix web_portal run build` -> PASS.

## Sesja 47 — zmiany (T-127 WATCHDOG STABILITY + AI TRUTHFULNESS)
- Wykryto, ze po recovery SQLite backend byl ponownie ubijany przez watchdog: timer wykonywal nakladajace sie przebiegi i restartowal `rldc-backend` po pojedynczym probe `/health`, zanim runtime zakonczyl rozruch.
- FIX #1: `scripts/watchdog.sh` dostal lock (`flock`), okno rozruchowe, progi kolejnych HTTP fail oraz poprawne zmienne busa dla `systemctl --user`; backend przestal wpadać w petle restartow podczas startu.
- FIX #2: `GET /api/account/ai-status` nie wybiera juz active providera po samym `configured=true`; bierze realny primary provider z orchestratora i mapuje niedostepny local AI na jawny blad.
- Efekt operacyjny: runtime startuje stabilniej, a diagnostyka AI przestaje klamac — aktywny provider to obecnie `groq`, lokalny `ollama` jest skonfigurowany, ale nieosiagalny.
- OTWARTY BLOKER: bezposrednie lokalne probe HTTP na `/api/system/full-status`, `/api/account/runtime-activity`, `/api/account/trading-status` nadal wisza intermitentnie mimo szybkiego wykonania tych samych funkcji in-process.

## Sesja 46 — zmiany (T-126 OVERLAY UI ACTIVATION)
- Wykryto, ze `live_overlay/index.html` wystawial wiele widocznych opcji i etykiet, ale bez realnych akcji i bez przejscia do danych. Timeframe, nav sidebar i czesc sekcji byly de facto martwe.
- FIX #1: overlay ma teraz klikalny ticker, realny focus symbolu, ulubione, zakladki `Historia`, `Analizy`, `Ustaw.`, `Stream` oraz aktywne przełączanie timeframe oparte o backend.
- FIX #2: adapter `serve_live_overlay.py` pobiera endpointy równolegle zamiast sekwencyjnie, co usunelo timeouty i "martwy" overlay przy wolniejszej odpowiedzi pojedynczego endpointu.
- Efekt operacyjny: overlay nie jest juz statyczna makieta; pokazuje zywe panele i reaguje na klikniecia operatora/OBS.

## Sesja 45 — zmiany (T-125 RUNTIME CONTROLS SYNC)
- Wykryto rozjazd operatorski: Telegram, Topbar i panel WWW nie sterowaly tym samym zestawem flag runtime; czesc UI zatrzymywala tylko `demo_trading_enabled`, mimo pracy w live.
- FIX #1: backend dostal admin-protected `POST /api/system/runtime-action` z akcja `restart_runtime`, planowana asynchronicznie dla user services runtime.
- FIX #2: Telegram dostal komendy `/start_trading`, `/stop_trading`, `/reboot_bot`; legacy `/stop` zatrzymuje teraz realne execution live, nie tylko demo.
- FIX #3: web_portal ma jawne przyciski `START HANDEL`, `STOP HANDEL`, `REBOOT BOT`, a Topbar przelacza realne flagi live/execution.
- Efekt operacyjny: operator ma jeden zestaw akcji sterowania runtime w backendzie, Telegramie i WWW; zniknal falszywy przycisk stop demo-only.

## Sesja 45 — zmiany (T-125 RUNTIME CONTROLS SYNC)
- Wykryto rozjazd operatorski: Telegram, Topbar i panel WWW nie sterowaly tym samym zestawem flag runtime; czesc UI zatrzymywala tylko `demo_trading_enabled`, mimo pracy w live.
- FIX #1: backend dostal admin-protected `POST /api/system/runtime-action` z akcja `restart_runtime`, planowana asynchronicznie dla user services runtime.
- FIX #2: Telegram dostal komendy `/start_trading`, `/stop_trading`, `/reboot_bot`; legacy `/stop` zatrzymuje teraz realne execution live, nie tylko demo.
- FIX #3: web_portal ma jawne przyciski `START HANDEL`, `STOP HANDEL`, `REBOOT BOT`, a Topbar przełącza realne flagi live/execution.
- Efekt operacyjny: operator ma jeden zestaw akcji sterowania runtime w backendzie, Telegramie i WWW; zniknal fałszywy przycisk stop demo-only.

## Sesja 44 — zmiany (T-124 RUNTIME PORTABILITY + ENDPOINT ALIASES)
- Wykryto kolejny operacyjny rozjazd: czesc klientow i overlay nadal oczekiwala legacy endpointow (`/api/status`, `/api/runtime/state`, `/api/live/state`), a backend nie wystawial ich juz pod tymi sciezkami.
- Root cause #1: kompatybilnosc sciezek byla niepelna po migracji na nowsze routery.
- Root cause #2: `backend.app --all` uruchamial `web_portal` przez relatywne `cd web_portal`, co psulo portability przy starcie z innego katalogu.
- FIX #1: dodano aliasy kompatybilnosci dla status/runtime/live/positions bez duplikowania logiki biznesowej.
- FIX #2: start `web_portal` w `backend.app --all` uzywa teraz absolutnej sciezki wyliczonej z repo.
- FIX #3: overlay adapter odpyta kanoniczne endpointy i nie opiera sie juz glownie na legacy-404.
- Efekt operacyjny: starsze klienty, overlay i narzedzia operatorskie dostaja znow poprawny JSON; backend jest mniej zalezny od lokalizacji repo.

## Sesja 43 — zmiany (T-123 LIVE SIGNAL ENGINE CONTRACT FIX)
- Wykryto glowny bloker handlu live po stronie analizy: nowy `signal_engine` odrzucal wszystkie symbole jako `insufficient_klines`, mimo ze `get_live_context()` zwracal prawidlowe EMA/RSI/ATR.
- Root cause #1: `get_live_context()` nie zwracal `klines_count`, a `signal_engine` traktowal brak pola jako `0`.
- Root cause #2: `_klines_to_df()` gubil `quote_volume` i `trades`, przez co liquidity gate zbijal wiele par do `liquidity_score=0.0`.
- Root cause #3: szybki filtr `15m` byl wolany z `limit=50`, podczas gdy `get_live_context()` wymaga minimum 60 swiec, wiec `fast_above_trend` czesto bylo stale puste.
- FIX #1: `backend/analysis.py` zwraca teraz pelny kontrakt live dla `signal_engine` (`klines_count`, Bollingery, `macd_signal`, `volume_spike_ratio`, `volume_24h_quote`, `trade_count`).
- FIX #2: `_klines_to_df()` zachowuje `quote_volume`, `trades`, `taker_buy_*` zamiast obcinac je przy budowie DataFrame.
- FIX #3: `backend/trading/signal_engine.py` ma fallback dla brakujacego `klines_count` oraz pobiera fast timeframe z limitem >=60.
- Efekt operacyjny: pipeline live przestal odrzucac wszystko z powodow technicznych; po poprawce widoczne sa juz tylko realne bramki ekonomiczne (`volume_too_low`, `negative_edge_after_costs`).

## Sesja 42 — zmiany (T-121 RUNTIME PATH SYNC + TELEGRAM MODE SYNC + OVERLAY 8099)
- Wykryto glowny rozjazd operacyjny: systemd uruchamial backend/frontend/Telegram z historycznych sciezek `/media/...`, a aktualny kod i poprawki byly w `/home/...`.
- FIX #1: runtime scripts `start_backend.sh`, `start_frontend.sh`, `start_overlay.sh` sa przepiete na aktualny workspace `/home/rldc/RLdC_AiNalyzator/RLdC_AiNalyzator`.
- FIX #2: user units `rldc-backend`, `rldc-frontend`, `rldc-telegram`, `rldc-watchdog` sa przepiete na poprawne sciezki i logi w aktualnym repo.
- FIX #3: Telegram nie opiera sie juz na stalej wartosci `TRADING_MODE`; pobiera aktywny tryb z backendu i moze raportowac publiczny URL overlay.
- FIX #4: `8099` serwuje juz poprawny adapter `serve_live_overlay.py`; overlay JSON jest dostepny na `/overlay/api/live-state`.
- BLOKER ZEWNĘTRZNY: panelowy `trycloudflare` nadal zwraca `1015 / 429 Too Many Requests`, co wskazuje na rate limit po stronie Cloudflare, a nie lokalny blad backendu/frontendu.

## Sesja 41 — zmiany (T-120 LIVE PLAN SYNC + OVERLAY ADAPTER)
- Wykryto rozjazd entry→execution: LIVE pipeline liczył plan wyjścia w `risk_engine`, ale po BUY fill `collector` odbudowywał plan z fallbacku ATR, przez co pozycja mogła dostać inne `planned_tp/sl` niż te zaakceptowane przy wejściu.
- FIX #1: LIVE pending z nowego pipeline zapisuje plan trade'u (`stop_loss`, `take_profit`, `take_profit_2`, `trailing_activation_price`, `break_even_price`) w payloadzie reason.
- FIX #2: przy BUY fill collector odzyskuje ten plan i zapisuje go do `Position.planned_tp`, `Position.planned_sl` oraz `exit_plan_json`; fallback ATR działa tylko gdy brak zapisanego planu.
- FIX #3: regresja potwierdza zachowanie planu po fillu (`tests/test_live_execution_cash_management.py`).
- Runtime: fix z tej sesji zostal domkniety — adapter overlay siedzi juz na `8099`, nie na tymczasowym `8100`.

## Sesja 40 — zmiany (T-119 WWW PENDING SYNC FIX)
- Wykryto rozjazd WWW↔backend: `DecisionsRiskPanel` pobierał tylko `status=PENDING`, a manualne/webowe pending orders są tworzone kanonicznie jako `PENDING_CREATED`.
- FIX #1: `GET /api/orders/pending` obsługuje teraz CSV statusów oraz alias `ACTIONABLE`, co pozwala klientom pytać o pełną kolejkę wymagającą akcji bez ręcznego sklejanego filtrowania po stronie UI.
- FIX #2: `web_portal` używa filtra `PENDING_CREATED,PENDING`, więc licznik i lista pending nie gubią już nowych rekordów po utworzeniu zlecenia.
- FIX #3: smoke test zabezpiecza alias `ACTIONABLE` i CSV filter, aby nie wrócił rozjazd statusów po kolejnych zmianach lifecycle.
- Efekt operacyjny: panel WWW pokazuje realne pending orders oczekujące na confirm/reject/cancel zamiast pozornie pustej kolejki.

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
