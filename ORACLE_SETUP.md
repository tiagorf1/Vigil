# Vigil on Oracle Cloud

End state: Oracle runs the heavy worker and Telegram bot. Your Mac only opens the
Vigil cockpit and submits jobs to the worker. You still choose what to screen and
when to run it.

## Current Oracle wizard note

Oracle's Create Instance wizard is now split into steps:

1. Basic Information
2. Security
3. Networking
4. Storage
5. Review

The SSH key section is no longer beside Image and Shape in every console layout.
It is under **Networking -> Add SSH Keys (Linux)**.

If you do not see SSH keys, confirm you are creating a Linux VM from:
**Compute -> Instances -> Create instance**, then continue to the Networking step.

## 1. Create the VM

1. In Oracle Cloud, open **Compute -> Instances -> Create instance**.
2. Name it `vigil`.
3. In **Image and shape**, choose:
   - Image: **Canonical Ubuntu 22.04**
   - Shape: **Ampere VM.Standard.A1.Flex**
   - OCPUs: `4`
   - Memory: `24 GB`
4. Continue to **Networking**.
5. Use a public subnet and keep **Automatically assign public IPv4 address** on.
6. Under **Add SSH Keys (Linux)**, use one of these options:

### Option A: Oracle generates the key

1. Choose **Generate a key pair for me**.
2. Click **Save Private Key**.
3. Save the downloaded private key somewhere safe.
4. Click **Save Public Key** too if Oracle offers it.

On your Mac, rename and lock the private key:

```bash
mv ~/Downloads/ssh-key-*.key ~/.ssh/vigil-oracle.key
chmod 600 ~/.ssh/vigil-oracle.key
```

### Option B: You create the key on your Mac

This is usually cleaner because the private key never leaves your Mac.

```bash
mkdir -p ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/vigil-oracle -C vigil-oracle
cat ~/.ssh/vigil-oracle.pub
```

In Oracle, choose **Paste public keys** and paste the output from the `cat`
command. Do not paste the private key.

7. Continue to **Review**, then click **Create**.
8. Wait until the instance says **Running**.
9. Copy the **Public IPv4 address**. Call it `YOUR_IP`.

If Oracle says the A1 shape is out of capacity, try another Availability Domain,
wait a few hours, or switch region. That is the common Oracle free-tier snag.

## 2. Open the ports to your home IP

Find your home public IP:

```bash
curl https://ifconfig.me
```

Call that value `MY_HOME_IP` = 213.22.99.97

In Oracle, open the instance page, then:

1. Click the **Subnet** link under the primary VNIC.
2. Click the default **Security List**.
3. Click **Add Ingress Rules**.
4. Add SSH if it is not already there:
   - Source CIDR: `MY_HOME_IP/32`
   - IP Protocol: `TCP`
   - Destination Port Range: `22`
5. Add the Vigil worker port:
   - Source CIDR: `MY_HOME_IP/32`
   - IP Protocol: `TCP`
   - Destination Port Range: `8090`

This keeps the worker reachable from your home internet only. The worker also
requires `VIGIL_WORKER_TOKEN`, so an open port is not free compute for strangers.

## 3. Connect from your Mac

If Oracle generated the key:

```bash
ssh -i ~/.ssh/vigil-oracle.key ubuntu@YOUR_IP
```

If you generated the key locally:

```bash
ssh -i ~/.ssh/vigil-oracle ubuntu@YOUR_IP
```

Type `yes` if macOS asks about authenticity. The prompt should change to something
like `ubuntu@vigil`.

## 4. Copy Vigil to the server

From a second Mac terminal tab, copy the project folder up:

```bash
rsync -av \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'outputs/*.json' \
  -e "ssh -i ~/.ssh/vigil-oracle" \
  "/Users/tiagoferreira/Scanner Project/" \
  ubuntu@YOUR_IP:~/Vigil/
```

If you used Oracle's generated key, change the `-i` path to:

```bash
-e "ssh -i ~/.ssh/vigil-oracle.key"
```

## 5. Install on the server

Back in the server terminal:

```bash
cd ~/Vigil
bash deploy/setup-oracle.sh
nano .env
```

Set at least:

```bash
GEMINI_API_KEY=your_key
LLM_PROVIDER=gemini
VIGIL_START_OPENALICE=false
KRONOS_DEVICE=cpu
VIGIL_WORKER_TOKEN=make_a_long_random_secret
```

Optional Telegram:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Restart and check:

```bash
sudo systemctl restart vigil-worker vigil-bot
systemctl status vigil-worker
```

It should say `active (running)`.

## 6. Point your Mac at Oracle

On the Mac, edit `/Users/tiagoferreira/Scanner Project/.env`:

```bash
VIGIL_WORKER_URL=http://YOUR_IP:8090
VIGIL_WORKER_TOKEN=the_same_long_random_secret
VIGIL_START_OPENALICE=false
```

Then launch normally:

```bash
cd "/Users/tiagoferreira/Scanner Project"
python3 -m scanner.server
```

The browser cockpit opens locally, but scans run on Oracle.

## 7. Quick worker test

From the Mac:

```bash
curl -s -X POST "http://YOUR_IP:8090/jobs" \
  -H "Content-Type: application/json" \
  -H "X-Vigil-Token: the_same_long_random_secret" \
  -d '{"directive":"AAPL MSFT","asset_class":"equity","provider":"none","offline":true,"max_results":2}'
```

It should return a `job_id`. Use that id here:

```bash
curl -s "http://YOUR_IP:8090/jobs/JOB_ID"
curl -s -H "X-Vigil-Token: the_same_long_random_secret" "http://YOUR_IP:8090/jobs/JOB_ID/result"
```

## 8. Optional scheduled signals

On the server:

```bash
crontab -e
```

Add:

```bash
0 12 * * 1-5 cd ~/Vigil && .venv/bin/python -m scanner.signals
```

That runs weekday signals from Oracle.
