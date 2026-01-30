# Telegram Bot Usage Guide

## Overview

The RLdC AI Analyzer Telegram Bot provides an interactive command center for managing your AI-powered trading platform. This guide demonstrates how to use all features of the bot.

## Getting Started

### 1. Initial Setup

After following the setup instructions in the main README:

1. Start the bot:
```bash
python main.py
```

2. Open Telegram and find your bot
3. Send `/start` to initialize the command center

### 2. Main Menu

When you send `/start`, you'll see the main menu with these options:

```
🤖 Welcome to RLdC AI Analyzer Command Center

Your interactive control panel for trading and analysis.
Select an option from the menu below:

[📊 Portfolio] [📈 Status]
[🧠 Sentiment] [📰 Latest Analysis]
[⚙️ System Controls]
```

## Features in Detail

### 📊 Portfolio

View your current portfolio holdings and performance.

**Example Output:**
```
📊 Portfolio Overview

💰 Total Value: $125,450.00
📈 24h Change: +$2,340.50 (+1.90%)

Top Holdings:
• BTC: $45,000 (35.8%)
• ETH: $32,000 (25.5%)
• SOL: $18,500 (14.7%)

[⬅️ Back to Main Menu]
```

### 📈 Status

Check the current status of your trading and AI systems.

**Example Output:**
```
📈 System Status

🔄 Trading: ACTIVE
🧠 AI System: RUNNING

All systems operational.

[⬅️ Back to Main Menu]
```

### 🧠 Sentiment

Get real-time market sentiment analysis based on AI analysis of news, social media, and market data.

**Example Output:**
```
🧠 Market Sentiment Analysis

📊 Score: 0.65 (Bullish)
📈 Confidence: 78%
[███████░░░]

💡 Market sentiment is moderately positive based on recent 
news and social media analysis.

[⬅️ Back to Main Menu]
```

The sentiment score ranges from 0 (extremely bearish) to 1 (extremely bullish).

### 📰 Latest Analysis

Read the most recent AI-generated market analysis.

**Example Output:**
```
📰 Latest Analysis

Daily Market Analysis: Crypto Trends for January 30, 2026

Today's analysis shows strong momentum in major 
cryptocurrencies. Bitcoin maintains support above $95K 
while Ethereum shows bullish patterns. Key altcoins 
demonstrate increased volume and positive sentiment 
indicators.

🕐 Published: 2026-01-30
🔗 Read full article

[⬅️ Back to Main Menu]
```

### ⚙️ System Controls

Access the control panel for managing trading and AI operations.

**Control Panel Menu:**
```
⚙️ System Controls

Manage trading and AI system settings.
Current trading status: ACTIVE

[🔴 Stop Trading]
[🔄 Restart AI]
[⬅️ Back to Main Menu]
```

#### Stop/Start Trading

Toggle trading operations on or off. When stopped, the system maintains existing positions but won't execute new trades.

**Stopping Trading:**
```
⏸️ Trading Paused

🔴 Trading operations are now paused.
Existing positions will be maintained, but no new trades 
will be executed.

[🟢 Start Trading]
[🔄 Restart AI]
[⬅️ Back to Main Menu]
```

**Starting Trading:**
```
✅ Trading Resumed

🟢 Trading operations are now active.
The system will execute trades based on AI signals.

[🔴 Stop Trading]
[🔄 Restart AI]
[⬅️ Back to Main Menu]
```

#### Restart AI

Restart the AI analysis system to reload configuration and models.

**Output:**
```
🔄 AI System Restarted

✅ The AI analysis system has been successfully restarted.
All models and services are now running with the latest 
configuration.

[🟢 Start Trading] (or [🔴 Stop Trading])
[🔄 Restart AI]
[⬅️ Back to Main Menu]
```

## Command Reference

| Command | Description |
|---------|-------------|
| `/start` | Show the main command center menu |
| `/help` | Display help information |

All interactions after `/start` are done through the interactive button menus.

## Security

### Owner-Only Access

The bot is restricted to the owner (configured via `OWNER_ID` in `.env`). Any other user attempting to use the bot will receive:

```
⛔ Access denied. This bot is restricted to the owner only.
```

### Finding Your User ID

To get your Telegram User ID:
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your user ID
3. Add this ID to your `.env` file as `OWNER_ID`

## Integration with Other Modules

### Checking Trading Status in Your Code

Other modules can check if trading is paused:

```python
from telegram_bot.controls import system_state

if not system_state.is_trading_paused:
    # Execute trading logic
    execute_trade()
else:
    # Skip trading
    pass
```

### Extending the Bot

#### Adding a New Menu Option

1. **Add button to keyboard** (`telegram_bot/keyboards.py`):
```python
def get_main_menu():
    keyboard = [
        # ... existing buttons ...
        [
            InlineKeyboardButton("🆕 New Feature", callback_data="menu_new_feature")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
```

2. **Add handler** (`telegram_bot/handlers.py`):
```python
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... existing code ...
    elif callback_data == "menu_new_feature":
        await handle_new_feature(query)

async def handle_new_feature(query):
    """Handle new feature."""
    message = "🆕 New Feature\n\nYour content here"
    await query.edit_message_text(
        message,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )
```

## Troubleshooting

### Bot Not Responding

1. Check that the bot is running:
```bash
python main.py
```

2. Verify your `TELEGRAM_BOT_TOKEN` is correct in `.env`

3. Check logs for errors

### "Access denied" Message

1. Verify your `OWNER_ID` is set correctly in `.env`
2. Make sure you're using the correct Telegram account
3. Restart the bot after changing `.env`

### "Bot is not configured properly"

This means either `TELEGRAM_BOT_TOKEN` or `OWNER_ID` is missing from `.env`:

1. Copy `.env.example` to `.env`
2. Fill in both required values
3. Restart the bot

## Best Practices

1. **Regular Monitoring**: Check the Status menu regularly to ensure systems are operational
2. **Trading Controls**: Use the Stop Trading feature before making manual adjustments or during high volatility
3. **AI Restarts**: Restart AI after updating configuration files or models
4. **Sentiment Tracking**: Monitor sentiment trends over time to inform trading decisions

## Support

For issues or questions:
- Check the main [README.md](README.md)
- Review error messages in the bot console
- Open an issue on GitHub
