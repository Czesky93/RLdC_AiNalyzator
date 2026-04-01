# RLdC AiNalyzator – Trading Bot v0.7 beta

Autonomiczny bot tradingowy na kryptowaluty z FastAPI backendem, Next.js portalem webowym i integracją z Binance + Telegram.

## Przegląd systemu

- 📈 **Silnik decyzyjny** – heurystyczny sygnalizator (RSI, EMA, trend, wolumen) bez zależności od OpenAI
- 🔒 **10-warstwowy system ryzyka** – kill switch, daily drawdown, loss streak, limity ekspozycji
- 🗄️ **SQLite z pełnym audytem** – każda decyzja logowana w `DecisionTrace` z `reason_code` i filtry diagnostyczne
- 📊 **Portal webowy** – dark-theme dashboard z trybem DEMO/LIVE, wykresy TradingView, widoki pozycji i sygnałów
- 🤖 **Telegram bot** – powiadomienia, potwierdzenia transakcji, podgląd statusu systemu
- 🗂️ **Config Snapshot** – wersjonowanie konfiguracji, porównywanie wydajności między konfiguracjami

## Struktura projektu

```
backend/          # Serwer FastAPI + silnik tradingowy
  app.py          # Punkt startowy (API + kolektor)
  collector.py    # Główna pętla decyzji — REST + WebSocket
  risk.py         # 10 bram ryzyka w evaluate_risk()
  database.py     # Modele SQLAlchemy + helpery DB
  accounting.py   # PnL, koszty, snapshoty ryzyka
  reporting.py    # Raporty analityczne
  runtime_settings.py  # Konfiguracja z ENV + RuntimeSetting (hot-reload)
  routers/        # Endpointy FastAPI
    account.py    # Portfel, KPI, Stan systemu
    market.py     # Klines, ticker, scanner, prognoza
    orders.py     # Historia zleceń, statystyki
    positions.py  # Otwarte pozycje, analiza
    signals.py    # Sygnały, execution-trace, szansa rynkowa
    control.py    # Sterowanie (start/stop kolektora, parametry)
    portfolio.py  # Wealth, equity, prognozy portfela
    blog.py       # Blog AI (posty generowane automatycznie)
    debug.py      # /state-consistency — diagnostyka stanu
    telegram_intel.py  # Telegram Intelligence — AI analiza wiadomości
telegram_bot/     # Bot Telegram (powiadomienia + potwierdzenia)
web_portal/       # Frontend Next.js 16 + Tailwind CSS v4
tests/            # Testy smoke (181 testów)
docs/             # Dokumentacja wewnętrzna
```

## Wymagania

- Python 3.11+
- Node.js 20.9+
- Konto Binance z kluczami API (read + spot trading)
- Bot Telegram (opcjonalnie — dla powiadomień)

## Uruchomienie od zera (Ubuntu)

### 1. Klonowanie i środowisko

```bash
git clone <repo-url>
cd RLdC_AiNalyzator

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Konfiguracja `.env`

```bash
cp .env.example .env   # jeśli brak, utwórz ręcznie
```

Minimalne zmienne środowiskowe:

```env
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
TRADING_MODE=demo            # demo lub live
PORTFOLIO_QUOTES=EUR,USDC    # quote currencies z portfela Binance
DEMO_INITIAL_BALANCE=10000   # startowy balans DEMO w EUR

# Opcjonalnie — Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Opcjonalnie — OpenAI (blog AI, analizy GPT)
OPENAI_API_KEY=...
```

> **Ważne**: Bot działa bez `OPENAI_API_KEY` — sygnały generowane są heurystycznie.

### 3. Start backendu

```bash
source .venv/bin/activate
python -m backend.app
```

API dostępne pod `http://localhost:8000`  
Dokumentacja Swagger: `http://localhost:8000/docs`

**Tryb dev z hot-reload:**
```bash
python -m backend.app --reload
```

