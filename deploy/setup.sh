#!/usr/bin/env bash
set -euo pipefail

# Polymarket Bot — Oracle Cloud ARM Setup
# Run as: bash setup.sh
# Prerequisites: Ubuntu 22.04+ ARM instance with SSH access

echo "=== Polymarket Bot Setup ==="
echo ""

# 1. System packages
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-dev git curl

# 2. Clone or update repo
REPO_DIR="$HOME/polymarket"
if [ -d "$REPO_DIR" ]; then
    echo "[2/6] Updating existing repo..."
    cd "$REPO_DIR"
    git pull
else
    echo "[2/6] Cloning repo..."
    # Replace with your actual repo URL
    echo "ERROR: No repo found at $REPO_DIR"
    echo "Upload your code first:"
    echo "  scp -r /path/to/polymarket ubuntu@<your-ip>:~/"
    echo "Then re-run this script."
    exit 1
fi

# 3. Python venv
echo "[3/6] Setting up Python virtual environment..."
cd "$REPO_DIR"
python3.12 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# 4. Check .env
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "[4/6] Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "  *** IMPORTANT: Edit .env with your credentials ***"
    echo "  Run: nano $REPO_DIR/.env"
    echo ""
else
    echo "[4/6] .env already exists"
fi

# 5. Install systemd service
echo "[5/6] Installing systemd service..."
sudo cp "$REPO_DIR/deploy/polybot.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polybot

# 6. Preflight check
echo "[6/6] Running preflight check..."
cd "$REPO_DIR"
.venv/bin/python preflight.py || true

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Commands:"
echo "  Start bot:    sudo systemctl start polybot"
echo "  Stop bot:     sudo systemctl stop polybot"
echo "  View logs:    journalctl -u polybot -f"
echo "  Bot status:   sudo systemctl status polybot"
echo "  Live mode:    Edit /etc/systemd/system/polybot.service"
echo "                Add --live flag, then: sudo systemctl restart polybot"
echo ""
