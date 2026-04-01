# CHANGELOG_LIVE — RLdC AiNalyzator
*Chronologiczny dziennik wszystkich zmian w projekcie.*
*Format: DATA | SESJA | PLIK | OPIS | STATUS*

---

## SESJA 2026-03-26 (Sesja A — Setup, Audyt backendowy, Pierwsze poprawki)

### [2026-03-26] — Audyt i pierwsze naprawki backendu

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/signals.py` | Dodano import `persist_insights_as_signals`; wszystkie 3 endpointy (`/latest`, `/top5`, `/top10`) teraz wywołują persistację po generowaniu sygnałów | ✅ GOTOWE |
| `backend/collector.py` | Dodano `_load_persisted_symbol_params()` — ładuje `symbol_params` z DB przy starcie | ✅ GOTOWE |
| `backend/collector.py` | Zmodyfikowano `run_once()` — heurystyczne sygnały generowane KAŻDY cykl, niezależnie od OpenAI | ✅ GOTOWE |
| `backend/collector.py` | Zmodyfikowano `_learn_from_history()` — wyniki uczenia zapisywane do `RuntimeSetting('learning_symbol_params')` | ✅ GOTOWE |
| `backend/analysis.py` | Zmieniono domyślny `AI_PROVIDER` z `"openai"` → `"auto"` | ✅ GOTOWE |
| `backend/analysis.py` | Tryb `openai` teraz fallbackuje do heurystyki gdy brak klucza (zamiast `return None`) | ✅ GOTOWE |
| `backend/routers/orders.py` | Naprawiono `md.close` → `md.price` w create_order MARKET (błędny atrybut) | ✅ GOTOWE |
| `tests/test_smoke.py` | Status po naprawkach: **174/174 ✅** | ✅ GOTOWE |

### [2026-03-26] — Dokumenty

| Plik | Opis | Status |
|------|------|--------|
| `MASTER_GAP_REPORT.md` | Pełny raport statusu: 37 plików backend + widoki frontend + plan 4 pilarów | ✅ GOTOWE |
| `/memories/repo/rldc-ainlyzator.md` | Zaktualizowano pamięć repo o nowe cele i poprawki sesji | ✅ GOTOWE |

---

## SESJA 2026-03-26 (Sesja B — Pełna inwentaryzacja funkcji)

### [2026-03-26] — Dokumenty inwentaryzacji

| Plik | Opis | Status |
|------|------|--------|
| `FUNCTIONS_MATRIX.md` | Pełna macierz funkcji: ~108 funkcji, statusy DONE/PARTIAL/BROKEN/NOT_STARTED | ✅ GOTOWE |
| `OPEN_GAPS.md` | 12 braków posortowanych wg priorytetu, z zakresem każdego | ✅ GOTOWE |
| `SYSTEM_RULES.md` | Zasady systemu: reguły decyzyjne, bezpieczeństwo, konfiguracja, kody UI/UX | ✅ GOTOWE |
| `CHANGELOG_LIVE.md` | Ten plik — chronologiczny dziennik zmian | ✅ GOTOWE |
| `MASTER_INDEX.md` | Indeks wszystkich plików projektu z opisem roli | ✅ GOTOWE |

### Kluczowe odkrycia z inwentaryzacji

| Odkrycie | Wpływ | Priorytet naprawy |
|----------|-------|-------------------|
| Kliknięcie w symbol — NIGDZIE nie istnieje | Krytyczny | P1 |
| Forecast — backend działa, UI nigdy nie wywołuje | Krytyczny | P1 |
| `macro-reports` i `reports` — brak w OtherView routerze | Wysoki | P2 |
| Economy/Alerty/Wiadomości — wszystkie to ta sama tabela | Wysoki | P2 |
| PortfolioView — brak auto-refresh | Wysoki | P2 |
| OpenOrders widget — brak auto-refresh | Wysoki | P2 |
| Drawdown real Binance — zawsze 0.0 | Wysoki | P4 |
| Akcje handlowe (KUP/SPRZEDAJ) — brak w głównych widokach | Wysoki | P2 |

### [2026-03-26] — Implementacja GAP-01 + GAP-02 + GAP-04 + GAP-06

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/MainContent.tsx` | Dodano globalny `selectedSymbol` state w `MainContent` — kliknięcie z dowolnego widoku otwiera panel | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Dodano `SymbolDetailPanel` — slide-in overlay z prawej strony: cena, PnL, wykres, prognoza AI | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Dodano `ForecastChart` — wykres historyczny (klines) + prognoza AI (forecast) jako przerywana linia pomarańczowa z pionową linią "teraz" | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Kliknięcia w symbole: CommandCenterView scanner ✅, pozycje ✅, StrategiesView ✅, SignalsView ✅, RiskView tabela ✅, MarketsView tabela ✅, PositionAnalysisView nagłówki kart ✅ | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-04: Przyciski "KUP" (z kwotą EUR) i "ZAMKNIJ POZYCJĘ" w SymbolDetailPanel | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-06: Routing dla `macro-reports` i `reports` w OtherView — wyświetlają "Moduł w trakcie przygotowania" zamiast generic fallback | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | TypeScript kompiluje się bez błędów (`npx tsc --noEmit`) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-07: Auto-refresh dodany do PortfolioView (30s), BacktestView (60s), MarketProxyView (30s) | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy backend po zmianach: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-27 (Sesja C — Symbol Tiers, GAP-03, GAP-05, GAP-08/09/10)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/account.py` | Endpoint `/api/account/user-target` — persistacja celu użytkownika do DB (GAP-05) | ✅ GOTOWE |
| `backend/routers/positions.py` | Endpoint `/api/positions/decisions/{symbol}` — historia decyzji dla symbolu (GAP-10) | ✅ GOTOWE |
| `backend/routers/market.py` | Endpoint `/api/market/forecast-accuracy/{symbol}` — trafność prognoz (GAP-03) | ✅ GOTOWE |
| `backend/risk.py` | `drawdown_real` poprawiony dla trybu live Binance (GAP-08) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | ForecastChart: linie EMA20/EMA50 na wykresie historycznym (GAP-09) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | ForecastChart: mini-panel RSI(14) pod wykresem (GAP-09) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | SymbolDetailPanel: ustawianie celu użytkownika z persistacją (GAP-05) | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | SymbolDetailPanel: historia decyzji dla symbolu (GAP-10) | ✅ GOTOWE |
| `backend/database.py` | Model `ForecastRecord` — tabela trafności prognoz (GAP-03) | ✅ GOTOWE |
| `docs/ETAP_C_SYMBOL_TIERS_REPORT.md` | Raport z drobiazgowej inwentaryzacji system symbol tiers | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-27 (Sesja D — PION B: WLFI hold-status)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/account.py` | Endpoint `GET /api/account/wlfi-status` — wartość WLFI, cel 300 EUR, brakująca kwota | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `WlfiStatusCard` widget w DashboardV2View — wartość WLFI, pasek postępu do celu | ✅ GOTOWE |
| `web_portal/src/components/widgets/AccountSummary.tsx` | Naprawiono pole `account_mode` — poprawne odczytywanie trybu konta | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-28 (Sesja E — Poprawki bezpieczeństwa Telegram + artefakty)

