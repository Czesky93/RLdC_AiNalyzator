# RLdC AiNalyzator — Trading Bot

Bot do handlu kryptowalutami na Binance (spot) z panelem WWW, botem Telegram oraz AI-wspomaganą analizą sygnałów.

> **OSTRZEŻENIE:** Ten system może realizować zlecenia na giełdzie Binance za prawdziwe środki. Używaj trybu `demo` do testowania. Przed włączeniem trybu `live` rozumiej ryzyka i odpowiadasz za własne finanse.

---

## Główne funkcje

- **Sygnały tradingowe** — analiza techniczna (RSI, EMA, Bollinger Bands, MACD, ATR, OBV), scoring wielowskaźnikowy, cost-aware (sygnał musi pokryć koszty wejścia/wyjścia)
- **Wykonanie zleceń** — tryb live (Binance spot) i demo (symulacja); trailing stop, TP/SL, partial TP, break-even
- **Portfolio engine** — śledzenie equity, pozycji, unrealized/realized PnL, synchronizacja z Binance
- **Risk gates** — 10 bram ryzyka: max drawdown, max dzienny loss, kill switch, crash protection, cooldown, max pozycji, min edge po kosztach
- **AI orchestrator** — multi-provider: Ollama (local) → Groq → Gemini → OpenAI → heuristic (free-first fallback chain)
- **Panel WWW** — Next.js dashboard: portfolio, sygnały, pozycje, ordery, logi, terminal online
- **Telegram bot** — `/ip`, `/ai`, `/status`, `/portfolio`, `/env`, `/config`, naturalny język (command brain)
- **Control center** — zarządzanie konfiguracją `.env` przez WWW/Telegram, bezpieczny terminal online, diagnostyka IP/AI

---

## Architektura (skrót)

```
backend/          FastAPI — logika tradingowa, API, kolektor danych
  routers/        Thin routery: account, control, debug, market, orders, portfolio, positions, signals
  collector.py    Pętla kolekcji danych i sygnałów (co N sekund)
  analysis.py     Wskaźniki techniczne, scoring, edge calculation
  risk.py         Risk gates i position sizing
  portfolio_engine.py  Equity, PnL, snapshot history
  binance_client.py    Binance REST API wrapper
  ai_orchestrator.py   Multi-provider AI (free-first)
  telegram_formatter.py Formatowanie wiadomości Telegram

telegram_bot/     aiogram bot
web_portal/       Next.js frontend (src/app, components, lib)
tests/            pytest smoke + testy jednostkowe
```

---

## Wymagania

- Python 3.11+
- Node.js 18+
- Konto Binance (do trybu live — klucze API z prawami spot)
- Telegram bot token (opcjonalnie)
- AI API key (opcjonalnie — Groq/Gemini darmowe, Ollama lokalnie)

---

## Uruchomienie lokalne

### 1. Klonowanie i środowisko Python

```bash
git clone https://github.com/Czesky93/RLdC_AiNalyzator.git
cd RLdC_AiNalyzator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Konfiguracja `.env`

```bash
cp .env.example .env
# Edytuj .env — uzupełnij klucze Binance, Telegram i AI
```

Minimum do uruchomienia w trybie demo:
- `TRADING_MODE=demo`
- `ALLOW_LIVE_TRADING=false`

Do trybu live: `BINANCE_API_KEY`, `BINANCE_API_SECRET`.

### 3. Backend (FastAPI)

```bash
source .venv/bin/activate
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

API dostępne na `http://localhost:8000`. Swagger: `http://localhost:8000/docs`.

### 4. Frontend (Next.js)

```bash
cd web_portal
npm install
npm run dev
```

Panel WWW dostępny na `http://localhost:3000`.

Build produkcyjny:
```bash
npm run build && npm start
```

### 5. Bot Telegram

```bash
source .venv/bin/activate
python3 -m telegram_bot.bot
```

Wymaga `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID` w `.env`.

### 6. Skrypty dev (wszystko naraz)

```bash
./scripts/start_dev.sh   # uruchamia backend + frontend + bot
./scripts/status_dev.sh  # status procesów
./scripts/stop_dev.sh    # zatrzymuje wszystko
```

---

## Testy

```bash
source .venv/bin/activate
pytest tests/ -q
```

Główne zestawy testów:
- `tests/test_smoke.py` — ~220 smoke testów (endpointy, sygnały, portfolio, risk)
- `tests/test_control_center.py` — 6 testów (IP diagnostics, AI orchestrator, command brain, env, terminal)
- `tests/test_portfolio_engine.py` — portfolio engine
- `tests/test_sync_consistency.py` — spójność DB↔Binance
- `tests/test_telegram_formatter.py` — formatowanie Telegram

---

## Endpointy API (kluczowe)

| Endpoint | Opis |
|---|---|
| `GET /api/account/ip-diagnostics` | IP, Cloudflare, DNS diagnostics |
| `GET /api/account/ai-orchestrator-status` | Status AI providers |
| `GET /api/signals/summary` | Sygnały BUY/SELL/HOLD z scoring |
| `GET /api/portfolio/summary` | Equity, PnL, pozycje |
| `GET /api/positions/` | Aktywne pozycje |
| `GET /api/orders/` | Historia orderów |
| `GET /api/control/env` | Lista konfiguracji (wymaga `X-Admin-Token`) |
| `POST /api/control/command/execute` | Command brain (wymaga `X-Admin-Token`) |
| `POST /api/control/terminal/exec` | Online terminal (wymaga `X-Admin-Token`) |

Pełna dokumentacja: `http://localhost:8000/docs`

---

## Autoryzacja wrażliwych endpointów

Endpointy `/api/control/*` wymagają nagłówka:

```
X-Admin-Token: <ADMIN_TOKEN z .env>
```

Jeśli `ADMIN_TOKEN` jest pusty — autoryzacja wyłączona (tylko środowisko lokalne/dev).

---

## Tryb Live — ważne ograniczenia i znane problemy

**Znane ograniczenia:**
- Tryb WebSocket (`WS_ENABLED`) jest zaimplementowany częściowo — zalecany polling
- Ollama (lokalny LLM) działa tylko jeśli jest uruchomiony serwis `ollama serve`
- Synchronizacja z Binance wymaga stabilnego połączenia — przy zaniku sieci bot wchodzi w tryb bezpieczny
- `*.db` (SQLite) nie powinno być trzymane na produkcji — zaleca się PostgreSQL dla stabilności

**Znane ograniczenia handlowe:**
- System handluje tylko spot Binance (brak futures, margin)
- Min. notional Binance musi być spełnione (ok. 5 EUR/USDC per trade)
- Sygnały mogą być blokowane przez risk gates nawet przy pozornie dobrej okazji — to jest zamierzone zachowanie

---

## Bezpieczeństwo

- **Nigdy nie commituj `.env`** — zawiera klucze API
- Klucze Binance powinny mieć tylko prawa **spot trading** (bez withdraw)
- `ADMIN_TOKEN` powinien być losowym, silnym kluczem na produkcji
- System loguje wszystkie decyzje z `reason_code` — sprawdzaj logi przed live trading

---

## Licencja

Projekt prywatny. Brak licencji open-source.
