# RLdC AI Analyzer - Web Portal

Professional trading dashboard with AI-powered trading analysis.

## Architecture

The web portal consists of two main components:

### Backend API (FastAPI)
- **Location**: `web_portal/api/`
- **Framework**: FastAPI
- **Purpose**: Bridge between core Python modules and Frontend UI

### Frontend UI (React)
- **Location**: `web_portal/ui/`
- **Framework**: React with Vite
- **UI Library**: Material-UI (MUI)
- **Charts**: Recharts

## Quick Start

### Prerequisites
- Python 3.8+ (for backend)
- Node.js 18+ (for frontend)

### Backend Setup

1. Navigate to the API directory:
```bash
cd web_portal/api
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the FastAPI server:
```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

**API Endpoints:**
- `GET /` - API information
- `GET /status` - System health status
- `GET /portfolio` - Portfolio holdings
- `GET /ai/signals` - Latest AI trading signals

**API Documentation:** Visit `http://localhost:8000/docs` for interactive API documentation.

### Frontend Setup

1. Navigate to the UI directory:
```bash
cd web_portal/ui
```

2. Install dependencies:
```bash
npm install
```

3. Start the development server:
```bash
npm run dev
```

The UI will be available at `http://localhost:3000`

### Build for Production

**Frontend:**
```bash
cd web_portal/ui
npm run build
```

The production build will be in `web_portal/ui/dist/`

## Features

### Dashboard
- **KPI Cards**: Total Balance, Daily P&L, Active AI Agents
- **Portfolio Performance Chart**: Visual representation of portfolio growth
- **Latest AI Signals**: Real-time trading signals from AI strategies

### Theme
- **Dark Mode**: Professional dark theme inspired by trading terminals
- **Cyberpunk Aesthetics**: Green/Red accents for financial data
- **Responsive Design**: Works on desktop and mobile devices

### Navigation
- Dashboard - Main overview
- AI Strategies - AI trading strategies (placeholder)
- Portfolio - Portfolio management (placeholder)
- Quantum Lab - Quantum computing features (placeholder)
- System Health - System monitoring (placeholder)

## Technology Stack

### Backend
- **FastAPI**: Modern, fast web framework for building APIs
- **Uvicorn**: ASGI server
- **Pydantic**: Data validation using Python type annotations

### Frontend
- **React 18**: UI library
- **Material-UI (MUI)**: Professional React component library
- **Recharts**: Composable charting library
- **Axios**: HTTP client
- **React Router**: Client-side routing
- **Vite**: Fast build tool and dev server

## Development

### API Development
The API uses stub data for demonstration. To integrate with real data:
1. Update `web_portal/api/endpoints.py`
2. Import your core trading modules
3. Replace stub responses with actual data

### Frontend Development
The frontend is designed to be modular:
- **Components**: Reusable UI components in `src/components/`
- **Pages**: Full page views in `src/pages/`
- **Theme**: Centralized theme configuration in `src/theme.js`

## Project Structure

```
web_portal/
├── api/                      # FastAPI Backend
│   ├── __init__.py
│   ├── main.py              # FastAPI app initialization
│   ├── endpoints.py         # API endpoints
│   └── requirements.txt     # Python dependencies
└── ui/                      # React Frontend
    ├── public/
    │   └── index.html       # HTML entry point
    ├── src/
    │   ├── components/
    │   │   └── Layout.jsx   # Main layout with sidebar
    │   ├── pages/
    │   │   └── Dashboard.jsx # Dashboard page
    │   ├── App.jsx          # Root component
    │   ├── index.jsx        # JavaScript entry point
    │   └── theme.js         # MUI theme configuration
    ├── package.json         # Node dependencies
    └── vite.config.js       # Vite configuration
```

## Contributing

1. Follow the existing code style
2. Update documentation for new features
3. Test both backend and frontend changes
4. Ensure responsive design for mobile devices

## License

This project is part of the RLdC AI Analyzer system.
