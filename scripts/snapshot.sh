#!/usr/bin/env bash
# Snapshot current Docker container configs as markdown snippets
# Run this after any infra change, then cross-check against installation.md
set -euo pipefail

containers=("$@")
if [ ${#containers[@]} -eq 0 ]; then
  containers=(open-webui vllm-llm)
fi

for name in "${containers[@]}"; do
  if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
    echo "⚠  $name not running, skipping"
    echo ""
    continue
  fi

  echo "### $name"
  echo ""
  echo '```bash'
  echo "# docker inspect $name"
  echo ""

  # Networks
  nets=$(docker inspect "$name" --format '{{range $k, $_ := .NetworkSettings.Networks}}{{$k}} {{end}}')
  echo "# Networks: $nets"

  # Ports
  ports=$(docker inspect "$name" --format '{{range $p, $h := .HostConfig.PortBindings}}{{$p}} -> {{range $h}}{{.HostIp}}:{{.HostPort}} {{end}}{{end}}')
  echo "# Ports: $ports"

  # Restart policy
  restart=$(docker inspect "$name" --format '{{.HostConfig.RestartPolicy.Name}}')
  echo "# Restart: $restart"

  # Image
  image=$(docker inspect "$name" --format '{{.Config.Image}}')
  echo "# Image: $image"

  echo ""
  echo "# Env:"
  docker inspect "$name" --format '{{range .Config.Env}}{{println .}}{{end}}' | sort

  echo ""
  echo "# Volumes:"
  docker inspect "$name" --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'

  echo '```'
  echo ""
done
