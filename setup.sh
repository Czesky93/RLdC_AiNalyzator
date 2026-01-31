#!/bin/bash
# Automated setup script for RLdC AI Analyzer Telegram Bot
# This script automates the complete setup process

set -e

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  RLdC AI Analyzer - Automated Setup                             ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed!"
    echo "Please install Python 3.8 or higher and try again."
    exit 1
fi

# Run the Python setup script
python3 setup.py
