# RLdC AI Trading Dashboard

This is the React-based web dashboard for monitoring the AI trading bot's performance in real-time.

## Features

- **Real-time Dashboard Stats**: View current balance, total PnL, and win rate
- **Equity Curve Visualization**: Interactive chart showing portfolio equity over time
- **Recent Trades Table**: List of recent trades with profit/loss tracking
- **Responsive Design**: Works on desktop and mobile devices

## Getting Started

### Prerequisites

- Node.js (v14 or higher)
- npm or yarn

### Installation

1. Install dependencies:
```bash
cd web_portal/ui
npm install
```

2. Configure the API endpoint:
```bash
cp .env.example .env
# Edit .env and set REACT_APP_API_URL to your backend API URL
```

### Running the Application

Development mode:
```bash
npm start
```

The application will open at [http://localhost:3000](http://localhost:3000)

Build for production:
```bash
npm run build
```

## API Integration

The dashboard connects to the backend trading API using three endpoints:

1. **GET /api/dashboard/stats** - Retrieves current balance, PnL, and win rate
2. **GET /api/dashboard/equity-history** - Fetches historical equity data for charting
3. **GET /api/dashboard/trade-history** - Gets recent trade records

## Project Structure

```
src/
├── services/
│   └── api.js              # API client and service methods
├── pages/
│   ├── Dashboard.js        # Main dashboard component
│   └── Dashboard.css       # Dashboard styles
├── utils/
│   └── format.js           # Formatting utilities (currency, percentage)
├── App.js                  # Root application component
└── index.js                # Application entry point
```

## Technologies Used

- React 18
- Recharts (for data visualization)
- Axios (for API requests)
- React Hooks (useState, useEffect)
