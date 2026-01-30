# Quantum Portfolio Optimization Module

This module implements quantum-based portfolio optimization using real live market data from cryptocurrency exchanges.

## Features

- **Real Market Data**: Attempts to fetch live OHLCV data from cryptocurrency exchanges using the CCXT library
- **Fallback Demo Data**: Uses realistic demo data based on historical patterns when live data is unavailable
- **Quantum Algorithms**: Implements portfolio optimization using Qiskit's SamplingVQE and QAOA algorithms
- **Risk Analysis**: Calculates expected returns and covariance matrices from historical data
- **Portfolio Metrics**: Computes Sharpe ratio, expected returns, and risk metrics

## Installation

Install the required dependencies:

```bash
cd quantum_optimization
pip install -r requirements.txt
```

## Components

### 1. Data Service (`data_service.py`)
- Attempts to connect to cryptocurrency exchanges (default: Binance) via CCXT
- Fetches historical OHLCV data for specified trading pairs
- Computes expected returns (mean historical returns) and covariance matrices (risk)
- Falls back to realistic demo data based on historical cryptocurrency market patterns when live data is unavailable
- Validates data quality before optimization

### 2. Quantum Optimizer (`optimizer.py`)
- Implements `QuantumPortfolioOptimizer` class
- Supports SamplingVQE (Variational Quantum Eigensolver) and QAOA (Quantum Approximate Optimization Algorithm)
- Manually constructs portfolio optimization as a Quadratic Program
- Converts portfolio optimization to QUBO (Quadratic Unconstrained Binary Optimization) format
- Runs on local statevector simulator (simulating quantum hardware)
- Returns binary asset selection and normalized weights

### 3. Live Execution Script (`run_live.py`)
- End-to-end execution of quantum portfolio optimization
- Uses real market data from multiple cryptocurrency pairs (BTC, ETH, BNB, SOL)
- Displays optimal allocation with detailed metrics
- Includes comprehensive error handling

### 4. Examples (`examples.py`)
- Demonstrates custom asset portfolio optimization
- Shows how to compare different risk levels
- Illustrates using QAOA vs VQE algorithms

## Usage

### Run the main live optimization script:

```bash
cd quantum_optimization
python run_live.py
```

This will:
1. Attempt to fetch real market data for BTC/USDT, ETH/USDT, BNB/USDT, and SOL/USDT
2. Fall back to realistic demo data if live fetching fails
3. Calculate risk/return metrics from the data
4. Perform quantum optimization using VQE
5. Display the optimal portfolio allocation

### Run the examples:

```bash
cd quantum_optimization
python examples.py
```

## Example Output

```
OPTIMAL QUANTUM ALLOCATION - BASED ON CURRENT MARKET CONDITIONS
========================================================================

Asset Selection:
  BTC/USDT     ✗ Not Selected  Weight:  0.00%  Expected Return: -0.8106%
  ETH/USDT     ✗ Not Selected  Weight:  0.00%  Expected Return: -0.1009%
  BNB/USDT     ✗ Not Selected  Weight:  0.00%  Expected Return: -0.1700%
  SOL/USDT     ✓ SELECTED      Weight: 100.00%  Expected Return:  0.5527%

Portfolio Metrics:
  Expected Return:   0.5527%
  Portfolio Risk:    4.3599%
  Sharpe Ratio:       0.1268
  Optimal Value:     -0.0046
```

## Configuration

You can customize the optimization by modifying parameters in `run_live.py` or when calling the functions:

- **assets**: List of trading pairs to optimize (e.g., `['BTC/USDT', 'ETH/USDT']`)
- **days**: Number of days of historical data (default: 90)
- **budget**: Maximum number of assets to select (default: 2)
- **risk_factor**: Risk tolerance (0.0 = risk-averse, 1.0 = risk-seeking, default: 0.5)
- **algorithm**: 'VQE' or 'QAOA' (default: 'VQE')

## Technical Details

### Portfolio Optimization Problem

The module solves the classic Markowitz portfolio optimization problem:
- **Objective**: Minimize: -Expected_Return + (risk_factor × Variance)
- **Constraint**: Number of selected assets ≤ budget

### Quantum Approach

1. Formulates the problem as a Quadratic Unconstrained Binary Optimization (QUBO)
2. Converts to quantum Hamiltonian using Qiskit
3. Uses SamplingVQE or QAOA to find the ground state (optimal solution)
4. Maps quantum solution (bitstring) to asset selection (binary array)
5. Calculates optimal weights for selected assets based on expected returns

### Data Source

- **Primary**: Real-time market data from cryptocurrency exchanges via CCXT library
- **Fallback**: Realistic demo data with parameters based on historical cryptocurrency market patterns:
  - BTC: ~0.15% daily return, 4% volatility
  - ETH: ~0.18% daily return, 5% volatility
  - BNB: ~0.12% daily return, 4.5% volatility
  - SOL: ~0.20% daily return, 6% volatility
  - Inter-asset correlation: 0.5-0.8 (typical for crypto markets)

## Important Notes

- **Educational Purpose**: This implementation is for research and educational purposes only
- **Live Data Attempt**: The system attempts to use REAL market data when network access permits
- **Fallback Data**: Uses realistic demo data when exchanges are unreachable (network restrictions)
- **Simulation**: Runs on a quantum simulator, not actual quantum hardware
- **Not Financial Advice**: Past performance does not guarantee future results
- **Professional Advice**: Consult a qualified financial advisor for investment decisions

## Dependencies

- `qiskit>=0.45.0`: Quantum computing framework
- `qiskit-optimization>=0.6.0`: Optimization library for Qiskit
- `qiskit-algorithms>=0.3.0`: Quantum algorithms including VQE and QAOA
- `ccxt>=4.1.0`: Cryptocurrency exchange trading library (for real data)
- `pandas>=2.0.0`: Data manipulation
- `numpy>=1.24.0`: Numerical computing
- `scipy>=1.10.0`: Scientific computing

## API Compatibility

This module is compatible with:
- Qiskit 2.x API (uses `StatevectorSampler`, `SamplingVQE`)
- Modern quantum optimization workflows
- Qiskit Optimization 0.6+

## License

See repository LICENSE file.
