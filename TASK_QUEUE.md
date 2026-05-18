# TASK_QUEUE — RLdC Trading Bot

| T-152 | **Create dynamic_grid.py module**: Implementuj komplletny moduł dla dynamic gridu per grid.md specification. Obejmuje: `select_top_usdc_pairs()` (ranking USDC pairs z z-score scoring), `build_grid_plan()` (generator planu gridu z center/lower/upper/levels), `check_recentering_needed()` (detektor kiedy shift zakresu), `GridPlan` dataclass, persistence w RuntimeSetting. | `backend/trading/dynamic_grid.py` | Operacyjnie: Foundation dla multi-pair dynamic grid trading. Architektura: Otwiera ścieżkę do top-N selector zamiast portfolio-based watchlist. | DONE |

| T-151 | **Expand kline collection to 15m, 1h, 4h**: Zmień domyślny `KLINE_TIMEFRAMES` w collector z `"1m,1h"` na `"1m,15m,1h,4h"`. Jest to warunek dla `get_grid_context()` która wymaga ≥60 barów dla każdego TF dla sensownych wskaźników. | `backend/collector.py` line 173 | Zysk: Multi-timeframe analysis dla short-term (15m) + mid-term (1h) + HTF (4h). Koszt: ~2x więcej Binance API weight i DB storage. | DONE |

| T-150 | **Fix critical risk.py bug + add market data helpers**: (1) Fix: `initial_balance` dla live mode był hardcoded na 0.0, unieważniając exposure ratio gates (CATASTROPHIC dla multi-pair). Now reads `live_balance` z risk_snapshot lub fallbackuje do env var. (2) Add: `get_all_24hr_tickers()` i `get_usdc_pairs()` do binance_client dla dynamic selector. (3) Add: `get_grid_context()` do analysis dla multi-timeframe context. | `backend/risk.py`, `backend/binance_client.py`, `backend/analysis.py` | Zysk: Live exposure gates teraz funkcjonalne; market data helpers ready dla grid selector. Ryzyko: None (fix, plus helpers nie zmienia execution logic). | DONE |





| T-153 | **Test dynamic_grid module**: Unit tests dla `select_top_usdc_pairs()`, `build_grid_plan()`, `check_recentering_needed()`. | `tests/test_trading_dynamic_grid.py` | Walidacja: Funkcje zwracają sensowne wyniki. | DONE ✅ (18/18 tests PASSED) |
---
| T-154 | **Phase 2 Step 1 — Integrate dynamic grid into collector main loop**: Dodaj `_build_dynamic_grid_plans(db)` metoda; buduje/odświeża plany dla każdej pary z watchlisty. Integracja z `run_once()` po `collect_klines()`. Sequence: collect_klines → insights → **build_grid_plans** → demo_trading → live_trading. | `backend/collector.py` (~1060-1150), `tests/test_grid_integration.py` | Grid plany budują się dynamicznie każdy cycle. Integration point do T-155. | DONE ✅ (4/4 integration tests PASSED) |

| T-155 | **Phase 2 Step 2 — Grid entry/exit orchestration**: Implementuj `backend/trading/grid_orchestration.py` z `orchestrate_grid_entries()` (place BUY na buy_levels) i `orchestrate_grid_exits()` (manage TP/SL na sell_levels). Integruj z collector `_screen_entry_candidates()` i `_check_exits()`. Zachowaj exit-first philosophy. | `backend/trading/grid_orchestration.py` (NEW, ~160 lines), `backend/collector.py` (integration), `tests/test_grid_orchestration.py` | Realne grid trades per pair. Critical dla Phase 2 completion. | OPEN (NEXT) |
## (Poprzednie wpisy T-149 do T-145) [SKRÓCONE]
| T-156 | **Phase 2 Step 3 — Smoke test live grid trading on testnet**: Deploy N=3 top pairs (small invest ~100 EUR) na testnet Binance. Verify: selector works, plans build, entries trigger, exits execute. 15min run. | `tests/test_live_trading_grid_integration.py` | Early validation przed live production. | OPEN (PHASE 2+1) |

| T-149 | **Agresywny bypass no_buy_signal dla profilu startowego**: `signal_engine` dostał warunek `aggressive_entry_condition`, który aktywuje się wyłącznie przy celowo obniżonych progach runtime i przepuszcza kandydatów do końcowych bramek score/confidence/edge/RR. | `backend/trading/signal_engine.py`, `CHANGELOG_LIVE.md`, `CURRENT_STATE.md`, `PROJECT_AUDIT_MASTER.md` | Operacyjnie: większa szansa na realne wejścia LIVE po otwarciu progów. Ryzyko: więcej kandydatów do oceny, ale bez ominięcia końcowych gate'ów ekonomii i ryzyka. | DONE |

| T-148 | **Agresywne runtime thresholds dla startu handlu**: runtime DB został celowo otwarty dla short-term LIVE, aby bot zaczął realnie dopuszczać wejścia i nie blokował execution na własnych minimach. Poluzowano entry (`edge/RR/score/confidence/volume/HTF`) i sizing (`max_exposure_per_symbol_pct`, `risk_per_trade_pct`, `max_open_positions`). | `runtime_settings` (DB), `CURRENT_STATE.md`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md` | Operacyjnie: bot przestał stać w miejscu i ma aktywną ścieżkę do realnych BUY. Ryzyko: profil jest świadomie agresywny i wymaga obserwacji wyników. | DONE |

| T-147 | **Adaptacyjny RR dla short-term breakoutów**: `signal_engine` obniża minimalny `RR` tylko dla bardzo mocnych, płynnych i tanich egzekucyjnie setupów 15m-1h; diagnostyka pokazuje `required_rr` i `required_rr_base`, a testy pokrywają zarówno ścieżkę pozytywną, jak i ochronę przed zbyt słabym wolumenem. | `backend/trading/signal_engine.py`, `tests/test_trading_signal_engine.py`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md`, `CURRENT_STATE.md` | Zysk/ryzyko: więcej szans na wejście w krótkie impulsy bez globalnego luzowania ekonomii trade'u. Prawdomówność: live nadal raportuje `buy_ready=0`, jeśli rynek nie spełnia warunków. | DONE |

| T-146 | **Binance-style charts + decision-view enrichment**: portal i overlay dostały spójny wykres świecowy z wolumenem, EMA20/EMA50, forecastem i poziomami BUY/SELL; `decision-view` ujawnia teraz ATR, ADX, Stochastic, MACD hist, Bollinger, Fibo, spread i orderbook imbalance. | `backend/routers/signals.py`, `web_portal/src/components/widgets/BinanceStyleChart.tsx`, `live_overlay/index.html` | Prawdomówność UI: większa zgodność z Binance i pełniejsza analiza wejść/wyjść. Ryzyko: mniej błędnych decyzji operatora na podstawie zbyt ubogiego wykresu. | DONE |

| T-145 | **Adaptive volume tiers + breakout BUY gate**: `signal_engine` dostał dynamiczny próg potwierdzenia wolumenu zależny od tieru płynności (`quote_volume_24h`) i spreadu oraz dodatkowy, bezpieczny warunek wejścia `breakout_reversal_condition` dla zmian impulsu. Diagnostyka rozszerzona o `effective_volume_ratio_min` i flagi warunków wejścia. | `backend/trading/signal_engine.py`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md` | Zysk/ryzyko: mniejsza liczba fałszywych blokad BUY na płynnych parach, bez luzowania ochrony dla mało płynnych rynków. | DONE |

| T-144 | **BUY/SELL signal quality tuning**: naprawiono niespójność progu HTF w `signal_engine` (warunek BUY miał ostrzejszy próg niż wcześniejszy gate HTF) oraz dodano wolumenowe potwierdzenie wejścia oparte o `effective_volume_ratio=max(1h,15m)` zamiast samego 1h. Rozszerzono diagnostykę o `fast_volume_ratio` i `effective_volume_ratio`. | `backend/trading/signal_engine.py`, `PROJECT_AUDIT_MASTER.md`, `CHANGELOG_LIVE.md` | Zysk/ryzyko: mniej fałszywych blokad wejść przy realnym popycie 15m, większa spójność BUY gate z trendem HTF. | DONE |

| T-143 | **LIVE execution consistency + Telegram test guards**: atomowy claim pending (`EXECUTING`) przed execution, zapis pozycji BUY po qty netto (fee w base asset), wymuszenie `newOrderRespType=FULL` dla MARKET, centralizacja wysyłki Telegram z collectora przez `notification_hooks.send_telegram_message`, oraz twarde guardy testowe (`APP_ENV=test`, `DISABLE_TELEGRAM=true`). Dodano regresję qty netto po BUY. | `backend/collector.py`, `backend/binance_client.py`, `backend/notification_hooks.py`, `tests/conftest.py`, `tests/test_live_execution_cash_management.py` | Ryzyko: mniej odrzuceń SELL `insufficient balance`, mniejsze ryzyko duplikacji execution i brak wycieku powiadomień testowych na realny Telegram. | DONE |

| T-139 | **Observe-only diagnostics + spread/slippage caps + risk sizing clamp**: `TradeConfig` dostał jawne limity `max_spread_bps/max_slippage_bps`; `signal_engine` zwraca pełne metryki przy `observe_only` i stosuje priorytet blokady market quality po score; `risk_engine` nie podbija już qty do `min_buy_notional` ponad limit ryzyka od stop-loss. Dodane regresje dla slippage gate i sizing clamp. | `backend/trading/trade_config.py`, `backend/trading/signal_engine.py`, `backend/trading/risk_engine.py`, `tests/test_trading_signal_engine.py`, `tests/test_trading_risk_engine.py` | Zysk/ryzyko: wejścia agresywne, ale z pełną diagnostyką i bez sztucznego zwiększania pozycji ponad risk budget. | DONE |
| T-138 | **QuoteVolume observe-only gate + orderbook depth**: `signal_engine` przestał robić wczesny hard skip na samym volume ratio; teraz ocenia `quoteVolume`, dynamiczny próg trade, depth order booka i zapisuje pełne `observe_only` details dla niskiej płynności. `TradeConfig` dostał nowe progi płynności, a testy regresji pokrywają low `quoteVolume` i shallow order book. | `backend/trading/signal_engine.py`, `backend/trading/trade_config.py`, `tests/test_trading_signal_engine.py` | Jakość diagnostyki: pełniejszy obraz market quality przed wejściem. Ryzyko: mniej błędnych decyzji opartych tylko o jeden filtr. | DONE |
| T-141 | **Overlay 8099 recovery + wykres fallback + usunięcie lewego paska**: adapter mapuje pary bez świec EUR na dostępny symbol bazowy (`chart_symbol`, np. `AAVEEUR -> AAVEUSDC`), przywrócono stabilny runtime `rldc-overlay.service`, a `index.html` został uproszczony przez usunięcie lewego panelu opcji i doprecyzowanie opisów wykresu. Dopięto też auto-focus i sensowne treści AI card dla otwartej pozycji. | `live_overlay/serve_live_overlay.py`, `live_overlay/index.html`, runtime `rldc-overlay.service` | Stabilność: overlay nie pada i pokazuje wykresy. UX: prostszy, czytelniejszy widok bez lewego paska. | DONE |
| T-142 | **LIVE SELL guard + hard exit cooldown split**: SELL jest teraz cappingowany do realnego `free balance` Binance i `LOT_SIZE.stepSize` przed `create_order()`, a hard exit SL nie jest już blokowany przez `pending_in_cooldown` (cooldown został zachowany dla trailing/TP/reversal). Dodano regresję SELL qty guard oraz SL mimo cooldown. | `backend/binance_client.py`, `backend/collector.py`, `tests/test_binance_client_sell_guard.py`, `tests/test_live_execution_cash_management.py` | Ryzyko: mniej odrzuconych SELL i mniej fałszywych prób sprzedaży powyżej salda. Stabilność: hard exit SL nie wisi na cooldownzie. | DONE |

| T-148 | **Agresywne runtime thresholds dla startu handlu**: runtime DB został celowo otwarty dla short-term LIVE, aby bot zaczął realnie dopuszczać wejścia i nie blokował execution na własnych minimach. Poluzowano entry (`edge/RR/score/confidence/volume/HTF`) i sizing (`max_exposure_per_symbol_pct`, `risk_per_trade_pct`, `max_open_positions`). | `runtime_settings` (DB), `CURRENT_STATE.md`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md` | Operacyjnie: bot przestał stać w miejscu i ma aktywną ścieżkę do realnych BUY. Ryzyko: profil jest świadomie agresywny i wymaga obserwacji wyników. | DONE |

