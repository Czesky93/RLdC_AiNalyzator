"""
Live Quantum Portfolio Optimization Script
Fetches real market data and performs quantum portfolio optimization.
"""

import sys
import numpy as np
from data_service import fetch_market_data, validate_data
from optimizer import QuantumPortfolioOptimizer


def main():
    """
    Main execution function for live quantum portfolio optimization.
    """
    print("=" * 70)
    print("QUANTUM PORTFOLIO OPTIMIZATION - LIVE MARKET DATA")
    print("=" * 70)
    
    # Define assets to optimize
    assets = [
        'BTC/USDT',
        'ETH/USDT', 
        'BNB/USDT',
        'SOL/USDT'
    ]
    
    print(f"\nAssets for optimization: {assets}")
    
    try:
        # Step 1: Fetch real market data
        print("\n" + "=" * 70)
        print("STEP 1: FETCHING REAL MARKET DATA")
        print("=" * 70)
        
        expected_returns, covariance_matrix, symbol_names = fetch_market_data(
            symbols=assets,
            days=90,
            exchange_name='binance'
        )
        
        # Validate data
        validate_data(expected_returns, covariance_matrix)
        
        # Step 2: Perform quantum optimization
        print("\n" + "=" * 70)
        print("STEP 2: QUANTUM PORTFOLIO OPTIMIZATION")
        print("=" * 70)
        
        # Initialize quantum optimizer (using VQE)
        optimizer = QuantumPortfolioOptimizer(algorithm='VQE')
        
        # Optimize portfolio (select up to 2 assets)
        result = optimizer.optimize_portfolio(
            expected_returns=expected_returns,
            covariance_matrix=covariance_matrix,
            budget=2,  # Select up to 2 assets
            risk_factor=0.5  # Moderate risk tolerance
        )
        
        # Step 3: Display results
        print("\n" + "=" * 70)
        print("OPTIMAL QUANTUM ALLOCATION - BASED ON CURRENT MARKET CONDITIONS")
        print("=" * 70)
        
        print("\nAsset Selection:")
        for i, symbol in enumerate(symbol_names):
            status = "✓ SELECTED" if result['selection'][i] == 1 else "✗ Not Selected"
            weight = result['weights'][i]
            ret = expected_returns[i]
            
            print(f"  {symbol:12s} {status:15s} Weight: {weight:6.2%}  "
                  f"Expected Return: {ret:8.4%}")
        
        print("\nPortfolio Metrics:")
        print(f"  Expected Return:  {result['portfolio_return']:8.4%}")
        print(f"  Portfolio Risk:   {result['portfolio_risk']:8.4%}")
        print(f"  Sharpe Ratio:     {result['sharpe_ratio']:8.4f}")
        print(f"  Optimal Value:    {result['optimal_value']:8.4f}")
        
        print("\n" + "=" * 70)
        print("OPTIMIZATION COMPLETE")
        print("=" * 70)
        
        print("\nNOTE: This allocation is based on real historical market data.")
        print("Past performance does not guarantee future results.")
        print("This is for educational and research purposes only.")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
