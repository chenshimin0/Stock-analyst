#!/bin/bash
# Deploy bot v2 (a-stock-data skill integration) to server
# Usage: bash deploy.sh

SERVER="ubuntu@101.36.106.113"
REMOTE_BOT_DIR="/home/ubuntu/stock-analysis-system/bot"
REMOTE_BACKEND_DIR="/home/ubuntu/stock-analysis-system/backend"

echo "=== Deploying bot v2 (a-stock-data integration) ==="

# 1. Upload new astock_data.py (NEW — replaces custom scrapers)
echo "[1/7] Uploading astock_data.py..."
scp bot/astock_data.py ${SERVER}:${REMOTE_BOT_DIR}/astock_data.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload astock_data.py"
    exit 1
fi

# 2. Upload queue_processor.py (NEW)
echo "[2/7] Uploading queue_processor.py..."
scp bot/queue_processor.py ${SERVER}:${REMOTE_BOT_DIR}/queue_processor.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload queue_processor.py"
    exit 1
fi

# 3. Upload updated telegram_bot.py (v2 thin client)
echo "[3/7] Uploading telegram_bot.py..."
scp bot/telegram_bot.py ${SERVER}:${REMOTE_BOT_DIR}/telegram_bot.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload telegram_bot.py"
    exit 1
fi

# 4. Upload updated deep_report.py
echo "[4/7] Uploading deep_report.py..."
scp bot/deep_report.py ${SERVER}:${REMOTE_BOT_DIR}/deep_report.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload deep_report.py"
    exit 1
fi

# 5. Delete old scraper files on server
echo "[5/7] Removing old scrapers on server..."
ssh ${SERVER} "rm -rf ${REMOTE_BOT_DIR}/scrapers/ ${REMOTE_BOT_DIR}/scraper_bridge.py"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to remove old scrapers (may not exist)"
fi

# 6. Install mootdx on server (required by a-stock-data)
echo "[6/7] Ensuring mootdx is installed..."
ssh ${SERVER} "pip3 install mootdx"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to install mootdx (may already be installed)"
fi

# 7. Restart bot service
echo "[7/7] Restarting bot service..."
ssh ${SERVER} "sudo systemctl restart stock-bot"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to restart stock-bot"
fi

echo "=== Deploy complete ==="
echo ""
echo "Uploaded files:"
echo "  bot/astock_data.py (NEW — a-stock-data API wrapper)"
echo "  bot/queue_processor.py (NEW — queue processing)"
echo "  bot/telegram_bot.py (v2 thin client)"
echo "  bot/deep_report.py (updated)"
echo ""
echo "Removed on server: bot/scrapers/, bot/scraper_bridge.py"
echo ""
echo "Start queue processor on server:"
echo "  ssh ${SERVER}"
echo "  cd /home/ubuntu/stock-analysis-system/bot"
echo "  nohup python3 queue_processor.py --watch > queue.log 2>&1 &"
