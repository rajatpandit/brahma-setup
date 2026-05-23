# Setup Documentation Maintenance

This repository documents the production setup of the `brahma` machine.

## Critical Rule: Docs Must Match Reality

Whenever you make ANY change to the following, you MUST immediately update **`installation.md`**:

- Docker container configuration (ports, networks, images, env vars)
- Docker network topology (adding/removing networks, connecting containers)
- Hermes config or deployment method
- vLLM model, flags, or run command
- OpenWebUI config or deployment
- ComfyUI/SparkyUI setup
- iptables rules or systemd services
- Management scripts
- Any new service addition

**This is mandatory — not optional. Do not end the session without syncing docs.**

## Automated Verification

After making infra changes, run the snapshot script to capture current config:

```bash
bash scripts/snapshot.sh
```

Cross-reference every value against `installation.md`. If anything differs, update the doc.

## What to Update

- Keep the "Current Status" table accurate (date, running/stopped, ports)
- Update architecture diagram if topology changes
- Add/remove sections for new or decommissioned services
- Update version numbers, image tags, and flags
- Run `bash scripts/snapshot.sh` and verify every env var, volume, port, and network

## Commit

After updating, commit with a descriptive message referencing what changed:
```
git add installation.md && git commit -m "docs: <what changed>"
```
