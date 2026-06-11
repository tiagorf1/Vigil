# Vigil Kronos forecasting — RunPod serverless image.
# Bakes the model into the image so cold starts don't re-download (~400MB).
# Build via RunPod's GitHub integration (no local Docker needed) or:
#   docker build -t <you>/vigil-kronos:latest -f serverless/Dockerfile .
#   docker push <you>/vigil-kronos:latest
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /
RUN git clone --depth 1 https://github.com/shiyu-coder/Kronos.git /Kronos && \
    git clone --depth 1 https://github.com/tiagorf1/Vigil.git /Vigil

WORKDIR /Vigil
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r /Kronos/requirements.txt && \
    pip install --no-cache-dir runpod

ENV KRONOS_REPO_PATH=/Kronos \
    KRONOS_MODEL=NeoQuasar/Kronos-base \
    KRONOS_TOKENIZER=NeoQuasar/Kronos-Tokenizer-base \
    KRONOS_DEVICE=cuda \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    PYTHONPATH=/Vigil

# Pre-download model + tokenizer into the image layer.
RUN python -c "from huggingface_hub import snapshot_download; \
    snapshot_download('NeoQuasar/Kronos-base'); \
    snapshot_download('NeoQuasar/Kronos-Tokenizer-base')"

CMD ["python", "-u", "/Vigil/serverless/handler.py"]
