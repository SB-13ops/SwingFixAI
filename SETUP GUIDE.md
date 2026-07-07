#!/bin/bash
# SwingFix AI - One-click startup for Mac/Linux
# Double-click this file on Mac to run

clear
echo ""
echo " ============================================"
echo "  SwingFix AI - Starting Up"
echo " ============================================"
echo ""

# Move to the folder where this script lives
cd "$(dirname "$0")"

# --- Check Python ---
if ! command -v python3 &>/dev/null; then
    echo " ERROR: Python 3 is not installed."
    echo ""
    echo " Mac:   Install from https://www.python.org/downloads/"
    echo "        Or run: brew install python3"
    echo ""
    read -p " Press Enter to exit..."
    exit 1
fi

# --- Check for API key ---
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo " OPTIONAL: Anthropic API key for AI-written coaching."
    echo " No key? Just press Enter - full analysis still works."
    echo ""
    read -p "  Paste key or press Enter to skip: " ANTHROPIC_API_KEY
    export ANTHROPIC_API_KEY
    echo ""
fi

cd backend

# --- Create virtual environment if needed ---
if [ ! -d "venv" ]; then
    echo " First-time setup: installing dependencies..."
    echo " This takes 2-5 minutes and only happens once."
    echo ""
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet -r requirements.txt
    echo ""
    echo " Setup complete!"
    echo ""
else
    source venv/bin/activate
fi

# --- Start backend in background ---
echo " Starting SwingFix AI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

# Wait for server
sleep 3

# --- Open frontend in browser ---
echo " Opening SwingFix AI in your browser..."
if command -v open &>/dev/null; then
    open "../frontend/swingfix-ai.html"   # Mac
elif command -v xdg-open &>/dev/null; then
    xdg-open "../frontend/swingfix-ai.html"  # Linux
fi

echo ""
echo " ============================================"
echo "  SwingFix AI is running!"
echo ""
echo "  - App is open in your browser"
echo "  - Keep this window open while using the app"
echo "  - Press Ctrl+C to stop"
echo " ============================================"
echo ""

# Keep running and show logs
wait $SERVER_PID
