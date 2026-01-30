#!/bin/bash

# RLdC AiNalyzator - Automated Installation Script
# This script checks prerequisites and deploys the application using Docker

set -e

echo "================================================"
echo "  RLdC AiNalyzator - Installation Script"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
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

# Check if Docker is installed
echo "Checking prerequisites..."
echo ""

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed!"
    echo ""
    echo "Please install Docker first:"
    echo "  - Visit: https://docs.docker.com/get-docker/"
    echo "  - Or use your package manager:"
    echo "    Ubuntu/Debian: sudo apt-get install docker.io"
    echo "    macOS: brew install --cask docker"
    echo ""
    exit 1
fi

print_success "Docker is installed ($(docker --version))"

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not installed!"
    echo ""
    echo "Please install Docker Compose:"
    echo "  - Visit: https://docs.docker.com/compose/install/"
    echo ""
    exit 1
fi

# Determine which docker compose command to use
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
    print_success "Docker Compose is installed ($(docker-compose --version))"
else
    DOCKER_COMPOSE="docker compose"
    print_success "Docker Compose plugin is installed ($(docker compose version))"
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running!"
    echo ""
    echo "Please start Docker first:"
    echo "  - Linux: sudo systemctl start docker"
    echo "  - macOS/Windows: Start Docker Desktop"
    echo ""
    exit 1
fi

print_success "Docker daemon is running"
echo ""

# Check/Create .env file
if [ ! -f .env ]; then
    print_warning ".env file not found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        print_success ".env file created successfully"
        print_info "You can customize .env file before running the application"
    else
        print_error ".env.example file not found!"
        exit 1
    fi
else
    print_success ".env file already exists"
fi

echo ""
print_info "Starting deployment process..."
echo ""

# Stop existing containers if running
print_info "Stopping any existing containers..."
$DOCKER_COMPOSE down 2>/dev/null || true

# Build images
print_info "Building Docker images..."
echo ""
if $DOCKER_COMPOSE build; then
    print_success "Docker images built successfully"
else
    print_error "Failed to build Docker images"
    exit 1
fi

echo ""

# Start containers
print_info "Starting containers..."
echo ""
if $DOCKER_COMPOSE up -d; then
    print_success "Containers started successfully"
else
    print_error "Failed to start containers"
    exit 1
fi

echo ""
print_info "Waiting for services to become healthy..."
sleep 5

# Check service status
echo ""
print_info "Service Status:"
$DOCKER_COMPOSE ps

echo ""
echo "================================================"
print_success "Installation completed successfully!"
echo "================================================"
echo ""
echo "Access your application:"
echo ""
print_success "Dashboard:  http://localhost:3000"
print_success "API:        http://localhost:8000"
print_success "API Docs:   http://localhost:8000/docs"
echo ""
echo "Useful commands:"
echo "  View logs:       $DOCKER_COMPOSE logs -f"
echo "  Stop services:   $DOCKER_COMPOSE down"
echo "  Restart:         $DOCKER_COMPOSE restart"
echo "  View status:     $DOCKER_COMPOSE ps"
echo ""
echo "================================================"
