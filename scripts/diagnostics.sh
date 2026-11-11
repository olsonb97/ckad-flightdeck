#!/usr/bin/env bash
# Read-only diagnostics. No namespaces or volumes are removed.
set -u
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
echo '=== Compose services ==='
docker compose ps
echo '=== App initialization ==='
docker compose exec -T app python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/api/state")); print(json.dumps(d["environment"],indent=2))'
echo '=== Nodes ==='
docker compose exec -T app kubectl --kubeconfig /run/lab-kubeconfig get nodes -o wide
echo '=== System Pods ==='
docker compose exec -T app kubectl --kubeconfig /run/lab-kubeconfig get pods -n kube-system -o wide
echo '=== Recent cluster events ==='
docker compose exec -T app kubectl --kubeconfig /run/lab-kubeconfig get events -A --sort-by=.metadata.creationTimestamp | tail -60
echo '=== Container logs ==='
docker compose logs --tail=80 app cluster worker builder