**Start wszystkiego naraz (backend + portal):**
```bash
python -m backend.app --all
```

### 4. Portal webowy (oddzielnie)

```bash
cd web_portal
npm install
npm run dev
```

Web UI: `http://localhost:3000`

### 5. Bot Telegram (opcjonalnie)

```bash
source .venv/bin/activate
python -m telegram_bot.bot
```

## Testy

```bash
source .venv/bin/activate
DISABLE_COLLECTOR=true python -m pytest tests/test_smoke.py --tb=short -q
```

## Potwierdzanie transakcji przez Telegram

Komendy bota:
- `/confirm <ID>` – potwierdza transakcję
- `/reject <ID>` – odrzuca transakcję
- `/status` – bieżący stan systemu

## Kluczowe endpointy API

| Endpoint | Opis |
|----------|------|
| `GET /api/account/system-status` | Stan kolektora, WS, tryb |
| `GET /api/portfolio/wealth?mode=demo` | Equity, balans, PnL |
| `GET /api/signals/latest?limit=50` | Ostatnie sygnały |
| `GET /api/signals/execution-trace` | Historia decyzji z powodami |
| `GET /api/market/scanner` | Top 5 par do handlu |
| `POST /api/control/state` | Zmiana parametrów, start/stop |
| `GET /api/reporting/analytics` | Pełny raport analityczny |

## Design System

Dark-theme oparty na kolorach terminala tradingowego:
- Tło: `#0a1219`, karty: `#111c26`
- Akcent teal: `#14b8a6`
- Cały UI w języku polskim

## Reset bazy danych

```bash
curl -X POST "http://localhost:8000/api/account/reset?scope=full"
```

Jeśli ustawisz `ADMIN_TOKEN` w `.env`, dodaj nagłówek:

```bash
curl -X POST "http://localhost:8000/api/account/reset?scope=full" -H "X-Admin-Token: $ADMIN_TOKEN"
```

## Web confirm/reject pending orders (DEMO)

Poza Telegramem, pending orders da sie obsluzyc z web UI (przyciski Potwierdz/Odrzuc).

API (na start: tylko `mode=demo`, status musi byc `PENDING`, inaczej 409):

```bash
curl -X POST "http://localhost:8000/api/orders/pending/123/confirm"
curl -X POST "http://localhost:8000/api/orders/pending/123/reject"
curl -X POST "http://localhost:8000/api/orders/pending/123/cancel"
```

Jesli ustawisz `ADMIN_TOKEN`, dodaj naglowek:

```bash
curl -X POST "http://localhost:8000/api/orders/pending/123/confirm" -H "X-Admin-Token: $ADMIN_TOKEN"
```

## Web create pending order (DEMO)

Mozesz tez tworzyc pending ordery z web UI (Trade ticket) lub przez API:

```bash
curl -X POST "http://localhost:8000/api/orders/pending?mode=demo" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC/EUR","side":"BUY","quantity":0.01,"price":100.0,"reason":"manual"}'
```

Jesli ustawisz `ADMIN_TOKEN`, dodaj naglowek `X-Admin-Token`.

## Zamkniecie pozycji (DEMO -> pending SELL)

Zamykanie pozycji robi pending SELL (trzeba potwierdzic).

```bash
# 100%
curl -X POST "http://localhost:8000/api/positions/1/close?mode=demo"

# czesciowe (np. 25%)
curl -X POST "http://localhost:8000/api/positions/1/close?mode=demo&quantity=0.25"

# wszystkie pozycje
curl -X POST "http://localhost:8000/api/positions/close-all?mode=demo"
```

Jesli ustawisz `ADMIN_TOKEN`, dodaj naglowek `X-Admin-Token`.

## Control Plane (STOP TRADING)

Stan runtime (z ENV + override z DB):

```bash
curl "http://localhost:8000/api/control/state"
```

Wylaczenie DEMO trading (persist do DB):

