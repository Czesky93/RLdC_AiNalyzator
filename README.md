# RLdC Trading Bot – Ultimate AI

A comprehensive project for an advanced autonomous trading system integrating Quantum AI, Deep Reinforcement Learning, Blockchain Analysis, and HFT.

## Overview

RLdC Trading Bot combines cutting-edge technologies to create a powerful autonomous trading platform:

- 🤖 **Quantum AI** - Portfolio optimization using quantum algorithms
- 🧠 **Deep Reinforcement Learning** - Autonomous learning and market adaptation
- ⛓️ **Blockchain Analysis** - Real-time on-chain analysis for cryptocurrencies
- ⚡ **High-Frequency Trading** - Microsecond-level transaction execution
- 📊 **Multi-Asset Support** - Stocks, forex, crypto, commodities, and futures
- 🛡️ **AI-Powered Risk Management** - Advanced risk management and alerting

## Project Structure

- `ai_trading/` - AI Trading Engine with ML/DRL models
- `quantum_optimization/` - Quantum computing for portfolio optimization
- `hft_engine/` - High-Frequency Trading engine
- `blockchain_analysis/` - On-chain analysis for cryptocurrencies
- `portfolio_management/` - Portfolio management and rebalancing
- `recommendation_engine/` - AI recommendations and risk alerts
- `web_portal/` - Web-based user interface
- `telegram_bot/` - Telegram AI bot for conversational interaction
- `infrastructure/` - Docker, Kubernetes, CI/CD configuration
- `tests/` - Global test suite

## Documentation

- [Project Plan](docs/PROJECT_PLAN.md) - Full project architecture and implementation plan
- [Design System](docs/DESIGN_SYSTEM.md) - Complete design system and UI guidelines

## Design System

The project uses a professional dark-themed design inspired by modern trading terminals:

- **Dark Background**: `#0a1219` with card backgrounds `#111c26`
- **Teal/Green Accents**: Primary color `#14b8a6` for actions and highlights
- **Polish Interface**: All UI elements in Polish language
- **Responsive Layout**: Mobile-first approach with breakpoints

See [Design System Documentation](docs/DESIGN_SYSTEM.md) for complete guidelines.

## Getting Started

### Wymagania

- Python 3.11+
- Node.js 20.9+

### Konfiguracja

1. Skopiuj `.env.example` do `.env` i uzupełnij wartości:
   - `OPENAI_API_KEY` (wymagany - bez OpenAI bot nie startuje)
   - `BINANCE_API_KEY`, `BINANCE_API_SECRET` (wymagane do portfela i listy symboli)
   - `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID` (dla bota)
   - `PORTFOLIO_QUOTES=EUR,USDC` (quote do budowy symboli z portfela)
   - `TRADING_MODE=demo` (demo lub live)

### Uruchomienie backendu (API + kolektor)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start API (uruchamia kolektor REST + WS w tle)
python -m backend.app
```

API będzie dostępne pod `http://localhost:8000`

### Tryb developerski (hot-reload)

Domyślnie hot-reload jest wyłączony (żeby nie spamować logów `watchfiles` i nie restartować backendu od zmian w DB/logach).

```bash
python -m backend.app --reload
```

### Uruchomienie wszystkiego naraz

```bash
python -m backend.app --all
```

Dev (hot-reload backendu):

```bash
python -m backend.app --all --reload
```

### Uruchomienie bota Telegram

```bash
source .venv/bin/activate
python -m telegram_bot.bot
```

### Uruchomienie web portalu

```bash
cd web_portal
npm install
npm run dev
```

Web UI: `http://localhost:3000`

## Potwierdzanie transakcji (Telegram)

Każda transakcja wymaga potwierdzenia przez Telegram.

Komendy:
- `/confirm <ID>` – potwierdza transakcję
- `/reject <ID>` – odrzuca transakcję

Transakcje DEMO są wykonywane, ale muszą być potwierdzone do walidacji działania.

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
