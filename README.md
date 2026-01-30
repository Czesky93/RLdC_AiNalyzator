# RLdC_AiNalyzator

A paper trading bot with persistent data storage and a web API for visualizing trading results.

## Features

- **Persistent Data Layer**: SQLAlchemy-based ORM with SQLite (easily upgradable to PostgreSQL)
- **Paper Trading Engine**: Simulates trading with database persistence
- **REST API**: FastAPI-based endpoints for accessing trading data
- **Real-time Data**: Trade history, equity curves, and performance statistics

## Architecture

```
RLdC_AiNalyzator/
├── database/               # Database layer
│   ├── models.py          # SQLAlchemy models (Trade, PortfolioSnapshot)
│   └── session.py         # Database engine and session management
├── decision_engine/        # Trading logic
│   └── paper_trader.py    # Paper trading implementation with DB integration
├── web_portal/            # Web API
│   └── api/
│       ├── main.py        # FastAPI application
│       └── routers/
│           └── trading.py # Trading endpoints
└── tests/                 # Test suite
    ├── test_database.py   # Database model tests
    ├── test_paper_trader.py # Paper trader tests
    └── test_api.py        # API endpoint tests
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

## Quick Start

### 1. Run the Example

```bash
python example_usage.py
```

This creates sample trades and demonstrates the system functionality.

### 2. Start the API Server

```bash
python -m web_portal.api.main
```

Or with uvicorn:

```bash
uvicorn web_portal.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Access the API

Visit http://localhost:8000/docs for interactive API documentation.

## API Endpoints

### Trading History
```
GET /trading/history?limit=100&offset=0&symbol=BTCUSDT
```

Returns paginated list of trades with optional symbol filter.

### Equity Curve
```
GET /trading/equity?limit=1000&offset=0
```

Returns portfolio snapshots for charting equity over time.

### Trading Statistics
```
GET /trading/stats
```

Returns:
- Total trades
- Winning/losing trade counts
- Win rate percentage
- Total and average P/L

## Database Models

### Trade
- `id`: Primary key
- `symbol`: Trading pair (e.g., "BTCUSDT")
- `side`: "BUY" or "SELL"
- `amount`: Quantity traded
- `price`: Price per unit
- `timestamp`: Trade execution time
- `profit_loss`: Optional P/L for the trade

### PortfolioSnapshot
- `id`: Primary key
- `timestamp`: Snapshot time
- `total_equity_usdt`: Total portfolio value
- `cash_balance`: Available cash

## Usage Example

```python
from database.session import SessionLocal, init_db
from decision_engine.paper_trader import PaperTrader

# Initialize database
init_db()
db = SessionLocal()

# Create paper trader
trader = PaperTrader(db, initial_balance=10000.0)

# Execute trades
trader.execute_order("BTCUSDT", "BUY", 0.1, 50000.0)
trader.step({"BTCUSDT": 51000.0})  # Save snapshot

trader.execute_order("BTCUSDT", "SELL", 0.1, 52000.0, profit_loss=200.0)
trader.step({})

db.close()
```

## Running Tests

```bash
pytest tests/ -v
```

## Future-Proofing: PostgreSQL Migration

The system uses SQLAlchemy ORM, making database migration seamless:

```python
# Simply change the database URL in database/session.py:
DATABASE_URL = "postgresql://user:password@localhost/trading_db"
```

No code changes required!

## Development

- **Database**: SQLite stored in `trading_history.db` (excluded from git)
- **API Framework**: FastAPI with automatic OpenAPI documentation
- **ORM**: SQLAlchemy 2.0+ with declarative models
- **Testing**: pytest with in-memory SQLite

## Contributing

1. Make changes to the codebase
2. Add/update tests as needed
3. Run the test suite: `pytest tests/`
4. Ensure all tests pass before submitting

## License

MIT License