```bash
curl -X POST "http://localhost:8000/api/control/state" \
  -H "Content-Type: application/json" \
  -d '{"demo_trading_enabled": false}'
```

Jesli ustawisz `ADMIN_TOKEN`, dodaj naglowek `X-Admin-Token`.

## ENV vs .env

Backend laduje `.env` z `override=false`, wiec zmienne srodowiskowe procesu maja pierwszenstwo przed wartosciami z `.env`.

## Diagnostyka (ważne)

### Szybki test OpenAI (czy klucz jest poprawny)

```bash
curl "http://localhost:8000/api/account/openai-status"
```

Jeśli dostaniesz `status=error` i `code=invalid_api_key`, to **OpenAI odrzuca klucz z `.env`** (to nie jest błąd aplikacji).

### Brak kasy / chcesz za free? (AI bez OpenAI)

Możesz uruchomić darmowy „mózg” bez LLM: zakresy i decyzje liczone heurystycznie (ATR/Bollinger).

W `.env` ustaw:

```bash
AI_PROVIDER=heuristic
```

Rekomendowane (auto): jeśli masz czasem działające OpenAI, a czasem nie — ustaw:

```bash
AI_PROVIDER=auto
```

Potem zrestartuj backend i wymuś analizę:

```bash
curl -X POST "http://localhost:8000/api/market/analyze-now?force=true"
```

### Wymuszenie analizy teraz (bez czekania 1h)

```bash
curl -X POST "http://localhost:8000/api/market/analyze-now?force=true"
```

### OpenAI nie działa (401 / invalid_api_key)

Jeśli w **Logi** (WWW) lub w `system_logs` widzisz wpisy typu:

- `OpenAI HTTP 401 (invalid_api_key) ...`

to znaczy, że `OPENAI_API_KEY` w `.env` jest niepoprawny lub wygasł. Bot nie wygeneruje zakresów i decyzji dopóki nie podmienisz klucza na poprawny.

### Watchlista pusta mimo sald na Binance

Binance czasem zwraca aktywa z prefiksem `LD*` (Simple Earn/Savings). Program mapuje je na aktywa bazowe (np. `LDBTC` → `BTC`) aby zbudować pary typu `BTCEUR`, `BTCUSDC`.

## Zasady działania bota

- Jeśli `AI_PROVIDER=openai`: OpenAI jest wymagany (brak klucza = bot nie generuje nowych zakresów i wstrzymuje decyzje).
- Jeśli `AI_PROVIDER=auto`: używa OpenAI jeśli działa, a jeśli nie — przełącza na heurystykę (ATR/Bollinger).
- Jeśli `AI_PROVIDER=heuristic`: działa darmowy fallback bez OpenAI (ATR/Bollinger).
- Symbole są pobierane wyłącznie z portfela Binance.
- Handel działa wyłącznie w trybie DEMO (LIVE wyłączony).
- Uczenie hybrydowe: krótkie backtesty + bieżące dostrajanie (parametr `LEARNING_DAYS`, domyślnie 180).
- Uczenie wykonywane co 1h.
- Telegram: raporty tylko na żądanie (`/report`), alerty tylko przy skrajnych momentach (konfigurowalne progi).
- Telegram: tryby treści `TELEGRAM_STYLE=brief|layman|tech|both` oraz opcja `TELEGRAM_ERROR_ONLY=true` (wysyła tylko krytyczne alerty).
- Telegram: raporty uczenia nie są wysyłane automatycznie.

### Maksimum pewności (bardzo konserwatywnie)

Jeśli chcesz **maksimum pewności kosztem liczby transakcji** (bot głównie będzie pisał `CZEKAJ`), w `.env` ustaw:

```bash
MAX_CERTAINTY_MODE=true
```

To automatycznie:
- podnosi progi confidence,
- wymaga rating `5/5`,
- ogranicza liczbę transakcji,
- zwiększa cooldown,
- zmniejsza ryzyko per trade w DEMO.

## License

*(License information to be added)*
