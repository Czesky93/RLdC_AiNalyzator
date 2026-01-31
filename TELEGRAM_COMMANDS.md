# Telegram Bot Commands - Complete Reference

## Overview
RLdC AI Analyzer Telegram Bot now includes all P0 priority commands from the system audit.

## Command Categories

### 1. Core Commands
| Command | Description | Status |
|---------|-------------|--------|
| `/start` | Show interactive main menu | ✅ Implemented |
| `/help` | Display all available commands | ✅ Implemented |
| `/status` | System and trading status report | ✅ Implemented |

### 2. Trading Operations
| Command | Description | Status |
|---------|-------------|--------|
| `/stop` | Stop/pause trading operations | ✅ Implemented |
| `/portfolio` | Portfolio overview with holdings | ✅ Implemented |
| `/orders` | View active orders | ✅ Implemented |
| `/positions` | View open positions | ✅ Implemented |
| `/risk` | Risk management overview | ✅ Implemented |

### 3. Market Analysis
| Command | Description | Status |
|---------|-------------|--------|
| `/lastsignal` | Last trading signal details | ✅ Implemented |
| `/top5` | Top 5 performing assets (24h) | ✅ Implemented |
| `/top10` | Top 10 performing assets (24h) | ✅ Implemented |
| `/blog` | Latest blog posts | ✅ Implemented |

### 4. System Monitoring
| Command | Description | Status |
|---------|-------------|--------|
| `/logs` | Recent system logs | ✅ Implemented |

## Interactive Menu Options

The bot also provides an interactive keyboard menu accessible via `/start`:

- 📊 **Portfolio** - View holdings and performance
- 📈 **Status** - Check system status  
- 🧠 **Sentiment** - Market sentiment analysis
- 📰 **Latest Analysis** - Read latest blog post
- ⚙️ **System Controls** - Manage trading and AI

## Implementation Details

### Authentication
All commands are protected by the `@restricted` decorator, ensuring only the bot owner (configured via `OWNER_ID`) can access them.

### Data Sources
- **Real-time data**: Portfolio, orders, positions (placeholder - ready for backend integration)
- **Mock data**: Currently using placeholders for demonstration
- **Integration ready**: All commands structured to easily connect to backend API

### Error Handling
All commands include comprehensive error handling and user-friendly error messages.

## Usage Examples

### Check System Status
```
User: /status

Bot Response:
📊 System Status Report

🔄 Trading: ACTIVE
🧠 AI System: RUNNING
📡 Bot Status: ONLINE
💾 State Persistence: ACTIVE

✅ All systems operational.
```

### View Portfolio
```
User: /portfolio

Bot Response:
💼 Portfolio Overview

💰 Total Value: $125,450.00
📈 24h Change: +$2,340.50 (+1.90%)
📊 7d Change: +$5,120.00 (+4.25%)

Top Holdings:
• BTC: $45,000 (35.8%)
• ETH: $32,000 (25.5%)
• SOL: $18,500 (14.7%)
• Other: $30,000 (23.9%)

📊 Diversification: Good
✅ Portfolio healthy
```

### View Last Signal
```
User: /lastsignal

Bot Response:
🎯 Last Trading Signal

📅 Time: 2026-01-31 15:30 UTC
📊 Symbol: BTC/USDT
🔔 Signal: BUY
💰 Entry: $94,800 - $95,200
🎯 Target 1: $96,500
🎯 Target 2: $97,800
🛑 Stop Loss: $93,500

📈 Confidence: 78%
⚡ Strength: Strong

💡 Reason: Bullish momentum + positive sentiment
```

## Backend Integration

All commands are ready for backend integration. To connect to real data:

1. Update placeholder functions in handlers.py
2. Import backend API clients
3. Replace mock data with API calls
4. Add error handling for API failures

Example integration pattern:
```python
@restricted
async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Replace this placeholder with real API call
        portfolio_data = await backend_api.get_portfolio()
        
        message = format_portfolio_message(portfolio_data)
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}")
        await update.message.reply_text(
            "❌ Unable to retrieve portfolio data."
        )
```

## Testing

All commands are tested in `test_bot.py`:
- ✅ Command handlers exist
- ✅ Commands are registered in bot
- ✅ Authentication applied correctly
- ✅ All 15 commands verified

Run tests: `python test_bot.py`

## Next Steps

1. **Backend Integration**: Connect commands to real backend APIs
2. **Real Data**: Replace placeholders with actual trading data
3. **Notifications**: Add push notifications for important events
4. **Scheduling**: Implement periodic updates and reports
5. **Advanced Features**: Add command parameters and filters
