# FUNCTIONS_MATRIX — RLdC AiNalyzator v0.7 beta
*Inwentaryzacja end-to-end: każda funkcja, każdy ekran, każdy endpoint.*
*Data: 2026-03-31 (zaktualizowano po sesjach B–G + GAP-15) | Zasada: DONE = działa od kliknięcia do danych, bez wyjątku.*

---

## LEGENDA

| Status | Definicja |
|--------|-----------|
| ✅ DONE | Działa end-to-end: UI → backend → dane → widoczny wynik |
| 🟡 PARTIAL | Część działa, ale brak pełnego flow lub dane są niekompletne |
| 🖼️ UI_ONLY | Widoczne w UI, endpoint nie istnieje lub zawsze zwraca puste |
| 🔧 BACKEND_ONLY | Endpoint działa, brak UI lub nie podłączony |
| 🔴 BROKEN | Wywołanie kończy się błędem, pustą stroną lub fałszywymi danymi |
| ⬜ NOT_STARTED | Nie istnieje w UI ani backendzie |

---

## A. PANEL GŁÓWNY (`dashboard`)

### A1. CommandCenterView (activeView='dashboard')

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| Status systemu (kolektor/WS/dane) | ✅ DONE | `/api/account/system-status` | Kolory, świeżość, czas | — |
| KPI konta (equity, cash, pozycje, 24h) | ✅ DONE | `/api/account/kpi?mode=demo` | 5 kart z danymi | Nie pokazuje realnego Binance |
| Market Scanner top-5 | ✅ DONE | `/api/market/scanner?top_n=5` | Symbol, kierunek, sygnał, confidence | Brak kliknięcia w symbol |
| Aktywne pozycje — karty | ✅ DONE | `/api/positions/analysis?mode=demo` | Decyzja, PnL, RSI, trend | Brak kliknięcia w symbol |
| "Co teraz zrobić?" | ✅ DONE | — (z danych powyżej) | SPRZEDAJ/KUP banner | Brak akcji buy/sell w jednym kroku |
| Rozkład rynku (BUY/HOLD/SELL) | ✅ DONE | z scanner | 3 liczniki | — |
| Reset konta demo | ✅ DONE | `POST /api/account/demo/reset-balance` | Formularz z kwotą, kasuje historię | — |
| **Kliknięcie w symbol → panel szczegółów** | ❌ NOT_STARTED | brak | — | Brak onClick, brak panelu |
| Forecast portfela (1h/2h/tydzień) | ❌ NOT_STARTED | brak | — | Endpoint nie istnieje |
| Wartość real Binance obok demo | ❌ NOT_STARTED | brak w tym widoku | — | Brak zakładek |

### A2. DashboardV2View (activeView='dashboard-classic')

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| KPI strip (6 kart) | ✅ DONE | `/api/account/summary` | Equity, cash, pozycje, PnL | — |
| TradingView wykres | 🟡 PARTIAL | `/api/market/klines/{symbol}` | Wykres Recharts ze świecami | Brak forecast overlay, brak kliknięcia w symbol z list |
| EquityCurve | 🟡 PARTIAL | `/api/account/snapshots` | Linia equity | Tylko demo, brak Binance live |
| Pozycje otwarte z close 25%/50%/100% | ✅ DONE | `/api/positions + /close` | Partial close działa | — |
| OpenOrders | ✅ DONE | `/api/orders` | Lista zleceń | — |
| OpenAI Ranges Widget | 🟡 PARTIAL | `/api/market/ranges` | Zakresy BUY/SELL | Może pokazywać puste gdy brak OpenAI |
| DecisionsRiskPanel | 🟡 PARTIAL | `/api/positions/analysis` | Panel z decyzjami | Dane dla 1 symbolu |
| MarketInsights | ✅ DONE | `/api/signals/latest` | Sygnały z analizy | — |
| **Zmiana symbolu** | 🟡 PARTIAL | — | Dropdown w TradingView | Zmiana nie propaguje wszystkich widgetów |

