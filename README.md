# RLdC AiNalyzator / RLdC Trading Bot

System działa jako hybrydowy trader AI:
- program sam buduje snapshot rynku,
- liczy wskaźniki i koszty,
- tworzy plan transakcji z entry / TP / SL / break-even,
- monitoruje plan i oznacza rewizję przy zmianie warunków,
- blokuje wejścia i wyjścia bez przewagi netto,
- w LIVE pilnuje zgodności z filtrami Binance.

## Najważniejsze elementy

- Backend: FastAPI + collector + silnik decyzji w `backend/`
- Frontend: Next.js w `web_portal/`
- Telegram: bot sterujący i raportujący w `telegram_bot/`
- Baza: SQLite domyślnie, z trwałym audytem sygnałów, pozycji, zleceń i planów

## Wymagania

- Ubuntu
- Python 3.11+
- Node.js 20+
- `python -m venv`

## Szybki start od zera

```bash
git clone <repo-url>
cd RLdC_AiNalyzator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Minimalne `.env`

```env
TRADING_MODE=demo
DATABASE_URL=sqlite:///./rldc_trading.db
DEMO_INITIAL_BALANCE=10000
ADMIN_TOKEN=

BINANCE_API_KEY=
BINANCE_API_SECRET=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

OPENAI_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
OLLAMA_BASE_URL=
```

Uwagi:
- `TRADING_MODE=demo|live`
- bez kluczy Binance system działa w trybie publicznych danych / demo
- bez klucza LLM działa fallback heurystyczny i nadal generuje plan transakcji

## Uruchomienie backendu

```bash
source .venv/bin/activate
python -m backend.app
```

Backend:
- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Uruchomienie WWW

```bash
cd web_portal
npm install
npm run dev
```

Frontend:
- `http://localhost:3000`

## Uruchomienie Telegram

```bash
source .venv/bin/activate
python -m telegram_bot.bot
```

## Tryby pracy

- `DEMO`: zapis do lokalnej bazy, execution bez realnego Binance
- `LIVE`: realne odczyty i zlecenia Binance, z guardami kosztów i filtrów
- `BACKTEST`: UI może prezentować ten tryb, ale pełny silnik backtest wymaga dalszej rozbudowy

## Najważniejsze endpointy

- `GET /api/market/summary`
- `GET /api/market/kline?symbol=BTCEUR&tf=1h`
- `GET /api/portfolio`
- `GET /api/portfolio/summary`
- `GET /api/orders`
- `GET /api/orders/pending`
- `GET /api/positions`
- `GET /api/signals/latest`
- `GET /api/signals/top10`
- `GET /api/signals/top5`

Plan transakcji jest zwracany w payloadach pozycji, sygnałów, zleceń i pending orders:
- `plan_status`
- `action`
- `entry_price`
- `take_profit_price`
- `stop_loss_price`
- `break_even_price`
- `expected_total_cost`
- `expected_net_profit`
- `confidence_score`
- `risk_score`
- `requires_revision`
- `last_consulted_at`

## Telegram

Obsługiwane komendy:
- `/status`
- `/portfolio`
- `/positions`
- `/orders`
- `/top10`
- `/top5`
- `/lastsignal`
- `/risk`
- `/blog`
- `/logs`
- `/ip`

Bot pokazuje plan tradera: entry, TP, SL, break-even, expected net profit, confidence i status rewizji.

## Testy

```bash
source .venv/bin/activate
pytest tests/test_smoke.py -q
python -m compileall backend telegram_bot tests
```

Stan po tej zmianie:
- `200 passed` w `tests/test_smoke.py`

## Ważne ograniczenia

- LIVE nadal zależy od jakości danych Binance, kluczy API i stabilności sieci
- pełny autonomiczny loop re-konsultacji istnieje w collectorze i planach, ale dalsze strojenie parametrów wejścia/wyjścia jest nadal wymagane przed agresywnym LIVE
- UI jest po polsku, ale część starszych widoków nadal wymaga dalszego porządkowania
