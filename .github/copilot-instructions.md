# Instrukcje dla agentów AI (RLdC_AiNalyzator)

## Szybki kontekst
- Backend: [main.py](main.py) (FastAPI + SQLite).
- Frontend: [web_portal/ui](web_portal/ui) (React + lightweight-charts).
- Konfiguracja: [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [install.sh](install.sh), [.env.example](.env.example).
- Testy: [tests/unit/test_api_smoke.py](tests/unit/test_api_smoke.py).
- Bot Telegram: [telegram_bot](telegram_bot).

## Co to oznacza dla pracy agenta
- Stosuj spójne API zgodne z dokumentacją w README.
- Wszystkie etykiety i teksty w języku polskim.
- Zachowuj spójność między UI, backendem i botem Telegram.

## Jak postępować przy kolejnych zadaniach
- Zanim wprowadzisz zmiany, sprawdź: [main.py](main.py), [web_portal/ui](web_portal/ui), [telegram_bot](telegram_bot).
- Komendy:
  - Docker: `./install.sh` lub `docker-compose up -d`
  - Testy: `pytest -q`

## Miejsca referencyjne
- [README.md](README.md)
