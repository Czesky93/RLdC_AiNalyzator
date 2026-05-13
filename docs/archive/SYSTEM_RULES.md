# SYSTEM_RULES — RLdC AiNalyzator
*Zasady działania systemu, granice odpowiedzialności i reguły decyzyjne.*
*Dokument dla architekta i code-reviewera — "jak system ma działać" vs "jak działa teraz".*

---

## 1. ZASADY OGÓLNE

### 1.1 Tryb pracy
- System domyślnie pracuje w trybie **DEMO** (wirtualne konto testowe)
- Tryb **REAL** (Binance live) jest celowo zablokowany — bot nie składa zleceń na giełdzie
- Przełączenie trybu nie zmienia algorytmów — tylko źródło danych i cel transakcji
- Dane rynkowe (ceny, OHLCV, sygnały) są zawsze dane REAL — demo to tylko wirtualny portfel

### 1.2 Źródła danych
- Dane cenowe: Binance WebSocket (live) + REST API (fallback/uzupełnienie)
- Dane portfela demo: lokalna baza SQLite (`trading_bot.db`)
- Dane portfela real: Binance API (kluczem w `.env`)
- Sygnały: generowane przez kolektor co 60s — najpierw AI (jeśli klucz OpenAI), potem heurystyka (zawsze)

### 1.3 Odświeżanie
- Kolektor cykl: 60 sekund
- WebSocket: ciągły strumień cen (Binance stream)
- Frontend polling: 15–30s zależnie od widoku (patrz FUNCTIONS_MATRIX.md sekcja L)
- Dane „stale" = starsze niż 120 sekund (SystemStatusBar pokazuje ostrzeżenie)

---

## 2. REGUŁY DECYZYJNE BOTA

### 2.1 Kiedy bot podejmuje akcję
Warunki wejścia (wszystkie MUSZĄ być spełnione):
1. Sygnał `signal = BUY` z confidence ≥ progu (`MIN_CONFIDENCE`, domyślnie 0.60)
2. Wolne środki > próg minimalny (`MIN_TRADE_USD`, domyślnie 20 USD)
3. Liczba otwartych pozycji < `MAX_POSITIONS` (domyślnie 10)
4. Symbol nie jest w `blocked_symbols` listy
5. Drawdown demo < `MAX_DRAWDOWN` (domyślnie 20%)

Warunki wyjścia (jeden wystarczy):
- Sygnał `SELL` z confidence ≥ progu — natychmiastowe zamknięcie
- Cena osiągnęła `take_profit` poziom (TP)
- Cena spadła do `stop_loss` poziomu (SL)
- Drawdown pozycji > `MAX_POSITION_DRAWDOWN` (domyślnie 8%)

### 2.2 Tryby decyzji bota

| Tryb | Opis | Stan w systemie |
|------|------|----------------|
| `HOLD` | Bot trzyma pozycję, nie sprzedaje | Aktywny — bot widzi sygnał SELL ale ignoruje |
| `MANAGED` | Bot handluje normalnie | Domyślny |
| `MANUAL` | Bot nie handluje, czeka na decyzję użytkownika | Opcjonalny |
| `PAUSED` | Kolektor jest zatrzymany | Przez `DISABLE_COLLECTOR=true` lub API |

### 2.3 Governance / Zatwierdzanie
- Jeśli `REQUIRE_APPROVAL=true` — bot tworzy zlecenie ze statusem `PENDING`
- Zlecenie musi być zatwierdzone (przez Telegram lub API `/api/orders/{id}/confirm`) w ciągu `APPROVAL_TIMEOUT_SECONDS`
- Po upływie czasu niezatwierdzone zlecenia są odrzucane
- Bot działający bez zatwierdzenia: `REQUIRE_APPROVAL=false` (domyślnie w demo)

---

## 3. ZASADY BEZPIECZEŃSTWA

### 3.1 Ochrona środków
- W trybie REAL: **NIGDY nie jest wysyłane zlecenie** bez wyraźnego `LIVE_TRADING=true` w `.env`
- Klucze Binance powinny być **READ-ONLY** gdy `LIVE_TRADING=false`
- Reset demo konta: kasuje pozycje i historię, NIE dotyka Binance
- Zlecenia `MARKET` vs `LIMIT`: system preferuje LIMIT aby kontrolować cenę wejścia

### 3.2 Limity ryzyka (zablokowanie handlu)
- `MAX_DRAWDOWN` (default 20%) — przekroczenie = bot zatrzymuje wszystkie BUY
- `MAX_POSITIONS` (default 10) — przekroczenie = bot nie otwiera nowych
- `DAILY_LOSS_LIMIT_EUR` (default 50) — przekroczenie = blokada 24h

### 3.3 Logowanie
- Każde zlecenie: logowane do DB (`Order` tabela) ze statusem, ceną, timestampem, źródłem
- Każdy błąd Binance: logowany do `system_logger.py` z kodem HTTP
- Każde wywołanie Telegram: logowane z poziomem sukces/błąd
- `trading_bot.db`: NIGDY nie usuwać ręcznie bez backup

---

## 4. ZASADY UI / UX

