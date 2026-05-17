#!/bin/bash

BASE=~/RLdC_AiNalyzator/RLdC_AiNalyzator

echo "=== PROCESY ==="
ps aux | grep -E "python|uvicorn|next|node|worker" | grep -v grep

echo
echo "=== PORTY ==="
ss -tulpn | grep -E "3000|8000|8080|5000"

echo
echo "=== OSTATNIE BUY ==="
grep -R "LIVE BUY" $BASE/logs 2>/dev/null | tail -20

echo
echo "=== SIGNAL FILTERS ==="
grep -R "signal_filters_not_met" $BASE/logs 2>/dev/null | tail -20

echo
echo "=== AI ERRORS ==="
grep -R "OpenAI HTTP\|Gemini HTTP\|Groq HTTP\|Ollama" $BASE/logs 2>/dev/null | tail -20

echo
echo "=== MARKET DATA ==="
grep -R "RSI\|EMA\|candles\|market data" $BASE/logs 2>/dev/null | tail -20

echo
echo "=== SYMBOL MAP ==="
grep -R "BANKUSDC\|BANANAS31USDC" $BASE 2>/dev/null | tail -50

echo
echo "=== FRONTEND API ==="
grep -R "EUR" $BASE/web_portal 2>/dev/null | head -50

echo
echo "=== SQLITE ==="
find $BASE -name "*.db"

echo
echo "=== CACHE ==="
find $BASE -type d | grep -E "cache|tmp|redis"

echo
echo "=== ENV ==="
cat $BASE/config/.env | grep -E "MARKET|SYMBOL|PAIR|AI|OPENAI|GROQ|GEMINI"

echo
echo "=== OPEN POSITIONS ==="
grep -R "FILLED" $BASE/logs 2>/dev/null | tail -20
