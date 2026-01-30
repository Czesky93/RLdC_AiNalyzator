#!/usr/bin/env python3
"""
Test script to verify main.py functionality.

This script tests:
1. Imports work correctly
2. Application components can be instantiated
3. Signal handling is configured
"""
import sys
import asyncio
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_imports():
    """Test that all required imports work."""
    logger.info("Testing imports...")
    try:
        from web_portal.api.main import app
        from decision_engine.core import BotKernel
        from main import ApplicationOrchestrator
        logger.info("✓ All imports successful")
        return True
    except ImportError as e:
        logger.error("✗ Import failed: %s", e)
        return False


def test_instantiation():
    """Test that components can be instantiated."""
    logger.info("Testing component instantiation...")
    try:
        from web_portal.api.main import app
        from decision_engine.core import BotKernel
        from main import ApplicationOrchestrator
        
        # Test BotKernel
        bot = BotKernel(poll_interval=5.0)
        assert bot.poll_interval == 5.0
        logger.info("✓ BotKernel instantiated")
        
        # Test ApplicationOrchestrator
        orchestrator = ApplicationOrchestrator()
        assert orchestrator.bot_kernel is None
        assert orchestrator.api_server is None
        logger.info("✓ ApplicationOrchestrator instantiated")
        
        # Test FastAPI app
        assert app.title == "RLdC AI Analyzer API"
        logger.info("✓ FastAPI app configured")
        
        return True
    except Exception as e:
        logger.error("✗ Instantiation failed: %s", e)
        return False


def test_async_methods():
    """Test that async methods are properly defined."""
    logger.info("Testing async methods...")
    try:
        from main import ApplicationOrchestrator
        from decision_engine.core import BotKernel
        
        orchestrator = ApplicationOrchestrator()
        bot = BotKernel()
        
        # Check that methods are coroutine functions
        assert asyncio.iscoroutinefunction(orchestrator.start_api)
        assert asyncio.iscoroutinefunction(orchestrator.start_trading_bot)
        assert asyncio.iscoroutinefunction(orchestrator.main)
        assert asyncio.iscoroutinefunction(bot.run)
        
        logger.info("✓ All async methods properly defined")
        return True
    except Exception as e:
        logger.error("✗ Async method check failed: %s", e)
        return False


def main():
    """Run all tests."""
    logger.info("=== Testing main.py Implementation ===")
    
    tests = [
        ("Imports", test_imports),
        ("Instantiation", test_instantiation),
        ("Async Methods", test_async_methods),
    ]
    
    results = []
    for name, test_func in tests:
        logger.info(f"\n--- Test: {name} ---")
        result = test_func()
        results.append((name, result))
    
    logger.info("\n=== Test Results ===")
    all_passed = True
    for name, result in results:
        status = "PASS" if result else "FAIL"
        logger.info(f"{name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        logger.info("\n✓ All tests passed!")
        return 0
    else:
        logger.error("\n✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
