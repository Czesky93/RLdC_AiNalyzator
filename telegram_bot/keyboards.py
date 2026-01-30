"""
Interactive Keyboards module for Telegram Bot.
Provides inline keyboard layouts for bot menus.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu():
    """
    Create the main menu inline keyboard.
    
    Returns:
        InlineKeyboardMarkup: Main menu with Portfolio, Status, Sentiment, 
                              Latest Analysis, and System Controls buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton("📊 Portfolio", callback_data="menu_portfolio"),
            InlineKeyboardButton("📈 Status", callback_data="menu_status")
        ],
        [
            InlineKeyboardButton("🧠 Sentiment", callback_data="menu_sentiment"),
            InlineKeyboardButton("📰 Latest Analysis", callback_data="menu_latest_analysis")
        ],
        [
            InlineKeyboardButton("⚙️ System Controls", callback_data="menu_system_controls")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_system_controls_menu(trading_paused=False):
    """
    Create the system controls submenu.
    
    Args:
        trading_paused (bool): Whether trading is currently paused.
    
    Returns:
        InlineKeyboardMarkup: Control panel with trading and AI controls.
    """
    # Toggle button text based on current state
    if trading_paused:
        trading_button = InlineKeyboardButton("🟢 Start Trading", callback_data="control_start_trading")
    else:
        trading_button = InlineKeyboardButton("🔴 Stop Trading", callback_data="control_stop_trading")
    
    keyboard = [
        [trading_button],
        [InlineKeyboardButton("🔄 Restart AI", callback_data="control_restart_ai")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_button():
    """
    Create a simple back button to return to main menu.
    
    Returns:
        InlineKeyboardMarkup: Single back button.
    """
    keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="menu_main")]]
    return InlineKeyboardMarkup(keyboard)