---

## B. KLIKNIĘCIE W SYMBOL

| Miejsce | Status | Co się dzieje po kliknięciu |
|---------|--------|----------------------------|
| Market Scanner (CommandCenter) | ✅ DONE | Otwiera `SymbolDetailPanel` slide-in z prawej (sesja B) |
| Aktywne pozycje (CommandCenter) | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| BestOpportunityCard (symbol w karcie) | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja F) |
| PortfolioView — tabela pozycji | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| StrategiesView — top10 tabela | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| SignalsView — tabela sygnałów | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| TradeDeskView — tabela zleceń | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| RiskView — tabela ryzyka | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| MarketsView — tabela rynków | ✅ DONE | Otwiera `SymbolDetailPanel` (sesja B) |
| DashboardV2 — TradingView symbol select | 🟡 PARTIAL | Zmienia symbol wykresu lokalnie, nie otwiera panelu |

**WNIOSEK: Kliknięcie w symbol DZIAŁA we wszystkich 9 głównych widokach.** Globalny stan `selectedSymbol` w `MainContent.tsx` → `SymbolDetailPanel` overlay.

---

## C. WIDOK SYMBOLU (Symbol Detail Panel)

| Funkcja | Status | Endpoint | Uwagi |
|---------|--------|----------|-------|
| **Cały widok** | ✅ DONE | — | `SymbolDetailPanel` — slide-in overlay z prawej (sesja B) |
| Nazwa symbolu z formatowaniem | ✅ DONE | — | Nagłówek panelu |
| Stan w portfelu (ilość, wejście, wartość) | ✅ DONE | `/api/positions/analysis` | Karta pozycji jeśli otwarta |
| Cena zakupu vs cena teraz | ✅ DONE | `/api/market/analyze/{symbol}` | Cena live + entry_price + delta |
| PnL (EUR + %) | ✅ DONE | `/api/positions/analysis` | Zielony/czerwony |
| Wykres historyczny | ✅ DONE | `/api/market/klines/{symbol}` | `ForecastChart` — Recharts ze świecami |
| **Forecast do przodu** | ✅ DONE | `/api/market/forecast/{symbol}` | Przerywana linia pomarańczowa po „teraz" (sesja B) |
| Oznaczenie: historia vs prognoza | ✅ DONE | — | Pionowa linia „TERAZ" na wykresie |
| EMA20/EMA50 na wykresie | ✅ DONE | z klines | Linie EMA na ForecastChart (sesja C) |
| Panel RSI(14) | ✅ DONE | z klines | Mini-panel RSI pod wykresem (sesja C) |
| Trafność poprzednich prognoz | 🟡 PARTIAL | `/api/market/forecast-accuracy/{symbol}` | Endpoint istnieje; tabela ForecastRecord rzadko wypełniona |
| Ruchy wielorybów (whale alerts) | ❌ NOT_STARTED | brak endpointu | Brak całkowicie |
| Decyzja systemu: KUP/SPRZEDAJ/CZEKAJ | ✅ DONE | `/api/market/analyze/{symbol}` | Baner decyzji z uzasadnieniem |
| Uzasadnienie po ludzku | ✅ DONE | `/api/positions/analysis` | Lista `reasons[]` w panelu |
| Ustawianie celu ręcznie | ✅ DONE | `POST /api/account/user-target` | Backend persists (sesja C) |
| Ustawianie celu przez AI | ❌ NOT_STARTED | brak endpointu | AI nie proponuje celu automatycznie |
| Edycja celu | ✅ DONE | `POST /api/account/user-target` | Pole input w panelu |
| Historia decyzji dla symbolu | ✅ DONE | `/api/positions/decisions/{symbol}` | Endpoint + UI (sesja C) |
| **KUP TERAZ** (z kwotą EUR) | ✅ DONE | `POST /api/orders` | Przycisk „KUP" w SymbolDetailPanel (sesja B) |
| **KUP Z CELEM** | ❌ NOT_STARTED | brak endpointu | Nie istnieje |
| **ZAMKNIJ POZYCJĘ** | ✅ DONE | `POST /api/positions/{id}/close` | Przycisk „ZAMKNIJ POZYCJĘ" (jeśli pozycja otwarta) |
| Ustawienie ilości | 🟡 PARTIAL | — | Używa domyślnej kwoty EUR z ustawień |
| Tryb demo / real toggle per symbol | ❌ NOT_STARTED | — | Brak |
| **Auto-refresh danych w panelu** | ✅ DONE | — | co 15s: analysis, signals, ticker; DataStatus w nagłówku — GAP-15 ✅ (sesja G) |
| Komentarz AI: „ma sens / nie ma sensu" | ❌ NOT_STARTED | brak endpointu | Brak |

