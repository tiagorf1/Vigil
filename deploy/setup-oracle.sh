#!/usr/bin/env bash
# One-shot setup for an Oracle (or any Ubuntu) ARM/x86 VM.
# Run as the default user after SSH-ing in:  bash setup-oracle.sh
set -euo pipefail

echo "== Vigil cloud setup =="
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git openssl curl
cd "$HOME"

# Vigil (your repo) + Kronos (the forecaster).
[ -d Vigil ]  || git clone "${VIGIL_REPO:-https://github.com/tiagorf1/Vigil.git}" Vigil
[ -d Kronos ] || git clone https://github.com/shiyu-coder/Kronos.git Kronos

cd Vigil
git pull --ff-only || true            # pick up latest if re-running
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip

# Torch: ARM64 (Oracle A1) needs the default PyPI aarch64 wheel; the CPU index
# is x86-only. Pick the right source by architecture.
ARCH="$(uname -m)"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
  echo "ARM64 detected -> installing torch from PyPI"
  pip install torch
else
  echo "x86_64 detected -> installing CPU torch wheel"
  pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
pip install -r requirements.txt -r "$HOME/Kronos/requirements.txt"

# .env: copy the example, force cloud-appropriate settings, and auto-generate a
# worker token so the open port is NOT free compute for the internet.
[ -f .env ] || cp .env.example .env
sed -i 's/^KRONOS_DEVICE=.*/KRONOS_DEVICE=cpu/' .env
sed -i 's/^VIGIL_START_OPENALICE=.*/VIGIL_START_OPENALICE=false/' .env
grep -q '^KRONOS_MODEL=' .env && sed -i 's#^KRONOS_MODEL=.*#KRONOS_MODEL=NeoQuasar/Kronos-base#' .env

CURTOK="$(grep '^VIGIL_WORKER_TOKEN=' .env | head -1 | cut -d= -f2 | tr -d ' ' || true)"
if [ -z "$CURTOK" ]; then
  TOKEN="$(openssl rand -hex 24)"
  sed -i "s|^VIGIL_WORKER_TOKEN=.*|VIGIL_WORKER_TOKEN=$TOKEN|" .env
else
  TOKEN="$CURTOK"
fi

echo "== install systemd services =="
sudo cp deploy/vigil-worker.service /etc/systemd/system/
sudo cp deploy/vigil-bot.service /etc/systemd/system/
sudo sed -i "s#__HOME__#$HOME#g; s#__USER__#$USER#g" /etc/systemd/system/vigil-*.service
sudo systemctl daemon-reload
# Start ONLY the worker now. The Telegram bot needs your token in .env first, so
# it is enabled later (it would otherwise crash-loop until secrets are set).
sudo systemctl enable --now vigil-worker

# Oracle's Ubuntu image blocks every port except 22 with local iptables, so the
# cloud Security List rule alone is not enough. Open :8090 on the OS firewall too.
echo "== open OS firewall for :8090 =="
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8090 -j ACCEPT 2>/dev/null || true
sudo netfilter-persistent save 2>/dev/null \
  || sudo bash -c 'mkdir -p /etc/iptables && iptables-save > /etc/iptables/rules.v4' 2>/dev/null || true

PUBIP="$(curl -s --max-time 5 ifconfig.me || echo '<your-vm-ip>')"
cat <<EOF

============================================================
  Vigil worker is running on  :8090
  Worker token (KEEP SECRET)  :  $TOKEN
============================================================

NEXT — fill your secrets:
  nano ~/Vigil/.env
    GEMINI_API_KEY=...           (your Gemini key)
    TELEGRAM_BOT_TOKEN=...       (optional, for signals)
    TELEGRAM_CHAT_ID=...         (optional)
  then:
    sudo systemctl restart vigil-worker
    sudo systemctl enable --now vigil-bot   # only if Telegram is configured

ON YOUR MAC — point the cockpit at this box (~/Scanner Project/.env):
    VIGIL_WORKER_URL=http://$PUBIP:8090
    VIGIL_WORKER_TOKEN=$TOKEN

Check it:   curl -s http://localhost:8090/ ; systemctl status vigil-worker
============================================================
EOF
