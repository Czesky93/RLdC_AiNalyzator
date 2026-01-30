#!/usr/bin/env python3
"""
Demo script for the Decision Engine module.
Shows how to use the BotKernel with simulated data.
"""

import random
from decision_engine import BotKernel, SignalAggregator, PaperTrader, TradeSignal
from decision_engine.aggregator import Action


def demo_basic_signal_aggregation():
    """Demo: Basic signal aggregation."""
    print("=" * 80)
    print("DEMO 1: Basic Signal Aggregation")
    print("=" * 80)
    
    aggregator = SignalAggregator()
    
    # Test various scenarios
    scenarios = [
        (0.8, 0.7, 0.9, "Strong Bullish"),
        (-0.8, -0.7, -0.9, "Strong Bearish"),
        (0.2, -0.1, 0.0, "Neutral"),
        (-0.9, 0.5, 0.5, "Veto: Negative Sentiment"),
        (0.85, 0.0, 0.7, "Veto: Positive Sentiment + AI Agreement"),
    ]
    
    for sentiment, quantum, ai, description in scenarios:
        signal = aggregator.aggregate_signals(sentiment, quantum, ai)
        print(f"\n{description}:")
        print(f"  Inputs: Sentiment={sentiment:.2f}, Quantum={quantum:.2f}, AI={ai:.2f}")
        print(f"  Signal: {signal.action.value} (Confidence: {signal.confidence:.2f})")
        print(f"  Reason: {signal.reason}")
    print()


def demo_paper_trading():
    """Demo: Paper trading with simulated trades."""
    print("=" * 80)
    print("DEMO 2: Paper Trading Simulation")
    print("=" * 80)
    
    trader = PaperTrader(virtual_balance=10000.0)
    
    # Simulate a trading sequence
    trades = [
        (Action.BUY, 100.0, "Buy at $100"),
        (Action.HOLD, 105.0, "Hold at $105"),
        (Action.SELL, 120.0, "Sell at $120 (profit!)"),
        (Action.BUY, 115.0, "Buy again at $115"),
        (Action.SELL, 110.0, "Sell at $110 (loss)"),
    ]
    
    for action, price, description in trades:
        signal = TradeSignal(action=action, confidence=0.8, reason=description)
        trade = trader.execute_order(signal, price)
        
        print(f"\n{description}")
        print(f"  Action: {action.value}")
        print(f"  Price: ${price:.2f}")
        if trade:
            print(f"  Executed: {trade.amount:.6f} units")
            print(f"  Fee: ${trade.fee:.2f}")
        print(f"  Balance: ${trader.balance:.2f}")
        print(f"  Holdings: {trader.holdings:.6f} units")
        print(f"  Portfolio Value: ${trader.get_portfolio_value(price):.2f}")
    
    # Final summary
    pl = trader.get_profit_loss(110.0)
    summary = trader.get_trade_summary()
    
    print("\n" + "-" * 80)
    print("Final Summary:")
    print(f"  Total Trades: {summary['total_trades']}")
    print(f"  Buys: {summary['buy_count']}, Sells: {summary['sell_count']}, Holds: {summary['hold_count']}")
    print(f"  Total Fees: ${summary['total_fees']:.2f}")
    print(f"  Profit/Loss: ${pl['absolute']:.2f} ({pl['percentage']:.2f}%)")
    print()


def demo_bot_kernel():
    """Demo: Full bot kernel with simulated market."""
    print("=" * 80)
    print("DEMO 3: BotKernel Full Trading Cycle")
    print("=" * 80)
    
    # Simulated market data
    market_step = {'count': 0}
    
    def simulate_sentiment():
        """Simulate sentiment that changes over time."""
        market_step['count'] += 1
        if market_step['count'] <= 3:
            return 0.7  # Bullish phase
        elif market_step['count'] <= 6:
            return -0.2  # Cooling down
        else:
            return -0.7  # Bearish phase
    
    def simulate_quantum():
        """Simulate quantum indicators."""
        return random.uniform(-0.5, 0.5)
    
    def simulate_ai():
        """Simulate AI predictions."""
        if market_step['count'] <= 3:
            return 0.8
        elif market_step['count'] <= 6:
            return 0.1
        else:
            return -0.8
    
    def simulate_price():
        """Simulate price movement."""
        base_price = 100.0
        if market_step['count'] <= 3:
            return base_price + (market_step['count'] * 5)  # Rising
        elif market_step['count'] <= 6:
            return 115.0  # Plateau
        else:
            return 115.0 - ((market_step['count'] - 6) * 3)  # Falling
    
    # Initialize bot
    bot = BotKernel(
        sentiment_fetcher=simulate_sentiment,
        quantum_fetcher=simulate_quantum,
        ai_predictor=simulate_ai,
        price_fetcher=simulate_price,
        virtual_balance=10000.0,
        trade_percentage=0.8  # Use 80% of available funds per trade
    )
    
    # Run simulation for 10 steps
    print("\nRunning 10-step simulation...\n")
    
    for i in range(10):
        result = bot.step()
        
        print(f"Step {result['step']}:")
        print(f"  Price: ${result['price']:.2f}")
        print(f"  Signals: S={result['sentiment']:.2f}, Q={result['quantum']:.2f}, AI={result['ai']:.2f}")
        print(f"  Decision: {result['signal'].action.value} (confidence: {result['signal'].confidence:.2f})")
        if result['trade']:
            print(f"  Trade: {result['trade'].action.value} {result['trade'].amount:.6f} units")
        print(f"  Portfolio: ${result['portfolio_value']:.2f} (P/L: ${result['profit_loss']['absolute']:.2f})")
        print()
    
    # Final status
    status = bot.get_status()
    print("-" * 80)
    print("Final Bot Status:")
    print(f"  Total Steps: {status['step_count']}")
    print(f"  Portfolio Value: ${status['portfolio_value']:.2f}")
    print(f"  Profit/Loss: ${status['profit_loss']['absolute']:.2f} ({status['profit_loss']['percentage']:.2f}%)")
    
    summary = status['trade_summary']
    print(f"  Trade Summary:")
    print(f"    Total: {summary['total_trades']}")
    print(f"    Buys: {summary['buy_count']}, Sells: {summary['sell_count']}, Holds: {summary['hold_count']}")
    print(f"    Fees Paid: ${summary['total_fees']:.2f}")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("Decision Engine Demo")
    print("=" * 80)
    print()
    
    demo_basic_signal_aggregation()
    demo_paper_trading()
    demo_bot_kernel()
    
    print("=" * 80)
    print("Demo Complete!")
    print("=" * 80)
