# Brahma Setup Documentation

> Machine: `brahma` — Grace-Blackwell (ARM SBSA) server with unified memory.

## Architecture Overview

```
Host (brahma)
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │  hermes-net (172.19.0.0/16, user-defined bridge)                                │
 │                                                                                 │
 │  ┌─────────────────────────┐  ┌──────────────────────────────────┐             │
 │  │ vLLM (vllm-llm)          │  │ Hermes (hermes)                  │             │
 │  │ 172.19.0.3               │  │ GPU: no                          │             │
 │  │ GPU: yes                 │  │ Vol: hermes-data → /opt/data     │             │
 │  │ Port: 11002→8000         │  │ Vol: hermes-venv → /.venv        │             │
 │  │ SSL: /certs/*.pem        │  │ Gateway + Dashboard              │             │
 │  │ Model: Qwen3.6-35B-A3B   │  └──────────────────────────────────┘             │
 │  └──────────┬──────────────┘                                                    │
 │             │ https://vllm-llm:8000/v1 (CA signed, hermes-net)                   │
 │             │                                                                   │
 │  ┌──────────┴──────────────┐    ┌──────────────────────────┐                    │
 │  │ OpenWebUI (open-webui)   │    │ Open Terminal            │                    │
 │  │ Network: hermes-net      │◄──►│ (open-terminal)          │                    │
 │  │ Port: 12000→8080         │    │ RAM: 2g, CPU: 2          │                    │
 │  │ GPU: yes                 │    │ Slim: 430MB              │                    │
 │  │ SSL_CERT_FILE: combined  │    │ No GPU, no egress        │                    │
 │  │ Terminal: auto-configured│    └──────────────────────────┘                    │
 │  │ STT: whisper-stt:9001    │                                                   │
 │  │ TTS: kokoro-tts:8880     │                                                   │
 │  └──────┬──────────┬───────┘                                                   │
 │         │          │                                                            │
 │  ┌──────┴────┐ ┌───┴───────┐    ┌──────────────────┐                            │
 │  │whisper-stt│ │kokoro-tts │    │ Caddy (caddy)     │                            │
 │  │ GPU: yes  │ │ GPU: yes  │    │ Port: 443 (HTTPS) │                            │
 │  │ Port:9001 │ │ Port:8880 │    │ Proxy → webui:8080│                            │
 │  │Whisper Lrg│ │Kokoro-82M │    │ Self-signed certs │                            │
 │  └───────────┘ └───────────┘    └──────────────────┘                            │
 │                                                                                 │
 │  SparkyUI / ComfyUI (optional, currently off)                                   │
 │  sparky_net bridge, GPU: yes, Port: 8188                                       │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

## Services

### 1. vLLM — LLM Inference Engine

Runs `Qwen/Qwen3.6-35B-A3B-FP8` with GPU acceleration.

**Container:** `vllm-llm`
**Image:** `vllm/vllm-openai:latest`
**Networks:** `hermes-net` (172.19.0.3), `bridge` (172.17.0.2)
**Port:** `11002:8000` (host → container)
**GPU:** all GPUs via `--gpus all`
**SSL:** certs mounted from `~/.hermes/certs/`
**Cache:** HF cache at `~/.cache/huggingface`
**Auto-start:** `systemctl --user enable vllm-llm` (enabled, starts on boot via systemd user service)

Run command:
```bash
docker run --gpus all \
  --name vllm-llm \
  --network hermes-net \
  -p 11002:8000 \
  --shm-size=32g \
  --restart no \
  -e HF_TOKEN=hf_... \
  -v /home/rajatpandit/.cache/huggingface:/root/.cache/huggingface \
  -v /home/rajatpandit/.hermes/certs:/certs:ro \
  vllm/vllm-openai:latest \
  Qwen/Qwen3.6-35B-A3B-FP8 \
  --host 0.0.0.0 --port 8000 \
  --ssl-keyfile /certs/server-key.pem \
  --ssl-certfile /certs/server.pem \
  --max-model-len 262144 \
  --max-num-batched-tokens 16384 \
  --gpu-memory-utilization 0.65 \
  --load-format fastsafetensors \
  --attention-backend flashinfer \
  --kv-cache-dtype fp8 \
  --enable-prefix-caching \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --max-num-seqs 64 \
  --trust-remote-code
