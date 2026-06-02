#!/bin/bash
# Deploy bot v2 (a-stock-data skill integration) to server
# Usage: bash deploy.sh

SERVER="ubuntu@101.36.106.113"
REMOTE_BOT_DIR="/home/ubuntu/stock-analysis-system/bot"
REMOTE_BACKEND_DIR="/home/ubuntu/stock-analysis-system/backend"

echo "=== Deploying bot v4 (real financial data + peer comparison) ==="

# 1. Upload astock_data.py
echo "[1/14] Uploading astock_data.py..."
scp bot/astock_data.py ${SERVER}:${REMOTE_BOT_DIR}/astock_data.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload astock_data.py"
    exit 1
fi

# 2. Upload astock_data_10jqka.py (NEW — 10jqka data layer)
echo "[2/14] Uploading astock_data_10jqka.py..."
scp bot/astock_data_10jqka.py ${SERVER}:${REMOTE_BOT_DIR}/astock_data_10jqka.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload astock_data_10jqka.py"
    exit 1
fi

# 3. Upload queue_processor.py (updated — data_10jqka integration)
echo "[3/14] Uploading queue_processor.py..."
scp bot/queue_processor.py ${SERVER}:${REMOTE_BOT_DIR}/queue_processor.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload queue_processor.py"
    exit 1
fi

# 4. Upload updated telegram_bot.py
echo "[4/14] Uploading telegram_bot.py..."
scp bot/telegram_bot.py ${SERVER}:${REMOTE_BOT_DIR}/telegram_bot.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload telegram_bot.py"
    exit 1
fi

# 5. Upload updated deep_report.py (10jqka data fetching)
echo "[5/14] Uploading deep_report.py..."
scp bot/deep_report.py ${SERVER}:${REMOTE_BOT_DIR}/deep_report.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload deep_report.py"
    exit 1
fi

# 6. Upload updated ai_analyzer.py (10jqka prompt integration)
echo "[6/14] Uploading ai_analyzer.py..."
scp bot/ai_analyzer.py ${SERVER}:${REMOTE_BOT_DIR}/ai_analyzer.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload ai_analyzer.py"
    exit 1
fi

# 7. Upload deepseek.enc (API key)
echo "[7/14] Uploading deepseek.enc..."
scp bot/deepseek.enc ${SERVER}:${REMOTE_BOT_DIR}/deepseek.enc
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload deepseek.enc"
    exit 1
fi

# 8. Upload regenerate_reports.py
echo "[8/14] Uploading regenerate_reports.py..."
scp regenerate_reports.py ${SERVER}:/home/ubuntu/stock-analysis-system/regenerate_reports.py
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to upload regenerate_reports.py"
    exit 1
fi

# 9. Upload backend files
echo "[9/14] Uploading backend files..."
scp backend/app/models/report.py ${SERVER}:${REMOTE_BACKEND_DIR}/app/models/report.py
scp backend/app/schemas/__init__.py ${SERVER}:${REMOTE_BACKEND_DIR}/app/schemas/__init__.py
scp backend/app/services/report_service.py ${SERVER}:${REMOTE_BACKEND_DIR}/app/services/report_service.py
scp backend/app/routers/reports.py ${SERVER}:${REMOTE_BACKEND_DIR}/app/routers/reports.py

# 10. Upload HTML template
echo "[10/14] Uploading report template..."
scp backend/app/templates/report.html ${SERVER}:${REMOTE_BACKEND_DIR}/app/templates/report.html

# 11. Delete old scraper files on server
echo "[11/14] Removing old scrapers on server..."
ssh ${SERVER} "rm -rf ${REMOTE_BOT_DIR}/scrapers/ ${REMOTE_BOT_DIR}/scraper_bridge.py"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to remove old scrapers (may not exist)"
fi

# 12. DB migration — add financial_data_raw, peer_comparison_raw columns
echo "[12/14] Running DB migration..."
ssh ${SERVER} "cd /home/ubuntu/stock-analysis-system/backend && python3 -c \"
import sqlite3
conn = sqlite3.connect('stock_analysis.db')
cur = conn.cursor()
for col in ['financial_data_raw', 'peer_comparison_raw']:
    try:
        cur.execute(f'ALTER TABLE reports ADD COLUMN {col} JSON DEFAULT NULL')
        print(f'Added column: {col}')
    except Exception as e:
        print(f'Column {col}: {e}')
conn.commit()
conn.close()
\""
if [ $? -ne 0 ]; then
    echo "WARNING: DB migration may have partially failed (columns may already exist)"
fi

# 13. Install deps on server
echo "[13/14] Ensuring dependencies..."
ssh ${SERVER} "pip3 install mootdx pandas lxml beautifulsoup4"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to install dependencies (may already be installed)"
fi

# 14. Restart services
echo "[14/14] Restarting services..."
ssh ${SERVER} "sudo systemctl restart stock-bot"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to restart stock-bot"
fi
ssh ${SERVER} "sudo systemctl restart stock-backend"
if [ $? -ne 0 ]; then
    echo "WARNING: Failed to restart stock-backend"
fi

echo "=== Deploy complete ==="
echo ""
echo "Uploaded files:"
echo "  bot/astock_data.py (Phase 1: financial data + peer comparison scraping)"
echo "  bot/astock_data_10jqka.py (10jqka data layer)"
echo "  bot/queue_processor.py (Phase 3: financial/peer data threading)"
echo "  bot/telegram_bot.py"
echo "  bot/deep_report.py (Phase 3: financial/peer data fetching)"
echo "  bot/ai_analyzer.py (Phase 2: real financial data in prompt)"
echo "  bot/deepseek.enc"
echo "  regenerate_reports.py"
echo "  backend/app/models/report.py (+financial_data_raw +peer_comparison_raw)"
echo "  backend/app/schemas/__init__.py (+financial_data_raw +peer_comparison_raw)"
echo "  backend/app/services/report_service.py (+financial_data_raw +peer_comparison_raw)"
echo "  backend/app/templates/report.html (Phase 5: real data tables + peer comparison)"
echo ""
echo "DB migration: added financial_data_raw, peer_comparison_raw columns"
echo ""
echo "Start queue processor on server:"
echo "  ssh ${SERVER}"
echo "  cd /home/ubuntu/stock-analysis-system/bot"
echo "  nohup python3 queue_processor.py --watch > queue.log 2>&1 &"
