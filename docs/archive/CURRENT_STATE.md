# CURRENT_STATE — RLdC AiNalyzator
*Jeden dokument, jeden prawdziwy stan. Data: 2026-03-28.*
*Zasada: tylko fakty potwierdzone kodem lub żywym endpointem — żadnych domysłów.*

---

## JAK URUCHOMIĆ PROJEKT

```bash
bash scripts/start_dev.sh          # uruchamia backend + frontend
bash scripts/status_dev.sh         # sprawdza stan
bash scripts/stop_dev.sh           # zatrzymuje
```

| Adres | Co to |
|-------|-------|
| http://localhost:3000 | Aplikacja (lokalnie) |
| http://192.168.0.109:3000 | Aplikacja (LAN) |
| http://localhost:8000/docs | Dokumentacja API |

---

## CO DZIAŁA (w pełni, end-to-end)

### UI → dane widoczne dla użytkownika

| Funkcja | Gdzie widoczna | Odświeżanie |
|---------|---------------|-------------|
| Status systemu (kolektor, WS, dane) | Dashboard główny | co 20s |
| KPI konta (equity, cash, PnL, pozycje) | Dashboard główny | co 15s |
| Market Scanner top-5 | Dashboard główny | co 30s |
| Aktywne pozycje | Dashboard główny | co 30s |
| **Najlepsza okazja (BestOpportunityCard)** | Dashboard główny | co 20s |
| Kliknięcie w symbol → panel szczegółów | WSZYSTKIE widoki | przy otwarciu |
| Panel symbolu: cena, PnL, TP/SL, powody | Slide-in z prawej | przy otwarciu |
| Panel symbolu: wykres historyczny + prognoza AI | Slide-in z prawej | przy otwarciu |
| Panel symbolu: przycisk KUP (z kwotą EUR) | Slide-in z prawej | — |
| Panel symbolu: przycisk ZAMKNIJ (jeśli ma pozycję) | Slide-in z prawej | — |
| WLFI status (wartość, cel 300 EUR) | DashboardV2 | co 30s |
| Portfel: KPI (wartość konta, gotówka, wynik, poz.) | Portfel | co 30s |
| Portfel: prognoza wartości 1h/2h/7d | Portfel | co 60s |
| Portfel: wykres historii equity (ostatnie 48h) | Portfel | co 30s |
| Portfel: tabela składu (symbol, ilość, cena, wartość EUR, wynik) | Portfel | co 30s |
| Portfel LIVE: graceful fallback jeśli brak kluczy Binance | Portfel | co 30s |
| Strategie / top10 sygnałów | Strategie | co 20s |
| AI Sygnały (20 najnowszych) | AI Sygnały | co 15s |
| Ryzyko (drawdown, limity, pozycje) | Ryzyko | co 30s |
| Historia zleceń z filtrem czasu/symbolu | Zlecenia | brak auto-refresh |
| Potwierdzanie/odrzucanie pending orders | Zlecenia | — |
| Decyzje dla każdej pozycji (TRZYMAJ/SPRZEDAJ) | Decyzje | — |
| EquityCurve (krzywa equity) | DashboardV2 | co 60s |
| Wykres świecowy | DashboardV2 | co 60s |
| Reset konta demo | Dashboard (przycisk) | — |
| Blog (lista postów) | Blog | raz przy załadowaniu |

### Backend (API działa, ≥ 200)

| Obszar | Endpointy |
|--------|----------|
| Sygnały | `/api/signals/latest`, `/top10`, `/top5`, `/best-opportunity` ✅ |
| Analiza pozycji | `/api/positions/analysis`, `/api/positions/decisions/{symbol}`, `/api/positions/goal/{symbol}` ✅ |
| Market | `/api/market/scanner`, `/klines/{symbol}`, `/forecast/{symbol}`, `/forecast-accuracy/{symbol}`, `/analyze/{symbol}` ✅ |
| **Konto (źródło danych)** | **`/api/portfolio/wealth?mode=` — JEDYNE źródło KPI konta w UI** ✅ |
| Konto (pomocnicze) | `/api/account/risk`, `/system-status`, `/system-logs`, `/openai-status`, `/snapshots` ✅ |
| Zlecenia | `/api/orders`, `/pending`, `/{id}/confirm`, `/{id}/reject`, `/stats`, `/export.csv` ✅ |
| Portfel | `/api/portfolio/wealth?mode=`, `/api/portfolio/forecast?mode=` ✅ |
| Kontrola | `/api/control/state`, `/api/control/hold-status` ✅ |
| WLFI | `/api/account/wlfi-status` ✅ |

### Testy

```
175 / 175 passed ✅   (TypeScript: 0 błędów ✅)
```

---

## CO NIE DZIAŁA (brakujące lub zepsute)

