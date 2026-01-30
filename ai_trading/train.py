"""
Training Script for AI Trading PoC
Trains a PPO agent on the trading environment
"""

import os
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback
import numpy as np

from data_loader import load_data
from trading_env import TradingEnv


class TradingCallback(BaseCallback):
    """
    Custom callback for monitoring training progress.
    """
    
    def __init__(self, verbose: int = 1):
        super().__init__(verbose)
        self.episode_rewards = []
        self.episode_lengths = []
    
    def _on_step(self) -> bool:
        """
        Called at each step of the environment.
        
        Returns:
            True to continue training
        """
        # Check if episode is done
        if self.locals.get('dones')[0]:
            # Get episode info
            info = self.locals.get('infos')[0]
            
            if self.verbose > 0:
                print(f"\nEpisode finished:")
                print(f"  Net Worth: ${info.get('net_worth', 0):.2f}")
                print(f"  Profit: ${info.get('profit', 0):.2f} ({info.get('profit_percent', 0):.2f}%)")
                print(f"  Total Trades: {info.get('total_trades', 0)}")
        
        return True


def train_agent(
    symbol: str = 'BTC/USDT',
    timeframe: str = '1h',
    limit: int = 1000,
    total_timesteps: int = 10000,
    initial_balance: float = 10000.0,
    model_save_path: str = 'models/ppo_trading_poc.zip',
    verbose: int = 1
):
    """
    Train a PPO agent for cryptocurrency trading.
    
    Args:
        symbol: Trading pair symbol
        timeframe: Candlestick timeframe
        limit: Number of candles to fetch
        total_timesteps: Total training timesteps
        initial_balance: Starting balance for trading
        model_save_path: Path to save the trained model
        verbose: Verbosity level (0=none, 1=info, 2=debug)
    """
    print("="*60)
    print("AI Trading PoC - Training PPO Agent")
    print("="*60)
    
    # Step 1: Load data
    print(f"\n[1/4] Loading data for {symbol} ({timeframe})...")
    try:
        df = load_data(symbol=symbol, timeframe=timeframe, limit=limit)
        print(f"✓ Loaded {len(df)} candles")
        print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(f"  Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    except Exception as e:
        print(f"✗ Error loading data: {str(e)}")
        raise
    
    # Step 2: Initialize environment
    print(f"\n[2/4] Initializing trading environment...")
    try:
        env = TradingEnv(df=df, initial_balance=initial_balance)
        # Wrap in DummyVecEnv for stable-baselines3
        env = DummyVecEnv([lambda: env])
        print(f"✓ Environment created")
        print(f"  Action space: {env.envs[0].action_space}")
        print(f"  Observation space: {env.envs[0].observation_space.shape}")
        print(f"  Initial balance: ${initial_balance:.2f}")
    except Exception as e:
        print(f"✗ Error initializing environment: {str(e)}")
        raise
    
    # Step 3: Initialize PPO agent
    print(f"\n[3/4] Initializing PPO agent...")
    try:
        model = PPO(
            "MlpPolicy",
            env,
            verbose=verbose,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            tensorboard_log="./tensorboard_logs/"
        )
        print(f"✓ PPO agent initialized")
        print(f"  Policy: MlpPolicy")
        print(f"  Learning rate: 3e-4")
    except Exception as e:
        print(f"✗ Error initializing agent: {str(e)}")
        raise
    
    # Step 4: Train the agent
    print(f"\n[4/4] Training agent for {total_timesteps} timesteps...")
    print("-" * 60)
    try:
        callback = TradingCallback(verbose=verbose)
        model.learn(
            total_timesteps=total_timesteps,
            callback=callback,
            progress_bar=True
        )
        print("-" * 60)
        print(f"✓ Training completed!")
    except Exception as e:
        print(f"✗ Error during training: {str(e)}")
        raise
    
    # Step 5: Save the model
    print(f"\nSaving model to {model_save_path}...")
    try:
        # Create models directory if it doesn't exist
        os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
        model.save(model_save_path)
        print(f"✓ Model saved successfully!")
    except Exception as e:
        print(f"✗ Error saving model: {str(e)}")
        raise
    
    # Summary
    print("\n" + "="*60)
    print("Training Summary")
    print("="*60)
    print(f"Symbol: {symbol}")
    print(f"Timeframe: {timeframe}")
    print(f"Data points: {len(df)}")
    print(f"Total timesteps: {total_timesteps}")
    print(f"Model saved: {model_save_path}")
    print("="*60)
    
    return model


if __name__ == "__main__":
    # Train with default parameters
    # Note: For a real PoC, you might want to use more timesteps (e.g., 50000-100000)
    # Using 10000 here for quick testing
    train_agent(
        symbol='BTC/USDT',
        timeframe='1h',
        limit=1000,
        total_timesteps=10000,
        initial_balance=10000.0,
        model_save_path='models/ppo_trading_poc.zip',
        verbose=1
    )