---

## D. PANEL PORTFELA (`portfolio`)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| **Demo pozycje** | 🟡 PARTIAL | `/api/portfolio?mode=demo` | Lista z danymi | Brak live price, brak kliknięcia w symbol |
| Wartość demo konta łącznie | ❌ NOT_STARTED | brak w portfolio endpoincie | — | Brak KPI na górze widoku Portfel |
| **Binance Spot balances** | 🟡 PARTIAL | `/api/portfolio?mode=live` | Tabela z tokenami | Często puste — wymaga kluczy API |
| Binance Futures balance | 🟡 PARTIAL | `/api/portfolio?mode=live` | Tabela | Często brak danych |
| Binance Simple Earn Flexible | 🟡 PARTIAL | `/api/portfolio?mode=live` | Tabela | Dane mogą być puste |
| Binance Simple Earn Locked | 🟡 PARTIAL | `/api/portfolio?mode=live` | Tabela | Dane mogą być puste |
| **Łączna wartość Binance w EUR** | ❌ NOT_STARTED | brak | — | Brak przeliczenia aktywów na EUR |
| Wykres equity portfela (demo) | ❌ NOT_STARTED | brak w tym widoku | — | EquityCurve jest tylko w DashboardV2 |
| Wykres equity portfela (Binance) | ❌ NOT_STARTED | brak | — | Brak danych historycznych Binance equity |
| Porównanie demo vs Binance | ❌ NOT_STARTED | brak | — | Brak zakładek DEMO / LIVE |
| Kliknięcie w aktywo → panel | ❌ NOT_STARTED | — | — | Brak |

---

## E. PANEL STRATEGII (`strategies`)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| Top 10 sygnałów tabela | ✅ DONE | `/api/signals/top10` | Symbol, sygnał, pewność, cena, czas | Brak kliknięcia w symbol |
| Filtr po sygnale (BUY/SELL/HOLD) | ❌ NOT_STARTED | — | — | Brak filtrow UI |
| Sortowanie po pewności | ❌ NOT_STARTED | — | Dane są posortowane przez API | Brak sortowania w UI |
| Historia sygnałów | ❌ NOT_STARTED | — | — | Brak |

---

## F. AI SYGNAŁY (`ai-signals`)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| 20 najnowszych sygnałów | ✅ DONE | `/api/signals/latest` | Tabela z danymi | Brak kliknięcia w symbol, brak wskaźników (RSI/EMA) |
| Trafność sygnałów historycznie | ❌ NOT_STARTED | brak | — | Brak całkowicie |
| Filtr po typie sygnału | ❌ NOT_STARTED | — | — | Brak |

---

## G. RYZYKO (`risk`)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| KPI ryzyka (drawdown, limity) | ✅ DONE | `/api/account/risk` | 6 kart | — |
| Alert limit straty przekroczony | ✅ DONE | z risk endpointu | Czerwony banner | — |
| Tabela pozycji z decyzjami | ✅ DONE | `/api/positions/analysis` | Symbol, decyzja, wynik, RSI, trend | Brak kliknięcia w symbol |
| Drawdown live (real Binance) | 🔴 BROKEN | `/api/account/risk?mode=live` | Zwraca 0.0 zawsze | Niezaimplementowane w risk.py |

