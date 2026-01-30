# RLdC_AiNalyzator

AI-powered blockchain and crypto analysis platform.

## Modules

### Blockchain Analysis Module
Foundation for interacting with Ethereum and EVM-compatible blockchain networks. See [blockchain_analysis/README.md](blockchain_analysis/README.md) for detailed documentation.

**Features:**
- Blockchain connection management via RPC
- On-chain data fetching (blocks, balances, gas prices)
- Extensible architecture for mempool monitoring and MEV detection

## Installation

Install dependencies:
```bash
pip install -r blockchain_analysis/requirements.txt
```

## Testing

Run the test suite:
```bash
python -m unittest discover tests -v
```

## Project Structure

```
RLdC_AiNalyzator/
├── blockchain_analysis/      # Blockchain interaction module
│   ├── connector.py          # Blockchain connection management
│   ├── data_fetcher.py       # On-chain data fetching
│   ├── mempool.py            # Mempool monitoring (placeholder)
│   ├── mev_detector.py       # MEV detection (placeholder)
│   ├── requirements.txt      # Module dependencies
│   └── README.md             # Module documentation
├── tests/                    # Test suite
│   └── test_blockchain.py   # Blockchain module tests
├── .gitignore                # Git ignore rules
└── README.md                 # This file
```
