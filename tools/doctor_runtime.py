#!/usr/bin/env python3
"""
RLdC Doctor Runtime — diagnostyka środowiska uruchomieniowego
Wymagania: Python 3.8+, psutil, git, dostęp do zmiennych środowiskowych i DB
"""
import os
import sys
import subprocess
import socket
import psutil
from datetime import datetime

# --- Helper functions ---
def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def get_git_info():
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).decode().strip()
        return commit, branch
    except Exception:
        return 'unknown', 'unknown'

def get_env_var(name, default=None):
    return os.environ.get(name, default)

# --- Main diagnostic ---
def main():
    print(f"RLdC Doctor Runtime — {datetime.now().isoformat()}")
    print("\n[PROCESY RLdC]")
    keywords = [
        'uvicorn', 'main.py', 'telegram_bot/bot.py', 'collector', 'reevaluation_worker',
        'celery', 'rq', 'apscheduler', 'docker', 'systemd', 'screen', 'tmux', 'nohup'
    ]
    found = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = ' '.join(proc.info['cmdline'])
            if any(k in cmd for k in keywords):
                print(f"PID {proc.info['pid']}: {cmd}")
                found = True
        except Exception:
            continue
    if not found:
        print("Brak aktywnych procesów RLdC wg słów kluczowych.")

    print("\n[PORTY]")
    for port in [8000, 3000, 5173]:
        status = 'OPEN' if check_port(port) else 'CLOSED'
        print(f"Port {port}: {status}")

    print("\n[GIT]")
    commit, branch = get_git_info()
    print(f"Commit: {commit}")
    print(f"Branch: {branch}")

    print("\n[ŚCIEŻKI URUCHOMIENIA]")
    print(f"Backend: {sys.argv[0]}")
    # Frontend: heurystyka — do uzupełnienia wg deploymentu
    print(f"Frontend: [do uzupełnienia]")

    print("\n[KONFIG]")
    for var in [
        'DATABASE_URL', 'TRADING_MODE', 'ALLOW_LIVE_TRADING',
        'BOT_ENABLED', 'TELEGRAM_ENABLED', 'BINANCE_API_KEY', 'BINANCE_API_SECRET'
    ]:
        val = get_env_var(var, '[unset]')
        if var.startswith('BINANCE_API'):
            val = 'true' if val and val != '[unset]' else 'false'
        print(f"{var}: {val}")

    # TODO: DB i Binance — liczba pozycji, różnice
    print("\n[POZYCJE: DB vs Binance]")
    print("Liczba pozycji w DB: [do zaimplementowania]")
    print("Liczba pozycji w Binance: [do zaimplementowania]")
    print("Różnice: [do zaimplementowania]")

if __name__ == "__main__":
    main()
