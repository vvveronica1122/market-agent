#!/bin/bash
# Double-click this file in Finder to start the dashboard.
# It activates the virtualenv, starts the server, and opens the browser.
# Close the window (or press Ctrl+C) to stop it.

cd "$(dirname "$0")" || exit 1

if [ ! -d ".venv" ]; then
  echo "No .venv found. Run this once first:"
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  read -r -p "Press return to close."
  exit 1
fi

source .venv/bin/activate

# Give the server a moment to bind the port, then open the browser.
( sleep 2; open http://127.0.0.1:5050 ) &

echo "Starting Market Agent — close this window to stop it."
python3 web/app.py