---

## H. HISTORIA ZLECEŃ (`backtest`)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| Statystyki 30 dni (total/filled/fill_rate) | ✅ DONE | `/api/orders/stats` | 3 liczniki | Brak wykresu, brak per-symbol |
| Lista zleceń historycznych | 🔧 BACKEND_ONLY | `/api/orders` | Endpoint zwraca dane | Widok Backtest nie wyświetla listy zleceń |
| Eksport CSV | 🔧 BACKEND_ONLY | `/api/orders/export.csv` | Endpoint OK | Brak przycisku w UI |
| Filtrowanie po symbolu/czasie | 🟡 PARTIAL | dostępne w TradeDeskView | Działa w Zlecenia | Nie ma w widoku Historia |

---

## I. ZLECENIA (trade-desk)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| Lista zleceń z filtrem czasu | ✅ DONE | `/api/orders` | Filtr 24h/3d/7d/30d | Brak kliknięcia w symbol |
| Filtr po symbolu | ✅ DONE | — (client-side) | Dropdown | Tylko symbole z historii |
| Lista oczekujących zleceń | ✅ DONE | `/api/orders/pending` | Tabela | Brak akcji confirm/reject z UI (tylko przez Telegram) |
| Confirm pending order | ✅ DONE | `POST /api/orders/{id}/confirm` | Endpoint ✅ | Przyciski w TradeDeskView (sesja B) |
| Reject pending order | ✅ DONE | `POST /api/orders/{id}/reject` | Endpoint ✅ | Przyciski w TradeDeskView (sesja B) |
| **Nowe zlecenie** | ❌ NOT_STARTED | `POST /api/orders` | Endpoint ✅ | Brak formularza w UI |

---

## J. DECYZJE (`position-analysis`)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| Karty wszystkich pozycji | ✅ DONE | `/api/positions/analysis` | Pełna karta pozycji | — |
| KPI podsumowania portfela | ✅ DONE | z powyższego | 5 kart | — |
| Decyzja: TRZYMAJ/SPRZEDAJ/OBSERWUJ | ✅ DONE | — | Kolor i label | — |
| Powody decyzji | ✅ DONE | — | Lista reasons | — |
| Co teraz zrobić (opis) | ✅ DONE | — | Tekst per decyzja | — |
| Analiza techniczna (RSI/EMA/trend) | ✅ DONE | — | Po każdej karcie | — |
| TP/SL system | ✅ DONE | — | Pokazuje jeśli ustawione | — |
| Cel HOLD (jeśli HOLD mode) | ✅ DONE | — | Wartość i brakująca kwota | — |
| **Ustawianie celu użytkownika** | 🟡 PARTIAL | localStorage | Działa tylko tu | Nie persists do backendu, nie widoczne w innych widokach |
| Ocena realizmu celu | ✅ DONE | — | % i opis | — |
| **Kliknięcie w symbol → pełny panel** | ✅ DONE | — | Nagłówek karty otwiera SymbolDetailPanel (sesja B) | — |
| **Akcja: Zamknij pozycję** | ✅ DONE | `/api/positions/{id}/close` | Przycisk „ZAMKNIJ" w SymbolDetailPanel (sesja B) | — |
| Forecast dla symbolu | ✅ DONE | `/api/market/forecast/{symbol}` | Widoczne w ForecastChart w SymbolDetailPanel | — |

---

## K. WYKRES (`TradingView` widget)

