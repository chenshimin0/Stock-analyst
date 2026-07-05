#!/usr/bin/env python3
"""Deploy local code to server via rsync over SSH with password."""
import pexpect
import sys
import os

HOST = "101.36.106.113"
USER = "ubuntu"
PASSWORD = "@Wangbadan0959"
PROJECT_DIR = "/Users/shiminchen/stock-analysis-system"
REMOTE_DIR = "/home/ubuntu/stock-analysis-system"

EXCLUDES = [
    "--exclude=.git",
    "--exclude=__pycache__",
    "--exclude=node_modules",
    "--exclude=*.pyc",
    "--exclude=.venv",
    "--exclude=venv",
    "--exclude=dist",
    "--exclude=.claude",
    "--exclude=deploy.py",
]

def run_cmd(cmd, timeout=120):
    """Run command with pexpect, return output."""
    print(f"\n>>> {cmd[:100]}...")
    child = pexpect.spawn(cmd, timeout=timeout, encoding="utf-8")
    child.logfile_read = sys.stdout
    idx = child.expect(["password:", "yes/no", pexpect.EOF, pexpect.TIMEOUT], timeout=30)
    if idx == 1:
        child.sendline("yes")
        child.expect("password:", timeout=30)
        child.sendline(PASSWORD)
    elif idx == 0:
        child.sendline(PASSWORD)
    elif idx == 2:
        print("\nEOF reached before password prompt")
        return
    elif idx == 3:
        print("\nTIMEOUT waiting for password prompt")
        return
    child.expect(pexpect.EOF, timeout=timeout)
    print(child.before or "")
    child.close()
    if child.exitstatus != 0:
        print(f"Exit code: {child.exitstatus}")

# Step 1: Rsync
rsync_cmd = (
    f"rsync -avz {' '.join(EXCLUDES)} "
    f"-e ssh {PROJECT_DIR}/ {USER}@{HOST}:{REMOTE_DIR}/"
)
run_cmd(rsync_cmd, timeout=180)

# Step 2: Rebuild frontend on server
build_cmd = (
    f"ssh {USER}@{HOST} "
    f"'cd {REMOTE_DIR}/frontend && npm run build'"
)
run_cmd(build_cmd, timeout=120)

# Step 3: Restart services
restart_cmd = (
    f"ssh {USER}@{HOST} "
    f"'sudo systemctl restart stock-backend stock-bot stock-queue stock-strategy'"
)
run_cmd(restart_cmd, timeout=30)

print("\n✅ Deploy completed!")
