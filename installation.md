# Brahma Setup Documentation

> Machine: `brahma` — Grace-Blackwell (ARM SBSA) server with unified memory.

## Architecture Overview

```
Host (brahma)
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  hermes-net (172.19.0.0/16, user-defined bridge)                        │
 │                                                                         │
 │  ┌─────────────────────────┐  ┌──────────────────────────────┐         │
 │  │ vLLM (vllm-llm)          │  │ Hermes (hermes)              │         │
 │  │ 172.19.0.3               │  │ network_mode: host           │         │
 │  │ GPU: yes                 │  │ GPU: no                      │         │
 │  │ Port: 11002→8000         │  │ Vol: hermes-data → /opt/data │         │
 │  │ SSL: /certs/*.pem        │  │ Gateway + Dashboard          │         │
 │  │ Model: Qwen3.6-35B-A3B   │  │                              │         │
 │  └──────────┬──────────────┘  └──────────────────────────────┘         │
 │             │                                                           │
 │             │ https://vllm-llm:8000/v1 (CA signed, hermes-net)          │
 │             │                                                           │
 │  ┌──────────┴──────────────┐    ┌──────────────────────────┐           │
 │  │ OpenWebUI (open-webui)   │    │ Open Terminal            │           │
 │  │ Network: hermes-net      │◄──►│ (open-terminal)          │           │
 │  │ Port: 12000→8080         │    │ RAM: 2g, CPU: 2          │           │
 │  │ SSL_CERT_FILE: /certs/   │    │ Slim: 430MB              │           │
 │  │ Terminal: auto-configured│    │ No GPU, no egress        │           │
 │  │ No GPU                  │    │                          │           │
 │  └─────────────────────────┘    └──────────────────────────┘           │
 │                                                                         │
 │  SparkyUI / ComfyUI (optional, currently off)                           │
 │  sparky_net bridge, GPU: yes, Port: 8188                               │
 └─────────────────────────────────────────────────────────────────────────┘
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

Web UI for interacting with LLMs. Connects to vLLM via HTTPS on `hermes-net`.

**Container:** `open-webui`
**Image:** `ghcr.io/open-webui/open-webui:main`
**Network:** `hermes-net` (not bridge — avoids hairpin NAT issues with host-published ports)
**Port:** `12000:8080`
**API Base:** `https://vllm-llm:8000/v1`
**SSL:** CA cert mounted at `/certs/ca.pem`, trusted via `SSL_CERT_FILE`

Run command:
```bash
OPEN_TERMINAL_KEY=$(cut -d= -f2- < ~/.hermes/certs/open-terminal-key.env)

docker run -d \
  --name open-webui \
  -p 12000:8080 \
  --network hermes-net \
  --restart unless-stopped \
  -e OPENAI_API_BASE_URLS="https://vllm-llm:8000/v1" \
  -e USE_CUDA_DOCKER=false \
  -e DO_NOT_TRACK=true \
  -e RAG_EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2" \
  -e AUXILIARY_EMBEDDING_MODEL="TaylorAI/bge-micro-v2" \
  -e WHISPER_MODEL="base" \
  -e ANONYMIZED_TELEMETRY=false \
  -e SCARF_NO_ANALYTICS=true \
  -e SSL_CERT_FILE="/certs/ca.pem" \
  -e TERMINAL_SERVER_CONNECTIONS="[{\"id\":\"open-terminal\",\"url\":\"http://open-terminal:8000\",\"key\":\"${OPEN_TERMINAL_KEY}\",\"name\":\"Open Terminal\",\"auth_type\":\"bearer\"}]" \
  -v open-webui-data:/app/backend/data \
  -v /home/rajatpandit/.hermes/certs/ca.pem:/certs/ca.pem:ro \
  ghcr.io/open-webui/open-webui:main
```

**Environment:**
| Variable | Value |
|----------|-------|
| `OPENAI_API_BASE_URLS` | `https://vllm-llm:8000/v1` |
| `RAG_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `AUXILIARY_EMBEDDING_MODEL` | `TaylorAI/bge-micro-v2` |
| `WHISPER_MODEL` | `base` |
| `SSL_CERT_FILE` | `/certs/ca.pem` |
| `TERMINAL_SERVER_CONNECTIONS` | JSON array pre-configuring Open Terminal integration |

**Access:** http://brahma:12000

**Note:** Must be on `hermes-net` to resolve `vllm-llm` hostname. The CA cert from `~/.hermes/certs/ca.pem` is mounted into the container so Python/requests can verify the self-signed vLLM certificate.

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

### 4. Hermes — AI Agent (Messaging Gateway)

Runs inside Docker with sandboxed access.

**Container:** `hermes-sandbox`
**Image:** `hermes-agent:latest` (built locally)
**Network:** `hermes-net` (not host — connects to vLLM + OpenWebUI internally)
**Volume:** `hermes-data` → `/opt/data` (config, sessions, logs, skills)
**Browser:** Debian Chromium (ARM64) installed in volume, uses `chromium-wrapper.sh` for library path

#### Build
```bash
cd ~/.hermes/hermes-agent
docker build -t hermes-agent:latest .
```

#### Data Volume
```bash
docker volume create hermes-data
```

Seeded via `~/.hermes/seed-sandbox.sh` with `config.yaml` and `.env`.

#### Run
```bash
cd ~/.hermes/hermes-agent
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose up -d gateway
```

Or using the management script:
```bash
~/.hermes/manage-sandbox.sh start
```

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

---

### 5. SparkyUI / ComfyUI — Image Generation (Optional)

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
| `hermes-net` | bridge | 172.19.0.0/16 | vLLM ↔ OpenWebUI ↔ Hermes communication |
| `open-webui_default` | bridge | — | OpenWebUI internal (unused) |
| `sparky_net` | bridge | — | ComfyUI internal |
| `bridge` | bridge | 172.17.0.0/16 | Default Docker bridge |

### Container Network Map

| Container | Networks | IPs |
|-----------|----------|-----|
| `vllm-llm` | hermes-net, bridge | 172.19.0.3, 172.17.0.2 |
| `open-webui` | hermes-net | — |
| `open-terminal` | hermes-net | — |
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

### Current Status (as of 2026-05-23)

| Service | Container | Status | Port |
|---------|-----------|--------|------|
| vLLM | `vllm-llm` | ✅ Running | 11002 |
| OpenWebUI | `open-webui` | ✅ Running | 12000 |
| Open Terminal | `open-terminal` | ✅ Running | internal (hermes-net) |
| Hermes | `hermes-sandbox` | ✅ Running | gateway (internal) |
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

# SSH tunnel for dashboard (if needed)
ssh -L 9119:localhost:9119 brahma
```
