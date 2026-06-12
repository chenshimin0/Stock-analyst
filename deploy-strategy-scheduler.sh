#!/bin/bash
# Deploy strategy scheduler process (iwenc picker + T+N tracker).
# Usage: ./deploy-strategy-scheduler.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "==> Stopping existing strategy_scheduler (if any)..."
pkill -f "strategy_scheduler.py" || true
sleep 1

echo "==> Starting strategy_scheduler in background..."
mkdir -p logs
nohup sudo backend/venv/bin/python3 bot/strategy_scheduler.py > logs/strategy_scheduler.log 2>&1 &
disown
sleep 2

echo "==> Verifying process is running..."
if pgrep -f "strategy_scheduler.py" > /dev/null; then
  echo "✓ strategy_scheduler started (pid=$(pgrep -f strategy_scheduler.py))"
  echo "  Logs: $PROJECT_DIR/logs/strategy_scheduler.log"
else
  echo "✗ Failed to start strategy_scheduler; check logs"
  exit 1
fi