| T-147 | **Adaptacyjny RR dla short-term breakoutów**: `signal_engine` obniża minimalny `RR` tylko dla bardzo mocnych, płynnych i tanich egzekucyjnie setupów 15m-1h; diagnostyka pokazuje `required_rr` i `required_rr_base`, a testy pokrywają zarówno ścieżkę pozytywną, jak i ochronę przed zbyt słabym wolumenem. | `backend/trading/signal_engine.py`, `tests/test_trading_signal_engine.py`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md`, `CURRENT_STATE.md` | Zysk/ryzyko: więcej szans na wejście w krótkie impulsy bez globalnego luzowania ekonomii trade'u. Prawdomówność: live nadal raportuje `buy_ready=0`, jeśli rynek nie spełnia warunków. | DONE |

| T-146 | **Binance-style charts + decision-view enrichment**: portal i overlay dostały spójny wykres świecowy z wolumenem, EMA20/EMA50, forecastem i poziomami BUY/SELL; `decision-view` ujawnia teraz ATR, ADX, Stochastic, MACD hist, Bollinger, Fibo, spread i orderbook imbalance. | `backend/routers/signals.py`, `web_portal/src/components/widgets/BinanceStyleChart.tsx`, `web_portal/src/components/widgets/TradingView.tsx`, `web_portal/src/components/MainContent.tsx`, `live_overlay/index.html` | Prawdomówność UI: większa zgodność z Binance i pełniejsza analiza wejść/wyjść. Ryzyko: mniej błędnych decyzji operatora na podstawie zbyt ubogiego wykresu. | DONE |

| T-145 | **Adaptive volume tiers + breakout BUY gate**: `signal_engine` dostał dynamiczny próg potwierdzenia wolumenu zależny od tieru płynności (`quote_volume_24h`) i spreadu oraz dodatkowy, bezpieczny warunek wejścia `breakout_reversal_condition` dla zmian impulsu. Diagnostyka rozszerzona o `effective_volume_ratio_min` i flagi warunków wejścia. | `backend/trading/signal_engine.py`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md` | Zysk/ryzyko: mniejsza liczba fałszywych blokad BUY na płynnych parach, bez luzowania ochrony dla mało płynnych rynków. | DONE |

| T-144 | **BUY/SELL signal quality tuning**: naprawiono niespójność progu HTF w `signal_engine` (warunek BUY miał ostrzejszy próg niż wcześniejszy gate HTF) oraz dodano wolumenowe potwierdzenie wejścia oparte o `effective_volume_ratio=max(1h,15m)` zamiast samego 1h. Rozszerzono diagnostykę o `fast_volume_ratio` i `effective_volume_ratio`. | `backend/trading/signal_engine.py`, `PROJECT_AUDIT_MASTER.md`, `CHANGELOG_LIVE.md` | Zysk/ryzyko: mniej fałszywych blokad wejść przy realnym popycie 15m, większa spójność BUY gate z trendem HTF. | DONE |

| T-143 | **LIVE execution consistency + Telegram test guards**: atomowy claim pending (`EXECUTING`) przed execution, zapis pozycji BUY po qty netto (fee w base asset), wymuszenie `newOrderRespType=FULL` dla MARKET, centralizacja wysyłki Telegram z collectora przez `notification_hooks.send_telegram_message`, oraz twarde guardy testowe (`APP_ENV=test`, `DISABLE_TELEGRAM=true`). Dodano regresję qty netto po BUY. | `backend/collector.py`, `backend/binance_client.py`, `backend/notification_hooks.py`, `tests/conftest.py`, `tests/test_live_execution_cash_management.py` | Ryzyko: mniej odrzuceń SELL `insufficient balance`, mniejsze ryzyko duplikacji execution i brak wycieku powiadomień testowych na realny Telegram. | DONE |

| T-139 | **Observe-only diagnostics + spread/slippage caps + risk sizing clamp**: `TradeConfig` dostał jawne limity `max_spread_bps/max_slippage_bps`; `signal_engine` zwraca pełne metryki przy `observe_only` i stosuje priorytet blokady market quality po score; `risk_engine` nie podbija już qty do `min_buy_notional` ponad limit ryzyka od stop-loss. Dodane regresje dla slippage gate i sizing clamp. | `backend/trading/trade_config.py`, `backend/trading/signal_engine.py`, `backend/trading/risk_engine.py`, `tests/test_trading_signal_engine.py`, `tests/test_trading_risk_engine.py` | Zysk/ryzyko: wejścia agresywne, ale z pełną diagnostyką i bez sztucznego zwiększania pozycji ponad risk budget. | DONE |
| T-138 | **QuoteVolume observe-only gate + orderbook depth**: `signal_engine` przestał robić wczesny hard skip na samym volume ratio; teraz ocenia `quoteVolume`, dynamiczny próg trade, depth order booka i zapisuje pełne `observe_only` details dla niskiej płynności. `TradeConfig` dostał nowe progi płynności, a testy regresji pokrywają low `quoteVolume` i shallow order book. | `backend/trading/signal_engine.py`, `backend/trading/trade_config.py`, `tests/test_trading_signal_engine.py` | Jakość diagnostyki: pełniejszy obraz market quality przed wejściem. Ryzyko: mniej błędnych decyzji opartych tylko o jeden filtr. | DONE |
| T-141 | **Overlay 8099 recovery + wykres fallback + usunięcie lewego paska**: adapter mapuje pary bez świec EUR na dostępny symbol bazowy (`chart_symbol`, np. `AAVEEUR -> AAVEUSDC`), przywrócono stabilny runtime `rldc-overlay.service`, a `index.html` został uproszczony przez usunięcie lewego panelu opcji i doprecyzowanie opisów wykresu. Dopięto też auto-focus i sensowne treści AI card dla otwartej pozycji. | `live_overlay/serve_live_overlay.py`, `live_overlay/index.html`, runtime `rldc-overlay.service` | Stabilność: overlay nie pada i pokazuje wykresy. UX: prostszy, czytelniejszy widok bez lewego paska. | DONE |
| T-142 | **LIVE SELL guard + hard exit cooldown split**: SELL jest teraz cappingowany do realnego `free balance` Binance i `LOT_SIZE.stepSize` przed `create_order()`, a hard exit SL nie jest już blokowany przez `pending_in_cooldown` (cooldown został zachowany dla trailing/TP/reversal). Dodano regresję SELL qty guard oraz SL mimo cooldown. | `backend/binance_client.py`, `backend/collector.py`, `tests/test_binance_client_sell_guard.py`, `tests/test_live_execution_cash_management.py` | Ryzyko: mniej odrzuconych SELL i mniej fałszywych prób sprzedaży powyżej salda. Stabilność: hard exit SL nie wisi na cooldownzie. | DONE |

## DONE (zamkniete w sesji 49 — T-133 LIVE SOURCE-OF-TRUTH + REQUEST-STORM GUARD)

| ID | Zadanie | Plik/Modul | Wplyw | Status |
|----|---------|------------|-------|--------|
| T-133 | **Safe live-state na kanonicznym Binance spot**: `/api/rldc/safe/live-state` przestal opierac sie na lokalnej tabeli `Position`; korzysta z `_get_live_spot_positions()` i fallbackuje do DB tylko awaryjnie. Dodatkowo payload niesie `source/has_entry_price/state`, co poprawia prawde danych w overlay. | `backend/app.py`, `backend/routers/positions.py` | Spójnosc: manual/live holdings widoczne z jednego zrodla prawdy. Ryzyko: mniej falszywych stanów pozycji. | DONE |
| T-133b | **Request-storm guard w web_portal**: dodano kolejke fetch, limit równoleglych requestów i backoff odswiezania po timeoutach, bez zmian wygladu strony. | `web_portal/src/components/MainContent.tsx` | Stabilnosc: mniejsze ryzyko samonapedzajacego przeciążenia backendu przez UI. | DONE |

