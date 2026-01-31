# Automated Setup Scripts

This directory contains automated setup scripts to simplify the installation and configuration of the RLdC AI Analyzer Telegram Bot.

## Available Scripts

### `setup.py` - Python Setup Script (Cross-platform)
The main automated setup script that works on all platforms.

**Features:**
- ✅ Checks Python version compatibility (3.8+)
- ✅ Automatically installs dependencies from requirements.txt
- ✅ Interactive configuration of .env file
- ✅ Validates bot credentials
- ✅ Runs component tests to verify installation
- ✅ Offers to run demo
- ✅ Displays helpful next steps

**Usage:**
```bash
python setup.py
```

### `setup.sh` - Bash Script (Linux/Mac)
Convenience wrapper for the Python setup script on Unix-like systems.

**Usage:**
```bash
chmod +x setup.sh
./setup.sh
```

### `setup.bat` - Batch Script (Windows)
Convenience wrapper for the Python setup script on Windows.

**Usage:**
```bash
setup.bat
```

## What the Setup Does

1. **Python Version Check**
   - Verifies Python 3.8 or higher is installed
   - Shows current Python version

2. **Dependency Installation**
   - Installs python-telegram-bot
   - Installs python-dotenv
   - Shows installation progress

3. **Environment Configuration**
   - Creates .env file from template
   - Optionally prompts for credentials
   - Validates credential format

4. **Testing**
   - Runs all component tests
   - Verifies bot functionality
   - Reports test results

5. **Demo**
   - Optionally runs bot demonstration
   - Shows all features without real credentials

6. **Next Steps**
   - Displays helpful instructions
   - Lists documentation
   - Shows how to run the bot

## Interactive vs Non-Interactive Mode

### Interactive Mode
Run normally and answer prompts:
```bash
python setup.py
```

The script will ask:
- Do you have credentials ready?
- Would you like to enter them now?
- Would you like to see a demo?

### Non-Interactive Mode
For automated installations:
```bash
echo "n" | python setup.py
```

This will:
- Skip credential prompts
- Create .env from template
- Skip demo
- Show instructions for manual configuration

## Credential Setup

The setup script guides you through getting:

### Telegram Bot Token
1. Open Telegram
2. Search for @BotFather
3. Send: `/newbot`
4. Follow prompts to create your bot
5. Copy the token (format: `123456789:ABCdefGHI...`)

### Your User ID
1. Open Telegram
2. Search for @userinfobot
3. Start a chat
4. Copy your user ID (format: `123456789`)

## Troubleshooting

### Python Not Found
**Error:** `python: command not found`

**Solution:**
- Install Python 3.8 or higher
- Try `python3` instead of `python`

### Permission Denied (Linux/Mac)
**Error:** `Permission denied: ./setup.sh`

**Solution:**
```bash
chmod +x setup.sh
./setup.sh
```

### Dependencies Fail to Install
**Error:** Package installation errors

**Solution:**
```bash
# Upgrade pip first
python -m pip install --upgrade pip

# Try manual installation
pip install -r requirements.txt
```

### .env Already Exists
**Behavior:** Script detects existing .env

**Options:**
- Keep existing: Press `N`
- Overwrite: Press `Y`

## Manual Setup Alternative

If automated setup doesn't work, you can set up manually:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env file
cp .env.example .env

# 3. Edit .env with your credentials
nano .env  # or your preferred editor

# 4. Run tests
python test_bot.py

# 5. Start the bot
python main.py
```

## After Setup

Once setup is complete:

### Run the Bot
```bash
python main.py
```

### Run Tests
```bash
python test_bot.py
```

### Run Demo
```bash
python demo_bot.py
```

### Read Documentation
- `README.md` - Overview and setup
- `QUICKSTART.md` - Quick start guide
- `USAGE.md` - Detailed usage instructions
- `ARCHITECTURE.md` - Technical architecture

## Advanced Options

### Skip Tests
If you want to skip tests during setup, modify `setup.py`:
```python
# Comment out or remove:
run_tests()
```

### Skip Demo
To skip the demo prompt:
```bash
echo "n" | python setup.py
```

### Custom .env Location
Edit `setup.py` to change the .env file location:
```python
env_file = Path("/custom/path/.env")
```

## Support

If you encounter issues:
1. Check Python version: `python --version`
2. Check pip installation: `pip --version`
3. Review error messages carefully
4. Consult the main README.md
5. Open an issue on GitHub

## License

Same license as the main project.
