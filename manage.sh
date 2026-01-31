#!/usr/bin/env bash
# Skrypt pomocniczy do zarządzania RLdC AiNalyzer

set -e

COMMAND="${1:-help}"

case "$COMMAND" in
  start)
    echo "🚀 Uruchamianie RLdC AiNalyzer..."
    docker-compose up -d
    echo "✅ Uruchomiono!"
    echo "   UI: http://localhost:3000"
    echo "   API: http://localhost:8000"
    echo "   Docs: http://localhost:8000/docs"
    ;;
  
  stop)
    echo "🛑 Zatrzymywanie RLdC AiNalyzer..."
    docker-compose down
    echo "✅ Zatrzymano!"
    ;;
  
  restart)
    echo "🔄 Restartowanie RLdC AiNalyzer..."
    docker-compose restart
    echo "✅ Zrestartowano!"
    ;;
  
  logs)
    SERVICE="${2:-}"
    if [ -z "$SERVICE" ]; then
      docker-compose logs -f
    else
      docker-compose logs -f "$SERVICE"
    fi
    ;;
  
  status)
    echo "📊 Status kontenerów:"
    docker-compose ps
    ;;
  
  build)
    echo "🔨 Budowanie obrazów Docker..."
    docker-compose build
    echo "✅ Zbudowano!"
    ;;
  
  clean)
    echo "🧹 Czyszczenie (zatrzymanie i usunięcie kontenerów)..."
    docker-compose down -v
    echo "✅ Wyczyszczono!"
    ;;
  
  test)
    echo "🧪 Uruchamianie testów..."
    python -m pytest tests/unit/ -v
    echo "✅ Testy zakończone!"
    ;;
  
  help|*)
    echo "RLdC AiNalyzer - Skrypt zarządzania"
    echo ""
    echo "Użycie: ./manage.sh [KOMENDA]"
    echo ""
    echo "Komendy:"
    echo "  start       Uruchom wszystkie serwisy"
    echo "  stop        Zatrzymaj wszystkie serwisy"
    echo "  restart     Zrestartuj wszystkie serwisy"
    echo "  logs [svc]  Pokaż logi (opcjonalnie dla konkretnego serwisu)"
    echo "  status      Pokaż status kontenerów"
    echo "  build       Zbuduj obrazy Docker"
    echo "  clean       Zatrzymaj i usuń kontenery oraz volumeny"
    echo "  test        Uruchom testy jednostkowe"
    echo "  help        Pokaż tę pomoc"
    echo ""
    echo "Serwisy: backend, frontend, telegram_bot"
    ;;
esac
