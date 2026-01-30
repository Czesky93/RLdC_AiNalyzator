#!/usr/bin/env python3
"""
Test script for Telegram Bot components.
Tests keyboards, controls, auth, and service integrations without running the actual bot.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def test_keyboards():
    """Test keyboard creation."""
    print("Testing keyboards...")
    from telegram_bot.keyboards import get_main_menu, get_system_controls_menu, get_back_button
    
    # Test main menu
    main_menu = get_main_menu()
    assert main_menu is not None, "Main menu should not be None"
    assert len(main_menu.inline_keyboard) == 3, "Main menu should have 3 rows"
    print("  ✓ Main menu created successfully")
    
    # Test system controls menu
    controls_menu = get_system_controls_menu(trading_paused=False)
    assert controls_menu is not None, "Controls menu should not be None"
    print("  ✓ System controls menu (trading active) created successfully")
    
    controls_menu_paused = get_system_controls_menu(trading_paused=True)
    assert controls_menu_paused is not None, "Controls menu (paused) should not be None"
    print("  ✓ System controls menu (trading paused) created successfully")
    
    # Test back button
    back_button = get_back_button()
    assert back_button is not None, "Back button should not be None"
    print("  ✓ Back button created successfully")
    
    print("✅ All keyboard tests passed!\n")


def test_controls():
    """Test system controls and state management."""
    print("Testing system controls...")
    from telegram_bot.controls import SystemState, system_state
    
    # Test singleton
    state1 = SystemState()
    state2 = SystemState()
    assert state1 is state2, "SystemState should be a singleton"
    print("  ✓ Singleton pattern working")
    
    # Test trading pause/resume
    system_state.resume_trading()
    assert not system_state.is_trading_paused, "Trading should not be paused"
    print("  ✓ Trading resume working")
    
    system_state.pause_trading()
    assert system_state.is_trading_paused, "Trading should be paused"
    print("  ✓ Trading pause working")
    
    # Test AI restart
    system_state.restart_ai()
    print("  ✓ AI restart working")
    
    # Test status
    status = system_state.get_status()
    assert 'trading' in status, "Status should contain trading"
    assert 'ai' in status, "Status should contain ai"
    print("  ✓ Status retrieval working")
    
    # Reset to default state
    system_state.resume_trading()
    
    print("✅ All control tests passed!\n")


def test_auth():
    """Test authentication decorator."""
    print("Testing authentication...")
    from telegram_bot.auth import restricted
    
    # Test that decorator can be applied
    @restricted
    async def dummy_handler(update, context):
        return "success"
    
    assert callable(dummy_handler), "Decorated function should be callable"
    print("  ✓ Auth decorator can be applied")
    
    print("✅ Auth tests passed!\n")


def test_sentiment_service():
    """Test sentiment analysis service."""
    print("Testing sentiment analysis service...")
    from sentiment_analysis.service import get_sentiment_score
    
    sentiment = get_sentiment_score()
    assert sentiment is not None, "Sentiment should not be None"
    assert 'score' in sentiment, "Sentiment should have score"
    assert 'label' in sentiment, "Sentiment should have label"
    assert 'confidence' in sentiment, "Sentiment should have confidence"
    assert 'description' in sentiment, "Sentiment should have description"
    print(f"  ✓ Sentiment score: {sentiment['score']} ({sentiment['label']})")
    
    print("✅ Sentiment service tests passed!\n")


def test_blog_storage():
    """Test blog storage service."""
    print("Testing blog storage...")
    from blog_generator.storage import get_latest_post
    
    post = get_latest_post()
    assert post is not None, "Post should not be None"
    assert 'title' in post, "Post should have title"
    assert 'summary' in post, "Post should have summary"
    assert 'timestamp' in post, "Post should have timestamp"
    print(f"  ✓ Latest post: {post['title'][:50]}...")
    
    print("✅ Blog storage tests passed!\n")


def test_handlers():
    """Test handlers module can be imported."""
    print("Testing handlers...")
    from telegram_bot import handlers
    
    assert hasattr(handlers, 'start'), "Handlers should have start function"
    assert hasattr(handlers, 'button_handler'), "Handlers should have button_handler function"
    assert hasattr(handlers, 'help_command'), "Handlers should have help_command function"
    print("  ✓ All handler functions exist")
    
    print("✅ Handler tests passed!\n")


def test_bot_module():
    """Test bot module can be imported."""
    print("Testing bot module...")
    from telegram_bot import bot
    
    assert hasattr(bot, 'main'), "Bot should have main function"
    print("  ✓ Bot main function exists")
    
    print("✅ Bot module tests passed!\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("RLdC AI Analyzer Telegram Bot - Component Tests")
    print("=" * 60 + "\n")
    
    try:
        test_keyboards()
        test_controls()
        test_auth()
        test_sentiment_service()
        test_blog_storage()
        test_handlers()
        test_bot_module()
        
        print("=" * 60)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("=" * 60)
        print("\nThe Telegram Bot is ready to use!")
        print("\nNext steps:")
        print("1. Copy .env.example to .env")
        print("2. Add your TELEGRAM_BOT_TOKEN and OWNER_ID")
        print("3. Run: python main.py")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
