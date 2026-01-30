# AI Trading Module - Phase 1 PoC

This module implements a Proof of Concept (PoC) for an AI-powered cryptocurrency trading system using Reinforcement Learning.

## Features

- **Data Loading**: Fetch historical OHLCV (Open, High, Low, Close, Volume) data from cryptocurrency exchanges
- **Trading Environment**: Custom Gymnasium environment for simulating cryptocurrency trading
- **RL Agent**: PPO (Proximal Policy Optimization) agent for learning trading strategies
- **Training Pipeline**: Complete training pipeline with progress monitoring

## Installation

Install the required dependencies:

```bash
cd ai_trading
pip install -r requirements.txt
```

## Components

### 1. Data Loader (`data_loader.py`)

Fetches historical OHLCV data using the `ccxt` library.

**Example usage:**
```python
from data_loader import load_data

# Load 1000 hourly candles of BTC/USDT
df = load_data(symbol='BTC/USDT', timeframe='1h', limit=1000)
```

**Features:**
- Error handling with retry logic
- Data cleaning and validation
- Support for multiple exchanges via ccxt

### 2. Trading Environment (`trading_env.py`)

Custom Gymnasium environment for cryptocurrency trading simulation.

**Action Space:**
- 0: Hold (do nothing)
- 1: Buy (purchase with all available balance)
- 2: Sell (sell entire position)

**Observation Space:**
- Market data: Normalized OHLCV data for the last N timesteps
- Account state: Balance, position, and net worth

**Reward:**
- Percentage change in net worth

**Example usage:**
```python
from trading_env import TradingEnv
import pandas as pd

# Create environment with your data
env = TradingEnv(df=your_dataframe, initial_balance=10000.0)

# Reset environment
obs, info = env.reset()

# Take a step
action = 1  # Buy
obs, reward, terminated, truncated, info = env.step(action)
```

### 3. Training Script (`train.py`)

Trains a PPO agent on the trading environment.

**Example usage:**
```bash
# Run with default parameters (uses mock data)
python train.py
```

**Example in code:**
```python
from train import train_agent

# Train agent with custom parameters
model = train_agent(
    symbol='BTC/USDT',
    timeframe='1h',
    limit=1000,
    total_timesteps=50000,
    initial_balance=10000.0,
    model_save_path='models/my_model.zip',
    use_mock_data=False  # Use real data
)
```

### 4. Mock Data Generator (`mock_data.py`)

Generates synthetic OHLCV data for testing without API access.

**Example usage:**
```python
from mock_data import generate_mock_ohlcv

# Generate 1000 candles of mock data
df = generate_mock_ohlcv(n_candles=1000, base_price=50000.0)
```

## Training

To train the PPO agent:

1. **With real data (requires internet):**
   ```python
   from train import train_agent
   
   model = train_agent(
       symbol='BTC/USDT',
       timeframe='1h',
       limit=1000,
       total_timesteps=50000,
       use_mock_data=False
   )
   ```

2. **With mock data (for testing):**
   ```python
   from train import train_agent
   
   model = train_agent(
       symbol='BTC/USDT',
       timeframe='1h',
       limit=1000,
       total_timesteps=10000,
       use_mock_data=True
   )
   ```

The trained model will be saved to `models/ppo_trading_poc.zip`.

## Using a Trained Model

```python
from stable_baselines3 import PPO
from trading_env import TradingEnv
from data_loader import load_data

# Load data
df = load_data(symbol='BTC/USDT', timeframe='1h', limit=500)

# Create environment
env = TradingEnv(df=df, initial_balance=10000.0)

# Load trained model
model = PPO.load('models/ppo_trading_poc.zip')

# Run the agent
obs, info = env.reset()
for _ in range(100):
    action, _states = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    
    if terminated or truncated:
        break
    
print(f"Final net worth: ${info['net_worth']:.2f}")
print(f"Profit: ${info['profit']:.2f} ({info['profit_percent']:.2f}%)")
```

## Configuration

Key parameters you can adjust:

- **Symbol**: Trading pair (e.g., 'BTC/USDT', 'ETH/USDT')
- **Timeframe**: Candlestick interval (e.g., '1m', '5m', '1h', '1d')
- **Initial Balance**: Starting capital in quote currency
- **Commission**: Trading fee percentage (default: 0.001 = 0.1%)
- **Window Size**: Number of historical steps in observation (default: 10)
- **Total Timesteps**: How many steps to train the agent

## Model Output

The trained model is saved as a ZIP file containing:
- Policy network weights
- Value network weights
- Training configuration
- Normalization statistics

## Next Steps

This PoC demonstrates the basic pipeline. Future enhancements could include:

1. **Advanced Features**: Technical indicators (RSI, MACD, Bollinger Bands)
2. **Multiple Assets**: Portfolio management across multiple cryptocurrencies
3. **Risk Management**: Position sizing, stop-loss, take-profit
4. **Backtesting**: Historical performance evaluation
5. **Live Trading**: Integration with exchange APIs for real-time trading
6. **Hyperparameter Tuning**: Optimize agent parameters
7. **Alternative Algorithms**: A2C, DQN, SAC, etc.

## Notes

- This is a PoC and should NOT be used for real trading without extensive testing
- The mock data generator is for testing purposes only
- Always validate strategies on historical data before live deployment
- Consider transaction costs, slippage, and market impact in real scenarios

## License

See project root for license information.
