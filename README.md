# RLdC_AiNalyzator

AI-Powered Trading Analysis & Monitoring System

## 🚀 Features

- **Real-time Trading Monitoring**: Track and analyze trading activities in real-time
- **AI-Powered Analysis**: Advanced analysis capabilities for trading patterns
- **Modern Web Dashboard**: Intuitive React-based user interface
- **RESTful API**: FastAPI-powered backend with automatic API documentation
- **Data Persistence**: SQLite database for storing trading history and analysis results
- **Production-Ready**: Fully containerized with Docker for easy deployment

## 📋 Prerequisites

Before deploying RLdC AiNalyzator, ensure you have the following installed:

- **Docker** (version 20.10 or higher)
- **Docker Compose** (version 2.0 or higher)

### Installing Docker

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

#### macOS
```bash
brew install --cask docker
# Or download Docker Desktop from https://www.docker.com/products/docker-desktop
```

#### Windows
Download and install Docker Desktop from [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)

## 🔧 Quick Deployment

RLdC AiNalyzator includes an automated installation script that handles all deployment steps.

### 1. Clone the Repository
```bash
git clone https://github.com/Czesky93/RLdC_AiNalyzator.git
cd RLdC_AiNalyzator
```

### 2. Run the Installation Script
```bash
./install.sh
```

The installation script will:
- ✅ Check if Docker and Docker Compose are installed
- ✅ Create `.env` file from `.env.example` if needed
- ✅ Build Docker images for backend and frontend
- ✅ Start all services using Docker Compose
- ✅ Display access URLs for the application

### 3. Access the Application

Once installation is complete, access the application at:

- **Web Dashboard**: [http://localhost:3000](http://localhost:3000)
- **API Endpoint**: [http://localhost:8000](http://localhost:8000)
- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

## 🐳 Manual Deployment

If you prefer to deploy manually without using the installation script:

### Build and Start Services
```bash
docker-compose build
docker-compose up -d
```

### View Logs
```bash
docker-compose logs -f
```

### Stop Services
```bash
docker-compose down
```

### Restart Services
```bash
docker-compose restart
```

### Check Service Status
```bash
docker-compose ps
```

## 📁 Project Structure

```
RLdC_AiNalyzator/
├── main.py                 # Backend application entry point
├── requirements.txt        # Python dependencies
├── Dockerfile             # Backend Docker configuration
├── docker-compose.yml     # Multi-container orchestration
├── install.sh            # Automated installation script
├── .env.example          # Environment variables template
├── web_portal/
│   └── ui/
│       ├── Dockerfile    # Frontend Docker configuration (multi-stage)
│       ├── nginx.conf    # Nginx configuration for SPA routing
│       ├── package.json  # Node.js dependencies
│       ├── public/       # Static assets
│       └── src/          # React application source
└── README.md
```

## ⚙️ Configuration

### Environment Variables

Configuration is managed through environment variables in the `.env` file:

```env
# Backend Configuration
DB_PATH=/data/trading_history.db
PORT=8000

# Frontend Configuration
REACT_APP_API_URL=http://localhost:8000

# Docker Configuration
COMPOSE_PROJECT_NAME=rldc-ainalyzator
```

### Customizing Ports

To change the default ports, edit the `docker-compose.yml` file:

```yaml
services:
  backend:
    ports:
      - "8000:8000"  # Change the first port (host port)
  
  frontend:
    ports:
      - "3000:80"    # Change the first port (host port)
```

## 🗄️ Data Persistence

Trading data is persisted in a Docker volume named `rldc-trading-data`. This ensures your data survives container restarts and updates.

### Backup Database
```bash
docker run --rm -v rldc-trading-data:/data -v $(pwd):/backup alpine tar czf /backup/trading_data_backup.tar.gz -C /data .
```

### Restore Database
```bash
docker run --rm -v rldc-trading-data:/data -v $(pwd):/backup alpine sh -c "cd /data && tar xzf /backup/trading_data_backup.tar.gz"
```

## 🔍 API Documentation

The backend provides automatic interactive API documentation powered by FastAPI:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Available Endpoints

#### Trading
- `GET /api/trades` - List all trades
- `POST /api/trades` - Create a new trade

#### Analysis
- `GET /api/analysis` - List all analysis results
- `POST /api/analysis` - Create a new analysis

#### System
- `GET /` - API information
- `GET /health` - Health check endpoint

## 🛠️ Development

### Local Development (Without Docker)

#### Backend
```bash
pip install -r requirements.txt
python main.py
```

#### Frontend
```bash
cd web_portal/ui
npm install
npm start
```

### Running Tests

Tests can be executed inside the Docker containers or locally.

## 🔐 Security Considerations

- The application includes basic CORS configuration. For production, configure specific allowed origins.
- Database is stored in a persistent Docker volume for data protection.
- Nginx security headers are configured in the frontend.
- Health checks are implemented for both services.

## 📊 Monitoring

### View Real-time Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Container Health Status
```bash
docker-compose ps
```

## 🐛 Troubleshooting

### Services Won't Start
1. Check Docker daemon is running: `docker info`
2. Check port availability: `netstat -tuln | grep -E '8000|3000'`
3. View logs: `docker-compose logs`

### Database Issues
1. Check volume exists: `docker volume ls | grep rldc-trading-data`
2. Remove and recreate: `docker-compose down -v && docker-compose up -d`

### Frontend Can't Connect to Backend
1. Verify backend is running: `docker-compose ps backend`
2. Check network: `docker network ls | grep rldc-network`
3. Verify REACT_APP_API_URL in `.env` matches your setup

## 📝 License

This project is open source and available under the MIT License.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open an issue on GitHub.