| Funkcja | Status | Endpoint | Co działa | Czego brakuje |
|---------|--------|----------|-----------|---------------|
| Pobieranie świec | ✅ DONE | `/api/market/klines/{symbol}` | Rekharty świecowe  | — |
| Wybór symbolu | 🟡 PARTIAL | — | Dropdown działa w DashboardV2 | Nie synchronizuje innych widoków |
| RSI overlay | ❌ NOT_STARTED | — | — | Brak w TradingView (DashboardV2); ✅ w SymbolDetailPanel |
| EMA overlay | ❌ NOT_STARTED | — | — | Brak w TradingView (DashboardV2); ✅ w SymbolDetailPanel |
| **Forecast overlay** | ❌ NOT_STARTED | `/api/market/forecast/{symbol}` | Backend ✅ | Brak w TradingView; ✅ w SymbolDetailPanel |
| **Oznaczenie granicy historia/prognoza** | ❌ NOT_STARTED | — | — | Brak w TradingView; ✅ w SymbolDetailPanel |
| Wejście/wyjście pozycji na wykresie | ❌ NOT_STARTED | — | — | Brak markerów entry/exit |
| Linia TP/SL na wykresie | ❌ NOT_STARTED | — | — | Brak |
| Timeframe switch (1m/5m/1h/1d) | ❌ NOT_STARTED | `/api/market/klines/{symbol}?timeframe=X` | Backend ✅ | Brak przełącznika w UI |

---

## L. SYNCHRONIZACJA I ODŚWIEŻANIE DANYCH

| Widok | Odświeżanie | Stan |
|-------|-------------|------|
| Panel główny — KPI | co 15s | ✅ |
| Panel główny — Scanner | co 30s | ✅ |
| Panel główny — Pozycje | co 30s | ✅ |
| SystemStatusBar | co 20s | ✅ |
| Portfel | co 30s | ✅ (sesja B, GAP-07) |
| Strategie | co 20s | ✅ |
| AI Sygnały | co 15s | ✅ |
| Ryzyko | co 30s | ✅ |
| Historia | co 60s | ✅ (sesja B, GAP-07) |
| SymbolDetailPanel — ticker | co 15s | ✅ (sesja G, GAP-15) |
| TradingView wykres | co 60s | 🟡 (wolno) |
| EquityCurve | co 60s | ✅ |
| OpenOrders | brak refresh | 🔴 BROKEN |
| Ekonomia/Alerty/Wiadomości | RAZ | 🔴 BROKEN (proxy do market/summary) |
| Raporty/Statystyki | ❌ NOT_STARTED | — |

---

## M. DEMO vs REAL

| Funkcja | DEMO | REAL Binance |
|---------|------|-------------|
| Equity / wolne środki | ✅ | 🟡 (na żądanie, brak auto-refresh) |
| Pozycje | ✅ | ❌ (brak synchronizacji z Binance) |
| Historia zleceń | ✅ | ❌ (Binance zlecenia nie importowane) |
| Bot handluje | ✅ | ❌ (celowo zablokowane) |
| Sygnały | ✅ | ✅ (te same) |
| Reset konta | ✅ | ❌ (nie ma sensu) |
| Panel portfela | 🟡 (tylko pozycje) | 🟡 (tabele Spot/Earn/Futures) |
| Wykres equity | ✅ | ❌ |
| Drawdown | ✅ | 🔴 (zawsze 0.0) |

---

## N. WIDOKI MARTWE / STUB

| Widok | Status | Co zwraca |
|-------|--------|-----------|
| `economics` | 🔴 BROKEN | Proxy do `/api/market/summary` — ta sama tabela co Markets |
| `alerts` | 🔴 BROKEN | To samo co Economics — brak własnego endpointu |
| `news` | 🔴 BROKEN | To samo co Economics |
| `macro-reports` | 🟡 PARTIAL | Routing obsłużony — pokazuje „Moduł w trakcie przygotowania" (sesja B) |
| `reports` | 🟡 PARTIAL | Routing obsłużony — pokazuje „Moduł w trakcie przygotowania" (sesja B) |
| `blog` | 🟡 PARTIAL | `/api/blog/list` — tabela, ale backend blog.py zwraca puste |
| `backtest` | 🟡 PARTIAL | Statystyki 30 dni, bez listy zleceń i wykresów |
| `ClassicDashboardView` | ❌ NOT_STARTED | Nigdy nie wywoływana (`dashboard-classic` nie ma w Sidebar) |

