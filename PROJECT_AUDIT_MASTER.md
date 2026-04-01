# PROJECT_AUDIT_MASTER.md — RLdC Trading BOT

**Data audytu:** 2 kwietnia 2026
**Wersja:** v0.7 beta
**Testy:** 181/181 PASSED
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

### Telegram (`telegram_bot/`)

| Plik | Rola | Stan |
|------|------|------|
| `bot.py` | Komendy Telegram: /status /portfolio /risk /orders | ⚠️ DZIAŁA CZĘŚCIOWO |

### Testy (`tests/`)

| Plik | Testy | Stan |
|------|-------|------|
| `test_smoke.py` | 181 testów (175 smoke + 6 akceptacyjnych v0.7) | ✅ WSZYSTKIE PRZECHODZĄ |

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
| DEBT-1 | Telegram: /confirm i /reject wymienione w /start ale NIE zaimplementowane | `telegram_bot/bot.py` | HIGH |
| DEBT-2 | Telegram: /governance /freeze /incidents /logs /report — stub | `telegram_bot/bot.py` | LOW |
| DEBT-3 | CORS: allow_origins=["*"] | `backend/app.py` | LOW |
| DEBT-4 | Qty sizing nie odejmuje prowizji od ilości | `backend/collector.py` L2234+ | MEDIUM |
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
| TASK-01 | LIVE CostLedger: użyj actual Binance commission z fills | CRITICAL | `collector.py` | Dokładność net PnL |
| TASK-02 | Periodyczny sync pozycji DB ↔ Binance | CRITICAL | `collector.py` | Spójność portfela |
| TASK-03 | Telegram /confirm i /reject implementacja | HIGH | `telegram_bot/bot.py` | UX LIVE trading |
| TASK-04 | Qty sizing: odejmij prowizję od ilości | MEDIUM | `collector.py` | Dokładność allocation |
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
- TASK-01: Fix LIVE CostLedger fees
- TASK-02: Binance position sync loop
- TASK-03: Telegram /confirm /reject
- Full regression test + commit
