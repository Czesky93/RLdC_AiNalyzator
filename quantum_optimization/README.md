# Quantum Portfolio Optimization Module

This module implements quantum-based portfolio optimization using real live market data from cryptocurrency exchanges.

## Features

- **Real Market Data**: Fetches live OHLCV data from cryptocurrency exchanges using the CCXT library
- **Quantum Algorithms**: Implements portfolio optimization using Qiskit's VQE and QAOA algorithms
- **Risk Analysis**: Calculates expected returns and covariance matrices from historical data
- **Portfolio Metrics**: Computes Sharpe ratio, expected returns, and risk metrics

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Components

### 1. Data Service (`data_service.py`)
- Connects to cryptocurrency exchanges (default: Binance)
- Fetches historical OHLCV data
- Computes expected returns and covariance matrices
- Validates data quality

### 2. Quantum Optimizer (`optimizer.py`)
- Implements `QuantumPortfolioOptimizer` class
- Supports VQE (Variational Quantum Eigensolver) and QAOA algorithms
- Converts portfolio optimization to QUBO format
- Runs on local statevector simulator

### 3. Live Execution Script (`run_live.py`)
- End-to-end execution of quantum portfolio optimization
- Uses real market data from multiple cryptocurrency pairs
- Displays optimal allocation with metrics

## Usage

Run the live optimization script:

```bash
cd quantum_optimization
python run_live.py
```

This will:
1. Fetch real market data for BTC/USDT, ETH/USDT, BNB/USDT, and SOL/USDT
2. Calculate risk/return metrics
3. Perform quantum optimization
4. Display the optimal portfolio allocation

## Example Output

```
OPTIMAL QUANTUM ALLOCATION - BASED ON CURRENT MARKET CONDITIONS
========================================================================

Asset Selection:
  BTC/USDT     ✓ SELECTED      Weight: 60.00%  Expected Return:  0.0234%
  ETH/USDT     ✓ SELECTED      Weight: 40.00%  Expected Return:  0.0189%
  BNB/USDT     ✗ Not Selected  Weight:  0.00%  Expected Return:  0.0156%
  SOL/USDT     ✗ Not Selected  Weight:  0.00%  Expected Return:  0.0145%

Portfolio Metrics:
  Expected Return:   0.0215%
  Portfolio Risk:    0.0342%
  Sharpe Ratio:      0.6287
  Optimal Value:    -0.0023
```

## Configuration

You can customize the optimization by modifying parameters in `run_live.py`:

- **assets**: List of trading pairs to optimize
- **days**: Number of days of historical data (default: 90)
- **budget**: Maximum number of assets to select
- **risk_factor**: Risk tolerance (0.0 = risk-averse, 1.0 = risk-seeking)
- **algorithm**: 'VQE' or 'QAOA'

## Technical Details

### Portfolio Optimization Problem

The module solves the classic Markowitz portfolio optimization problem:
- Maximize: Expected Return - (risk_factor × Risk)
- Subject to: Budget constraint (number of assets)

### Quantum Approach

1. Formulates the problem as a Quadratic Unconstrained Binary Optimization (QUBO)
2. Converts to quantum Hamiltonian
3. Uses VQE/QAOA to find the ground state
4. Maps quantum solution to asset selection

## Notes

- **Educational Purpose**: This implementation is for research and educational purposes
- **Live Data**: Uses real market data, so results vary with market conditions
- **Simulation**: Runs on a quantum simulator, not actual quantum hardware
- **No Investment Advice**: Past performance does not guarantee future results

## Dependencies

- `qiskit`: Quantum computing framework
- `qiskit-optimization`: Optimization library for Qiskit
- `qiskit-algorithms`: Quantum algorithms including VQE and QAOA
- `ccxt`: Cryptocurrency exchange trading library
- `pandas`: Data manipulation
- `numpy`: Numerical computing
- `scipy`: Scientific computing

## License

See repository LICENSE file.