```

**Verify:**
```bash
curl -k https://localhost:11002/v1/models
curl http://vllm-llm:8000/v1/models    # from hermes-net
```

---

### 2. OpenWebUI — Chat Interface

Web UI for interacting with LLMs. Connects to vLLM via HTTPS on `hermes-net`. Uses GPU acceleration for local Whisper STT (`whisper-stt`) and Kokoro TTS (`kokoro-tts`) — all audio processing is fully local with no cloud dependency.

**Container:** `open-webui`
**Image:** `ghcr.io/open-webui/open-webui:cuda`
**Network:** `hermes-net` (not bridge — avoids hairpin NAT issues with host-published ports)
**Port:** `12000:8080`
**GPU:** yes (`--gpus all`)
**API Base:** `https://vllm-llm:8000/v1`
**SSL:** Combined CA bundle at `/tmp/combined_ca_bundle.pem` (system CAs + local CA for vLLM), mounted at `/certs/combined-ca-bundle.pem`, trusted via `SSL_CERT_FILE`
**STT:** External OpenAI-compatible Whisper server at `http://whisper-stt:9001/v1` (GPU)
**TTS:** External OpenAI-compatible Kokoro server at `http://kokoro-tts:8880/v1` (GPU)

Run command:
```bash
OPEN_TERMINAL_KEY=$(cut -d= -f2- < ~/.hermes/certs/open-terminal-key.env)

# Build combined CA bundle (system CAs + local CA)
cat /etc/ssl/certs/ca-certificates.crt \
  /home/rajatpandit/.hermes/certs/ca.pem \
  > /tmp/combined_ca_bundle.pem

docker run -d \
  --name open-webui \
  -p 12000:8080 \
  --network hermes-net \
  --restart unless-stopped \
  --gpus all \
  -e OPENAI_API_BASE_URLS="https://vllm-llm:8000/v1" \
  -e USE_CUDA_DOCKER=true \
  -e AUDIO_STT_ENGINE="openai" \
  -e AUDIO_STT_OPENAI_API_BASE_URL="http://whisper-stt:9001/v1" \
  -e AUDIO_STT_OPENAI_API_KEY="not-needed-but-required" \
  -e AUDIO_STT_MODEL="whisper-1" \
  -e AUDIO_TTS_ENGINE="openai" \
  -e AUDIO_TTS_OPENAI_API_BASE_URL="http://kokoro-tts:8880/v1" \
  -e AUDIO_TTS_OPENAI_API_KEY="not-needed-but-required" \
  -e AUDIO_TTS_VOICE="alloy" \
  -e DO_NOT_TRACK=true \
  -e RAG_EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2" \
  -e AUXILIARY_EMBEDDING_MODEL="TaylorAI/bge-micro-v2" \
  -e ANONYMIZED_TELEMETRY=false \
  -e SCARF_NO_ANALYTICS=true \
  -e SSL_CERT_FILE="/certs/combined-ca-bundle.pem" \
  -e TERMINAL_SERVER_CONNECTIONS="[{\"id\":\"open-terminal\",\"url\":\"http://open-terminal:8000\",\"key\":\"${OPEN_TERMINAL_KEY}\",\"name\":\"Open Terminal\",\"auth_type\":\"bearer\"}]" \
  -v open-webui-data:/app/backend/data \
  -v /tmp/combined_ca_bundle.pem:/certs/combined-ca-bundle.pem:ro \
  ghcr.io/open-webui/open-webui:cuda
```

