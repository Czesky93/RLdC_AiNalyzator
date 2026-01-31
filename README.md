# RLdC_AiNalyzator

System analizy i monitoringu handlu z modułem AI, panelem WWW, API oraz botem Telegram.

## 🚀 Funkcje

- **Monitoring rynku w czasie rzeczywistym** (dane Binance, market summary, kline)
- **Analiza i historia transakcji** (SQLite)
- **Panel WWW po polsku** z wykresem i dashboardem
- **REST API (FastAPI)** z dokumentacją Swagger
- **Bot Telegram** z komendami operacyjnymi
- **Docker** gotowy do uruchomienia od zera

## ✅ Wymagania

- Docker 20.10+
- Docker Compose 2+

## ⚡ Szybki start

1. Klon repozytorium i wejście do katalogu:

2. Uruchom instalację:

3. Po zakończeniu:

- UI: http://localhost:3000
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs

## 🧩 Struktura projektu

Główne elementy:
- backend: [main.py](main.py)
- konfiguracja: [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [install.sh](install.sh)
- środowisko: [.env.example](.env.example)
- frontend: [web_portal/ui](web_portal/ui)
- bot Telegram: [telegram_bot](telegram_bot)

## ⚙️ Konfiguracja

Zmień wartości w `.env` na podstawie [.env.example](.env.example). Najważniejsze:

- `BINANCE_API_KEY`, `BINANCE_API_SECRET` – do danych prywatnych (konto/zlecenia/pozycje)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` – do bota Telegram
- `REACT_APP_API_URL` – URL API dla UI

## 🧪 Testy

Uruchom testy lokalnie:

1. Instalacja zależności
2. `pytest -q`

## 🔎 API – kluczowe endpointy

- `/health`
- `/api/market/summary`
- `/api/market/kline?symbol=BTCUSDT&tf=1h`
- `/api/live/account`
- `/api/live/orders`
- `/api/live/positions`
- `/api/demo/summary`
- `/api/demo/orders`
- `/api/demo/orders/export`
- `/api/blog`
- `/api/alerts/telegram?message=...`

## 🧠 Bot Telegram

Komendy:
- `/status`, `/start`, `/risk`, `/top10`, `/top5`, `/portfolio`, `/orders`, `/positions`, `/lastsignal`, `/blog`, `/logs`

## 🛡️ Bezpieczeństwo

- Nie commituj `.env` z sekretami
- Ogranicz `CORS_ORIGINS` w produkcji

## 📌 Uwaga

Wszystkie teksty i etykiety są po polsku zgodnie z wymaganiami projektu.