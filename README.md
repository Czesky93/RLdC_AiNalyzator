# RLdC_AiNalyzator

AI-powered trading bot with real-time performance monitoring dashboard.

## Project Structure

- **`web_portal/ui/`** - React-based web dashboard for visualizing trading performance
- **`mock_backend/`** - Mock API server for testing the dashboard (development only)

## Features

### Trading Dashboard
- Real-time performance metrics (Balance, PnL, Win Rate)
- Interactive equity curve visualization
- Recent trades history with profit/loss tracking
- Responsive design for desktop and mobile

## Getting Started

### Web Dashboard

1. Navigate to the UI directory:
```bash
cd web_portal/ui
```

2. Install dependencies:
```bash
npm install
```

3. Configure API endpoint (optional):
```bash
cp .env.example .env
# Edit .env to set REACT_APP_API_URL
```

4. Start the development server:
```bash
npm start
```

The dashboard will be available at http://localhost:3000

### Mock Backend (for testing)

1. Navigate to the mock backend directory:
```bash
cd mock_backend
```

2. Install dependencies:
```bash
npm install
```

3. Start the server:
```bash
npm start
```

The mock API will be available at http://localhost:8000

## API Integration

The dashboard connects to a backend API with the following endpoints:

- `GET /api/dashboard/stats` - Current balance, total PnL, and win rate
- `GET /api/dashboard/equity-history` - Historical equity data for charting
- `GET /api/dashboard/trade-history` - Recent trade records

## Technologies

- **Frontend**: React, Recharts, Axios
- **Mock Backend**: Node.js, Express
- **Testing**: Jest, React Testing Library