**Environment:**
| Variable | Value |
|----------|-------|
| `OPENAI_API_BASE_URLS` | `https://vllm-llm:8000/v1` |
| `USE_CUDA_DOCKER` | `true` |
| `AUDIO_STT_ENGINE` | `openai` |
| `AUDIO_STT_OPENAI_API_BASE_URL` | `http://whisper-stt:9001/v1` |
| `AUDIO_STT_MODEL` | `whisper-1` |
| `AUDIO_TTS_ENGINE` | `openai` |
| `AUDIO_TTS_OPENAI_API_BASE_URL` | `http://kokoro-tts:8880/v1` |
| `AUDIO_TTS_VOICE` | `alloy` |
| `RAG_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `AUXILIARY_EMBEDDING_MODEL` | `TaylorAI/bge-micro-v2` |
| `SSL_CERT_FILE` | `/certs/combined-ca-bundle.pem` |
| `TERMINAL_SERVER_CONNECTIONS` | JSON array pre-configuring Open Terminal integration |

**Access:** http://brahma:12000 or https://brahma (via Caddy reverse proxy)

**Note:** Must be on `hermes-net` to resolve `vllm-llm` hostname. The combined CA bundle merges system CA certificates (for HuggingFace, PyPI, etc.) with the local CA (for vLLM's self-signed cert).

---

### 3. Open Terminal — Remote Shell for AI Agents

Lightweight remote shell server that OpenWebUI AI assistants can use to run commands, manage files, and install packages. Integrated via OpenWebUI's admin panel (pre-configured via `TERMINAL_SERVER_CONNECTIONS`).

**Container:** `open-terminal`
**Image:** `ghcr.io/open-webui/open-terminal:slim` (430MB, no sudo, git/curl/jq)
**Network:** `hermes-net` (no host port exposed — internal only)
**RAM/CPU:** `--memory 2g --cpus 2`
**GPU:** none
**Egress:** restricted to `pypi.org,github.com,files.pythonhosted.org` (pip install + git clone)

Run command:
```bash
docker volume create open-terminal-data

docker run -d \
  --name open-terminal \
  --network hermes-net \
  --restart unless-stopped \
  --memory 2g \
  --cpus 2 \
  -e OPEN_TERMINAL_API_KEY="$(openssl rand -hex 32)" \
  -e OPEN_TERMINAL_ALLOWED_DOMAINS="pypi.org,github.com,files.pythonhosted.org" \
  -v open-terminal-data:/home/user \
  ghcr.io/open-webui/open-terminal:slim
```

**API Key:** stored at `~/.hermes/certs/open-terminal-key.env` (git-ignored, `chmod 600`). Also injected into OpenWebUI via `TERMINAL_SERVER_CONNECTIONS`.

**Security notes:**
- No host port exposure — reachable only from `hermes-net` containers
- API key required (Bearer auth) — auto-generated at first run, rotate via `OPEN_TERMINAL_API_KEY`
- Egress restricted to package repositories only
- Memory/CPU capped via Docker flags
- No Docker socket mount
- No TLS needed — traffic stays on private Docker network

**Verify:**
```bash
docker exec open-webui sh -c 'curl -s http://open-terminal:8000/health'
```

---

### 4. Whisper STT — GPU-Accelerated Speech-to-Text

Local GPU-accelerated Whisper Large speech-to-text server. Exposes an OpenAI-compatible `/v1/audio/transcriptions` endpoint for OpenWebUI. Replaces the built-in CPU Whisper with full GPU acceleration on the DGX Spark.

Uses `openai-whisper` (PyTorch-native) instead of `faster-whisper` (CTranslate2) because CTranslate2 does not ship CUDA wheels for `aarch64`.

**Container:** `whisper-stt`
**Image:** `whisper-stt` (custom, built locally)
**Network:** `hermes-net`
**Port:** `9001` (internal to hermes-net)
**GPU:** yes (`--gpus all`)
**Model:** Whisper `large` (~3 GB on GPU, ~4 GB transient during transcription)
**Framework:** PyTorch 2.9.1+cu128, CUDA 12.8 (ARM64)

#### Build

```bash
cd ~/whisper-stt
docker build -t whisper-stt .
```

#### Run

```bash
docker run -d \
  --name whisper-stt \
  --network hermes-net \
  --gpus all \
  -p 9001:9001 \
  --restart unless-stopped \
  whisper-stt
```

#### Dockerfile

`~/whisper-stt/Dockerfile`:
```dockerfile
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip3 install torch==2.9.1+cu128 \
    --index-url https://download.pytorch.org/whl/cu128

RUN pip3 install openai-whisper fastapi uvicorn python-multipart

COPY whisper_server.py .

