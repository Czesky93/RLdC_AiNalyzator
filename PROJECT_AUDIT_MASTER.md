# PROJECT_AUDIT_MASTER.md — RLdC Trading BOT

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