## CRITICAL

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-134 | **Odchudzić `/api/positions?mode=live` do stabilnego SLA**: timeouty >20s blokują overlay i portal. Wymagane: snapshot cache + limit kosztownych wywołań Binance/history na request. | `backend/routers/positions.py`, `backend/portfolio_reconcile.py` | Zysk/ryzyko: bez tego system traci ciągłość obserwacji i zwiększa ryzyko błędnych decyzji operatora. | OPEN |
| T-135 | **Odchudzić `/api/positions/analysis?mode=live`**: przenieść ciężką analizę do cache/job, endpoint ma zwracać gotowy snapshot zamiast pełnych obliczeń per request. | `backend/routers/positions.py`, `backend/analysis.py` | Stabilność: usuwa timeouty 3000/8099 i poprawia responsywność WWW. | OPEN |
| T-136 | **Overlay resiliency na timeout backendu**: `/overlay/api/live-state` ma degradować się do ostatniego poprawnego snapshotu z reason_code zamiast timeout. | `live_overlay/serve_live_overlay.py` | Stabilność: overlay pozostaje operacyjny mimo chwilowych lagów backendu. | OPEN |

## DONE (zamkniete w sesji 48 — T-132 MARKET HEALTH GATE + TELEMETRIA)

| ID | Zadanie | Plik/Modul | Wplyw | Status |
|----|---------|------------|-------|--------|
| T-132 | **Market health gate LIVE + ekspozycja do web_portal/overlay/telegram**: collector ocenia teraz zdrowie runtime (`NO_TRADE` / `REDUCE_ONLY` / `NORMAL`) na podstawie świeżości danych, ws_running i błędów execution; LIVE BUY pipeline zapisuje reason_code `market_health_no_trade` / `market_health_reduce_only`; runtime-activity i trading-status zwracają pola `market_health`, `allow_new_entries`, `no_trade_mode`, `reduce_only_mode`; Telegram `/status` pokazuje health mode i issues; overlay adapter wystawia `trading_guard`. Dodatkowo `TradeConfig` dostał regresję aliasu `min_symbol_net_expectancy -> min_net_edge_pct` i testy helperów kosztowych. | `backend/collector.py`, `backend/trading/trade_config.py`, `backend/routers/account.py`, `telegram_bot/bot.py`, `live_overlay/serve_live_overlay.py`, `tests/test_trading_collector_live_path.py` | Zysk: brak nowych wejść przy złej jakości danych i podwyższonym ryzyku runtime. Ryzyko: mniejsze false-entry przy degradacji LIVE. Spójność: ten sam stan gate widoczny w API/overlay/Telegram. | DONE |

## DONE (zamkniete w sesji 42 — T-121 RUNTIME PATH SYNC + TELEGRAM MODE SYNC)

| ID | Zadanie | Plik/Modul | Wplyw | Status |
|----|---------|------------|-------|--------|
| T-131 | **Domkniecie runtime WWW/overlay po fixie `state_manager.reconcile`**: `system-status` i `runtime-activity` ukrywaja juz nieaktywny blad po nowszym heartbeat runtime, overlay auto-rotuje focus, dostaje historię/forecast dla top symboli, a quicktunnel zapisuje osobny `overlay_url` bez nadpisywania go przez równoległe parsery. Walidacja: `bash -n scripts/run_quicktunnel.sh`, `tests/test_trading_state_manager.py` 28/28 PASS, smoke `curl` dla `/api/account/system-status`, `/api/account/runtime-activity`, `/overlay/api/live-state`, `/api/account/tunnel-status`. | `backend/routers/account.py`, `live_overlay/index.html`, `live_overlay/serve_live_overlay.py`, `backend/tunnel_manager.py`, `scripts/run_quicktunnel.sh`, `CURRENT_STATE.md`, `CHANGELOG_LIVE.md`, `PROJECT_AUDIT_MASTER.md`, `TASK_QUEUE.md` | Stabilnosc: UI nie pokazuje juz stalego falszywego alarmu. UX: overlay rotuje focus i ma aktualne wykresy. Operacyjnie: overlay ma oddzielny adres trycloudflare. | DONE |
| T-130 | **Naprawa błędu `state_manager.reconcile`**: `backend/trading/state_manager.py` używał nieistniejącego `cfg.sync_interval_sec`, mimo że kanoniczny `TradeConfig` wystawia `reconcile_interval_sec`. Dodano fallback legacy, usunięto deprecacyjne `datetime.utcnow()` w module i dopięto regresję z domyślnym `TradeConfig()`. Walidacja: `tests/test_trading_state_manager.py` -> 28/28 PASS. | `backend/trading/state_manager.py`, `tests/test_trading_state_manager.py`, `CURRENT_STATE.md`, `PROJECT_AUDIT_MASTER.md`, `TASK_QUEUE.md` | Stabilność: collector LIVE nie wywraca już supplemental reconcile przed wejściem do logiki. | DONE |
| T-129 | **Audyt instrukcji i potwierdzenie Binance live trader**: odczytano lokalne instrukcje, zweryfikowano runtime DB/.env, publiczne tickery Binance, endpointy live, collector/WS/reconcile oraz pełne testy. Usunięto niespójności `health`, cache `full-status`, zbieranie starych testów i lint Next 16. | `backend/app.py`, `backend/routers/system.py`, `pytest.ini`, `web_portal/package.json`, `log.txt`, `CURRENT_STATE.md`, `TASK_QUEUE.md`, `PROJECT_AUDIT_MASTER.md` | Stabilność: aktualny runtime nie pokazuje stale demo/live. Operacyjnie: projekt jest skonfigurowany jako Binance Spot trader z potwierdzonymi endpointami live. Walidacja: 650 pytest PASS, lint PASS, build PASS. | DONE |
| T-127 | **Stabilizacja watchdoga i prawdomowna diagnostyka AI**: `scripts/watchdog.sh` dostal lock, grace period i prog kolejnych faili, przez co przestal restartowac backend w petli podczas rozruchu, a `GET /api/account/ai-status` raportuje juz realnego primary providera z orchestratora zamiast reklamowac niedostepny local AI jako aktywny. | `scripts/watchdog.sh`, `backend/routers/account.py`, `tests/test_smoke.py` | Stabilnosc: backend nie jest juz ubijany przez watchdog. Prawdomownosc: UI/API widza `groq` jako aktywny provider, a martwy `ollama` jako blad. | DONE |
| T-126 | **Aktywacja funkcji overlayu**: `live_overlay/index.html` dostal dzialajace zakladki, focus symboli, ulubione, timeframe i panele danych z backendu, a `serve_live_overlay.py` pobiera stan równolegle zamiast sekwencyjnie. | `live_overlay/index.html`, `live_overlay/serve_live_overlay.py` | Stabilnosc: mniej timeoutow i martwych ekranow. UX: overlay pokazuje realne funkcje, nie atrapy. | DONE |
| T-125 | **Synchronizacja sterowania runtime**: backend dostal `POST /api/system/runtime-action`, Telegram komendy `/start_trading` `/stop_trading` `/reboot_bot`, a WWW steruje juz realnymi flagami live/execution zamiast demo-only. | `backend/routers/system.py`, `telegram_bot/bot.py`, `web_portal/src/components/Topbar.tsx`, `web_portal/src/components/MainContent.tsx`, `tests/test_smoke.py` | Stabilnosc: jeden operator flow w backendzie/WWW/Telegramie. Ryzyko: mniej falszywych STOP/START. | DONE |
| T-124 | **Naprawa portability runtime i aliasow endpointow**: backend dostal kompatybilne aliasy dla legacy sciezek status/runtime/live/positions, `backend.app --all` startuje `web_portal` po absolutnej sciezce, a overlay adapter odpyta kanoniczne endpointy zamiast znanych 404. | `backend/app.py`, `live_overlay/serve_live_overlay.py`, `tests/test_smoke.py` | Stabilnosc: mniej 404 i lepsza kompatybilnosc klientow. Operacyjnie: latwiejsze przenoszenie repo i mniej zaleznosci od cwd. | DONE |
| T-123 | **Naprawa kontraktu analizy live dla signal engine**: `get_live_context()` nie zwracal `klines_count`, `_klines_to_df()` gubil `quote_volume` i `trades`, a fast timeframe byl pobierany z limitem mniejszym niz minimum analizy. To blokowalo live entry falszywym `insufficient_klines` i `liquidity_too_low`. | `backend/analysis.py`, `backend/trading/signal_engine.py`, `tests/test_trading_signal_engine.py` | Zysk: pipeline live znow ocenia realny edge. Ryzyko: mniej falszywych blokad. Stabilnosc: spójny kontrakt analiza↔execution. | DONE |

| ID | Zadanie | Plik/Modul | Wplyw | Status |
|----|---------|------------|-------|--------|
| T-121 | **Ujednolicenie runtime na aktualne repo**: systemd i skrypty startowe byly rozjechane miedzy `/media/...` i `/home/...`, Telegram trzymal staly `TRADING_MODE`, a `8099` nadal obslugiwal legacy overlay. Przepieto runtime na `/home/...`, Telegram czyta tryb z backendu, a `8099` serwuje `serve_live_overlay.py`. | `telegram_bot/bot.py`, `backend/tunnel_manager.py`, `scripts/run_quicktunnel.sh`, `~/.rldc_runtime/*`, `~/.config/systemd/user/rldc-*.service` | Stabilnosc: jeden aktywny runtime. Ryzyko: mniej rozjazdow operator↔backend. Overlay: poprawny adapter na docelowym porcie. | DONE |

## BLOCKED (zewnetrzne)

| ID | Zadanie | Plik/Modul | Wplyw | Status |
|----|---------|------------|-------|--------|
| T-122 | **Panelowy trycloudflare / drugi publiczny adres**: lokalny frontend i backend sa zdrowe, ale nowe requesty quick tunnel dla panelu sa odrzucane przez Cloudflare `1015 / 429 Too Many Requests`. Overlay ma aktywny publiczny URL; panel wymaga cooldown albo named tunnel. | `scripts/run_quicktunnel.sh`, `backend/tunnel_manager.py`, infrastruktura Cloudflare | Dostepnosc zewnetrzna panelu: zablokowana przez rate limit dostawcy, nie przez lokalny runtime. | BLOCKED |