EXPOSE 9001
CMD ["uvicorn", "whisper_server:app", "--host", "0.0.0.0", "--port", "9001"]
```

#### API

- `POST /v1/audio/transcriptions` — accepts audio file upload, returns `{"text": "..."}`
- `GET /health` — health check

**Verify:**
```bash
curl -s http://whisper-stt:9001/health
# {"status":"ok"}
```

---

### 5. Kokoro TTS — GPU-Accelerated Text-to-Speech

Local GPU-accelerated Kokoro-82M text-to-speech server. Exposes an OpenAI-compatible `/v1/audio/speech` endpoint. Features 54 voices, ~1 GB GPU footprint, fully local with no cloud dependency.

**Container:** `kokoro-tts`
**Image:** `kokoro-tts` (custom, built locally)
**Network:** `hermes-net`
**Port:** `8880` (internal to hermes-net)
**GPU:** yes (`--gpus all`)
**Model:** Kokoro-82M (~1 GB on GPU)
**Framework:** PyTorch 2.9.1+cu128, CUDA 12.8 (ARM64)
**Voices:** 54 (default `alloy` maps to `af_heart`; see `kokoro_server.py` for voice map)

#### Build

```bash
cd ~/kokoro-tts
docker build -t kokoro-tts .
```

#### Run

```bash
docker run -d \
  --name kokoro-tts \
  --network hermes-net \
  --gpus all \
  -p 8880:8880 \
  --restart unless-stopped \
  kokoro-tts
```

#### Dockerfile

`~/kokoro-tts/Dockerfile`:
```dockerfile
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip3 install torch==2.9.1+cu128 \
    --index-url https://download.pytorch.org/whl/cu128

RUN pip3 install kokoro soundfile fastapi uvicorn python-multipart

COPY kokoro_server.py .

EXPOSE 8880
CMD ["uvicorn", "kokoro_server:app", "--host", "0.0.0.0", "--port", "8880"]
```

#### Voice Map

| OpenAI Voice | Kokoro Voice |
|-------------|--------------|
| `alloy`     | `af_heart`   |
| `echo`      | `am_mind`    |
| `fable`     | `af_bella`   |
| `nova`      | `am_adam`    |
| `onyx`      | `am_michael` |
| `shimmer`   | `af_nicole`  |

#### API

- `POST /v1/audio/speech` — accepts `{ model, input, voice, response_format, speed }`, returns WAV audio
- `GET /health` — health check

**Verify:**
```bash
curl -s http://kokoro-tts:8880/health
# {"status":"ok"}
```

---

### 6. Caddy — HTTPS Reverse Proxy

Serves HTTPS on port 443 using self-signed certificates, proxying to OpenWebUI's HTTP port 8080. Required for microphone access in the browser (browsers block `getUserMedia` on non-HTTPS origins).

**Container:** `caddy`
**Image:** `caddy:latest`
**Network:** `hermes-net`
**Ports:** `80:80`, `443:443`
**Certs:** from `~/.hermes/certs/` (mounted at `/certs`)

#### Caddyfile

`~/Caddyfile`:
```
brahma, brahma.local {
    tls /certs/server.pem /certs/server-key.pem

    reverse_proxy open-webui:8080
}
```

#### Run

```bash
docker run -d \
  --name caddy \
  --network hermes-net \
  -p 80:80 \
  -p 443:443 \
  --restart unless-stopped \
  -v /home/rajatpandit/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v /home/rajatpandit/.hermes/certs:/certs:ro \
  caddy:latest
```

#### Combined CA Bundle

OpenWebUI needs to trust both system CA certificates (for HuggingFace, PyPI) and the local CA (for vLLM's self-signed cert). A combined bundle is created at `/tmp/combined_ca_bundle.pem`:

```bash
cat /etc/ssl/certs/ca-certificates.crt \
  /home/rajatpandit/.hermes/certs/ca.pem \
  > /tmp/combined_ca_bundle.pem
