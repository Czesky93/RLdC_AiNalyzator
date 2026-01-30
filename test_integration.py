#!/usr/bin/env python3
"""
Integration test for Telegram Bot Interface.

This script tests all components of the Telegram Bot without requiring
an actual Telegram connection.
"""
import os
import sys
import asyncio

# Set test token
os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token_for_integration'

def test_imports():
    """Test that all modules can be imported."""
    print("=" * 60)
    print("TEST 1: Module Imports")
    print("=" * 60)
    
    try:
        from telegram_bot import config
        print("✓ Config module imported")
        
        from telegram_bot import handlers
        print("✓ Handlers module imported")
        
        from telegram_bot import bot
        print("✓ Bot module imported")
        
        from telegram_bot import notifier
        print("✓ Notifier module imported")
        
        from portfolio_management import portfolio
        print("✓ Portfolio module imported")
        
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_portfolio_manager():
    """Test PortfolioManager functionality."""
    print("\n" + "=" * 60)
    print("TEST 2: Portfolio Manager")
    print("=" * 60)
    
    try:
        from portfolio_management.portfolio import PortfolioManager
        
        # Create portfolio
        pm = PortfolioManager(initial_cash=10000.0)
        print(f"✓ Portfolio created with ${pm.get_cash_balance():,.2f}")
        
        # Test methods
        cash = pm.get_cash_balance()
        assert cash == 10000.0, f"Expected 10000.0, got {cash}"
        print(f"✓ get_cash_balance() returns ${cash:,.2f}")
        
        holdings = pm.get_holdings()
        assert holdings == {}, f"Expected empty dict, got {holdings}"
        print(f"✓ get_holdings() returns {holdings}")
        
        summary = pm.get_portfolio_summary()
        assert 'cash' in summary and 'holdings' in summary
        print(f"✓ get_portfolio_summary() returns complete summary")
        
        return True
    except Exception as e:
        print(f"✗ Portfolio test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_handlers():
    """Test that handlers are properly defined."""
    print("\n" + "=" * 60)
    print("TEST 3: Command Handlers")
    print("=" * 60)
    
    try:
        from telegram_bot.handlers import (
            start_handler, 
            status_handler, 
            portfolio_handler,
            _portfolio
        )
        
        print("✓ start_handler defined")
        print("✓ status_handler defined")
        print("✓ portfolio_handler defined")
        print(f"✓ Shared portfolio instance with ${_portfolio.get_cash_balance():,.2f}")
        
        # Check they are async functions
        import inspect
        assert inspect.iscoroutinefunction(start_handler)
        print("✓ start_handler is async")
        
        assert inspect.iscoroutinefunction(status_handler)
        print("✓ status_handler is async")
        
        assert inspect.iscoroutinefunction(portfolio_handler)
        print("✓ portfolio_handler is async")
        
        return True
    except Exception as e:
        print(f"✗ Handlers test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bot_application():
    """Test bot application creation."""
    print("\n" + "=" * 60)
    print("TEST 4: Bot Application")
    print("=" * 60)
    
    try:
        from telegram_bot.bot import create_application
        
        app = create_application()
        print("✓ Application created successfully")
        
        # Check handlers are registered
        handlers = app.handlers
        if 0 in handlers:
            handler_count = len(handlers[0])
            print(f"✓ {handler_count} command handlers registered")
            assert handler_count == 3, f"Expected 3 handlers, got {handler_count}"
        
        return True
    except Exception as e:
        print(f"✗ Bot application test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_notifier():
    """Test notifier functions."""
    print("\n" + "=" * 60)
    print("TEST 5: Notifier/Alerting System")
    print("=" * 60)
    
    try:
        from telegram_bot.notifier import send_alert, send_bulk_alert
        
        print("✓ send_alert function imported")
        print("✓ send_bulk_alert function imported")
        
        # Check function signatures
        import inspect
        sig = inspect.signature(send_alert)
        params = list(sig.parameters.keys())
        assert 'chat_id' in params and 'message' in params
        print(f"✓ send_alert has correct signature: {params}")
        
        # Check it's async
        assert inspect.iscoroutinefunction(send_alert)
        print("✓ send_alert is async")
        
        assert inspect.iscoroutinefunction(send_bulk_alert)
        print("✓ send_bulk_alert is async")
        
        return True
    except Exception as e:
        print(f"✗ Notifier test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_configuration():
    """Test configuration module."""
    print("\n" + "=" * 60)
    print("TEST 6: Configuration")
    print("=" * 60)
    
    try:
        from telegram_bot import config
        
        # Check token is loaded
        assert hasattr(config, 'TELEGRAM_BOT_TOKEN')
        print("✓ TELEGRAM_BOT_TOKEN is loaded")
        
        token = config.TELEGRAM_BOT_TOKEN
        assert token == 'test_token_for_integration'
        print(f"✓ Token value is correct")
        
        return True
    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all integration tests."""
    print("\n")
    print("*" * 60)
    print("  TELEGRAM BOT INTEGRATION TESTS")
    print("*" * 60)
    print()
    
    tests = [
        test_imports,
        test_portfolio_manager,
        test_handlers,
        test_bot_application,
        test_notifier,
        test_configuration,
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n✗ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