| Problem | Priorytet | Opis |
|---------|-----------|------|
| **Live execution** | 🔴 KRYTYCZNY | `create_order` w `orders.py` celowo nie wysyła zleceń na Binance — brak logiki live |
| **Economics / Alerty / Wiadomości** | 🟡 ŚREDNI | Wyświetlają EmptyState „Moduł w przygotowaniu” — brak własnych danych |
| **macro-reports / reports** | 🟡 ŚREDNI | Widók obsłużony ale zwraca tylko „W trakcie przygotowania” + EmptyState |
| **Blog: zawsze puste** | 🟡 ŚREDNI | Backend generuje posty tylko z OpenAI — bez klucza API lista jest pusta |
| **Historia zleceń (Backtest View)** | 🟡 ŚREDNI | Pobiera statystyki zleceń, brak auto-refresh i pełnej historii |
| **Drawdown live Binance** | 🟡 ŚREDNI | `risk.py` zwraca `drawdown_real: 0.0` w trybie live — niezaimplementowane |
| **Trafność prognoz** | 🟡 ŚREDNI | Endpoint `/api/market/forecast-accuracy/{symbol}` istnieje, ale `ForecastRecord` tabela może być pusta — model accuracy niewidoczny |
| **Pozycje live Binance w UI** | 🟡 ŚREDNI | Panel Decyzje pokazuje tylko pozycje DEMO, nie synchronizuje z Binance live |

---

## CO JEST ZACZĘTE, ALE NIEKOMPLETNE

| Funkcja | Stan | Czego brakuje |
|---------|------|---------------|
| Symbol Detail Panel | Istnieje, zbudowany | Brak auto-refresh danych gdy panel jest otwarty (pobiera raz przy otwarciu) |
| TradingView wykres | Świece + EMA20/EMA50 + mini RSI ✅ | Brak: timeframe switch (1m/5m/1h/4h/1d), markery wejść/wyjść |
| Forecast AI | Backend ✅, widoczny w panelu | Brak wskaźnika % trafności prognoz (tabela ForecastRecord rzadko wypełniona) |
| Blog | Backend + UI istnieje | Backend potrzebuje OpenAI — bez klucza lista pusta |
| DashboardV2 (dashboard-classic) | Istnieje i działa | Nie istnieje jako pozycja w Sidebar (niedostępne bez ręcznej zmiany URL) |
| Pending orders confirm/reject | Działa w TradeDeskView | Brak w CommandCenter (dashboard główny) |
| Baktest View — historia | Ładuje listę zleceń | Brak wykresu equity na tym widoku, brak filtra po wyniku |

---

## DŁUG TECHNICZNY (kod działa, ale z problemem)

| Plik | Problem | Jak naprawić |
|------|---------|-------------|
| `backend/routers/market.py` | Podwójna definicja `_candidates` (L40 martwy kod — Python używa L374) | Usuń L40 |
| `backend/auth.py` | `require_admin` zdefiniowane, ale nieużywane na żadnym endpoincie | Podłącz lub usuń |
| `backend/routers/portfolio.py` | `import random` — nieużywane | Usuń |
| `backend/reporting.py` | `config_snapshot_payload_report` zwraca `{}` | Zaimplementuj lub usuń |
| `backend/candidate_validation.py` | Kompletny moduł, ale `collector.py` go nie importuje | Podłącz do collectora |
| Cały backend | ✅ `datetime.utcnow()` NAPRAWIONE — `utc_now_naive()` helper w `backend.database`, 203 zastąpienia w 26 plikach | — |
| `telegram_bot/bot.py` | Używa hardcoded `localhost:8000` zamiast `ENV API_BASE_URL` | Użyj zmiennej środowiskowej |

---

## CO JEST NASTĘPNE DO ZROBIENIA

### Kolejność priorytetów (od najważniejszego)

**1. Uzupełnienie martwych widoków lub ich ukrycie**
Economics, Alerty, Wiadomości, macro-reports, reports — albo własne dane, albo usunąć z Sidebar.
*Minimalny fix: ukryć 5 pozycji z Sidebar, poczekać na dane.*

**2. Auto-refresh w SymbolDetailPanel**
Panel pobiera dane raz przy otwarciu. Jeśli cena się zmienia, użytkownik nie widzi aktualizacji.
*Fix: dodać `refreshMs = 15000` do fetchów wewnątrz panelu.*

**3. Timeframe switch na wykresie TradingView**
Przełącznik 1h / 4h / 1d (backend endpoint obsługuje parametr `timeframe`).
*Fix: dropdown nad wykresem + przekazanie parametru do useFetch url.*

**4. Overlay RSI + EMA na wykresie TradingView**
Wskaźniki, których bot używa do decyzji, nie są widoczne na wykresie.
*Fix: dodaj panel RSI + linie EMA20/EMA50 na wykres Recharts.*

**5. Confirm/Reject pending orders z dashboardu głównego**
Teraz działa tylko w widoku Zlecenia. Wygodniej byłoby z dashboardu.
*Fix: dodaj przyciski akcji do listy pending w CommandCenterView.*

**6. Usunięcie martwego kodu backend**
market.py podwójna definicja, import random, require_admin.
*Szybkie 3-minutowe czyszczenie.*

**7. Live execution path**
`create_order` w `orders.py` nie wywołuje Binance.
*Większy zakres — wymagany moduł execute_market_order w binance_client.py.*