```

This is mounted into OpenWebUI at `/certs/combined-ca-bundle.pem` and referenced via `SSL_CERT_FILE`.

---

### 7. Hermes — AI Agent (Messaging Gateway)

Runs inside Docker with sandboxed access.

**Container:** `hermes-sandbox`
**Image:** `hermes-agent:latest` (built locally)
**Network:** `hermes-net` (not host — connects to vLLM + OpenWebUI internally)
**Volumes:** `hermes-data` → `/opt/data` (config, sessions, logs, skills); `hermes-venv` → `/opt/hermes/.venv` (persistent Python venv)
**Browser:** Debian Chromium (ARM64) installed in volume, uses `chromium-wrapper.sh` for library path

#### Build
```bash
cd ~/.hermes/hermes-agent
docker build -t hermes-agent:latest .
```

#### Data Volumes
```bash
docker volume create hermes-data      # config, sessions, logs, skills, Chromium
docker volume create hermes-venv      # persistent Python venv (survives container recreate)
```

- `hermes-data` is seeded via `~/.hermes/seed-sandbox.sh` with `config.yaml` and `.env`.
- `hermes-venv` is seeded automatically by `manage-sandbox.sh` on first start — copies the image's `/opt/hermes/.venv/` into the volume so packages installed by Hermes (`uv pip install`, `lazy_deps.py`) survive container recreation.
- On rebuild, re-seed `hermes-venv` to pick up new base dependencies: `docker volume rm hermes-venv && ~/.hermes/manage-sandbox.sh start`.

#### Run
```bash
~/.hermes/manage-sandbox.sh start
```

The management script runs `docker rm` + `docker run` every time, so only volume data survives. The `hermes-venv` volume (mounted at `/opt/hermes/.venv/`) ensures Python packages installed by Hermes persist across restarts.

#### Config (`config.yaml` — inside volume)
| Key | Value |
|-----|-------|
| `model.default` | `Qwen/Qwen3.6-35B-A3B-FP8` |
| `model.provider` | `custom` |
| `model.base_url` | `http://brahma:11002/v1` |
| `model.context_length` | `131072` |
| `agent.max_turns` | `90` |
| `agent.reasoning_effort` | `medium` |

#### Host Service (disabled)
The old system-level `hermes-gateway.service` is **disabled** and **stopped**. The gateway now runs inside the Docker container only.

```bash
sudo systemctl disable --now hermes-gateway.service   # already done
```

#### Management
```bash
~/.hermes/manage-sandbox.sh start     # Start container
~/.hermes/manage-sandbox.sh stop      # Stop container
~/.hermes/manage-sandbox.sh status    # Check status
~/.hermes/manage-sandbox.sh logs      # Follow logs
~/.hermes/manage-sandbox.sh cli       # Open CLI inside container
~/.hermes/manage-sandbox.sh rebuild   # Rebuild image
~/.hermes/manage-sandbox.sh reseed    # Re-seed config
```

#### Sandbox Environment

All persistent data lives in two Docker volumes: `hermes-data` (mounted at `/opt/data`) and `hermes-venv` (mounted at `/opt/hermes/.venv`). The container is recreated on every `start` — only the volumes survive.

| Item | Location | Persists? |
|------|----------|-----------|
| Config | `/opt/data/config.yaml` | ✅ Volume |
| Secrets | `/opt/data/.env` | ✅ Volume |
| Sessions/DB | `/opt/data/state.db` | ✅ Volume |
| Skills | `/opt/data/skills/` | ✅ Volume |
| Logs | `/opt/data/logs/` | ✅ Volume |
| Chromium | `/opt/data/chromium/` | ✅ Volume (installed once) |
| Browser wrapper | `/opt/data/chromium-wrapper.sh` | ✅ Volume |
| CA bundle | `/opt/data/combined-ca.pem` | ✅ Volume (rebuilt per start) |
| Python venv (user) | `/opt/data/.venv/` | ✅ Volume |
| Workspace | `/opt/data/workspace/` | ✅ Volume |
| Hermes software | `/opt/hermes/` | ❌ Image (rebuilt on `rebuild`) |
| Playwright Chromium | `/opt/hermes/.playwright/` | ❌ Image |
| Python venv (system) | `/opt/hermes/.venv/` | ✅ Volume (`hermes-venv`) |

**Available runtimes and tools (inside container):**

| Tool | Path | Version |
|------|------|---------|
| Python 3 | `/usr/bin/python3` | 3.13.5 |
| Node.js | `/usr/bin/node` | v20.19.2 |
| npm | `/usr/bin/npm` | 9.2.0 |
| git | `/usr/bin/git` | — |
| curl | `/usr/bin/curl` | — |
| ripgrep | `/usr/bin/rg` | — |
| ffmpeg | `/usr/bin/ffmpeg` | — |
| openssl | `/usr/bin/openssl` | — |
| gcc | `/usr/bin/gcc` | — |
| make | `/usr/bin/make` | — |
| uv (package mgr) | `/usr/local/bin/uv` | — |
| tini | `/usr/bin/tini` | — |
| Docker (DinD) | `/usr/bin/docker` | — |
| Chromium (headless) | `/opt/data/chromium-wrapper.sh` | 148.0.7778.178 |
| Chromium (headless shell) | `/opt/hermes/.playwright/chromium_headless_shell-1223/chrome-linux/headless_shell` | 1223 |