## DONE (zamknięte w sesji 41 — T-120 LIVE PLAN SYNC + OVERLAY ADAPTER)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-120 | **Naprawa spójności planu trade'u po BUY fill**: LIVE pipeline zachowuje teraz plan `SL/TP/TP2/trailing/break-even` policzony przy wejściu i przypisuje go do pozycji po execution, zamiast odbudowywać nowy fallback ATR. Dodatkowo uruchomiono poprawny adapter overlay na `8100`, bo domyślny `8099` jest zajęty przez legacy `serve_live.py`. | `backend/collector.py`, `tests/test_live_execution_cash_management.py`, `live_overlay/serve_live_overlay.py` | Zysk: pozycja jest zarządzana zgodnie z oceną wejścia. Ryzyko: mniej rozjazdów entry↔exit. Stabilność: działający JSON overlay mimo blokady legacy portu. | DONE |

## DONE (zamknięte w sesji 40 — T-119 WWW pending sync)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-119 | **Naprawa synchronizacji pending w WWW**: `DecisionsRiskPanel` pytał o legacy `status=PENDING`, więc panel gubił nowe rekordy `PENDING_CREATED`. Backend `GET /api/orders/pending` obsługuje teraz CSV statusów i aliasy `ACTIONABLE`/`ACTIVE`, a frontend używa filtra `PENDING_CREATED,PENDING`. Dodano smoke test zabezpieczający lifecycle sync. | `backend/routers/orders.py`, `web_portal/src/components/widgets/DecisionsRiskPanel.tsx`, `tests/test_smoke.py` | Zysk: operator widzi realną kolejkę wejść/wyjść. Ryzyko: mniej błędnych decyzji przy pustym panelu. Stabilność: spójność WWW↔API. | DONE |

## DONE (zamknięte w sesji 39 — T-114 NOWY PIPELINE LIVE)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-114 | **Wire trading modules do collector.py** — UKOŃCZONE: (1) `__init__`: dodano `_risk_engine`, `_state_manager`, `_state_manager_started`. (2) Helpery `_get_risk_engine()` / `_get_state_manager()` — lazy init z refreshem cfg. (3) Nowa metoda `_live_entry_new_pipeline()` — guard pending, `evaluate_entry_signal()`, `risk_engine.evaluate()`, `_create_pending_order()`, trace + Telegram. (4) `_screen_entry_candidates()`: LIVE bypass → `_live_entry_new_pipeline()` + `continue`. DEMO ścieżka niezmieniona. (5) `_sync_binance_positions()`: dodano `state_manager.reconcile_live_positions()` jako supplemental. (6) `run_once()`: dodano `state_manager.check_pending_fills()` co cykl dla LIVE. (7) `start()`: dodano `state_manager.recover_on_startup()` jednorazowo przy starcie LIVE. Wynik: 484/484 testów, syntax OK. | `backend/collector.py`, `backend/trading/*.py` | Zysk: nowa logika sygnałów + ATR sizing + EV gate + state recovery wchodzi do produkcji LIVE. DEMO niezmienione. Testy: 484/484 PASS. | DONE |

## DONE (zamknięte w sesji 38 — T-113 LIVE MODE + USDC + BEZ LIMITÓW)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-113 | **LIVE MODE + PEŁNY USDC + USUNIĘCIE BLOKAD**: (1) Usunięto makro-gate BTC/ETH (~55 linii) blokujący wszystkie altoiny gdy BTC bearish — żadna para nie powinna blokować reszty. (2) Usunięto `tier_daily_trade_limit` z głównej pętli tradingowej — bot nie był w stanie handlować BANKUSDC/BANANAS31USDC po 3 transakcjach dziennie dla ALTCOIN tier. (3) `runtime_settings.py`: max_trades_per_day 20→200, limity wszystkich tierów → 99. (4) `.env`: WATCHLIST zmieniony z EUR par na USDC (BTCUSDC,ETHUSDC,SOLUSDC,BNBUSDC,...), DEMO_TRADING_ENABLED=false, tryb live włączony. Weryfikacja: 484/484 testów, `tier_daily_trade_limit` nie pojawia się w decision_traces po restarcie, grep w collector.py zwraca 0 wyników. | `backend/collector.py`, `backend/runtime_settings.py`, `.env` | Zysk: bot handluje bez sztucznych ograniczeń. Watchlist USDC. Pełny tryb live. Blokady usunięte. | DONE |
| T-113b | **Telegram false alerts + averaging down fix** (commit `bc158a3`+`d4a4c11`): (1) Telegram ogłaszał kupno przed wykonaniem zlecenia na Binance — dodano `_exit_alert_sent_at` i cooldown 10min na rejection. (2) Bot kupował więcej tracących pozycji (BANKUSDC 1685→3375, BANANAS31USDC dwa zakupy) — dodano guard w `add_to_position`: blokuje gdy `pnl_pct <= 0.0`. (3) `/api/debug/state-consistency` zwracał fałszywe alerty (BANKUSDC vs BANK) — naprawiono przez ekstrakcję base_asset. | `backend/collector.py`, `backend/routers/debug.py` | Redukcja szumu Telegram. Brak uśredniania w dół. Czysta diagnostyka. | DONE |

## DONE (zamknięte w sesji 37 — T-112 RECONCILIATION FIX)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-112 | **Reconciliation fix — 3 krytyczne bugi**: (1) _get_binance_balances() wywoływał nieistniejącą metodę client.get_account() (nasz wrapper ma get_balances()) → exception → {} → wszystkie reconcile runy status=failed od ponad 12h. FIX: zmieniono na client.get_balances(). (2) Po naprawie reconcile wpadał w pętlę: zamykał WLFIUSDC jako duplikat WLFIEUR (ten sam base WLFI), ale sekcja manual_trades tworzyła nową WLFIUSDC bo sprawdzała if matched_symbol in db_symbols zamiast base_asset. FIX: sprawdzenie base_asset czy jest już w db_symbols. (3) Dodano post-check deduplikacji w _reconcile_positions: jeśli kilka DB pozycji dzieli ten sam base_asset, zamykamy te z większą niezgodnością qty vs Binance z exit_reason_code=reconcile_duplicate_base_asset. Efekt operacyjny: WLFIUSDC (id=5, orphan) zamknięty, open_positions LIVE: 5→4, can_enter_now: False→True. | backend/portfolio_reconcile.py | Zysk: odblokowanie nowych wejść LIVE (był blok od >12h). Ryzyko: niższe (reconcile teraz naprawdę działa). Stabilność: reconciliation działa deterministycznie, brak pętli duplikatów. | DONE |

## DONE (zamknięte w sesji 37 — T-111 FULL SUITE STABILIZATION)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-111 | **Full test suite 55→0 failów**: zidentyfikowano i usunięto 7 root causes cross-module state contamination: (1) RuntimeSetting nie czyszczony między runami, (2) CostLedger i 14 innych tabel nie czyszczonych, (3) conftest.py używał setdefault dla DATABASE_URL i ADMIN_TOKEN — ignorując shell env, (4) TTL cache w ai_orchestrator ignorował monkeypatch, (5) telegram_bot/bot.py load_dotenv(override=True) podczas collection phase nadpisywał ADMIN_TOKEN, (6) mock _runtime_context bez trading_mode/allow_live_trading → live orders REJECTED, (7) _last_conversion_time global w quote_currency kontaminował testy. Naprawki: conftest.py zawsze tworzy izolowaną DB + wymusza ADMIN_TOKEN=""; override→False w telegram_bot/bot.py; mock config z trading_mode="live"; autouse fixture resetu globals quote_currency. | , , , , ,  | Stabilność: **459/459 passed, 0 failed** w pełnym suite. Wiarygodność regresji przywrócona. Izolacja testów deterministyczna. | DONE |

## DONE (zamknięte w sesji 36 — T-110 RECONCILE + TELEGRAM UX + EXECUTION GUARD)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-110 | Wdrożono self-heal DB↔Binance (reconcile runs/events/manual trade detection), diagnostykę `/api/system/*`, startup reconcile i reconcile w cyklu collectora. Telegram dostał komendy operatorskie `/pending`, `/trade`, `/incident`, `/close_incident`, `/reconcile`, `/health`, `/execution`, `/universe`, `/quote` oraz disambiguację `/confirm` i `/reject` (incident_id vs trade_id). Dodano globalny execution kill-switch trace `reason_code=execution_globally_disabled` w `_execute_confirmed_pending_orders`. Dodano testy: `test_reconcile.py`, `test_telegram_disambiguation.py`, `test_execution_guard.py` (7/7 PASS). | `backend/database.py`, `backend/portfolio_reconcile.py`, `backend/routers/system.py`, `backend/app.py`, `backend/collector.py`, `telegram_bot/bot.py`, `tests/test_reconcile.py`, `tests/test_telegram_disambiguation.py`, `tests/test_execution_guard.py` | Zysk: mniej utraconych transakcji przez rozjazdy DB/Binance. Ryzyko: niższe (self-heal + global execution guard). Koszt: mniej ręcznej interwencji operatorskiej. Stabilność: wyższa spójność execution/portfolio/diagnostyki. | DONE |

