# PROJECT_AUDIT_MASTER.md — RLdC Trading BOT

**Data audytu:** 12 czerwca 2026 (aktualizacja: sesja 4)
**Wersja:** v0.7 beta
**Testy:** 182/182 PASSED
**TypeScript:** PASS (po naprawie `web_portal/src/lib/api.ts`)
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
- WWW — 18 widoków, endpointy podpięte przez centralny helper API
- Telegram — alerty entry+exit, portfolio, pozycje, sygnały
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
| `account.py` | ~90 EP: account summary, governance, analytics, AI status | ✅ DZIAŁA | 2064 |
| `signals.py` | Sygnały, analiza, execution-trace, decision trace | ✅ DZIAŁA | 1808 |
| `positions.py` | Pozycje, analiza pozycji | ✅ DZIAŁA | 1910 |
| `orders.py` | Zlecenia DEMO+LIVE, create_order, pending | ✅ DZIAŁA | 633 |
| `market.py` | Dane rynkowe, Klines, kontekst | ✅ DZIAŁA | 817 |
| `portfolio.py` | Portfel, wealth, forecast, equity | ✅ DZIAŁA | 569 |
| `control.py` | Sterowanie: demo ON/OFF, WS, watchlist | ✅ DZIAŁA | 185 |
| `blog.py` | Blog AI insights | ✅ DZIAŁA | 67 |
| `debug.py` | Diagnostyka dev | ✅ DZIAŁA | 278 |
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

#### Audyt widżetów i endpointów (sesja 3)

| Widżet / widok | Endpointy kluczowe | Status | Wpływ |
|---|---|---|---|
| Topbar | `/api/control/state` | ✅ działa | Krytyczny (status runtime, tryb handlu) |
| DecisionsRiskPanel | `/api/orders/pending`, `/api/market/ranges`, `/api/account/risk`, `/api/control/state` | ✅ działa | Krytyczny (potwierdzanie/odrzucanie zleceń) |
| OpenOrders | `/api/positions`, `/api/positions/{id}/close`, `/api/positions/close-all` | ✅ działa | Krytyczny (zamykanie pozycji) |
| EquityCurve | `/api/account/history` | ✅ działa | Wysoki (monitoring equity i drawdown) |
| TradingView | `/api/market/kline`, `/api/market/ranges`, `/api/market/summary` | ✅ działa | Wysoki (kontekst wejścia/wyjścia) |
| MarketInsights | `/api/signals/latest` | ✅ działa | Wysoki (ocena jakości sygnałów) |
| PositionsTable | `/api/positions` | ✅ działa | Wysoki (stan pozycji) |
| MarketOverview | `/api/market/summary` | ✅ działa | Średni |
| DecisionRisk | `/api/market/ranges`, `/api/account/risk` | ✅ działa | Średni |
| AccountSummary | `/api/account/summary` | ⚠️ częściowo (widget technicznie działa, ale nieużywany w głównym flow) | Niski (dług UI) |
| MainContent (widoki analityczne) | m.in. `/api/account/analytics/overview`, `/api/account/system-logs`, `/api/blog/list` | ✅ działa | Krytyczny (spójność panelu WWW) |

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

### CRITICAL: Brak otwartych blockerów krytycznych

Aktualna sesja nie wykazała nowego krytycznego błędu logiki tradingowej.

### HIGH-1: Brak twardego endpointu KPI „best bot” (zamknięte w sesji 3)
- **Plik:** `backend/routers/account.py`, `backend/reporting.py`
- **Status:** ✅ NAPRAWIONE
- **Fix:** dodano `/api/account/analytics/best-bot-kpi` + metryki `overtrading_score` i `sync_stability` w `performance_overview`.

### HIGH-2: Frontend nie budował się przez brak helpera API (zamknięte w sesji 3)
- **Plik:** `web_portal/src/lib/api.ts`
- **Status:** ✅ NAPRAWIONE
- **Fix:** przywrócono centralny helper `getApiBase`, `getAdminToken`, `withAdminToken`.

### HIGH-3: Brak hard gate LIVE przy niespójnym sync pozycji (zamknięte w sesji 4)
- **Plik:** `backend/collector.py`, `backend/routers/signals.py`
- **Status:** ✅ NAPRAWIONE
- **Fix:** dodano blokadę nowych wejść LIVE przy `sync_stability.status=inconsistent` z `reason_code=inconsistent_portfolio_sync` i diagnostyką w `DecisionTrace`.

