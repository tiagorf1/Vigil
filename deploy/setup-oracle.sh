#!/usr/bin/env bash
# One-shot setup for an Oracle (or any Ubuntu) ARM/x86 VM.
# Run as the default user after SSH-ing in:  bash setup-oracle.sh
set -euo pipefail

echo "== Vigil cloud setup =="
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git
cd "$HOME"

# Vigil (replace with your repo URL or scp the folder up)
[ -d Vigil ] || git clone "${VIGIL_REPO:-https://github.com/youruser/Vigil.git}" Vigil
# Kronos (the forecaster)
[ -d Kronos ] || git clone https://github.com/shiyu-coder/Kronos.git Kronos

cd Vigil
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r "$HOME/Kronos/requirements.txt"

# .env: copy the example and fill secrets (GEMINI/TELEGRAM/FMP optional)
[ -f .env ] || cp .env.example .env
sed -i 's/^KRONOS_DEVICE=.*/KRONOS_DEVICE=cpu/' .env
sed -i 's/^VIGIL_START_OPENALICE=.*/VIGIL_START_OPENALICE=false/' .env

echo "== install systemd services =="
sudo cp deploy/vigil-worker.service /etc/systemd/system/
sudo cp deploy/vigil-bot.service /etc/systemd/system/
sudo sed -i "s#__HOME__#$HOME#g; s#__USER__#$USER#g" /etc/systemd/system/vigil-*.service
sudo systemctl daemon-reload
sudo systemctl enable --now vigil-worker vigil-bot

echo "== done. worker on :8090, telegram bot running. =="
echo "Edit secrets:  nano ~/Vigil/.env   then:  sudo systemctl restart vigil-worker vigil-bot"