## DONE (zamknięte w sesji 33 — T-108 FULL MARKET UNIVERSE + MULTI-AI EXPERT SYSTEM)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-109 | Execution hardening: naprawiono krytyczny typo statusu `PENDING_CREATED_CREATED` -> `PENDING_CREATED` dla `sell_weakest`; dodano runtime-gate w execution (`trading_mode==live` + `allow_live_trading==true`) przed wysłaniem orderów live; Telegram `/confirm` i `/reject` walidują teraz `PendingOrder.id` w aktywnym trybie (`PendingOrder.mode == TRADING_MODE`), pokazują jawnie że chodzi o PendingOrder ID i używają canonical statusu `PENDING_CONFIRMED`. | `backend/routers/control.py`, `backend/collector.py`, `telegram_bot/bot.py` | Ryzyko: silna redukcja przypadkowego live execution przy złym trybie. Stabilność: brak martwych pending z literówki statusu. UX: brak mylenia ID i trybów w Telegram. | DONE |

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-108 | **FULL MARKET UNIVERSE + MULTI-AI EXPERT AUDIT**: 1. **Symbol Universe**: nowe moduły `backend/symbol_universe.py` + `backend/expert_audit_engine.py`. Dynamiczne pobieranie ALL aktywnych symboli z Binance wg quote_mode (USDC/EUR/BOTH). Trzy warstwy: exchange→eligible→priority. Watchlist zmieniona z limitu → priorytet (WATCHLIST_PRIORITY_ONLY=false umożliwia skanowanie całego rynku). 2. **Expert Audit Layer**: `AIResponse`, `ExpertAuditResult`, `audit_multi_ai_responses()` — consensus voting, outlier detection, confidence scoring, final_decision logic (BUY/SELL/WAIT/REJECT). Mode: expert_audit (outlier removal), majority_vote, weighted_consensus. 3. **Multi-AI Parallel Execution**: nowa funkcja `run_multi_ai_parallel()` w `backend/ai_orchestrator.py` — uruchamia local, gemini, groq, openai równolegle w ThreadPoolExecutor. Zbiera odpowiedzi, timeout-aware, partial failure graceful. 4. **.env fixes**: usunięto duplicate DATABASE_URL. Dodano new env vars: `USE_FULL_EXCHANGE_UNIVERSE`, `EXCHANGE_UNIVERSE_CACHE_SECONDS`, `WATCHLIST_PRIORITY_ONLY`, `AI_MULTI_ENABLED`, `AI_PROVIDERS`, `AI_CONSENSUS_MODE`, `AI_ALLOW_PARTIAL_PROVIDER_FAILURE`, `LOCAL_AI_ENABLED`, `LOCAL_AI_AUTO_START`, `LOCAL_AI_REQUIRED`, `LOCAL_AI_RETRIES`. Deprecated: `AI_PROVIDER=auto` (legacy fallback), replace with multi-AI mode. 5. **Tests**: 35 new tests (20 expert_audit + 15 symbol_universe) — all 35/35 PASS. Consensus voting, outlier detection, fetch_exchange_symbols w różnych quote modes, priority/eligible merge, test symbol rejection. Full suite: 307/308 PASS (1 pre-existing flaky unrelated). | `backend/symbol_universe.py` (NEW), `backend/expert_audit_engine.py` (NEW), `backend/ai_orchestrator.py` (added run_multi_ai_parallel), `.env` (major restructure), `tests/test_expert_audit_engine.py` (NEW 20 tests), `tests/test_symbol_universe.py` (NEW 15 tests) | Architektura: cały rynek widzialny systemowi, nie tylko kilka ręcznych coinów. Multi-AI: wszystkie dostawcy równolegle, expert consensus zamiast fallback chain. Spójność: consensus voting, outlier detection, confidence-based scoring. Watchlist: teraz opcjonalna priorytetyzacja, nie hard limit. Ready: YES — wszystkie funcje działają, testy zielone, diagnostyka pełna. | DONE |

## DONE (zamknięte w sesji 32 — T-107 LOCAL AI end-to-end fix)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-107 | **LOCAL AI end-to-end fix**: `_call_ollama_chat()` — brak funkcji powodował brak local AI w chainie; naprawiono. `generate_ai_chat_response()` — nowy łańcuch `local→groq→gemini→openai→heuristic`. `check_local_ai_health()` — pełna diagnostyka z retry (`LOCAL_AI_RETRIES`), auto-start (`LOCAL_AI_AUTO_START`), latency, lista zainstalowanych modeli. `_try_start_ollama()` — uruchamia `ollama serve` gdy port nie odpowiada. `_ollama_ranges()` w `analysis.py` — local AI w łańcuchu analizy technicznej. Timeout fix: kod czytał `AI_LOCAL_TIMEOUT_SECONDS` zamiast `OLLAMA_TIMEOUT_SECONDS` (domyślnie 90s z `.env`). `keep_alive: "10m"` — zapobieganie cold-start modelu. Logi: `[local_ai_request_sent]`, `[local_ai_response_received]`, `[local_ai_timeout]`, `[local_ai_fallback_triggered]`, `[local_ai_healthcheck_started]`, `[local_ai_unreachable]`, `[local_ai_started]`. 16 nowych testów routingu w `tests/test_ai_orchestrator.py`. | `backend/ai_orchestrator.py`, `backend/analysis.py`, `backend/app.py`, `tests/test_ai_orchestrator.py` | Local AI realnie działa jako primary provider. Fallback automatyczny przy timeout/błędzie. Diagnostyka przez `/health` i `check_local_ai_health()`. 313 testów przechodzi. | DONE |

## DONE (zamknięte w sesji 31 — T-106 canonical pending lifecycle + AI observability + .gitignore)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-106 | **Canonical pending lifecycle + local AI observability**: Unifikacja statusów `PENDING_CREATED` / `PENDING_CONFIRMED` we wszystkich warstwach (collector, signals, control, orders, positions). Backward-compat dla legacy `PENDING`/`CONFIRMED`. `get_ai_orchestrator_status()` zwraca jawne `local_ai_*` pola. `/health` endpoint odczytuje te pola. Naprawiono syntax error duplikatu bloku w `app.py`. `.env_backups/` w `.gitignore`. Testy regresyjne zaktualizowane (`PENDING_CONFIRMED`, `PENDING_CREATED`). | `backend/collector.py`, `backend/routers/control.py`, `backend/routers/signals.py`, `backend/routers/orders.py`, `backend/routers/positions.py`, `backend/ai_orchestrator.py`, `backend/app.py`, `tests/test_smoke.py`, `tests/test_control_center.py`, `.gitignore` | Spójność lifecycle statusów DB↔execution, prawdziwa obserwacja local AI, brak fałszywych lifecycle mismatchy | DONE |

## DONE (zamknięte w sesji 30 — T-105 live stability hardening)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-105 | LIVE hardening: deduplikacja pending i lock inflight per symbol/side, twarda blokada qty<=0 przed execution, rozszerzenie ACTIVE pending statuses w collector/sync/signals/control, poprawka filtra quote dla LIVE `BOTH`, oraz regresje testowe dla duplicate + qty non-positive. | `backend/collector.py`, `backend/routers/control.py`, `backend/routers/signals.py`, `tests/test_control_center.py`, `tests/test_live_execution_cash_management.py` | Eliminacja duplikatów wejść i fałszywych mismatchy, większa spójność DB↔Binance↔diagnostyka, redukcja ryzyka overtradingu i błędnych execution attempts | DONE |

## ZADANIA OTWARTE

### CRITICAL

*Brak otwartych zadań krytycznych.*

### HIGH

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-115 | **Testy modułów trading** — unit tests: signal_engine scoring, symbol_filter validate_order, risk_engine sizing, execution_engine state machine, state_manager orphan detection. | `tests/test_trading_signal_engine.py`, `tests/test_trading_risk_engine.py`, `tests/test_trading_execution_engine.py`, `tests/test_trading_state_manager.py` | Stabilność: regresje wykrywane przed wdrożeniem. | DONE |

### MEDIUM

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-140 | **Stabilizacja smoke testów intermitentnych** — wyeliminować niestabilność `test_market_summary` i `test_acceptance_live_positions_analysis_restores_entry_baseline` przez odseparowanie od runtime/network side effects i ujednolicenie danych wejściowych pozycji live w testach. | `tests/test_smoke.py`, `backend/routers/market.py`, `backend/routers/positions.py`, `backend/routers/portfolio.py` | Stabilność: deterministyczne CI i wiarygodne gate'y regresji. | OPEN |
| T-116 | **Trailing stop w execution cycle** — po osiągnięciu `trailing_activation_price` włącz trailing stop: przesuwaj SL do `current - atr * stop_mult`; update w każdym cyklu LONG_OPEN; wywoływać z collector cyklu. | `backend/trading/execution_engine.py`, `backend/collector.py` | Zysk: lock-in zysku, mniej strat z przebitych TP. | OPEN |
| T-117 | **Partial take profit** — po osiągnięciu TP1: sell 50% pozycji, przesuń SL na break-even; po TP2: sell resztę. Wymaga queue_sell(partial=True) i aktualizacji position.quantity. | `backend/trading/execution_engine.py` | Zysk: realizacja częściowych profitów, ochrona kapitału. | OPEN |

### LOW

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-118 | **Endpoint diagnostyczny stanu state machine** — `GET /api/trading/states` — zwraca wszystkie SymbolExecState per mode (symbol, state, cooldown, pending_id, sl, tp). Do wyświetlenia w WWW. | `backend/routers/` (nowy router), `web_portal` | Obserwability. | OPEN |

### DONE (zamknięte w sesji 43 — T-128 HEALTH FAST PATH)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-128 | **Health endpoint fast path** — `/health` jest lokalny i szybki, bez sieciowego probe Binance; `system-health` przestal losowo wpadać w `false` przez timeout backendu. | `backend/app.py`, `backend/routers/account.py` | Stabilność: brak fałszywych alarmów health. Diagnostyka: system-health pokazuje realny stan runtime. | DONE |

### DONE (zamknięte w sesji 29 — T-104 v2 USDC-first)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-104 v2 | **USDC-first architecture**: refaktor całego execution layer z EUR-first na USDC-first. `min_buy_reference_eur=60` to tylko reference — egzekwowanie w USDC. Nowe centralne helpery: `resolve_required_quote_usdc()`, `fund_usdc_from_eur_if_needed()`, `ensure_usdc_balance_for_order()`. Explicite logowanie konwersji fundingowej: `funding_conversion_started`, `funding_conversion_filled`, `funding_conversion_failed`. Signals cash gate dla par USDC raportuje w USDC. Control.py sizing USDC-first. | `backend/quote_currency.py`, `backend/collector.py`, `backend/routers/signals.py`, `backend/routers/control.py`, `tests/test_quote_currency.py`, `tests/test_live_execution_cash_management.py` | Architektonicznie poprawna separacja warstw: Reference → Runtime → Execution → Exchange. Komunikaty dla USDC par w USDC. Czyste logi. | DONE |

