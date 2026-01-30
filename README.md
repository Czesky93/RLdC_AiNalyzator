# RLdC_AiNalyzator

A comprehensive AI-powered trading analysis and decision-making system.

## Features

This repository includes a sophisticated **Decision Engine** module that unifies fragmented trading subsystems into a single acting entity running in safe paper trading mode.

### Decision Engine Components

1. **Signal Aggregator** - Combines multiple data sources (Sentiment, Quantum, AI) with weighted logic and veto rules
2. **Paper Trading System** - Simulates trades with virtual balance, realistic fees, and comprehensive logging
3. **Bot Kernel** - Orchestrates complete trading cycles: Fetch → Aggregate → Execute → Log

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the demo
python demo.py

# Run tests
pytest tests/ -v
```

## Documentation

See [decision_engine/README.md](decision_engine/README.md) for detailed documentation of the Decision Engine module.

## Structure

```
RLdC_AiNalyzator/
├── decision_engine/        # Core decision and trading engine
│   ├── aggregator.py       # Signal aggregation with veto rules
│   ├── paper_trader.py     # Paper trading simulation
│   ├── core.py             # Bot kernel orchestration
│   └── README.md           # Detailed module documentation
├── tests/                  # Comprehensive test suite
│   ├── test_aggregator.py
│   ├── test_paper_trader.py
│   └── test_core.py
├── demo.py                 # Interactive demo script
└── requirements.txt        # Python dependencies
```

## Testing

The project includes 43 comprehensive tests covering all components:

```bash
pytest tests/ -v
```

## License

This project is maintained by Czesky93.