| Plik | Zmiana | Status |
|------|--------|--------|
| `telegram_bot/bot.py` | `ADMIN_TOKEN` ładowany z `.env`; `_is_authorized()` poprawiony — brak CHAT_ID blokuje wszytkich | ✅ GOTOWE |
| `telegram_bot/bot.py` | `/stop` poprawiony — wywołuje `POST /api/control/state` z `ADMIN_TOKEN` (było: martwy kod) | ✅ GOTOWE |
| `telegram_bot/bot.py` | `/governance` i `/incidents` — dodano `_check_auth` (wcześniej bez autoryzacji) | ✅ GOTOWE |
| `telegram_bot/bot.py` | `reject_command` — naprawiono błąd wcięcia bloku `if not context.args:` | ✅ GOTOWE |
| `backend/routers/orders.py` | Usunięto blok `generate_demo_orders` w `export_orders_csv` (powodował `NameError` w runtime) | ✅ GOTOWE |
| `PROGRAM_REVIEW.md` | Zaktualizowano: 8 pozycji przeniesiono do NAPRAWIONE, KRYTYCZNE zredukowane z 6 do 3 | ✅ GOTOWE |
| `tests/test_smoke.py` | Testy: **174/174 ✅** | ✅ GOTOWE |

---

## SESJA 2026-03-28 (Sesja F — Best Trade Engine + F2)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/signals.py` | Dodano `_score_opportunity()` — scoring: confidence×10, trend±1.5, RSI±1.5, R/R+1.0, HOLD-3.0 | ✅ GOTOWE |
| `backend/routers/signals.py` | Nowy endpoint `GET /api/signals/best-opportunity` — zwraca BUY/SELL/CZEKAJ z uzasadnieniem | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `BestOpportunityCard` widget — zastąpił stary "Co teraz zrobić?" baner | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `BestOpportunityCard` — zielona/czerwona karta, pasek pewności, breakdown punktów, runner-up | ✅ GOTOWE |
| `tests/test_smoke.py` | Dodano `test_signals_best_opportunity`; testy: **175/175 ✅** | ✅ GOTOWE |
| Weryfikacja stanu systemu | Wszystkie 6 endpointów zwraca 200 (localhost + LAN) po resecie sesji | ✅ GOTOWE |

