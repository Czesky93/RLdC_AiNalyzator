#!/usr/bin/env python3
"""
Automated setup script for RLdC AI Analyzer Telegram Bot.
Automates the complete setup process including dependency installation,
environment configuration, and initial bot testing.
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_step(step_num, text):
    """Print a formatted step."""
    print(f"\n[{step_num}] {text}")


def print_success(text):
    """Print a success message."""
    print(f"✅ {text}")


def print_error(text):
    """Print an error message."""
    print(f"❌ {text}")


def print_warning(text):
    """Print a warning message."""
    print(f"⚠️  {text}")


def print_info(text):
    """Print an info message."""
    print(f"ℹ️  {text}")


def check_python_version():
    """Check if Python version is adequate."""
    print_step(1, "Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print_error(f"Python 3.8+ required, but found Python {version.major}.{version.minor}")
        return False
    print_success(f"Python {version.major}.{version.minor}.{version.micro} detected")
    return True


def install_dependencies():
    """Install required Python dependencies."""
    print_step(2, "Installing dependencies...")
    
    requirements_file = Path(__file__).parent / "requirements.txt"
    if not requirements_file.exists():
        print_error("requirements.txt not found!")
        return False
    
    try:
        print_info("Running: pip install -r requirements.txt")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(requirements_file)],
            check=True,
            capture_output=True
        )
        print_success("Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to install dependencies: {e}")
        return False


def setup_environment():
    """Set up the .env file with user input."""
    print_step(3, "Configuring environment variables...")
    
    env_example = Path(__file__).parent / ".env.example"
    env_file = Path(__file__).parent / ".env"
    
    # Check if .env already exists
    if env_file.exists():
        print_warning(".env file already exists!")
        try:
            response = input("Do you want to overwrite it? (y/N): ").strip().lower()
        except EOFError:
            print_info("Keeping existing .env file (non-interactive mode)")
            return True
        
        if response != 'y':
            print_info("Keeping existing .env file")
            return True
    
    print_info("\nYou need to provide two pieces of information:")
    print_info("1. Telegram Bot Token (from @BotFather)")
    print_info("2. Your Telegram User ID (from @userinfobot)")
    
    # Ask if user wants to set up now or later
    try:
        response = input("\nDo you have these credentials ready? (y/N): ").strip().lower()
    except EOFError:
        # Non-interactive mode - create from template
        if env_example.exists():
            shutil.copy(env_example, env_file)
            print_success(".env file created from template")
            print_warning("Remember to edit .env and add your credentials!")
            return True
        else:
            print_error(".env.example not found!")
            return False
    
    if response == 'y':
        print("\n" + "-" * 70)
        print("Please provide your credentials:")
        print("-" * 70)
        
        bot_token = input("\nTelegram Bot Token: ").strip()
        owner_id = input("Your Telegram User ID: ").strip()
        
        # Validate inputs
        if not bot_token or bot_token == 'your_bot_token_here':
            print_warning("Invalid bot token provided")
            bot_token = 'your_bot_token_here'
        
        if not owner_id or owner_id == 'your_telegram_user_id_here':
            print_warning("Invalid user ID provided")
            owner_id = 'your_telegram_user_id_here'
        
        # Create .env file
        with open(env_file, 'w') as f:
            f.write("# Telegram Bot Configuration\n")
            f.write(f"TELEGRAM_BOT_TOKEN={bot_token}\n")
            f.write(f"OWNER_ID={owner_id}\n")
        
        print_success(".env file created successfully")
        
        if bot_token == 'your_bot_token_here' or owner_id == 'your_telegram_user_id_here':
            print_warning("Remember to update .env with real credentials before running the bot!")
    else:
        # Create .env from example
        if env_example.exists():
            shutil.copy(env_example, env_file)
            print_success(".env file created from template")
            print_warning("Remember to edit .env and add your credentials!")
        else:
            print_error(".env.example not found!")
            return False
    
    return True


def display_credentials_help():
    """Display help for getting Telegram credentials."""
    print("\n" + "=" * 70)
    print("  HOW TO GET YOUR CREDENTIALS")
    print("=" * 70)
    
    print("\n📱 Getting Telegram Bot Token:")
    print("   1. Open Telegram and search for @BotFather")
    print("   2. Send: /newbot")
    print("   3. Follow the prompts to create your bot")
    print("   4. Copy the bot token (format: 123456789:ABCdefGHI...)")
    
    print("\n👤 Getting Your User ID:")
    print("   1. Open Telegram and search for @userinfobot")
    print("   2. Start a chat with the bot")
    print("   3. Copy your user ID (a number like: 123456789)")
    
    print("\n💡 Then edit .env file and replace the placeholder values")


def run_tests():
    """Run component tests to verify installation."""
    print_step(4, "Running component tests...")
    
    test_file = Path(__file__).parent / "test_bot.py"
    if not test_file.exists():
        print_warning("test_bot.py not found, skipping tests")
        return True
    
    try:
        print_info("Running: python test_bot.py")
        result = subprocess.run(
            [sys.executable, str(test_file)],
            check=True,
            capture_output=True,
            text=True
        )
        
        # Show last few lines of output
        lines = result.stdout.strip().split('\n')
        for line in lines[-5:]:
            print(f"   {line}")
        
        print_success("All tests passed!")
        return True
    except subprocess.CalledProcessError as e:
        print_error("Tests failed!")
        print(e.stdout)
        return False


def run_demo():
    """Offer to run the demo."""
    print_step(5, "Demo available...")
    
    demo_file = Path(__file__).parent / "demo_bot.py"
    if not demo_file.exists():
        print_warning("demo_bot.py not found")
        return
    
    try:
        response = input("\nWould you like to see a demo of the bot? (y/N): ").strip().lower()
    except EOFError:
        # Non-interactive mode
        print_info("Skipping demo (non-interactive mode)")
        return
    
    if response == 'y':
        print_info("Running demo...")
        try:
            subprocess.run([sys.executable, str(demo_file)], check=True)
        except subprocess.CalledProcessError:
            print_error("Demo failed to run")


def show_next_steps():
    """Display next steps for the user."""
    print("\n" + "=" * 70)
    print("  SETUP COMPLETE! 🎉")
    print("=" * 70)
    
    env_file = Path(__file__).parent / ".env"
    has_credentials = False
    
    if env_file.exists():
        with open(env_file, 'r') as f:
            content = f.read()
            has_credentials = (
                'your_bot_token_here' not in content and
                'your_telegram_user_id_here' not in content
            )
    
    if has_credentials:
        print("\n✅ Your bot is configured and ready to run!")
        print("\n🚀 Start the bot:")
        print("   python main.py")
    else:
        print("\n⚠️  You still need to add your credentials to .env")
        print("\n📝 Next steps:")
        print("   1. Get your credentials (see instructions above)")
        print("   2. Edit .env file and add your credentials")
        print("   3. Run: python main.py")
    
    print("\n📚 Documentation:")
    print("   • README.md - Overview and setup")
    print("   • QUICKSTART.md - Quick start guide")
    print("   • USAGE.md - Detailed usage instructions")
    print("   • ARCHITECTURE.md - Technical architecture")
    
    print("\n🧪 Testing:")
    print("   • python test_bot.py - Run component tests")
    print("   • python demo_bot.py - See feature demo")
    
    print()


def main():
    """Main setup function."""
    print("\n╔══════════════════════════════════════════════════════════════════╗")
    print("║  RLdC AI Analyzer - Automated Telegram Bot Setup                ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    
    # Change to script directory
    os.chdir(Path(__file__).parent)
    
    # Step 1: Check Python version
    if not check_python_version():
        print_error("Setup failed: Python version too old")
        return 1
    
    # Step 2: Install dependencies
    if not install_dependencies():
        print_error("Setup failed: Could not install dependencies")
        return 1
    
    # Step 3: Set up environment
    if not setup_environment():
        print_error("Setup failed: Could not configure environment")
        return 1
    
    # Display help for getting credentials
    display_credentials_help()
    
    # Step 4: Run tests
    if not run_tests():
        print_warning("Tests failed, but setup can continue")
    
    # Step 5: Offer demo
    run_demo()
    
    # Show next steps
    show_next_steps()
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
