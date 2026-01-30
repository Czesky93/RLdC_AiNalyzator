"""
Trading Environment for Reinforcement Learning
Custom Gymnasium environment for cryptocurrency trading
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any, Optional


class TradingEnv(gym.Env):
    """
    Custom Trading Environment that follows gym interface.
    
    This environment simulates cryptocurrency trading with:
    - Actions: Hold (0), Buy (1), Sell (2)
    - Observations: Market data + account state
    - Rewards: Based on change in net worth
    """
    
    metadata = {'render_modes': ['human']}
    
    def __init__(
        self,
        df: pd.DataFrame,
        initial_balance: float = 10000.0,
        commission: float = 0.001,
        window_size: int = 10
    ):
        """
        Initialize the trading environment.
        
        Args:
            df: DataFrame with OHLCV data (columns: timestamp, open, high, low, close, volume)
            initial_balance: Starting balance in quote currency (default: 10000)
            commission: Trading commission rate (default: 0.001 = 0.1%)
            window_size: Number of historical steps to include in observation (default: 10)
        """
        super().__init__()
        
        self.df = df.reset_index(drop=True)
        self.initial_balance = initial_balance
        self.commission = commission
        self.window_size = window_size
        
        # Validate data
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in self.df.columns for col in required_columns):
            raise ValueError(f"DataFrame must contain columns: {required_columns}")
        
        # Validate sufficient data for window size
        if len(self.df) <= window_size:
            raise ValueError(f"DataFrame must have more than {window_size} rows (has {len(self.df)})")
        
        # Action space: 0 = Hold, 1 = Buy, 2 = Sell
        self.action_space = spaces.Discrete(3)
        
        # Observation space: [price_features (5 * window_size) + account_state (3)]
        # Price features: normalized OHLCV for last window_size steps
        # Account state: balance (normalized), position (normalized), net_worth (normalized)
        obs_size = 5 * window_size + 3
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_size,),
            dtype=np.float32
        )
        
        # Episode state
        self.current_step = 0
        self.balance = 0.0
        self.position = 0.0  # Amount of base currency held
        self.net_worth = 0.0
        self.trades = []
        self.max_net_worth = 0.0
        
    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Reset the environment to initial state.
        
        Args:
            seed: Random seed for reproducibility
            options: Additional options (unused)
            
        Returns:
            observation: Initial observation
            info: Additional information dictionary
        """
        super().reset(seed=seed)
        
        # Reset to initial state
        self.current_step = self.window_size
        self.balance = self.initial_balance
        self.position = 0.0
        self.net_worth = self.initial_balance
        self.max_net_worth = self.initial_balance
        self.trades = []
        
        return self._get_observation(), self._get_info()
    
    def step(
        self,
        action: int
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Execute one step in the environment.
        
        Args:
            action: Action to take (0=Hold, 1=Buy, 2=Sell)
            
        Returns:
            observation: Current observation
            reward: Reward for this step
            terminated: Whether episode is done (end of data)
            truncated: Whether episode was truncated (not used here)
            info: Additional information
        """
        current_price = self.df.loc[self.current_step, 'close']
        prev_net_worth = self.net_worth
        
        # Execute action
        if action == 1:  # Buy
            self._execute_buy(current_price)
        elif action == 2:  # Sell
            self._execute_sell(current_price)
        # action == 0 (Hold) does nothing
        
        # Update net worth
        self.net_worth = self.balance + (self.position * current_price)
        
        # Track maximum net worth
        if self.net_worth > self.max_net_worth:
            self.max_net_worth = self.net_worth
        
        # Calculate reward (percentage change in net worth)
        # Add small epsilon to prevent division by zero
        epsilon = 1e-10
        reward = (self.net_worth - prev_net_worth) / (prev_net_worth + epsilon)
        
        # Move to next step
        self.current_step += 1
        
        # Check if episode is done
        terminated = self.current_step >= len(self.df) - 1
        truncated = False
        
        return (
            self._get_observation(),
            reward,
            terminated,
            truncated,
            self._get_info()
        )
    
    def _execute_buy(self, price: float):
        """Execute a buy order."""
        if self.balance > 0:
            # Buy as much as possible with current balance
            max_buyable = self.balance / (price * (1 + self.commission))
            self.position += max_buyable
            self.balance = 0.0
            
            self.trades.append({
                'step': self.current_step,
                'type': 'buy',
                'price': price,
                'amount': max_buyable
            })
    
    def _execute_sell(self, price: float):
        """Execute a sell order."""
        if self.position > 0:
            # Sell all position
            sell_value = self.position * price * (1 - self.commission)
            self.balance += sell_value
            
            self.trades.append({
                'step': self.current_step,
                'type': 'sell',
                'price': price,
                'amount': self.position
            })
            
            self.position = 0.0
    
    def _get_observation(self) -> np.ndarray:
        """
        Get current observation.
        
        Returns:
            Normalized observation array
        """
        # Get market data window
        start_idx = self.current_step - self.window_size
        end_idx = self.current_step
        
        window_data = self.df.iloc[start_idx:end_idx][
            ['open', 'high', 'low', 'close', 'volume']
        ].values
        
        # Normalize market data (percentage change from first value)
        if window_data[0, 3] != 0:  # close price at start of window
            normalized_prices = window_data[:, :4] / window_data[0, 3]
        else:
            normalized_prices = window_data[:, :4]
        
        # Normalize volume (scale to 0-1 range using max in window)
        max_volume = window_data[:, 4].max()
        if max_volume > 0:
            normalized_volume = window_data[:, 4:5] / max_volume
        else:
            normalized_volume = window_data[:, 4:5]
        
        normalized_window = np.hstack([normalized_prices, normalized_volume])
        
        # Flatten market data
        market_features = normalized_window.flatten()
        
        # Account state features (normalized by initial balance)
        account_features = np.array([
            self.balance / self.initial_balance,
            self.position * self.df.loc[self.current_step, 'close'] / self.initial_balance,
            self.net_worth / self.initial_balance
        ], dtype=np.float32)
        
        # Combine features
        observation = np.concatenate([market_features, account_features]).astype(np.float32)
        
        return observation
    
    def _get_info(self) -> Dict[str, Any]:
        """
        Get additional information about current state.
        
        Returns:
            Dictionary with current state information
        """
        return {
            'step': self.current_step,
            'balance': self.balance,
            'position': self.position,
            'net_worth': self.net_worth,
            'total_trades': len(self.trades),
            'profit': self.net_worth - self.initial_balance,
            'profit_percent': ((self.net_worth / self.initial_balance) - 1) * 100
        }
    
    def render(self):
        """
        Render the environment state.
        """
        info = self._get_info()
        print(f"Step: {info['step']}, "
              f"Balance: ${info['balance']:.2f}, "
              f"Position: {info['position']:.6f}, "
              f"Net Worth: ${info['net_worth']:.2f}, "
              f"Profit: ${info['profit']:.2f} ({info['profit_percent']:.2f}%)")