**Environment variables:**

| Variable | Value |
|----------|-------|
| `HERMES_HOME` | `/opt/data` |
| `HERMES_DASHBOARD` | `1` |
| `SSL_CERT_FILE` | `/opt/data/combined-ca.pem` |
| `CHROME_PATH` | `/opt/data/chromium-wrapper.sh` |
| `CHROME_BIN` | `/opt/data/chromium-wrapper.sh` |
| `PLAYWRIGHT_CHROMIUM_PATH` | `/opt/data/chromium-wrapper.sh` |
| `PATH` | `/opt/data/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` |

**Network:** `hermes-net` bridge — can reach `vllm-llm:8000`, `open-webui:8080`, `open-terminal:8000` by hostname. No host port exposure by default (dashboard UI on `127.0.0.1:9119`).

**Browser resolution:** The Debian `chromium` package (ARM64-native) is installed into the data volume to work around `agent-browser`/`browser-use` failing to download `chromium-for-testing` (no ARM64 builds). The wrapper sets `LD_LIBRARY_PATH` for the non-standard install path. Installed once; detected and skipped on subsequent container starts.

---

### 8. SparkyUI / ComfyUI — Image Generation (Optional)

**Container:** `comfyui` (currently exited)
**Image:** `sparkyui:cu130`
**Network:** `sparky_net` (bridge)
**Port:** `8188`
**GPU:** yes (NVIDIA, all GPUs)

```bash
cd ~/sparkyui
docker compose up -d
```

Access at http://brahma:8188.

---

## Networking

### Docker Networks

| Network | Driver | Subnet | Purpose |
|---------|--------|--------|---------|
| `hermes-net` | bridge | 172.19.0.0/16 | vLLM ↔ OpenWebUI ↔ Hermes ↔ STT/TTS |
| `open-webui_default` | bridge | — | OpenWebUI internal (unused) |
| `sparky_net` | bridge | — | ComfyUI internal |
| `bridge` | bridge | 172.17.0.0/16 | Default Docker bridge |

### Container Network Map

| Container | Networks | IPs |
|-----------|----------|-----|
| `vllm-llm` | hermes-net, bridge | 172.19.0.3, 172.17.0.2 |
| `open-webui` | hermes-net | — |
| `open-terminal` | hermes-net | — |
| `whisper-stt` | hermes-net | — |
| `kokoro-tts` | hermes-net | — |
| `caddy` | hermes-net | — |
| `hermes-sandbox` | hermes-net | — |
| `comfyui` | sparky_net | — |

### iptables Hardening

A DROP rule in `DOCKER-USER` chain blocks `hermes-net` from reaching the Docker bridge subnet:

```bash
iptables -I DOCKER-USER -i br-6e123b98ba63 -d 172.17.0.0/16 -j DROP
```

Survives reboot via `hermes-iptables-restore.service`:
```bash
sudo systemctl enable --now hermes-iptables-restore.service
```

---

## Management Scripts

| Script | Purpose |
|--------|---------|
| `~/.hermes/manage-sandbox.sh` | Start/stop/status/logs/rebuild/reseed Hermes sandbox |
| `~/.hermes/seed-sandbox.sh` | Populates `hermes-data` volume with config + secrets |
| `scripts/snapshot.sh` | Dump live container configs for cross-referencing docs |

---

## Troubleshooting

### Hermes won't start
```bash
~/.hermes/manage-sandbox.sh logs
docker logs hermes
```

### vLLM unreachable from Hermes
```bash
docker exec hermes curl -k https://brahma:11002/v1/models
docker exec hermes curl http://vllm-llm:8000/v1/models
```

If the container can't resolve `vllm-llm`, ensure both are on `hermes-net`:
```bash
docker network connect hermes-net vllm-llm
```

### iptables rule blocking legitimate traffic
```bash
sudo iptables -D DOCKER-USER -i br-6e123b98ba63 -d 172.17.0.0/16 -j DROP
```