---

## 5. Długi techniczne

| ID | Opis | Plik | Priorytet |
|----|------|------|-----------|
| ~~DEBT-1~~ | ~~Telegram: /confirm i /reject~~ | `telegram_bot/bot.py` | ✅ ZAMKNIĘTY — już zaimplementowane (L371-424) |
| ~~DEBT-2~~ | ~~Telegram: /governance /freeze /incidents /logs /report~~ | `telegram_bot/bot.py` | ✅ ZAMKNIĘTY — już zaimplementowane (L427-560) |
| ~~DEBT-3~~ | ~~CORS: allow_origins=["*"]~~ | `backend/app.py` | ✅ NAPRAWIONY — CORS z ENV |
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
| DB pozycje vs Binance pozycje | ⚠️ Nadal wymaga monitorowania w LIVE (metryka `sync_stability`) |
| Telegram alerty vs WWW dane | ✅ Spójne — ten sam source (DB) |
| LIVE fees vs CostLedger | ✅ Ujęte w logice prowizji rzeczywistej dla filli Binance |
| Decision trace WWW | ✅ Spójne — endpoint `/api/signals/execution-trace` |

---

## 8. Lista zadań otwartych

| ID | Zadanie | Priorytet | Plik/Moduł | Wpływ |
|----|---------|-----------|------------|-------|
| TASK-11 | Audyt widżetów WWW i endpointów (krytyczność + status) | HIGH | `PROJECT_AUDIT_MASTER.md` | ✅ DONE (sesja 3) |
| TASK-12 | Przywrócenie `web_portal/src/lib/api.ts` + naprawa builda WWW | HIGH | `web_portal/src/lib/api.ts` | ✅ DONE (sesja 3) |
| TASK-13 | Twardy endpoint KPI `best-bot-kpi` + overtrading/sync stability | HIGH | `backend/reporting.py`, `backend/routers/account.py` | ✅ DONE (sesja 3) |
| TASK-14 | Hard gate LIVE: blokada nowych wejść gdy `sync_stability` jest `inconsistent` | HIGH | `backend/collector.py`, `backend/routers/signals.py` | ✅ DONE (sesja 4) |
| ~~TASK-03~~ | ~~Telegram /confirm i /reject~~ | ~~HIGH~~ | `telegram_bot/bot.py` | ✅ już zaimplementowane (false positive) |
| ~~TASK-04~~ | ~~Qty sizing: odejmij prowizję~~ | ~~MEDIUM~~ | `collector.py` | ✅ DONE (sesja 2) |
| ~~TASK-05~~ | ~~CORS allow_origins → proper domains~~ | ~~LOW~~ | `app.py` | ✅ DONE (sesja 12.06) |
| ~~TASK-08~~ | ~~Przywrócenie `web_portal/src/lib/api.ts`~~ | ~~HIGH~~ | `web_portal/src/lib/api.ts` | ✅ DONE (sesja 12.06) |
| ~~TASK-09~~ | ~~Stabilizacja Binance init offline (`ping=False`)~~ | ~~HIGH~~ | `backend/binance_client.py` | ✅ DONE (sesja 12.06) |
| ~~TASK-10~~ | ~~Naprawa `npm run lint` (TypeScript check)~~ | ~~MEDIUM~~ | `web_portal/package.json` | ✅ DONE (sesja 12.06) |

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
| 12.06 sesja 4 | LIVE hard gate `inconsistent_portfolio_sync` + smoke test | ✅ |

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

## 11. Ostatnia sesja — 12 czerwca 2026 (sesja 4)

### Co zmieniono
- Dodano hard gate LIVE w `collector._screen_entry_candidates`: brak nowych wejść, gdy `sync_stability=inconsistent`
- Dodano `reason_code=inconsistent_portfolio_sync` z detalami mismatch do `DecisionTrace`
- Uzupełniono mapowanie `reason_code -> reason_pl` w `backend/routers/signals.py`
- Dodano test smoke `test_live_sync_inconsistent_blocks_new_entries`

### Co przetestowano
- `DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py -q` → 182/182 ✅
- `npm run lint` (web_portal) ✅
- `npm run build` (web_portal) ✅

### Co zostało
- DEBT-5: LIMIT orders w LIVE (LOW)
- DEBT-6: AccountSummary widget cleanup (LOW)
- Monitoring `sync_stability` w LIVE nadal wymagany operacyjnie (gate już aktywny)