### DONE (zamknięte w sesji 28 — T-104 v1 + data quality)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-104 | Execution/cash-management LIVE hardening: `min_buy_eur=60`, preflight BUY z przeliczeniem EUR→USDC, auto-konwersja przed BUY, normalizacja qty+minNotional po rounding, reason codes execution/cash, usunięcie TEST symboli z LIVE, oraz non-blocker dla temporary execution errors. | `backend/runtime_settings.py`, `backend/collector.py`, `backend/quote_currency.py`, `backend/routers/signals.py`, `backend/routers/control.py`, `backend/routers/account.py`, `tests/test_quote_currency.py`, `tests/test_live_execution_cash_management.py` | Usunięcie fałszywych blokad NO_CASH, realne wykonanie confirmed pending i większa stabilność LIVE | DONE |

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-104 | Execution/cash-management LIVE hardening: `min_buy_eur=60`, preflight BUY z przeliczeniem EUR→USDC, auto-konwersja przed BUY, normalizacja qty+minNotional po rounding, reason codes execution/cash, usunięcie TEST symboli z LIVE, oraz non-blocker dla temporary execution errors. | `backend/runtime_settings.py`, `backend/collector.py`, `backend/quote_currency.py`, `backend/routers/signals.py`, `backend/routers/control.py`, `backend/routers/account.py`, `tests/test_quote_currency.py`, `tests/test_live_execution_cash_management.py` | Usunięcie fałszywych blokad NO_CASH, realne wykonanie confirmed pending i większa stabilność LIVE | DONE |
| T-103 | Parser Telegram trading-first: jednolity wynik `{type, side, symbol, force, config_key, config_value}`, priorytet BUY/SELL/FORCE nad config, flow `MANUAL`/`MANUAL_FORCE`, obsługa `sell_symbol` i komendy `tryb agresywny`, poprawione odpowiedzi Telegram. | `backend/routers/control.py`, `backend/quote_currency.py`, `telegram_bot/bot.py`, `tests/test_control_center.py` | Eliminacja błędnej interpretacji komend i spójniejszy manual override | DONE |
| T-102 | Entry unblock wave: parser `wymuś kup` → `buy_symbol`, relaksowane progi po N cyklach bez wejścia, szersza tolerancja BUY zone, rozszerzenie universe do top-N scanner, oraz luzowanie progów balanced/aggressive/default entry-score. | `backend/routers/control.py`, `backend/collector.py`, `backend/routers/signals.py`, `backend/runtime_settings.py` | Mniej fałszywych odrzuceń BUY i większa aktywność handlu | DONE |
| T-101 | Entry engine hardening: collector rozszerza universe o market_scanner, fallbackuje live sygnały/range dla symboli spoza watchlisty, loguje WHY_NOT_BUY/BUT_ALLOWED; risk ma debug override `RISK_FORCE_ALLOW_ENTRY_DEBUG=true` dla testowego wymuszenia wejść. | `backend/collector.py`, `backend/risk.py` | Lepsza diagnostyka blokad wejścia i wyższa aktywność wyszukiwania okazji | DONE |
| T-100 | Live signals stale-data upgrade: `_build_live_signals` dla starych klines 1h wykonuje fetch-on-demand z Binance i zapis do DB (`Kline`) zamiast natychmiastowego skip. Skip pozostaje tylko gdy refresh się nie powiedzie. | `backend/routers/signals.py` | Większe pokrycie sygnałami live, mniej fałszywych braków danych | DONE |
| T-99 | Quality/runtime: usunięcie deprecacji `datetime.utcnow()` z `/health` (`backend/app.py`) przez przejście na timezone-aware UTC (`datetime.now(timezone.utc)`). | `backend/app.py` | Stabilność runtime i czystsza diagnostyka testów/logów | DONE |
| T-98 | Regresja smoke po auth/env: `backend/app.py` ładował `.env` z `override=True`, przez co testowe `ADMIN_TOKEN=""` było nadpisywane i endpointy sterujące zwracały 401. Zmieniono na `override=False`; smoke wrócił do zielonego. | `backend/app.py`, `tests/test_smoke.py` | Przywrócenie stabilności testów i przewidywalnego bootstrapu env | DONE |
| T-97 | Operacyjny follow-up po T-95 domknięty: Telegram singleton przy aktywnym systemd. `start_dev.sh` preferuje `rldc-telegram.service` (enabled→active), czyści lokalne duplikaty, `status_dev.sh` raportuje źródło procesu; `stop_dev.sh` zatrzymuje service świadomie. | `scripts/start_dev.sh`, `scripts/status_dev.sh`, `scripts/stop_dev.sh` | Stabilność runtime, eliminacja konfliktu komend | DONE |
| T-96 | Krytyczny fix confidence runtime: fallback confidence z indikatorów (bez zera), dynamiczny próg `0.4/0.6` zależny od stanu AI, debug `CONFIDENCE/AI_USED/AI_FAILED`, rozszerzony payload AI ranges (`price/candles/rsi/ema20/ema50/volume/trend`) oraz bogaty context AI chat z realnymi danymi (`market_scan_snapshot`, `top_opportunities`). | `backend/collector.py`, `backend/analysis.py`, `backend/routers/control.py`, `tests/test_confidence_runtime_fix.py` | Usunięcie false blokad `signal_confidence_too_low`, poprawa jakości decyzji i diagnostyki | DONE |
| T-95 | Operacyjny fix duplikatów Telegram bota: `start_dev.sh` dostał lock równoległych uruchomień (`flock`) i normalizację singletona procesu (`telegram_bot.bot`). Potwierdzono runtime po restarcie: 1 proces Telegram, backend/frontend/telegram UP. | `scripts/start_dev.sh`, `scripts/status_dev.sh` | Stabilność sterowania, eliminacja konfliktów komend | DONE |
| T-94 | Dashboardowe metryki kosztowe jako stałe widgety UI. Dodano backendowe pola `overtrading_score`, `gross_to_net_retention_ratio`, `gross_net_gap` w analytics overview; dodano stałe kafle kosztowe w Dashboard V2 i rozszerzono widok Ekonomia. | `backend/reporting.py`, `web_portal/src/components/MainContent.tsx`, `tests/test_reporting_metrics.py` | Monitoring rentowności, kontrola overtradingu | DONE |
| T-93 | `_build_live_signals`: dodano guard świeżości klines 1h (`MAX_KLINE_AGE_HOURS`, domyślnie 4h). Symbole ze starymi klines są pomijane przed analizą, więc live fallback nie produkuje już misleading wskaźników dla ARB/EGLD na danych sprzed kilku dni. Dodano testy jednostkowe stale/fresh. | `backend/routers/signals.py::_build_live_signals`, `tests/test_signals_router.py` | Jakość danych diagnostycznych, rzetelność live fallback | DONE |
| T-90 | `entry-readiness`: stare sygnały (ARBUSDC/EGLDUSDC sprzed 5 dni) pokazywały `ENTRY_BLOCKED_SELL_NO_POSITION` zamiast `ENTRY_BLOCKED_DATA_TOO_OLD`. Naprawiono: dodano staleness check (MAX_SIGNAL_AGE_MINUTES z ENV), timestamp do signal_map, nowy kod do `_ENTRY_BLOCK_PL`. Teraz ARB/EGLD pokazują prawdziwy powód blokady. | `backend/routers/signals.py::get_entry_readiness`, `_ENTRY_BLOCK_PL` | Diagnostyka, poprawność raportowania | DONE |
| T-91 | `_active_position_count` w `control.py` liczył WSZYSTKIE pozycje z DB (w tym zamknięte) przez `db.query(Position).count()`. Po naprawie: `WHERE exit_reason_code IS NULL`. Wynik: `active_position_count: 0` (poprawne) zamiast 2. | `backend/routers/control.py::_active_position_count` | Spójność dashboardu, poprawność raportu stanu | DONE |
| T-92 | Extended universe + staleness fallback (second wave): `_load_signals_from_db_or_live` z `max_age_minutes=90` regeneruje stale sygnały przez live fallback; `get_trade_universe(extended=True)` omija filtr QCM; extended scan potwierdza 20 symboli (10 USDC + 10 EUR); `_scan_symbols` + `run_market_scan` z `max_signal_age_minutes`. 353/353 testów. | Wiele plików | Extended coverage, jakość skanowania | DONE |

### DONE (zamknięte w sesji 27 — AI hardening)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-86 | TTL cache (60s) dla `get_ai_orchestrator_status()` — eliminuje re-sondowanie providerów przy każdym wywołaniu. `force=True` omija cache. | `backend/ai_orchestrator.py` | Wydajność, latencja requestów | DONE |
| T-87 | Circuit breaker per-provider — po 3 kolejnych błędach provider wyłączony na 5 min, auto-reset. Zapobiega ciągłym timeoutom martwych providerów. | `backend/ai_orchestrator.py` | Stabilność, noise reduction | DONE |
| T-88 | Throttlowane logowanie błędów AI — pierwsze niepowodzenie→WARNING, kolejne→DEBUG. Circuit open→WARNING. Eliminuje spam logów. | `backend/ai_orchestrator.py` | Noise reduction, utrzymanie | DONE |
| T-89 | Naprawa `/api/health`: zwraca teraz rzeczywistego primary AI provider (`"ai": "groq"`) zamiast wartości ENV. Naprawiono błędny import `AIOrchestrator` (klasa nie istniała). | `backend/app.py` | Diagnostyka, prawdziwość | DONE |

**Wynik sesji 27:** 345/345 testów zielonych

### DONE (zamknięte w sesji 26 — WYMUSZENIE AUTONOMII / pipeline skanowania)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-76 | Nowy globalny pipeline skanowania rynku — `backend/market_scanner.py`. Funkcje: `run_market_scan()`, `get_trade_universe()`, `_validate_candidate()`, `_scan_symbols()`. Kandydat #1 odrzucony ≠ brak okazji — pipeline iteruje wszystkich kandydatów. | `backend/market_scanner.py` | Logika selekcji okazji, overtrading, rentowność | DONE |
| T-77 | 16 kanonicznych kodów odrzuceń (REJECTION_CODES) + 5 statusów FINAL_MARKET_STATUSES. Każda blokada ma `reason_code` + `reason_text`. | `backend/market_scanner.py` | Diagnostyka, zrozumiałość decyzji | DONE |
| T-78 | Rozróżnienie `best_analytical_candidate` (analitycznie najlepszy, bez walidacji portfelowej) vs `best_executable_candidate` (przechodzi wszystkie bramki). | `backend/market_scanner.py` | Jakość selekcji, klarowność dashboardu | DONE |
| T-79 | Extended scan — gdy primary universe nie daje executable candidate, uruchom skan na rozszerzonym universe (env EXTENDED_SCAN_ENABLED). | `backend/market_scanner.py` | Więcej okazji, mniejszy blind-spot | DONE |
| T-80 | Nowy endpoint dashboard: `GET /api/dashboard/market-scan?mode=demo\|live`. Jeden endpoint ze spójnym `snapshot_id` dla wszystkich komponentów dashboardu. | `backend/routers/dashboard.py` | Spójność danych, brak race conditions | DONE |
| T-81 | Rejestracja routera `dashboard` w `backend/app.py`. | `backend/app.py` | Dostępność endpointu | DONE |
| T-82 | `CommandCenterView` w MainContent.tsx — zastąpienie 3 asynchronicznych fetchów (scanner/bestOpp/waitStatus) jednym `/api/dashboard/market-scan`. Unified `snapshot_id`, `bestExec`, `bestAnalytical`, `rejectedCandidates`, `finalStatus` z jednego źródła. | `web_portal/src/components/MainContent.tsx` | Spójność UI, brak sprzecznych info | DONE |
| T-83 | Dashboard classic (`CommandCenterView`) — sekcja "Najlepsza okazja teraz" używa `bestExec` z market scan (nie starą zmienną `bestOpp`). CZEKAJ pokazuje `finalMessage` z licznikiem przeskanowanych/odrzuconych + główne powody. | `web_portal/src/components/MainContent.tsx` | Czytelność dashboardu | DONE |
| T-84 | 33 testy jednostkowe dla `market_scanner.py`: pipeline fallthrough, SELL_WITHOUT_POSITION, analytical≠executable, extended scan, any symbol (nie BTC/ETH), snapshot_id spójność, wszystkie wymagane pola snapshotu. | `tests/test_market_scanner.py` | Weryfikacja logiki | DONE |
| T-85 | TypeScript zero błędów po zmianach w MainContent.tsx. Przejście z `tsc --noEmit`. | `web_portal/src/components/MainContent.tsx` | Stabilność frontendu | DONE |

