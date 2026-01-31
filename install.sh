#!/usr/bin/env bash
set -e

if ! command -v docker >/dev/null 2>&1; then
  echo "Brak Dockera. Zainstaluj Docker i Docker Compose." >&2
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "Brak docker-compose. Zainstaluj Docker Compose v2." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "Tworzę .env na podstawie .env.example"
  cp .env.example .env
fi

docker-compose build

docker-compose up -d

echo "Uruchomiono RLdC AiNalyzer"
echo "UI: http://localhost:3000"
echo "API: http://localhost:8000"
