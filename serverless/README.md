# Vigil serverless forecasting (RunPod)

Replaces the manual GPU pod with a **scale-to-zero** endpoint: wakes on a
request, forecasts on GPU, sleeps. **$0 when idle, nothing to terminate.** Once
deployed, the box runs scans and only the forecasting goes here — results land
in the cockpit automatically. No web terminal.

## Deploy (no local Docker — let RunPod build it)

1. **RunPod → Serverless → New Endpoint → Import Git Repository.**
2. Repo: `https://github.com/tiagorf1/Vigil` · Dockerfile path: `serverless/Dockerfile`.
   RunPod builds the image for you (model baked in).
3. GPU: any **24GB** (e.g. RTX 4090 / A5000). Workers: **min 0**, max 1–2.
   Idle timeout: ~10s (scales to zero fast).
4. Deploy. Copy the **Endpoint ID**.
5. **RunPod → Settings → API Keys → create one.** Copy it.

(Alternative: build locally with `docker build -t <you>/vigil-kronos -f serverless/Dockerfile .`
then `docker push`, and point the endpoint at that image.)

## Point Vigil at it (on the box, once)

Add to `~/Vigil/.env`:
```
KRONOS_SERVERLESS_ENDPOINT=<endpoint id>
RUNPOD_API_KEY=<api key>
```
Then `sudo systemctl restart vigil-worker`. That's it — every scan now forecasts
on the serverless GPU, cold-starts in ~30–60s, and costs cents. To go back to
local CPU, comment those two lines out.

## How it wires in
- `config.kronos_is_serverless` flips on when both vars are set.
- `kronos_client.forecast_batch` submits chunked async jobs to
  `https://api.runpod.ai/v2/<id>/run`, polls `/status/<job>`, returns the same
  `{symbol: forecast}` shape — so `run.py`, `signals.py`, and `backtest.py` are
  unchanged.
- `serverless/handler.py` loads Kronos once per warm worker and answers
  `forecast_batch`.

## Cost
Pay per compute-second only. A daily S&P scan ≈ a few minutes of GPU ≈ pennies.
No idle billing, no pod to forget about.
