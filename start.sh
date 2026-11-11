#!/usr/bin/env bash
set -euo pipefail
# Git Bash must pass Linux paths to Docker unchanged; native Bash ignores this.
export MSYS_NO_PATHCONV=1
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker is required. Install Docker Engine + Compose v2, or start Docker Desktop in Linux-container mode.' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  printf '%s\n' 'The Docker daemon is not accessible. Start Docker Desktop/Engine and check Docker permissions.' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'The Docker Compose v2 plugin is required (docker compose, with a space).' >&2
  exit 1
fi
if [[ "$(docker info --format '{{.OSType}}')" != linux ]]; then
  printf '%s\n' 'Docker must be running Linux containers.' >&2
  exit 1
fi
source scripts/migrate-identities.sh
preserve_node_identities
docker compose up --build -d
printf '\n%s\n' 'Starting the lab. First launch downloads the required images...'
docker compose exec -T app python /app/wait_ready.py
printf '\nOpen http://%s\n' "$(docker compose port app 8080)"
printf '\n%s\n' 'Logs: docker compose logs -f app cluster worker builder'
printf '%s\n' 'Stop, preserving data: docker compose down'
