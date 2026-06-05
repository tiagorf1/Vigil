# Vigil GitHub Actions Setup

This is the one-time setup for free cloud scheduled scans.

## 1. GitHub Repo Settings

In your GitHub repository:

1. Open **Settings**.
2. Open **Secrets and variables** -> **Actions**.
3. Under **Secrets**, add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GEMINI_API_KEY` if you want Gemini-written reports in the cloud
4. Under **Variables**, add:
   - `SIGNAL_MARKETS=global-liquid`
   - `DEFAULT_PRED_LEN=90`
   - `KRONOS_MC_PATHS=24`
   - `MAX_SCREENED_SIZE=16`
   - `MAX_INDEX_COMPONENTS_LOCAL=80`

The workflow also has these defaults, so missing variables will not break the
first run. Secrets are still required for Telegram delivery.

## 2. Push This Folder To The Empty Repo

From this folder:

```bash
git init
git add .
git commit -m "Initial Vigil scanner"
git branch -M main
git remote add origin YOUR_GITHUB_REPO_URL
git push -u origin main
```

Use the HTTPS URL GitHub shows on the empty repository page, for example:

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

If Git says `remote origin already exists`, replace it:

```bash
git remote set-url origin YOUR_GITHUB_REPO_URL
```

## 3. Run The Workflow

1. Open the GitHub repo.
2. Open the **Actions** tab.
3. Choose **Vigil daily signals**.
4. Click **Run workflow**.
5. Leave the market input as `global-liquid` for the first run.

The first run downloads Kronos and caches the model. It will be slower than later
runs.

## 4. What The Default Cloud Profile Scans

`global-liquid` scans:

- US index ETFs: `SPY`, `QQQ`, `DIA`, `IWM`
- UK/Europe ETFs: `EWU`, `FEZ`, `EWG`, `EWQ`, `EWP`, `EWI`
- Asia ETFs: `EWJ`, `MCHI`, `FXI`, `EWY`, `EWT`, `INDA`
- Commodity ETFs: `GLD`, `SLV`, `USO`, `UNG`, `CPER`, `PPLT`, `PALL`, `DBA`, `CORN`, `WEAT`
- FX majors: `EURUSD=X`, `GBPUSD=X`, `USDJPY=X`, `USDCHF=X`, `USDCAD=X`, `AUDUSD=X`, `NZDUSD=X`, `EURJPY=X`, `GBPJPY=X`, `EURGBP=X`
- Crypto majors: `BTCUSD`, `ETHUSD`, `SOLUSD`, `BNBUSD`, `XRPUSD`, `ADAUSD`, `AVAXUSD`, `DOTUSD`, `LINKUSD`, `DOGEUSD`

## 5. Local Machine Guardrails

For local Mac scans:

- Comfortable: up to about `30 names x 60 days x 12 paths`.
- Heavy: around `30 names x 90 days x 24 paths`.
- Remote recommended: full component scans or anything much above that.

The app now warns before starting a heavy local Kronos run.
