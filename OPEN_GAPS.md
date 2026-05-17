# OPEN_GAPS

Data aktualizacji: 2026-04-20

## CRITICAL
- T-134: Krytyczna niestabilność endpointów live pozycji: `/api/positions?mode=live` i `/api/positions/analysis?mode=live` timeoutują (20s) pod obciążeniem runtime, co blokuje overlay 8099 i część widoków WWW.
- T-135: Overlay `/overlay/api/live-state` timeoutuje gdy backend pozycyjny przekracza SLA; potrzebny deterministyczny snapshot/cache i degradacja kontrolowana zamiast pełnego timeoutu.

## HIGH
- T-136: Ujednolicić kontrakt danych dla 3000 i 8099 na wspólnym, lekkim snapshot_id (bez równoległego dociążania `/api/positions/analysis` w ścieżce startowej).

## MEDIUM
- T-140: Ustabilizować intermitentne smoke fail (`test_market_summary`, `test_acceptance_live_positions_analysis_restores_entry_baseline`) i usunąć zależność od niestabilnych danych runtime/network podczas testów.
- T-137: Profilowanie funkcji w `backend/routers/positions.py` (`_get_live_spot_positions`, `_analyze_spot_position`) i wydzielenie ciężkich kalkulacji do joba cyklicznego/cache.

## LOW
- Ujednolicenie i utrzymanie dokumentów kontrolnych po każdej sesji.

## DONE W TEJ SESJI (sesja 49)
- **T-141**: overlay 8099 recovery + fallback wykresu. Adapter mapuje teraz pary bez świec EUR na dostępny symbol wykresowy (np. `AAVEEUR -> AAVEUSDC`), UI overlay usunięto z lewego paska opcji, a runtime usługi 8099 został przywrócony po awarii procesu.
- **T-133**: naprawiono źródło prawdy dla `/api/rldc/safe/live-state` — endpoint czyta teraz kanoniczne live spot holdings (`_get_live_spot_positions`) zamiast lokalnej tabeli `Position`; dodano fallback do DB tylko awaryjnie.
- **T-133b**: ograniczono request-storm frontendu (kolejka fetch, limit równoległości, backoff po błędach) bez zmian wyglądu UI.
- Testy: `tests/test_smoke.py` -> **227/227 PASS**.

## DONE W TEJ SESJI (sesja 33)
- **T-109**: domknięto krytyczne luki execution/Telegram. Naprawiono status typo `PENDING_CREATED_CREATED` blokujący wykonanie `sell_weakest`; dodano twardy gate runtime (`trading_mode==live` oraz `allow_live_trading==true`) przed LIVE execution; Telegram `/confirm` i `/reject` działają na `PendingOrder.id` w aktywnym trybie i nie mylą już kontekstu ID/mode. Walidacja: `tests/test_control_center.py` + `tests/test_smoke.py` = **257/257 PASS**.
- **T-103**: parser Telegram/control działa teraz jako trading-first i nie myli symboli par (`SOLUSDC`, `ETHUSDC`) z komendami konfiguracji quote-currency. Dodano jednolity wynik parsera (`type/side/symbol/force/config_key/config_value`), flow `MANUAL`/`MANUAL_FORCE`, obsługę `sprzedaj ...` i `wymuś sprzedaj ...`, komendę `tryb agresywny`, pełne logowanie `parser_decision` + `execution_path` oraz testy komend. Walidacja: `tests/test_control_center.py` 36/36 PASS, `tests/test_smoke.py` 220/220 PASS.
- **T-102**: odblokowano krytyczne ścieżki entry. Parser komendy `wymuś kup` jest teraz traktowany jak BUY action; collector po kilku cyklach bez wejścia uruchamia tryb relaksowany (niższy confidence/entry-score + szersza strefa BUY), a universe kandydatów rozszerza o top-N symboli skanera. Dodatkowo buy-trace używa wspólnego parametru tolerancji strefy BUY (`buy_zone_tolerance_pct`).
- **T-101**: collector przestał działać wyłącznie na statycznej watchliście. `_screen_entry_candidates` rozszerza universe symbolami z `market_scanner`, uzupełnia brakujące range dla nowych symboli i fallbackuje live sygnał on-demand przy braku `Signal` w DB. Dodano jawne logi `WHY_NOT_BUY` / `BUY_ALLOWED` oraz debug override risk (`RISK_FORCE_ALLOW_ENTRY_DEBUG=true`) do testowego wymuszenia wejść.
- **T-100**: `_build_live_signals` przestał tylko skipować stale klines 1h; dla stale symboli robi teraz fetch-on-demand z Binance i zapisuje brakujące świece do DB (`Kline`). Skip pozostaje wyłącznie przy nieudanym refreshu, co zwiększa szansę wygenerowania realnych sygnałów live dla symboli z przestarzałym lokalnym cache.
- **T-99**: usunięto deprecację `datetime.utcnow()` w `backend/app.py` (health API używa teraz `datetime.now(timezone.utc)`), co czyści ostrzeżenia testowe i stabilizuje format UTC.
- **T-98**: regresja 401 w smoke usunięta. `backend/app.py` przestał nadpisywać env z testów (`load_dotenv override=False`), co przywróciło poprawne zachowanie endpointów sterujących i domknęło `tests/test_smoke.py` do 220/220 PASS.
- **T-94**: Dashboardowe metryki kosztowe jako stałe widgety UI. Backend analytics overview zwraca teraz `overtrading_score`, `gross_to_net_retention_ratio`, `gross_net_gap`; Dashboard V2 pokazuje stałe kafle kosztowe bez przechodzenia do podwidoków; Ekonomia rozszerzona o nowe KPI.
- **T-93**: `_build_live_signals` sprawdza wiek ostatniego `Kline` 1h i pomija symbole starsze niż `MAX_KLINE_AGE_HOURS` (domyślnie 4h), więc nie generuje już misleading wskaźników dla orphaned symboli (ARB/EGLD).
- **T-90**: `entry-readiness` staleness fix — ARB/EGLD pokazują `ENTRY_BLOCKED_DATA_TOO_OLD` zamiast mylącego `ENTRY_BLOCKED_SELL_NO_POSITION`.
- **T-91**: `_active_position_count` naprawiony — liczył wszystkie pozycje (w tym zamknięte).
- **T-92**: Extended universe + staleness DB fallback (second wave, sesja 27/28).

## DONE W POPRZEDNICH SESJACH
- Odtworzenie pełnego zestawu plików kontrolnych w root.
- Naprawa root npm build scripts i walidacja build + smoke.
- Pipeline skanowania rynku (`market_scanner.py` + `/api/dashboard/market-scan`).
- Hardening AI providers: TTL cache + circuit breaker + throttled logging.
- RSI normalization, regime inference, DATA_TOO_OLD gate activation.
