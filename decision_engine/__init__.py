"""
Decision Engine Module
Aggregates signals from various sources and executes trades in paper trading mode.
"""

from .aggregator import SignalAggregator, TradeSignal
from .paper_trader import PaperTrader
from .core import BotKernel

__all__ = [
    'SignalAggregator',
    'TradeSignal',
    'PaperTrader',
    'BotKernel',
]