### 4.1 Język
- WSZYSTKIE etykiety, komunikaty i opisy w języku **POLSKIM**
- Nazwy symboli (BTCUSDT) — bez tłumaczenia
- Liczby: format polski (`1 234,56 EUR`)
- Daty: format `DD.MM.YYYY HH:MM:SS`

### 4.2 Hierarchia widoków
- Panel główny (`dashboard`) = CommandCenterView — ZAWSZE ma mieć dane
- Kliknięcie symbolu = otwiera Symbol Detail Panel (modal) zamiast zmieniać widok
- Zmiana widoku w Sidebar = zmiana głównej zawartości, Panel symbolu zostaje jeśli otwarty
- Dane "stale" (>120s) = żółty badge "NIEAKTUALNE" obok wartości

### 4.3 Sygnalizacja stanu systemu
- Zielony: kolektor działa, WebSocket podłączony, dane świeże
- Żółty: kolektor działa, WebSocket odłączony LUB dane starsze niż 60s
- Czerwony: kolektor zatrzymany LUB błąd API LUB dane >120s

### 4.4 Demo vs Real
- Zawsze widoczny badge aktualnego trybu (DEMO / REAL) w górnym pasku
- Zmiana trybu: od razu odświeża wszystkie widoki
- Tryb REAL wymaga potwierdzenia użytkownika przy akcjach handlowych

---

## 5. ZASADY KONFIGURACJI

### 5.1 Zmienne środowiskowe (`.env`)
```env
# Wymagane
SECRET_KEY=...              # JWT secret (min 32 znaków)

# Opcjonalne — Binance
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
LIVE_TRADING=false          # true = bot składa zlecenia na Binance

# Opcjonalne — AI
OPENAI_API_KEY=...          # brak = tryb heurystyczny (AI_PROVIDER=auto)
AI_PROVIDER=auto            # auto | openai | heuristic

# Opcjonalne — Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Opcjonalne — Tryb bota
DISABLE_COLLECTOR=false     # true = używane w testach
REQUIRE_APPROVAL=false      # true = każde zlecenie czeka na zatwierdzenie
MAX_POSITIONS=10
MAX_DRAWDOWN=0.20
MIN_CONFIDENCE=0.60
```

### 5.2 Runtime Settings (zmieniane przez UI/API)
Przechowywane w DB (`RuntimeSetting` tabela), nadpisują `.env`:
- `blocked_symbols` — lista JSON symboli zablokowanych
- `hold_mode` — czy bot jest w trybie trzymania
- `learning_symbol_params` — nauczone parametry per-symbol (persystowane)
- `min_confidence` — dynamiczny próg ufności
- `max_positions` — dynamiczny limit

---

## 6. ZASADY KODU I ARCHITEKTURY

### 6.1 Minimalna liczba plików
- Nie tworzyć nowych plików jeśli funkcja może być dodana do istniejącego
- Wyjątek: nowy widget/komponent frontend na osobny plik jeśli >200 linii
- `MainContent.tsx` — dozwolone do ~3000 linii ze względu na centralizację; powyżej — podziel na osobne pliki widoków

### 6.2 Obsługa błędów
- Każde wywołanie zewnętrznego API (Binance, OpenAI): `try/except` z logowaniem i fallbackiem
- Każdy endpoint FastAPI: `try/except` — nigdy nie zwracać stack trace do klienta
- Frontend: `useFetch` hook zawiera error state — zawsze obsłuż `error !== null`

### 6.3 Baza danych
- SQLite w pliku `trading_bot.db` — wszystkie migracje przez `database.py`
- Backup przed migracją: `cp trading_bot.db trading_bot.db.bak.$(date +%Y%m%d)`
- Bezpośrednie `DELETE` lub `DROP TABLE` — NIGDY bez potwierdzenia

### 6.4 Testy
- Każda nowa funkcja backendowa = minimalny test smoke w `tests/test_smoke.py`
- Uruchomienie: `DISABLE_COLLECTOR=true pytest tests/ -v`
- Stan docelowy: 100% testów OK przed każdym commitem

### 6.5 Standard czasu UTC — `utc_now_naive()`
- **Projekt operuje wyłącznie na czasie UTC** — nigdy na czasie lokalnym
- **SQLite przechowuje daty jako naive datetime strings** (bez timezone info)
- **JEDYNA dopuszczalna funkcja**: `utc_now_naive()` z `backend.database`
  ```python
  from backend.database import utc_now_naive
  now = utc_now_naive()   # datetime bez tzinfo, UTC
  ```
- **ZAKAZ używania**:
  - `datetime.utcnow()` — deprecated w Python 3.12+
  - `datetime.now()` — czas lokalny, nie UTC
  - `datetime.now(timezone.utc)` bez `.replace(tzinfo=None)` — aware datetime łamie filtry SQLAlchemy
- **Dlaczego naive?** SQLAlchemy + SQLite porównuje stringi; aware datetime powoduje ciche błędy (puste wyniki zapytań)
- **Definicja** (nie modyfikować):
  ```python
  # backend/database.py
  def utc_now_naive() -> datetime:
      return datetime.now(timezone.utc).replace(tzinfo=None)
  ```
