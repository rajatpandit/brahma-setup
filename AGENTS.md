# Setup Documentation Maintenance

This repository documents the production setup of the `brahma` machine.

## Critical Rule

Whenever you make a change to any of the following, **update `installation.md`**:
- Docker container configuration (ports, networks, images, env vars)
- Docker network topology (adding/removing networks, connecting containers)
- Hermes config or deployment method
- vLLM model, flags, or run command
- OpenWebUI config or deployment
- ComfyUI/SparkyUI setup
- iptables rules or systemd services
- Management scripts
- Any new service addition

## What to Update

- Keep the "Current Status" table accurate (date, running/stopped, ports)
- Update architecture diagram if topology changes
- Add/remove sections for new or decommissioned services
- Update version numbers, image tags, and flags

## Commit

After updating, commit with a descriptive message referencing what changed:
```
git add installation.md && git commit -m "docs: <what changed>"
```
