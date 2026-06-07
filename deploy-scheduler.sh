#!/bin/bash
# Deploy sector scheduler process.
# Usage: ./deploy-scheduler.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "==> Stopping existing sector_scheduler (if any)..."
pkill -f "sector_scheduler.py" || true
sleep 1

echo "==> Starting sector_scheduler in background..."
mkdir -p logs
nohup python3 bot/sector_scheduler.py > logs/sector_scheduler.log 2>&1 &
disown
sleep 2

echo "==> Verifying process is running..."
if pgrep -f "sector_scheduler.py" > /dev/null; then
  echo "✓ sector_scheduler started (pid=$(pgrep -f sector_scheduler.py))"
  echo "  Logs: $PROJECT_DIR/logs/sector_scheduler.log"
else
  echo "✗ Failed to start sector_scheduler; check logs"
  exit 1
fi
