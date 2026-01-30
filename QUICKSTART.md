# Quick Start Guide

Get your RLdC AI Analyzer Telegram Bot up and running in 5 minutes!

## Step 1: Get Your Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` to BotFather
3. Follow the prompts to create your bot
4. Copy the bot token (it looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

## Step 2: Get Your User ID

1. Open Telegram and search for [@userinfobot](https://t.me/userinfobot)
2. Start a chat with the bot
3. Copy your user ID (it's a number like: `123456789`)

## Step 3: Configure the Bot

```bash
# Navigate to the project directory
cd RLdC_AiNalyzator

# Copy the example environment file
cp .env.example .env

# Edit .env and add your credentials
# Replace the placeholders with your actual values
```

Your `.env` file should look like:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
OWNER_ID=123456789
```

## Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `python-telegram-bot` - Telegram Bot API wrapper
- `python-dotenv` - Environment variable management

## Step 5: Run the Bot

```bash
python main.py
```

You should see:
```
INFO - Starting RLdC AI Analyzer Bot...
INFO - Bot is running. Press Ctrl+C to stop.
```

## Step 6: Test the Bot

1. Open Telegram
2. Find your bot (the name you gave it when creating with BotFather)
3. Send `/start`
4. You should see the main menu with interactive buttons! 🎉

## Common Issues

### "No module named 'telegram'"

**Solution:** Install dependencies
```bash
pip install -r requirements.txt
```

### "TELEGRAM_BOT_TOKEN not found"

**Solution:** Make sure you:
1. Created a `.env` file (not `.env.example`)
2. Added your bot token to the `.env` file
3. Token is on the line starting with `TELEGRAM_BOT_TOKEN=`

### "Access denied" when trying to use the bot

**Solution:** Make sure:
1. You added YOUR user ID to `.env` as `OWNER_ID`
2. You're using the Telegram account that matches that user ID
3. You restarted the bot after changing `.env`

### Bot doesn't respond

**Solution:**
1. Check that `python main.py` is running
2. Check for errors in the terminal
3. Verify your bot token is correct
4. Make sure your bot is not blocked in Telegram

## Next Steps

Once your bot is running:

1. **Explore Features**: Try all the menu options
   - 📊 Portfolio - View holdings
   - 📈 Status - Check system status
   - 🧠 Sentiment - Market analysis
   - 📰 Latest Analysis - Read latest post
   - ⚙️ System Controls - Manage trading

2. **Read Documentation**:
   - [USAGE.md](USAGE.md) - Detailed feature guide
   - [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
   - [INTERFACE_DEMO.md](INTERFACE_DEMO.md) - Visual interface guide

3. **Integrate Services**:
   - Replace `sentiment_analysis/service.py` with real sentiment analysis
   - Replace `blog_generator/storage.py` with real blog database
   - Connect to your actual trading system

4. **Customize**:
   - Add new menu options in `telegram_bot/keyboards.py`
   - Add new handlers in `telegram_bot/handlers.py`
   - Extend system controls in `telegram_bot/controls.py`

## Security Reminders

- ⚠️ **Never commit your `.env` file** to version control
- ⚠️ **Never share your bot token** with anyone
- ⚠️ **Keep your OWNER_ID private** to maintain exclusive access
- ✅ The bot is configured to only respond to your user ID
- ✅ All unauthorized access attempts are logged

## Testing

Run the component tests to verify everything works:

```bash
python test_bot.py
```

You should see:
```
🎉 ALL TESTS PASSED! 🎉
```

## Support

Need help?

1. Check the [README.md](README.md) for setup instructions
2. Review [USAGE.md](USAGE.md) for feature documentation
3. Look at [ARCHITECTURE.md](ARCHITECTURE.md) to understand the system
4. Check error messages in your terminal
5. Open an issue on GitHub

## Development Mode

To run the bot in development mode with more logging:

```python
# In telegram_bot/bot.py, change logging level:
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Change from INFO to DEBUG
)
```

## Production Deployment

For production deployment:

1. Use a process manager (systemd, supervisor, pm2)
2. Set up log rotation
3. Monitor the bot process
4. Use environment-specific `.env` files
5. Set up alerts for bot downtime

Example systemd service file:

```ini
[Unit]
Description=RLdC AI Analyzer Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/RLdC_AiNalyzator
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Congratulations! 🎉

Your Telegram Bot Command Center is now operational!

You can now control your AI trading platform from anywhere using Telegram.
