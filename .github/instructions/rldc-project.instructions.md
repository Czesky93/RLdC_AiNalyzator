---
description: "Use when working on RLdC AiNalyzator / RLdC Trading Bot — coding conventions, architecture rules, Polish UI, testing commands, feature freeze policy, DB migrations, and module boundaries."
applyTo: "**/*.py, **/*.ts, **/*.tsx"
---

# RLdC AiNalyzator — Wytyczne projektowe v0.7 beta

## Rola
Główny architekt i code-reviewer projektu RLdC AiNalyzer / RLdC Trading Bot.
Cel: utrzymywać i rozwijać repozytorium do stanu spójnej wersji v0.7 beta.

---

## Zasady ogólne

### Język
- Wszystkie elementy UI (etykiety, komunikaty, tooltips, widoki) — **po polsku**
- Komentarze w kodzie — preferuj polski; angielski akceptowalny jeśli konsystentny w pliku
- Odpowiedzi w rozmowie — **po polsku**

### Minimalna liczba plików
- Nie twórz nowych plików bez wyraźnej potrzeby
- Edytuj istniejące zamiast tworzyć nowe — dotyczy `.py`, `.ts`, `.tsx`
- Jeśli dzielisz plik — tylko dla czytelności, nie na "przyszłość"
- Nie twórz plików Markdown podsumowujących wprowadzone zmiany (chyba że użytkownik wprost o to prosi)

### Usuwanie funkcji
- **Nie usuwaj** funkcji/modułów "na oko" — najpierw `grep` użyć, zidentyfikować zależności
- Decyzja: usuń / napraw / przenieś — po identyfikacji, nie przed
- Jeśli funkcja jest nieużywana i niepotrzebna — usuń; jeśli wątpliwość — zapytaj

### Logowanie i obsługa błędów
- `logger = logging.getLogger(__name__)` — w każdym module backendowym
- Obsługuj wyjątki na granicach zewnętrznych: Binance API, Telegram, FastAPI endpoints, I/O
- Loguj błędy z kontekstem (`logger.error("...", exc, exc_info=True)` lub podobnie)
- Nie loguj sekretów (klucze API, tokeny, hasła)

---

## Architektura

### Stack
- **Backend:** Python 3.11+, FastAPI, SQLite, SQLAlchemy (ORM)
- **Frontend:** Next.js 16.1.6, React 19.2.4, Tailwind v4, Recharts, Lucide icons
- **Porty:** backend `localhost:8000`, frontend `localhost:3000`
- **Zmienne środowiskowe:** `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENAI_API_KEY`

### Warstwy pipeline
```
config → experiment → recommendation → review
  → promotion → post-promotion monitoring
  → rollback decision → rollback execution
  → post-rollback monitoring → policy layer
```
- Każda warstwa konsumuje output poprzedniej; **nie recalkuluje ekonomii**
- Thin routers (`backend/routers/`) — tylko walidacja wejścia i delegacja do modułu logiki; zero logiki biznesowej w routerach

### Single source of truth
| Domena | Moduł |
|--------|-------|
| Konfiguracja runtime | `runtime_settings.py` |
| Ekonomia (P&L, equity) | `accounting.py` |
| Ochrona kapitału | `risk.py` |
| Analityka / raporty | `reporting.py` |
| Dane rynkowe | `database.py` (modele ORM) |

### Moduły read-only / prezentacyjne
- `operator_console.py` — tylko odczyt, brak efektów ubocznych
- `system_logger.py` — centralny logging; inne moduły NIE piszą bezpośrednio do `SystemLog`

---

## Baza danych (SQLite / SQLAlchemy)

- Wszystkie modele ORM w `backend/database.py`
- Nowe modele → dodaj tabele przez `Base.metadata.create_all()` + wpis do `_ensure_schema()`
- Nowe kolumny → `ALTER TABLE ... ADD COLUMN` w `_ensure_schema()` (nigdy drop/recreate)
- Po dodaniu modelu: wywołaj `init_db()` raz ręcznie lub przy starcie
- `utc_now_naive()` — używaj zamiast `datetime.utcnow()` (deprecated)

---

## Testy

```bash
# Uruchomienie testów
DISABLE_COLLECTOR=true .venv/bin/pytest tests/test_smoke.py

# Z trybem demo (bezpieczne)
DISABLE_COLLECTOR=true TRADING_MODE=demo ALLOW_LIVE_TRADING=false .venv/bin/pytest tests/test_smoke.py --tb=short -q
```

- **Baseline: 181 testów** (175 smoke + 6 akceptacyjnych v0.7) — wszystkie muszą przechodzić
- Testy używają izolowanej bazy SQLite (tempfile) — nie dotykają produkcyjnego `trading_bot.db`
- Po każdej zmianie: uruchom testy i potwierdź 181/181

---

## Feature freeze

**Nie dodawaj nowych funkcji dopóki 4 piony nie zamknięte:**

| Pion | Cel |
|------|-----|
| A — Live Data | `_build_live_signals` → zapis do DB; heuristic fallback w Collectorze |
| B — Portfel | Realne saldo Binance w UI, equity curve, live price update pozycji |
| C — Symbol Detail | Panel kliknięcia na symbol (wykres + forecast + buy/sell), forecast accuracy |
| D — Decision Engine | `_learn_from_history` z persistencją, `create_order` live → Binance API, daily_drawdown live |

---

## Uruchamianie (Ubuntu)

```bash
# Backend (z katalogu projektu)
source .venv/bin/activate
python -m backend.app

# Frontend
cd web_portal && npm run dev

# Skrypty devowe
./scripts/start_dev.sh
./scripts/stop_dev.sh
./scripts/status_dev.sh
```

---

## Bezpieczeństwo (OWASP)

- Waliduj input użytkownika na granicach API (FastAPI Pydantic schemas)
- Używaj zmiennych środowiskowych dla wszystkich sekretów — nie hardkoduj w kodzie
- Sanitizuj wszelkie dane wejściowe przed użyciem w zapytaniach DB (używaj tylko ORM, nie raw SQL)
- Nie ujawniaj stack trace w odpowiedziach HTTP 500 — loguj server-side, zwracaj ogólny komunikat