---

## ETAP 0 — 2026-03-28 (Stabilne uruchamianie projektu)

| Plik | Zmiana | Status |
|------|--------|--------|
| `scripts/start_dev.sh` | Skrypt startowy: wykrywa działające procesy, uruchamia backend+frontend, weryfikuje HTTP 200 | ✅ GOTOWE |
| `scripts/stop_dev.sh` | Skrypt stop: zatrzymuje przez PID file + fallback `fuser` na portach | ✅ GOTOWE |
| `scripts/status_dev.sh` | Skrypt status: sprawdza porty + 6 endpointów HTTP | ✅ GOTOWE |
| `START_HERE.md` | Dokument startowy: jak uruchomić, adresy, logi, zmienne env, pierwsze uruchomienie | ✅ GOTOWE |
| `MASTER_INDEX.md` | Zaktualizowano: sekcja `scripts/` + statusy aktualności dokumentów | ✅ GOTOWE |
| `CURRENT_STATE.md` | Zaktualizowano: sesje D-F, ETAP 0, GAP-13, GAP-14, GAP-15, GAP-16 | ✅ GOTOWE |
| `OPEN_GAPS.md` | Zaktualizowano: GAP-13 (F2 DONE), GAP-14 (ETAP 0 DONE), GAP-15, GAP-16 | ✅ GOTOWE |

---

