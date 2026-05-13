# CHECKLIST OPERACYJNA — RLdC AiNalyzer
*Ostatnia aktualizacja: 2026-03-30 | Wersja: v0.7-beta*
*Jedna kartka: co sprawdzić po restarcie, co działa, co jest stubem.*

---

## URUCHOMIENIE

```bash
# Backend (z katalogu projektu)
DISABLE_COLLECTOR=true .venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload &

# Frontend (z katalogu web_portal)
cd web_portal && npm run dev
```

| Adres | Co to |
|-------|-------|
| http://localhost:3000 | Aplikacja |
| http://localhost:8000/docs | Dokumentacja API |
| http://localhost:8000/api/account/system-status | Szybki test backendu |

---

## ŹRÓDŁA DANYCH — CO SKĄD POCHODZI

| Dane | Jedyne źródło prawdy | Odświeżanie UI |
|------|---------------------|----------------|
| KPI konta (equity, cash, PnL) | `/api/portfolio/wealth?mode=` | co 15s |
| Prognoza portfela | `/api/portfolio/forecast?mode=` | co 60s |
| Stan systemu (kolektor, WS) | `/api/account/system-status` | co 20s |
| Ryzyko (drawdown, limity) | `/api/account/risk?mode=` | co 30s |
| Sygnały AI | `/api/signals/latest`, `/top10`, `/best-opportunity` | co 15–20s |
| Analiza pozycji | `/api/positions/analysis?mode=` | co 30s |
| Decyzje historyczne | `/api/positions/decisions/{symbol}` | co 60s |
| Rynek (podsumowanie, zakresy) | `/api/market/summary`, `/market/ranges` | co 15s |
| Skaner rynku | `/api/market/scanner?top_n=5` | co 30s |
| Prognoza symbolu | `/api/market/forecast/{symbol}` | w panelu symbolu |
| Zlecenia | `/api/orders?mode=`, `/orders/pending?mode=` | co 30s |
| Logi systemu | `/api/account/system-logs` | co 60s |
| Kontrola (watchlist, trading) | `/api/control/state` | co 15s |

> ⚠️ **Stary `/api/account/summary` i `/api/account/kpi` NIE są wywoływane przez frontend.  
> Jedyne źródło KPI konta to `/api/portfolio/wealth`.**

---

## CO DZIAŁA — WIDOKI AKTYWNE

| Widok (menu) | Status | Źródła danych |
|---|---|---|
| **Panel główny** | ✅ OK | `/portfolio/wealth`, `/market/scanner`, `/positions/analysis`, `/signals/best-opportunity` |
| **Decyzje** (position-analysis) | ✅ OK | `/positions/analysis`, `/positions/goal/{sym}` |
| **Zlecenia** (trade-desk) | ✅ OK | `/orders`, `/orders/pending` |
| **Portfel** | ✅ OK | `/portfolio/wealth`, `/portfolio/forecast` |
| **Strategie** | ✅ OK | `/signals/top10` |
| **AI Sygnały** | ✅ OK | `/signals/latest` |
| **Ryzyko** | ✅ OK | `/account/risk`, `/positions/analysis` |
| **Historia** (backtest) | ✅ PARTIAL | `/orders/stats` — brak pełnej historii, tylko 30-dniowe statystyki |
| **Ekonomia / Alerty / Wiadomości** | 💤 STUB | Wyświetlają EmptyState — moduł w przygotowaniu |
| **Raporty / Statystyki** | 💤 STUB | Wyświetlają EmptyState — moduł w przygotowaniu |
| **Logi** | ✅ OK | `/account/system-logs` |
| **Ustawienia** | ✅ OK | `/portfolio/wealth` (konto), `/control/state` |
| **Panel symbolu** (kliknięcie) | ✅ OK | `/positions/analysis`, `/signals/latest`, `/market/forecast/{sym}`, `/market/forecast-accuracy/{sym}`, `/positions/decisions/{sym}` |

---

## TRYB LIVE vs DEMO

| Zachowanie | DEMO | LIVE |
|---|---|---|
| Dane konta | Wirtualne 10 000 EUR z DB | Binance API — wymaga kluczy w `.env` |
| Brak kluczy Binance | — | **Amber banner z info, nie crash** |
| Trading (zlecenia) | Pełny flow: PendingOrder → confirm | NIE DZIAŁA — brak live execution |
| Reset konta | TAK (przycisk w Ustawieniach) | — |

---

## CO SPRAWDZIĆ PO RESTARCIE

```bash
# 1. Backend odpowiada
curl -s http://localhost:8000/api/account/system-status | python3 -m json.tool | grep -E "collector_running|data_stale|last_tick_age"

# 2. Źródło KPI konta — DEMO
curl -s "http://localhost:8000/api/portfolio/wealth?mode=demo" | python3 -c "import sys,json; d=json.load(sys.stdin); print('equity:', d.get('total_equity'), '| free_cash:', d.get('free_cash'))"

# 3. Źródło KPI konta — LIVE (oczekiwany amber _info gdy brak kluczy)
curl -s "http://localhost:8000/api/portfolio/wealth?mode=live" | python3 -c "import sys,json; d=json.load(sys.stdin); print('equity:', d.get('total_equity'), '| _info:', d.get('_info','OK'))"

# 4. Testy (175/175 musi przejść)
DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py --tb=no -q

# 5. TypeScript (0 błędów)
cd web_portal && npx tsc --noEmit
```

---

## GDY COŚ PADNIE

| Objaw | Gdzie szukać | Co sprawdzić |
|---|---|---|
| Liczby konta = `--` lub `0` | `/api/portfolio/wealth?mode=demo` | Czy `total_equity` jest w odpowiedzi? Czy backend żyje? |
| Amber banner w UI | Normalny dla LIVE bez kluczy Binance | Ustaw `BINANCE_API_KEY` i `BINANCE_SECRET` w `.env` |
| Sygnały = `brak` | `/api/signals/latest` | Czy kolektor działa? `system-status.collector_running` |
| Zlecenia nie ExecuteError | Tryb LIVE — live execution niezaimplementowany | Użyj trybu DEMO |
| Frontend 404 | Sprawdź Next.js proxy w `next.config.js` | Rewrite `/api/*` → `http://localhost:8000/api/*` |
| TypeScript errors po edycji | `cd web_portal && npx tsc --noEmit` | Napraw przed commitem |

---

## CO JEST NIEGOTOWE (nie ukrywamy)

| Problem | Wpływ | Kiedy naprawić |
|---|---|---|
| **Live execution** | Brak realnych zleceń na Binance | Przed uruchomieniem real money |
| **Economics / Alerty / Wiadomości** | Wyświetlają EmptyState | Nie krytyczne |
| **Raporty / Statystyki** | Wyświetlają EmptyState | Nie krytyczne |
| **Blog** | Pusty bez klucza OpenAI | Nie krytyczne |
| **datetime.utcnow()** | 975 deprecation warnings w testach | Przy następnym sprzątaniu |
| **Drawdown LIVE** | Zawsze 0.0 bez kluczy Binance | Przy integracji live |

---

*Wersja: v0.7-beta | Testy: 175/175 ✅ | TypeScript: 0 ✅ | Endpointy: 30/30 ✅*