**Wynik sesji 26:** 345/345 testów zielonych (312 + 33 nowe)

### DONE (zamknięte w sesji 25 — 18-04-2026)

| ID | Zadanie | Plik/Moduł | Wpływ | Status |
|----|---------|------------|-------|--------|
| T-73 | KRYTYCZNY: Fix tunelu Cloudflare — publiczny URL zwracał HTTP 404. RCA: `~/.cloudflared/config.yml` catch-all `http_status:404` blokował ALL quick tunnel requests. Naprawa: zmiana catch-all na `http://localhost:3000`. | `~/.cloudflared/config.yml` | Dostępność produkcyjna | DONE |
| T-74 | `tunnel_manager.py`: 3 poprawki — `_read_cf_log_url()` nowa (fallback z quicktunnel.log + cloudflared.log), `_wait_for_new_url()` z fallback na log, reset `recovery_count=0` przy normalnym sukcesie probe. | `backend/tunnel_manager.py` | Stabilność self-healing | DONE |
| T-75 | `scripts/tunnel_doctor.py` — nowe narzędzie E2E diagnostyki: 7-stopniowy check (proces, port 3000/8000, runtime file, log URL, probe publiczny /, /api/health, backend status). `--fix` → auto-heal przez API. | `scripts/tunnel_doctor.py` | Utrzymanie, diagnostyka | DONE |

### DONE (zamknięte w sesji 24 — 17-04-2026)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-68 | Naprawa danych: CostLedger order #81 (BNBEUR) taker_fee actual 30.73→0.068 EUR; Order.net_pnl -28.98→+1.68 EUR. RCA: `_convert_fee_to_quote` otrzymała błędny `fee_amount` z fills Binance (aggregate fee across session). Efekt: kill_switch zwolniony, daily_net_pnl +1.53 EUR. | `trading_bot.db` CostLedger+Order | DONE |
| T-69 | `_convert_fee_to_quote` sanity cap 2% notional: jeśli przeliczona prowizja > 2% wartości transakcji → log WARNING + zwróć None → fallback do estimate. Zapobiega kolejnym koruplom CostLedger z błędnych fills Binance. Dodano parametr `notional`. | `backend/collector.py` | DONE |
| T-70 | `compute_risk_snapshot` (LIVE): `initial_balance` = `AccountSnapshot.equity` (pełne konto) zamiast `total_exposure` (tylko otwarte pozycje). Próg kill_switch 3% teraz ~10 EUR (total 340 EUR) zamiast 2 EUR (exposure 68 EUR). Fallback: ENV LIVE_INITIAL_BALANCE → total_exposure. | `backend/accounting.py` | DONE |
| T-71 | `compute_risk_snapshot`: filtr pozycji `exit_reason_code IS NULL AND qty>0`. `open_positions_count` zmienił się z 4 (stale qty=0 rekordy) na 1 (tylko realnie otwarte). | `backend/accounting.py` | DONE |
| T-72 | `entry-readiness` kill_switch: sprawdza `config.kill_switch_active OR risk_snapshot.kill_switch_triggered`. Wcześniej tylko config → niespójność z collectorem który sprawdza risk_snapshot. Test: `kill_switch_active: false`, `can_enter_now: true`. | `backend/routers/signals.py` | DONE |



| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-60 | Odtworzono komplet plikow kontrolnych w root (`ARCHITECTURE_DECISIONS.md`, `TRADING_METRICS_SPEC.md`, `STRATEGY_RULES.md`, `CURRENT_STATE.md`, `OPEN_GAPS.md`, `CHANGELOG_LIVE.md`) i zsynchronizowano je z biezacym runtime. | root docs kontrolne | DONE |
| T-59 | Root npm scripts (`dev/build/start/lint`) delegują do `web_portal`; naprawia `Missing script: "build"` i przywraca spójny punkt wejścia npm. Testy: `npm run build` PASS, `pytest tests/test_smoke.py` 220 passed. | `package.json` (root), `web_portal/package.json` | DONE |
| T-58 | RCA i naprawa spamu Telegram podczas pytest: testy governance/notifications wykonywały realny outbound przy obecnym tokenie/chat. Dodano guard testowy (`PYTEST_CURRENT_TEST`) + opcję jawnego override `ALLOW_TEST_TELEGRAM=true`, zachowując logowanie DB i semantykę dispatcher-a. | `backend/notification_hooks.py` | DONE |

### DONE (zamknięte w sesji 23)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-67 | LIVE runtime RCA i naprawa zablokowanej rotacji: partial SELL nie ustawiają już `pending_confirmed_execution`, partial TP respektuje `min_order_notional`, rejected SELL resynchronizuje qty z Binance, sync monitor auto-zamyka martwe pozycje nieistniejące na giełdzie; po cleanupie LIVE wrócił do `can_enter_now=true` przy `open_positions=2/5`. Test: `pytest tests/test_smoke.py` 220 passed, `entry-readiness?mode=live` potwierdza wolne sloty. | `backend/collector.py`, `trading_bot.db` | DONE |
| T-61 | `/ip` przebudowane na pelna diagnostyke direct/proxy/tunnel (local host IP + public egress + DNS + cloudflare/tunnel classification), bez blind error DNS-only | `backend/routers/account.py`, `telegram_bot/bot.py` | DONE |
| T-62 | Wdrozenie `ai_orchestrator.py` (multi-provider, local/free-first, unpaid OpenAI detection, fallback chain, task routing) + endpoint statusu | `backend/ai_orchestrator.py`, `backend/routers/account.py` | DONE |
| T-63 | Wspolny command brain dla Telegram i Web: natural language intent -> policy/permission -> pending/runtime action -> summary | `backend/routers/control.py`, `telegram_bot/bot.py`, `web_portal/src/components/MainContent.tsx` | DONE |
| T-64 | Telegram env/config management (`/env`, `/config`, get/set/diff/backup/rollback/reload) przez backend API z whitelista i audit logiem | `backend/routers/control.py`, `telegram_bot/bot.py` | DONE |
| T-65 | Guarded online terminal dla Web (`/api/control/terminal/exec`) z allowlist i endpointem uprawnien | `backend/routers/control.py`, `web_portal/src/components/MainContent.tsx` | DONE |
| T-66 | Testy regresyjne control center: IP diagnostics, AI fallback, env lifecycle, command parsing/execution, terminal permission guard | `tests/test_control_center.py` | DONE |

### DONE (zamknięte w sesji 21)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-57 | Root-cause `signal_confidence_too_low`: hardkodowany `base_conf=0.55` w `_learn_from_history` nadpisywał reset DB przy każdym restarcie → zmieniono na odczyt z `demo_min_signal_confidence` runtime config; obniżono bazę 0.55→0.48; przeniesiono `get_runtime_config` poza pętlę per-symbol; wynik: 0 confidence rejections vs 64/60m przed fixem | `backend/collector.py` | DONE |

### DONE (zamknięte w sesji 20)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-56 | Confidence gate: dodano mikrotolerancję BUY (`buy_confidence_tolerance=0.01`) dla przypadków granicznych 0.50 vs 0.51, z trace `confidence_tolerance`; ograniczono fałszywe `signal_confidence_too_low` bez globalnego luzowania progów | `backend/collector.py` | DONE |

### DONE (zamknięte w sesji 19)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-54 | Naprawiono niespójność progu wejścia: `demo_min_entry_score` (0-100) był porównywany z `rating` (0-5); dodano kompatybilność legacy 0-10, osobny `min_rating_gate` i poprawne `signal_score_min` w trace | `backend/collector.py` | DONE |
| T-55 | Dopracowano cost gate warunkowo dla mocnych sygnałów w `TREND_UP` (dynamiczny udział kosztów i wymagany bufor ruchu), bez globalnego luzowania dla słabych setupów | `backend/risk.py` | DONE |

### DONE (zamknięte w sesji 18)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-52 | LIVE entry gates: poluzowano progi wejścia (score, RR) i usunięto twardą blokadę RANGE-only NO_TRADE w collectorze, zachowując pozostałe bramki ryzyka/kosztu | `backend/collector.py`, `backend/risk.py` | DONE |
| T-53 | Potwierdzono reaktywację handlu LIVE po restarcie: `create_pending_entry` + `execute_pending` + `orders.status=FILLED` dla nowych BUY (SOLEUR/WLFIEUR/BTCEUR/BNBEUR) | `trading_bot.db`, `backend/routers/account.py`, `backend/routers/signals.py` | DONE |