## ETAP 2 — 2026-03-28 (Naprawa luk widocznych dla użytkownika)

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/MainContent.tsx` | GAP-15: `refreshMs=30000` dodany do 4 useFetch w `SymbolDetailPanel` (analysis, signals, accuracy, decisions) — dane live zamiast zamrożonych | ✅ GOTOWE |
| `web_portal/src/components/widgets/TradingView.tsx` | GAP-09: EMA20/EMA50 linie na wykresie TradingView (ComposedChart) + mini-panel RSI(14) pod wykresem | ✅ GOTOWE |
| `web_portal/src/components/widgets/TradingView.tsx` | GAP-09: Poprawiony import recharts (ComposedChart, Line, LineChart), dodano `calcEma()`, `calcRsi()`, stan `rsiData`, legenda wskaźników | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | GAP-06: `MarketProxyView` zastąpiony — Economics/Alerty/Wiadomości teraz wyświetlają EmptyState "Moduł w przygotowaniu" zamiast fałszywych danych proxy | ✅ GOTOWE |
| `OPEN_GAPS.md` | Zaktualizowano: GAP-06, GAP-09, GAP-15, GAP-16 oznaczone jako ✅ DONE; tabela planu zaktualizowana | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — 0 błędów po wszystkich zmianach | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## ETAP 3 — 2026-03-28 (Globalny przełącznik DEMO/LIVE — jedno źródło prawdy)

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/Topbar.tsx` | Zastąpiono niefunkcjonalny dropdown "Basic Dom" dwoma przyciskami DEMO/LIVE; typ zwężony do `'live' \| 'demo'` | ✅ GOTOWE |
| `web_portal/src/components/Sidebar.tsx` | Dodano props `tradingMode` + `setTradingMode`; usunięto hardcoded "DEMO AKTYWNY"; dodano interaktywny picker DEMO/LIVE | ✅ GOTOWE |
| `web_portal/src/components/Dashboard.tsx` | Zwężono typ z `'live' \| 'demo' \| 'backtest'` → `'live' \| 'demo'`; przekazano `tradingMode`/`setTradingMode` do Sidebar | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | Zwężono typ interfejsu; naprawiono hardcoded `mode=demo` → `mode=${mode}` w close-all; badge LIVE (amber) / DEMO (zielony) w DashboardHeader i ClassicDashboardView; dodano `const mode` w ClassicDashboardView; `<DecisionRisk mode={mode}>` | ✅ GOTOWE |
| `web_portal/src/components/widgets/OpenOrders.tsx` | Dodano `mode` prop z domyślnym `'demo'`; poprawiono 4 hardcoded `mode=demo` na `mode=${mode}`; dependency `[mode]` w useEffect | ✅ GOTOWE |
| `web_portal/src/components/widgets/DecisionRisk.tsx` | Dodano `mode` prop; fetch URL `risk?mode=${mode}` (był hardcoded `mode=demo`); dependency `[mode]` | ✅ GOTOWE |
| `web_portal/src/components/widgets/PositionsTable.tsx` | Dodano `mode` prop; fetch URL `positions?mode=${mode}` (był hardcoded `mode=demo`); dependency `[mode]` | ✅ GOTOWE |
| `web_portal/src/components/widgets/DecisionsRiskPanel.tsx` | Poprawiono 3 hardcoded `mode=demo` w URL-ach (reloadPending, useEffect tasks, submitTicket POST) na `mode=${mode}` | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — **0 błędów** po wszystkich zmianach | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## ETAP 4 — 2026-03-28 (Hotfix CSS + LIVE fallback + ForecastChart)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/account.py` | `get_account_summary` LIVE: zamieniono `HTTPException(401)` na graceful HTTP 200 + `_info` | ✅ GOTOWE |
| `web_portal/src/components/widgets/AccountSummary.tsx` | Auto-refresh co 60s + amber karta z `_info` gdy Binance niedostępne | ✅ GOTOWE |
| `web_portal/src/components/widgets/DecisionRisk.tsx` | Czytelne stany błędów, message zależny od `mode` | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `score_breakdown` jako lista punktowana; `ForecastChart` refreshMs 0→30000/60000 | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — **0 błędów** | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## ETAP 5 — 2026-03-28 (Portfel LIVE Binance — pełny majątek + prognoza)

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/routers/portfolio.py` | Nowy endpoint `GET /api/portfolio/wealth?mode=` — majątek portfela: pozycje z wartościami EUR, historia equity, wolna gotówka; LIVE + DEMO | ✅ GOTOWE |
| `backend/routers/portfolio.py` | Nowy endpoint `GET /api/portfolio/forecast?mode=` — prognoza wartości portfela za 1h/2h/7d bazowana na ForecastRecord; 2h interpolacja, 7d ekstrapolacja z 24h | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `PortfolioView` — pełna przebudowa: KPI cards, prognoza 1h/2h/7d, wykres equity 48h, tabela składu z klikalnymi symbolami | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `SymbolDetailPanel` — dodano blok „Ilość / Wartość pozycji / Zmiana %" gdy symbol jest w portfelu | ✅ GOTOWE |
| TypeScript | `npx tsc --noEmit` — **0 błędów** | ✅ GOTOWE |
| Testy backend | `pytest tests/test_smoke.py` — **175/175 ✅** | ✅ GOTOWE |

---

## SZABLON DLA PRZYSZŁYCH SESJI

```
## SESJA [DATA] (Sesja X — Tytuł)