### Open Terminal unreachable from OpenWebUI
```bash
docker exec open-webui sh -c 'curl -s http://open-terminal:8000/health'
```
If it fails, verify both are on `hermes-net`:
```bash
docker network inspect hermes-net --format '{{range .Containers}}{{.Name}} {{end}}'
```

### Whisper STT not responding
```bash
curl -s http://whisper-stt:9001/health
docker logs whisper-stt --tail 20
```
First load downloads the Whisper `large` model (~3 GB) — check logs for download progress.

### Kokoro TTS not responding
```bash
curl -s http://kokoro-tts:8880/health
docker logs kokoro-tts --tail 20
```
First load downloads the Kokoro model from HuggingFace.

### Caddy not serving HTTPS
```bash
docker logs caddy
```
Ensure cert files exist at `~/.hermes/certs/{server.pem,server-key.pem,ca.pem}`. Caddy will fail if they're missing.

### Combined CA bundle needs regeneration
If vLLM or HuggingFace certs change, regenerate the bundle:
```bash
cat /etc/ssl/certs/ca-certificates.crt \
  /home/rajatpandit/.hermes/certs/ca.pem \
  > /tmp/combined_ca_bundle.pem
docker restart open-webui
```

### Docker daemon not starting
```bash
sudo systemctl status docker
sudo journalctl -u docker --no-pager -n 50
```

---

## Rollback

To revert to host-based Hermes:

```bash
# 1. Stop sandboxed Hermes
systemctl --user stop hermes-gateway
docker stop hermes

# 2. Restore old system-level gateway
sudo systemctl enable --now hermes-gateway

# 3. Remove iptables hardening
sudo iptables -D DOCKER-USER -i br-6e123b98ba63 -d 172.17.0.0/16 -j DROP
sudo systemctl disable --now hermes-iptables-restore.service
sudo rm /etc/systemd/system/hermes-iptables-restore.service
sudo systemctl daemon-reload

# 4. Disconnect vLLM from hermes-net
docker network disconnect hermes-net vllm-llm

# 5. Clean up sandbox resources
docker rm hermes-sandbox  # or: docker rm hermes
docker volume rm hermes-data
docker network rm hermes-net
systemctl --user disable hermes-gateway
rm ~/.config/systemd/user/hermes-gateway.service
```

---

## Quick Reference

### Current Status (as of 2026-05-30)

| Service | Container | Status | Port |
|---------|-----------|--------|------|
| vLLM | `vllm-llm` | ✅ Running (auto-start enabled) | 11002 |
| OpenWebUI | `open-webui` | ✅ Running (GPU) | 12000 / 443 (Caddy) |
| Open Terminal | `open-terminal` | ✅ Running | internal (hermes-net) |
| Whisper STT | `whisper-stt` | ✅ Running (GPU) | 9001 |
| Kokoro TTS | `kokoro-tts` | ✅ Running (GPU) | 8880 |
| Caddy | `caddy` | ✅ Running (HTTPS) | 80, 443 |
| Hermes | `hermes` | ✅ Running | gateway (internal) |
| ComfyUI | `comfyui` | ❌ Exited | 8188 |

### Common Commands

```bash
# List all running containers
docker ps

# Check Hermes logs
~/.hermes/manage-sandbox.sh logs

# Rebuild Hermes image
~/.hermes/manage-sandbox.sh rebuild

# Verify vLLM API
curl -k https://localhost:11002/v1/models

# Verify Whisper STT
curl -s http://whisper-stt:9001/health

# Verify Kokoro TTS
curl -s http://kokoro-tts:8880/health

# Rebuild whisper-stt image (after code changes)
cd ~/whisper-stt && docker build -t whisper-stt .
docker rm -f whisper-stt && docker run -d --name whisper-stt --network hermes-net --gpus all -p 9001:9001 --restart unless-stopped whisper-stt

# Rebuild kokoro-tts image (after code changes)
cd ~/kokoro-tts && docker build -t kokoro-tts .
docker rm -f kokoro-tts && docker run -d --name kokoro-tts --network hermes-net --gpus all -p 8880:8880 --restart unless-stopped kokoro-tts

# SSH tunnel for dashboard (if needed)
ssh -L 9119:localhost:9119 brahma
```
