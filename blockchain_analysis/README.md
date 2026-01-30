# Blockchain Analysis Module

This module provides functionality to interact with Ethereum and EVM-compatible blockchain networks.

## Features

### Implemented
- **BlockchainConnector**: Manages connections to blockchain networks via RPC
- **OnChainDataFetcher**: Fetches on-chain data including blocks, balances, and gas prices

### Placeholders (Future Development)
- **MempoolMonitor**: For monitoring pending transactions in the mempool
- **MEVDetector**: For detecting MEV (Maximal Extractable Value) opportunities

## Installation

Install the required dependencies:

```bash
pip install -r blockchain_analysis/requirements.txt
```

## Usage

### Basic Connection

```python
from blockchain_analysis import BlockchainConnector, OnChainDataFetcher

# Initialize connector with custom RPC URL
connector = BlockchainConnector(rpc_url='https://eth.llamarpc.com')

# Or use environment variable ETHEREUM_RPC_URL
connector = BlockchainConnector()

# Connect to the blockchain
if connector.connect():
    print("Connected successfully!")
    
    # Get latest block number
    block_number = connector.get_latest_block_number()
    print(f"Latest block: {block_number}")
```

### Fetching On-Chain Data

```python
from blockchain_analysis import BlockchainConnector, OnChainDataFetcher

# Initialize
connector = BlockchainConnector()
connector.connect()
fetcher = OnChainDataFetcher(connector)

# Get block details
block_details = fetcher.get_block_details(12345678)
print(f"Block timestamp: {block_details['timestamp']}")
print(f"Miner: {block_details['miner']}")
print(f"Transactions: {block_details['transaction_count']}")

# Get wallet balance
address = '0x742d35Cc6634C0532925a3b844Bc9e7595f0bEbC'
balance = fetcher.get_native_balance(address)
print(f"Balance: {balance['ether']} ETH ({balance['wei']} Wei)")

# Get current gas price
gas_price = fetcher.get_gas_price()
print(f"Gas price: {gas_price['gwei']} Gwei")
```

### Configuration via Environment Variables

Set the `ETHEREUM_RPC_URL` environment variable to configure the default RPC endpoint:

```bash
export ETHEREUM_RPC_URL='https://your-rpc-endpoint.com'
```

## Testing

Run the test suite:

```bash
python -m unittest tests.test_blockchain -v
```

All tests use mocked Web3 providers, so no real network requests are made during testing.

## Module Structure

```
blockchain_analysis/
├── __init__.py           # Module initialization
├── connector.py          # BlockchainConnector class
├── data_fetcher.py       # OnChainDataFetcher class
├── mempool.py            # MempoolMonitor placeholder
├── mev_detector.py       # MEVDetector placeholder
└── requirements.txt      # Dependencies

tests/
├── __init__.py
└── test_blockchain.py    # Comprehensive test suite
```

## Dependencies

- `web3`: Python library for interacting with Ethereum
- `eth-utils`: Ethereum utility functions

## Future Enhancements

The placeholder classes (`MempoolMonitor` and `MEVDetector`) are designed for future implementation of:
- Real-time mempool monitoring
- Pending transaction analysis
- MEV opportunity detection
- Arbitrage detection across DEXes
- Sandwich attack detection
- Liquidation opportunity identification