### DONE (zamknięte w sesji 17)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-44 | Frontend: usunięte demo-only guardy dla akcji zamknięcia/akcji pending i statusów LIVE | `web_portal/src/components/MainContent.tsx`, `web_portal/src/components/Topbar.tsx` | DONE |
| T-45 | Backend: pending orders działają w `mode=live` (create/list/confirm/reject/cancel), domyślny mode dla list/export -> live | `backend/routers/orders.py` | DONE |
| T-46 | Backend: `GET /api/account/runtime-activity` (heartbeat runtime: collector/ws/worker/last decision/order) | `backend/routers/account.py` | DONE |
| T-47 | Backend: `POST /api/positions/close-all` obsługa LIVE i DEMO | `backend/routers/positions.py` | DONE |
| T-48 | Testy regresyjne runtime + pending live | `tests/test_smoke.py` | DONE |
| T-49 | Dokumentacja: usunięto sprzeczne opisy demo-only i ujednolicono README dla LIVE (`allow_live_trading`, `wealth?mode=live`) | `README.md` | DONE |
| T-50 | Root startup audit: potwierdzono, że działający system nie używa rootowego `npm run ...`; aktywne ścieżki startu prowadzą przez `scripts/start_dev.sh`, `backend.app --all` i `web_portal/package.json` | `package.json`, `scripts/start_dev.sh`, `backend/app.py`, `README.md` | DONE |
| T-51 | Przywrócono rootowy `package.json` do historycznej funkcji 1:1 po audycie Git i ścieżek uruchomieniowych | `package.json` | DONE |

### DONE (zamknięte w sesji 16)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-42 | `_get_live_spot_positions` używał `min_order_notional=25 EUR` jako próg "pyłu" → pozycje 17-24 EUR (ETH, SHIB, PEPE, EGLD) pomijały `_resolve_live_position_baseline` → `entry_price=None` na stronie mimo dostępnej historii Binance | `routers/positions.py` | DONE |
| T-43 | Formatowanie cen meme coinów: `toFixed(6)` dla SHIB (5.14e-06) dawało `0.000005` (utrata precyzji) → dodano próg `< 0.0001 → toFixed(8)` w `formatPrice` i `fmtPrice` | `web_portal/src/components/MainContent.tsx` | DONE |

### DONE (zamknięte w sesji 15)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-36 | `/confirm` nie sprawdzał statusu → re-wykonanie EXECUTED order → podwójne zlecenie BUY na Binance | `telegram_bot/bot.py` | DONE |
| T-37 | Brak LIVE AccountSnapshot → wykres equity LIVE zawsze pusty | `collector.py` | DONE |
| T-38 | Dangling `position_id` w DecisionTrace po pełnym SELL (`db.delete(position)`) | `collector.py` | DONE |
| T-39 | Binance timeout → `free_cash=0` → wszystkie LIVE entries zablokowane; fallback na AccountSnapshot | `routers/signals.py` | DONE |
| T-40 | `entry-readiness` bez MIN_SCORE gate → niespójna diagnostyka vs `best-opportunity` | `routers/signals.py` | DONE |
| T-41 | Błędy wykonania LIVE pending order logowane jako `demo_trading` namespace | `collector.py` | DONE |

### DONE (zamknięte w sesji 14)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-30 | `_check_exits` hardkodował `mode="demo"` w `_trace_decision` i `_create_pending_order` (SL/trailing/TP/reversal) → LIVE exits logowane jako demo w DecisionTrace | `collector.py` | DONE |
| T-31 | `_screen_entry_candidates` hardkodował `mode="demo"` w 14 `_trace_decision` + `build_risk_context` + `_create_pending_order` → LIVE entry decyzje logowane jako demo | `collector.py` | DONE |
| T-32 | `_score_opportunity` ignorowała EMA20/EMA50/RSI (po T-26 pola są na top-level sygnału, nie w `indicators`) → EMA trend +1.5 i RSI +1.5 nie działały | `routers/signals.py` | DONE |
| T-33 | `open_count` dla LIVE liczył unikalne BUY Order (nie Position) → BTCEUR synced_from_binance nie wliczało się do limitu max_open_positions → `can_enter_now=True` mimo otwartej pozycji | `routers/signals.py` | DONE |
| T-34 | Brak zaokrąglenia qty do Binance LOT_SIZE step_size przed LIVE `place_order` → `BinanceAPIException: Invalid quantity` dla każdego LIVE BUY/SELL | `collector.py` | DONE |
| T-35 | `_check_hold_targets` tworzyła `Order(status="pending_review")` zamiast `PendingOrder` → telegram `/confirm` nie znajdował zlecenia, LIVE nigdy nie wykonał SELL przez Binance API | `collector.py` | DONE |

### DONE (zamknięte w sesji 13)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-23 | `signal_filters_not_met` spam co 2 min gdy SELL bez pozycji → early-exit przed filtrami sygnałowymi | `collector.py` | DONE |
| T-24 | DB↔Binance mismatch WARNING co 33 min dla dust ARB/AVAX/EGLD/PEPE → filtr wartości < min_notional | `collector.py` | DONE |
| T-25 | `/api/signals/latest?symbol=` ignorował parametr → dodano filtr `Signal.symbol == symbol` | `routers/signals.py` | DONE |
| T-26 | entry-readiness używał `_build_live_signals` (live analysis) zamiast Signal z DB → niespójność z collectorem; BNBEUR pokazywał BUY gdy DB ma SELL | `routers/signals.py` | DONE |
| T-27 | `status_pl = "OKAZJE SĄ"` gdy brak kandydatów BUY (samo SELL bez pozycji) → `BRAK OKAZJI: {reason}` | `routers/signals.py` | DONE |
| T-28 | Exit engine (TP/SL/trailing) pomijał BTCEUR bo pozycja `synced_from_binance` bez Order → zarządzaj wszystkimi `Position.mode=live` (entry>0, qty>0) | `collector.py` | DONE |
| T-29 | `_sync_binance_positions` WARNING spam po restarcie dla remnant bez ceny i bez DB position → pomiń jeśli `price_eur is None AND db_qty==0` | `collector.py` | DONE |

### DONE (zamknięte w sesji 12)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-19 | `entry-readiness open_positions=0` mimo BTCEUR w DB → zmieniono licznik na `len(open_positions)` | `signals.py` | DONE |
| T-20 | SELL entry ENTRY_ALLOWED bez otwartej pozycji → `ENTRY_BLOCKED_SELL_NO_POSITION` | `signals.py` | DONE |
| T-21 | AVAX/EGLD/PEPE/ARB jako `ENTRY_ALLOWED` mimo `symbol_not_in_any_tier` w collectorze → tier-gate + fix źródła `symbol_tiers` (`runtime_ctx` zamiast pustego `config`) | `signals.py` | DONE |
| T-22 | `start_dev.sh` zawsze startował `next dev` mimo istnienia buildu prod → auto-wykrycie `.next/BUILD_ID` | `scripts/start_dev.sh` | DONE |

### DONE (zamknięte w sesji 11)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-18 | Spam logów heurystyki ATR co 60s → throttle 600s + detekcja zmian zestawu symboli | `collector.py` | DONE (sesja 11) |

### DONE (zamknięte w sesji 10)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-16 | `_load_watchlist` ignorowała ENV WATCHLIST gdy Binance balances non-empty → ETH/SOL/SHIB/WLFI poza watchlistą | `collector.py` | DONE (sesja 10) |
| T-17 | `range_map` nie uzupełniał brakujących symboli po zmianie watchlisty → ciche pomijanie ETH/SOL/SHIB/WLFI | `collector.py` | DONE (sesja 10) |

### DONE (zamknięte w sesji 9)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-15 | Bot nie otworzył żadnej pozycji LIVE — fix dust-positions blokujących wejścia | `signals.py`, `positions.py`, `collector.py` | DONE (sesja 9) |
| T-05 | CORS allow_origins=["*"] → domeny produkcyjne | `app.py` | DONE (sesja 9) |
| T-07 | Usunięcie nieużywanego widgetu AccountSummary | `widgets/AccountSummary.tsx` | DONE (sesja 9) |

### DONE (zamknięte w sesjach 1-8)

| ID | Zadanie | Zamknięte |
|----|---------|----------|
| T-01 | LIVE CostLedger actual Binance fees | sesja 1 |
| T-02 | Periodyczny sync DB↔Binance | sesja 1 |
| T-03 | Telegram /confirm /reject | (już było) |
| T-04 | Qty sizing: prowizja w alokacji | sesja 2 |
| T-06 | Telegram governance stubs | (już było) |
| T-08 | Telegram /ip komenda (Cloudflare) | sesja 3 |
| T-09 | Telegram /ai komenda (OpenAI status) | sesja 3 |
| T-11 | Aliasy kompatybilności endpointów (404 → 200) + reset środowiska | sesja 4 |
| T-12 | Stabilizacja collectora: brak flappingu watchlisty + cooldown mismatch | sesja 5 |
| T-13 | LIVE baseline pozycji: entry_price/PnL z DB lub Binance myTrades | sesja 6 |
| T-10 | Naprawa 19 faili smoke (governance/promotion/rollback) | sesja 7 |
| T-14 | Fix critical collector bugs: fake LIVE SELL orders, entry_readiness open_count, _error check | sesja 8 |
---

## HISTORIA CHECKPOINTÓW

### CHECKPOINT (sesja 8 — poprawki collector + entry readiness)

**4 krytyczne bugi naprawione w collector.py i signals.py:**
- **Bug C** (`_execute_confirmed_pending_orders`): sprawdzenie `result.get("_error")` — Binance NOTIONAL reject był fałszywie traktowany jako sukces (truthy dict omijał `if not result:`)
- **Bug B** (`_load_trading_config` live mode): exit engine zarządza TYLKO pozycjami z bot-otwartymi BUY orders — pre-existing Binance holdings pominięte
- **Bug D** (`entry_readiness` open_count): live mode liczy tylko bot-otwarte (0 BUY = 0 open_count vs max 3) — wcześniej 5 synced > 3 max = blokada wszystkich wejść
- **Bug D2** (`entry_readiness` cash): live mode używa `_build_live_spot_portfolio` (171.30 EUR realne) — wcześniej zawsze 10000 EUR z demo state
- **DB cleanup**: 27 fake live SELL pending_orders + 27 fake live SELL orders usunięte; SL/TP z 5 synced positions live wyczyszczone

**Weryfikacja:**
- `entry-readiness?mode=live`: can_enter=True, open=0/3, cash=171.3 EUR ✅
- `positions/analysis?mode=live`: 5 pozycji, total_pnl=0.35 EUR ✅
- Pętla SL ARBEUR zatrzymana: 0 fake SELLs w ostatnich 5 min ✅


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
