"""Transaction model for portfolio management."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class Transaction:
    """
    Represents a trade transaction.
    
    Attributes:
        id: Unique identifier for the transaction
        timestamp: When the transaction occurred
        symbol: Trading pair symbol (e.g., 'BTC/USD')
        side: 'buy' or 'sell'
        amount: Quantity of the asset traded
        price: Price per unit of the asset
        fee: Transaction fee
        total_cost: Total cost of the transaction (price * amount + fee for buy, price * amount - fee for sell)
    """
    id: str
    timestamp: datetime
    symbol: str
    side: Literal['buy', 'sell']
    amount: float
    price: float
    fee: float
    total_cost: float
