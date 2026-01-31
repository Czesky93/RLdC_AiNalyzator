#!/bin/bash

# RLdC AiNalyzator - Skrypt automatycznej instalacji
# Ten skrypt sprawdza wymagania wstępne i wdraża aplikację za pomocą Dockera

set -e

echo "================================================"
echo "  RLdC AiNalyzator - Skrypt instalacyjny"
echo "================================================"
echo ""

# Kolory dla wyjścia
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # Bez koloru

# Funkcje do wypisywania kolorowych komunikatów
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "ℹ $1"
}

# Sprawdź czy Docker jest zainstalowany
echo "Sprawdzanie wymagań wstępnych..."
echo ""

if ! command -v docker &> /dev/null; then
    print_error "Docker nie jest zainstalowany!"
    echo ""
    echo "Proszę najpierw zainstalować Docker:"
    echo "  - Odwiedź: https://docs.docker.com/get-docker/"
    echo "  - Lub użyj menedżera pakietów:"
    echo "    Ubuntu/Debian: sudo apt-get install docker.io"
    echo "    macOS: brew install --cask docker"
    echo ""
    exit 1
fi

print_success "Docker jest zainstalowany ($(docker --version))"

# Sprawdź czy Docker Compose jest zainstalowany
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_error "Docker Compose nie jest zainstalowany!"
    echo ""
    echo "Proszę zainstalować Docker Compose:"
    echo "  - Odwiedź: https://docs.docker.com/compose/install/"
    echo ""
    exit 1
fi

# Określ którą komendę docker compose użyć
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
    print_success "Docker Compose jest zainstalowany ($(docker-compose --version))"
else
    DOCKER_COMPOSE="docker compose"
    print_success "Wtyczka Docker Compose jest zainstalowana ($(docker compose version))"
fi

# Sprawdź czy demon Docker działa
if ! docker info &> /dev/null; then
    print_error "Demon Docker nie działa!"
    echo ""
    echo "Proszę najpierw uruchomić Docker:"
    echo "  - Linux: sudo systemctl start docker"
    echo "  - macOS/Windows: Uruchom Docker Desktop"
    echo ""
    exit 1
fi

print_success "Demon Docker działa"
echo ""

# Sprawdź/Utwórz plik .env
if [ ! -f .env ]; then
    print_warning "Plik .env nie został znaleziony. Tworzenie z .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        print_success "Plik .env został utworzony pomyślnie"
        print_info "Możesz dostosować plik .env przed uruchomieniem aplikacji"
    else
        print_error "Plik .env.example nie został znaleziony!"
        exit 1
    fi
else
    print_success "Plik .env już istnieje"
fi

echo ""
print_info "Rozpoczynanie procesu wdrażania..."
echo ""

# Zatrzymaj istniejące kontenery jeśli działają
print_info "Zatrzymywanie istniejących kontenerów..."
$DOCKER_COMPOSE down 2>/dev/null || true

# Buduj obrazy
print_info "Budowanie obrazów Docker..."
echo ""
if $DOCKER_COMPOSE build; then
    print_success "Obrazy Docker zbudowane pomyślnie"
else
    print_error "Nie udało się zbudować obrazów Docker"
    exit 1
fi

echo ""

# Uruchom kontenery
print_info "Uruchamianie kontenerów..."
echo ""
if $DOCKER_COMPOSE up -d; then
    print_success "Kontenery uruchomione pomyślnie"
else
    print_error "Nie udało się uruchomić kontenerów"
    exit 1
fi

echo ""
print_info "Oczekiwanie na uruchomienie usług..."
sleep 5

# Sprawdź status usług
echo ""
print_info "Status usług:"
$DOCKER_COMPOSE ps

echo ""
echo "================================================"
print_success "Instalacja zakończona pomyślnie!"
echo "================================================"
echo ""
echo "Dostęp do aplikacji:"
echo ""
print_success "Panel:      http://localhost:3000"
print_success "API:        http://localhost:8000"
print_success "Dok. API:   http://localhost:8000/docs"
echo ""
echo "Przydatne komendy:"
echo "  Zobacz logi:     $DOCKER_COMPOSE logs -f"
echo "  Zatrzymaj:       $DOCKER_COMPOSE down"
echo "  Restart:         $DOCKER_COMPOSE restart"
echo "  Zobacz status:   $DOCKER_COMPOSE ps"
echo ""
echo "================================================"
