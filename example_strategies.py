"""
Example trading strategies for the backtesting framework.

This module contains ready-to-use strategy implementations that can be
tested with the backtesting framework.
"""


def sma_crossover(short_window=10, long_window=30):
    """
    Simple Moving Average Crossover Strategy.
    
    Generates BUY signal when short-term SMA crosses above long-term SMA.
    Generates SELL signal when short-term SMA crosses below long-term SMA.
    
    Args:
        short_window: Period for short-term SMA (default: 10)
        long_window: Period for long-term SMA (default: 30)
        
    Returns:
        Strategy function compatible with Backtester
    """
    sma_short = []
    sma_long = []
    prices = []
    
    def strategy_logic(row):
        prices.append(row['close'])
        
        # Wait until we have enough data
        if len(prices) >= long_window:
            short_sma_val = sum(prices[-short_window:]) / short_window
            long_sma_val = sum(prices[-long_window:]) / long_window
            sma_short.append(short_sma_val)
            sma_long.append(long_sma_val)
            
            # Generate signals based on crossover
            if len(sma_short) >= 2:
                # Bullish crossover: short SMA crosses above long SMA
                if sma_short[-2] <= sma_long[-2] and sma_short[-1] > sma_long[-1]:
                    return 'BUY'
                # Bearish crossover: short SMA crosses below long SMA
                elif sma_short[-2] >= sma_long[-2] and sma_short[-1] < sma_long[-1]:
                    return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic


def rsi_strategy(period=14, oversold=30, overbought=70):
    """
    RSI (Relative Strength Index) Strategy.
    
    Generates BUY signal when RSI falls below oversold threshold.
    Generates SELL signal when RSI rises above overbought threshold.
    
    Args:
        period: RSI calculation period (default: 14)
        oversold: Oversold threshold (default: 30)
        overbought: Overbought threshold (default: 70)
        
    Returns:
        Strategy function compatible with Backtester
    """
    prices = []
    
    def calculate_rsi(prices, period):
        """Calculate RSI value."""
        if len(prices) < period + 1:
            return 50  # Neutral RSI
        
        # Calculate price changes
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Separate gains and losses
        gains = [max(c, 0) for c in changes[-period:]]
        losses = [abs(min(c, 0)) for c in changes[-period:]]
        
        # Calculate average gain and loss
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def strategy_logic(row):
        prices.append(row['close'])
        
        if len(prices) < period + 1:
            return 'HOLD'
        
        rsi = calculate_rsi(prices, period)
        
        # Generate signals based on RSI thresholds
        if rsi < oversold:
            return 'BUY'
        elif rsi > overbought:
            return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic


def momentum_strategy(lookback=20, threshold=0.02):
    """
    Simple Momentum Strategy.
    
    Buys when price is significantly above the lookback average.
    Sells when price is significantly below the lookback average.
    
    Args:
        lookback: Number of periods to calculate average (default: 20)
        threshold: Percentage threshold for signals (default: 0.02 = 2%)
        
    Returns:
        Strategy function compatible with Backtester
    """
    prices = []
    
    def strategy_logic(row):
        prices.append(row['close'])
        
        if len(prices) < lookback:
            return 'HOLD'
        
        # Calculate average price over lookback period
        avg_price = sum(prices[-lookback:]) / lookback
        current_price = row['close']
        
        # Calculate price momentum
        momentum = (current_price - avg_price) / avg_price
        
        # Generate signals based on momentum
        if momentum > threshold:
            return 'BUY'
        elif momentum < -threshold:
            return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic


def breakout_strategy(lookback=20, breakout_threshold=1.02):
    """
    Breakout Strategy.
    
    Buys when price breaks above recent high.
    Sells when price breaks below recent low.
    
    Args:
        lookback: Number of periods for high/low calculation (default: 20)
        breakout_threshold: Multiplier for breakout detection (default: 1.02 = 2%)
        
    Returns:
        Strategy function compatible with Backtester
    """
    highs = []
    lows = []
    
    def strategy_logic(row):
        current_high = row['high']
        current_low = row['low']
        current_price = row['close']
        
        # Calculate recent high and low (excluding current candle)
        if len(highs) >= lookback:
            recent_high = max(highs[-lookback:])
            recent_low = min(lows[-lookback:])
            
            # Generate signals based on breakouts
            if current_price > recent_high * breakout_threshold:
                highs.append(current_high)
                lows.append(current_low)
                return 'BUY'
            elif current_price < recent_low / breakout_threshold:
                highs.append(current_high)
                lows.append(current_low)
                return 'SELL'
        
        # Store current values for next iteration
        highs.append(current_high)
        lows.append(current_low)
        
        return 'HOLD'
    
    return strategy_logic


def mean_reversion_strategy(lookback=20, num_std=2.0):
    """
    Mean Reversion Strategy using Bollinger Bands logic.
    
    Buys when price is significantly below the mean (oversold).
    Sells when price is significantly above the mean (overbought).
    
    Args:
        lookback: Number of periods for mean calculation (default: 20)
        num_std: Number of standard deviations for bands (default: 2.0)
        
    Returns:
        Strategy function compatible with Backtester
    """
    prices = []
    
    def strategy_logic(row):
        prices.append(row['close'])
        
        if len(prices) < lookback:
            return 'HOLD'
        
        # Calculate mean and standard deviation
        recent_prices = prices[-lookback:]
        mean = sum(recent_prices) / lookback
        variance = sum((p - mean) ** 2 for p in recent_prices) / lookback
        std = variance ** 0.5
        
        current_price = row['close']
        
        # Generate signals based on deviation from mean
        upper_band = mean + (num_std * std)
        lower_band = mean - (num_std * std)
        
        if current_price < lower_band:
            return 'BUY'  # Oversold, expect reversion up
        elif current_price > upper_band:
            return 'SELL'  # Overbought, expect reversion down
        
        return 'HOLD'
    
    return strategy_logic


# Example: Buy and Hold Strategy
def buy_and_hold():
    """
    Simple Buy and Hold Strategy.
    
    Buys on the first candle and holds until the end.
    Useful as a baseline for comparing other strategies.
    
    Returns:
        Strategy function compatible with Backtester
    """
    has_bought = False
    
    def strategy_logic(row):
        nonlocal has_bought
        
        if not has_bought:
            has_bought = True
            return 'BUY'
        
        return 'HOLD'
    
    return strategy_logic