---

## PODSUMOWANIE STATUSÓW

| Status | Sesja B (stare) | Aktualne (2026-03-28) |
|--------|-----------------|----------------------|
| ✅ DONE | ~28 | **~65** |
| 🟡 PARTIAL | ~22 | **~18** |
| 🔧 BACKEND_ONLY | ~8 | **~2** |
| 🖼️ UI_ONLY | 0 | 0 |
| 🔴 BROKEN | ~12 | **~5** |
| ❌ NOT_STARTED | ~38 | **~18** |
| Blog | RAZ | 🟡 |

*Aktualizacja po sesji G (2026-03-31): GAP-15 DONE (+1 funkcja)*

---

## PRIORYTETY NAPRAWY (wg wpływu na użyteczność i trading)

### ✅ PRIORYTET 1 — Kliknięcie w symbol + Symbol Detail Panel — **ZROBIONE (sesja B)**

- [x] Globalny stan `selectedSymbol` w MainContent.tsx
- [x] SymbolDetailPanel komponent (slide-in overlay)
- [x] onClick dodany do: scanner, pozycje, strategie, sygnały, ryzyko, portfel, rynki
- [x] Forecast overlay na wykresie (linia „prognoza" po „teraz")
- [x] KUP / ZAMKNIJ w panelu symbolu
- [ ] **GAP-15: Auto-refresh danych w otwartym panelu** (dane zamrożone przy otwarciu)

### ✅ PRIORYTET 2 — Synchronizacja danych i martwe karty — **CZĘŚCIOWO ZROBIONE (sesja B)**

- [x] Portfel: auto-refresh co 30s
- [x] Historia zleceń: auto-refresh co 60s
- [x] macro-reports / reports: obsłużone w OtherView (stub z komunikatem)
- [ ] OpenOrders: brak auto-refresh (nadal broken)
- [ ] Economics/Alerty/Wiadomości: nadal proxy do market/summary

### ✅ PRIORYTET 3 — Brakujące akcje użytkownika — **ZROBIONE (sesja B)**

- [x] Confirm/Reject pending order z UI (TradeDeskView)
- [x] ZAMKNIJ pozycję z panelu SymbolDetailPanel
- [ ] Nowe zlecenie (formularz poza widokiem TradeDeskView)

### 🟡 PRIORYTET 4 — Forecast accuracy — **CZĘŚCIOWE (sesja C)**

- [x] Tabela ForecastRecord w DB
- [x] Zapis forecast przy generowaniu
- [x] Endpoint forecast-accuracy/{symbol}
- [ ] Po N minut: automatyczne porównanie z rzeczywistością (rzadko działa)
- [ ] Wyświetlenie % trafności w panelu symbolu (PARTIAL — dane rzadko dostępne)

### � PRIORYTET 5 — Uzupełnienia wykresu TradingView (DashboardV2)
*Uwaga: EMA/RSI/Forecast DONE w SymbolDetailPanel. W TradingView nadal brak.*

- [ ] RSI panel pod wykresem (TradingView)
- [ ] EMA20/EMA50 linie (TradingView)
- [ ] Timeframe switch (TradingView)
- [ ] Markery wejścia/wyjścia pozycji

### ✅ PRIORYTET 6 — GAP-15: Auto-refresh w SymbolDetailPanel — **ZROBIONE (sesja G)**

- [x] `refreshMs=15000` dla analysis, signals i ticker (`/api/market/ticker/{symbol}`) w SymbolDetailPanel
- [x] `DataStatus` z czasem ostatniej aktualizacji w nagłówku panelu
