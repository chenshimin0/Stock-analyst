#!/bin/bash
# Complete deployment script for Stock Analysis System (v2)
# Run from your local machine: bash deploy-all.sh

set -e

SERVER="ubuntu@101.36.106.113"
REMOTE_DIR="/home/ubuntu/stock-analysis-system"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo " Stock Analysis System - Full Deploy v2"
echo "=========================================="

# 1. Build frontend
echo ""
echo "[1/7] Building frontend..."
cd "$LOCAL_DIR/frontend"
npm run build
echo "Frontend built successfully."

# 2. Upload backend
echo ""
echo "[2/7] Uploading backend..."
scp -r "$LOCAL_DIR/backend/app" "$LOCAL_DIR/backend/requirements.txt" "$LOCAL_DIR/backend/run.py" "$LOCAL_DIR/backend/seed_data.py" "$SERVER:$REMOTE_DIR/backend/"

# 3. Upload frontend dist
echo "[3/7] Uploading frontend dist..."
scp -r "$LOCAL_DIR/frontend/dist/"* "$SERVER:$REMOTE_DIR/frontend/dist/"

# 4. Upload bot (v2 — all files, no scrapers)
echo "[4/7] Uploading bot v2..."
scp "$LOCAL_DIR/bot/"*.py "$SERVER:$REMOTE_DIR/bot/"

# 5. Remove old scrapers on server
echo "[5/7] Removing old scrapers on server..."
ssh "$SERVER" "rm -rf $REMOTE_DIR/bot/scrapers/ $REMOTE_DIR/bot/scraper_bridge.py" || true

# 6. Install dependencies
echo "[6/7] Installing dependencies..."
ssh "$SERVER" "pip3 install mootdx"

# 7. Restart services
echo ""
echo "[7/7] Restarting services..."
ssh "$SERVER" "sudo systemctl restart stock-backend && systemctl status stock-backend --no-pager | head -5"
ssh "$SERVER" "sudo systemctl restart stock-bot && systemctl status stock-bot --no-pager | head -3"

echo ""
echo "=========================================="
echo " Deployment Complete! (v2)"
echo "=========================================="
echo ""
echo "Access: http://101.36.106.113:8888"
echo ""
echo "Start queue processor on server:"
echo "  ssh $SERVER"
echo "  cd $REMOTE_DIR/bot"
echo "  nohup python3 queue_processor.py --watch > queue.log 2>&1 &"
echo ""
