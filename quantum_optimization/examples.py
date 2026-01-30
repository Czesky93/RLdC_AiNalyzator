"""
Example: Custom Portfolio Optimization
Demonstrates how to use the quantum optimizer with custom assets and parameters.
"""

from data_service import fetch_market_data, validate_data
from optimizer import QuantumPortfolioOptimizer


def example_custom_assets():
    """
    Example: Optimize a custom portfolio with different assets.
    """
    print("=" * 70)
    print("EXAMPLE: Custom Asset Portfolio Optimization")
    print("=" * 70)
    
    # Define custom assets
    assets = [
        'BTC/USDT',
        'ETH/USDT',
        'ADA/USDT',
        'DOT/USDT',
        'SOL/USDT'
    ]
    
    print(f"\nOptimizing portfolio with {len(assets)} assets:")
    for asset in assets:
        print(f"  • {asset}")
    
    # Fetch market data
    expected_returns, covariance_matrix, symbol_names = fetch_market_data(
        symbols=assets,
        days=60,  # Use 60 days of data
        exchange_name='binance',
        use_demo_on_fail=True
    )
    
    validate_data(expected_returns, covariance_matrix)
    
    # Initialize optimizer with QAOA instead of VQE
    optimizer = QuantumPortfolioOptimizer(algorithm='QAOA')
    
    # Optimize - select up to 3 assets
    result = optimizer.optimize_portfolio(
        expected_returns=expected_returns,
        covariance_matrix=covariance_matrix,
        budget=3,  # Select up to 3 assets
        risk_factor=0.3  # Lower risk tolerance (more conservative)
    )
    
    # Display results
    print("\n" + "=" * 70)
    print("OPTIMIZATION RESULTS")
    print("=" * 70)
    
    print(f"\nSelected {sum(result['selection'])}/{len(assets)} assets:")
    for i, symbol in enumerate(symbol_names):
        if result['selection'][i] == 1:
            print(f"  ✓ {symbol:12s}  Weight: {result['weights'][i]:6.2%}  "
                  f"Return: {expected_returns[i]:7.3%}")
    
    print(f"\nPortfolio Performance:")
    print(f"  Expected Return: {result['portfolio_return']:7.3%}")
    print(f"  Risk (Std Dev):  {result['portfolio_risk']:7.3%}")
    print(f"  Sharpe Ratio:    {result['sharpe_ratio']:7.3f}")


def example_different_risk_levels():
    """
    Example: Compare portfolios with different risk tolerances.
    """
    print("\n\n" + "=" * 70)
    print("EXAMPLE: Comparing Different Risk Levels")
    print("=" * 70)
    
    assets = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']
    
    # Fetch data once
    expected_returns, covariance_matrix, symbol_names = fetch_market_data(
        symbols=assets,
        days=90,
        exchange_name='binance',
        use_demo_on_fail=True
    )
    
    # Test different risk factors
    risk_factors = [0.1, 0.5, 0.9]
    risk_names = ["Conservative", "Moderate", "Aggressive"]
    
    optimizer = QuantumPortfolioOptimizer(algorithm='VQE')
    
    for risk_factor, name in zip(risk_factors, risk_names):
        print(f"\n{name} Portfolio (risk_factor={risk_factor}):")
        
        result = optimizer.optimize_portfolio(
            expected_returns=expected_returns,
            covariance_matrix=covariance_matrix,
            budget=2,
            risk_factor=risk_factor
        )
        
        selected = [symbol_names[i] for i in range(len(assets)) 
                   if result['selection'][i] == 1]
        print(f"  Selected: {', '.join(selected)}")
        print(f"  Return: {result['portfolio_return']:6.3%}  "
              f"Risk: {result['portfolio_risk']:6.3%}  "
              f"Sharpe: {result['sharpe_ratio']:6.3f}")


if __name__ == "__main__":
    # Run examples
    example_custom_assets()
    example_different_risk_levels()
    
    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70)