| Plik | Zmiana | Status |
|------|--------|--------|
| `ścieżka/pliku` | Opis zmiany | ✅/🔴/⏳ |
```

---

## SESJA (ETAP 8 — Stabilizacja danych konta)

### Frontend — pełna migracja na `/api/portfolio/wealth`

| Plik | Zmiana | Status |
|------|--------|--------|
| `web_portal/src/components/MainContent.tsx` | `DashboardV2View`: `/api/account/summary?mode=` → `/api/portfolio/wealth?mode=` — ujednolicone pola (total_equity, free_cash, positions_value, unrealized_pnl, equity_change, equity_change_pct). Etykiety KPI: "Zmiana equity (24h)" i "Zmiana equity % (24h)" | ✅ GOTOWE |
| `web_portal/src/components/MainContent.tsx` | `SettingsView`: `/api/account/summary?mode=` → `/api/portfolio/wealth?mode=` — wyświetlane pola total_equity i balance | ✅ GOTOWE |

### Weryfikacja backendu SymbolDetailPanel

| Endpoint | Status |
|----------|--------|
| `/api/positions/decisions/{symbol}` | ✅ Istnieje (positions.py:549) |
| `/api/market/forecast-accuracy/{symbol}` | ✅ Istnieje (market.py:702) |
| `/api/positions/goal/{symbol}` | ✅ Istnieje (positions.py:490) |

### Rezultat

- **Zero** odwołań do `/api/account/summary` lub `/api/account/kpi` w frontendzie ✅
- `AccountSummary.tsx` widget — sierota (niezaimportowany nigdzie), nieusuwany
- Testy: **175/175 ✅** | TypeScript: **0 błędów ✅**

---

## PODSUMOWANIE STANU

| Metryka | Wartość |
|---------|---------|
| Testy | **175/175 ✅** |
| TypeScript błędy | **0 ✅** |
| Źródło danych konta (frontend) | **Wyłącznie `/api/portfolio/wealth`** ✅ |
| Otwarte gapy aktywne | 5 (GAP-06, GAP-07 partial, GAP-09 partial, GAP-15, GAP-16) |
| Zrealizowane gapy | 10 (GAP-01 do GAP-10) + GAP-13 + GAP-14 |
| Status ogólny | v0.7-beta — backend ✅, UI ✅, uruchamianie ✅ |

---

## SESJA 2026-03-29 (Sesja G — Standard datetime UTC: `utc_now_naive()`)

### Backend — unifikacja obsługi czasu UTC

| Plik | Zmiana | Status |
|------|--------|--------|
| `backend/database.py` | Dodano `utc_now_naive()` — jedyna dopuszczalna funkcja zwracająca UTC jako naive datetime; 35+ `default=lambda: datetime.now(...)` → `default=utc_now_naive` | ✅ GOTOWE |
| 25 plików backend + `telegram_bot/bot.py` | `datetime.now(timezone.utc).replace(tzinfo=None)` → `utc_now_naive()` | ✅ GOTOWE |
| `backend/reporting.py`, `collector.py`, `reevaluation_worker.py`, `operator_console.py`, `policy_layer.py` | Naprawka uszkodzonych multi-line importów po masowym replacemencie | ✅ GOTOWE |

### Dokumentacja

| Plik | Zmiana | Status |
|------|--------|--------|
| `SYSTEM_RULES.md` | Dodano sekcję 6.5 — standard `utc_now_naive()` z przykładami i zakazami | ✅ GOTOWE |
| `PROGRAM_REVIEW.md` | Zaktualizowano: problem datetime → ✅ NAPRAWIONE, metryki (0 warnings) | ✅ GOTOWE |
| `CURRENT_STATE.md` | Zaktualizowano: 3 wpisy `datetime.utcnow` → NAPRAWIONE | ✅ GOTOWE |

### Metryki sesji

| Metryka | Wartość |
|---------|---------|
| Testy | **175/175 ✅** |
| Zastąpień `datetime.now(timezone.utc).replace(tzinfo=None)` | **203 w 26 plikach** |
| Deprecation warnings | **0** |
| Nowy helper | `utc_now_naive()` w `backend/database.py` |
