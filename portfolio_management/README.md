# Portfolio Management Module

This module provides the core financial logic for the RLdC_AiNalyzator trading bot.

## Components

### Transaction (`portfolio_management/transaction.py`)
A dataclass representing a trade transaction with the following attributes:
- `id`: Unique transaction identifier
- `timestamp`: When the transaction occurred
- `symbol`: Trading pair (e.g., 'BTC/USD')
- `side`: 'buy' or 'sell'
- `amount`: Quantity traded
- `price`: Price per unit
- `fee`: Transaction fee
- `total_cost`: Total cost (price * amount + fee for buy, price * amount - fee for sell)

### PortfolioManager (`portfolio_management/portfolio.py`)
Manages cash balance and asset positions.

**Methods:**
- `deposit(amount)`: Add cash to portfolio
- `withdraw(amount)`: Remove cash from portfolio  
- `execute_trade(transaction)`: Execute a buy/sell transaction
- `get_total_value(current_prices)`: Calculate total portfolio value
- `get_portfolio_state()`: Get current holdings and cash

**Exceptions:**
- `InsufficientFundsError`: Raised when buying without enough cash
- `InsufficientHoldingsError`: Raised when selling without enough holdings

### RiskEngine (`portfolio_management/risk_engine.py`)
Validates trades against risk management rules.

**Methods:**
- `set_initial_balance(balance)`: Set starting balance for drawdown tracking
- `check_trade_risk(portfolio, symbol, side, amount, price, current_prices)`: Validate trade against risk rules
- `check_max_drawdown(portfolio, current_prices)`: Check if portfolio drawdown is within limits

**Risk Rules:**
- **Max Position Size**: Rejects buy orders exceeding a configurable percentage of total portfolio value (default 25%)
- **Max Drawdown**: Rejects trades when portfolio has lost more than a configurable percentage from initial balance (default 20%)

## Usage Example

```python
from portfolio_management import Transaction, PortfolioManager, RiskEngine
from datetime import datetime

# Initialize portfolio with $10,000
portfolio = PortfolioManager(initial_cash=10000.0)

# Initialize risk engine
risk_engine = RiskEngine(max_position_size_pct=0.25, max_drawdown_pct=0.20)
risk_engine.set_initial_balance(10000.0)

# Check if trade is allowed
current_prices = {'BTC/USD': 50000.0}
if risk_engine.check_trade_risk(
    portfolio=portfolio,
    symbol='BTC/USD',
    side='buy',
    amount=0.04,
    price=50000.0,
    current_prices=current_prices
):
    # Create and execute transaction
    tx = Transaction(
        id='tx-001',
        timestamp=datetime.now(),
        symbol='BTC/USD',
        side='buy',
        amount=0.04,
        price=50000.0,
        fee=2.0,
        total_cost=2002.0  # 0.04 * 50000 + 2
    )
    portfolio.execute_trade(tx)
    print(f"Trade executed! New state: {portfolio.get_portfolio_state()}")
else:
    print("Trade rejected by risk engine")

# Check portfolio value
total_value = portfolio.get_total_value(current_prices)
print(f"Total portfolio value: ${total_value:.2f}")
```

## Testing

Run the unit tests with:
```bash
python3 -m unittest tests.test_portfolio -v
```

All 26 tests cover:
- Transaction creation
- Deposit/withdrawal operations
- Buy/sell trade execution
- Insufficient funds/holdings handling
- Portfolio value calculation
- Risk validation (position size and drawdown)