---

## 10 NAJWAŻNIEJSZYCH BRAKÓW Z PERSPEKTYWY UŻYTKOWNIKA

| # | Brak | Wpływ |
|---|------|-------|
| 1 | **Economics/Alerty/Wiadomości pokazują dane rynku** zamiast alertów | Dezorientuje — kliknięcie w "Alerty" nie daje alertów |
| 2 | **SymbolDetailPanel nie odświeża automatycznie** — ceny w panelu są "zamrożone" | Użytkownik widzi nieaktualne dane gdy analizuje symbol |
| 3 | **Brak timeframe switch na wykresie** (1m/5m/1h/4h/1d) | Nie można zobaczyć szerszego kontekstu, tylko domyślny interwał |
| 4 | **Brak RSI/EMA overlay na wykresie TradingView** | Bot używa RSI+EMA do decyzji, a użytkownik tego nie widzi |
| 5 | **Blog zawsze pusty** bez OpenAI API key | Sekcja niefunkcjonalna dla większości użytkowników |
| 6 | **Confirm/Reject pending order tylko w TradeDeskView** — nie w dashboardzie | Wymagane 2 kliknięcia w dodatkowy widok |
| 7 | **Historia zleceń nie odświeża się** — wymaga manualnego odwiedzenia widoku | Bez powiadomień — stare dane |
| 8 | **macro-reports i reports to placeholders** bez żadnych danych | 2 pozycje w Sidebar które nie działają |
| 9 | **Trafność prognoz niewidoczna** — tabela ForecastRecord pusta lub niezapełniona | Nie wiadomo czy prognoza AI jest wiarygodna |
| 10 | **Pozycje live Binance nie synchronizują się** — Portfel live pokazuje balanse, ale brak widoku pozycji analogicznego do demo | Użytkownik nie widzi stanu prawdziwego konta w formie kart pozycji |

---

## 5 NAJWAŻNIEJSZYCH BRAKÓW Z PERSPEKTYWY BOTA/TRADINGU

| # | Brak | Wpływ |
|---|------|-------|
| 1 | **Live execution nie istnieje** — `create_order` nie wywołuje Binance API | Bot w trybie live nie może handlować, tylko demo |
| 2 | **`candidate_validation.py` odłączony od `collector.py`** | Tuning→eksperyment→wdrożenie NIE jest domknięte; eksperymenty nie wpływają na collectora |
| 3 | **`market.py` podwójna definicja `_candidates` (L40 martwy kod)** | Python używa L374 — L40 nie ma żadnego efektu; myli przy debugowaniu |
| 4 | ✅ **`datetime.utcnow()` NAPRAWIONE** — `utc_now_naive()` w `backend.database`, 203 zastąpienia w 26 plikach | — |
| 5 | **`require_admin` w `auth.py` zdefiniowane, ale nieużywane** | Admin endpoints nie są chronione przez `require_admin` — dług bezpieczeństwa |

---

## METRYKI PROJEKTU (stan na 2026-03-28)

| Metryka | Wartość |
|---------|---------|
| Testy smoke | **175 / 175 ✅** |
| TypeScript błędy | **0 ✅** |
| MainContent.tsx | 2882 linii |
| Pliki backend .py | ~37 |
| Endpointy API | ~50+ |
| Widgety frontend | 11 + komponenty inline |
| Deprecation warnings | **0** (`utc_now_naive()` — helper w database.py) |
| Martwe katalogi (stub) | 6 (`hft_engine/`, `infrastructure/`, `quantum_optimization/`, `blockchain_analysis/`, `portfolio_management/`, `recommendation_engine/`, `ai_trading/`) |

---

## LEGENDA STATUSÓW W DOKUMENTACH PROJEKTU

| Plik | Rola | Stan aktualizacji |
|------|------|-------------------|
| `CURRENT_STATE.md` | **Ten plik** — jedyne źródło prawdy o stanie projektu | ✅ Aktualny (2026-03-28) |
| `OPEN_GAPS.md` | Lista braków użytkowych posortowana wg priorytetu | ✅ Aktualny (2026-03-28) |
| `FUNCTIONS_MATRIX.md` | Macierz ~108 funkcji: UI → backend → dane | ✅ Aktualny (2026-03-28) |
| `MASTER_INDEX.md` | Indeks plików projektu — role, powiązania | ✅ Aktualny (2026-03-28) |
| `PROGRAM_REVIEW.md` | Głęboki audyt kodu backend: każda funkcja, każdy plik | Aktualizowany po sesjach naprawczych |
| `START_HERE.md` | **Pierwsza instrukcja** — jak uruchomić projekt | ✅ Aktualny |
| `CHANGELOG_LIVE.md` | Dziennik zmian | Wymaga aktualizacji (sesje D-F, ETAP 0 nieodnotowane) |
| `TASK_QUEUE.md` | Stary format kolejki zadań | Archiwum — zastąpiony przez CURRENT_STATE.md |
| `MASTER_GAP_REPORT.md` | Stary raport statusu | Archiwum |
