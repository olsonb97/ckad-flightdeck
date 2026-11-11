#!/usr/bin/env bash
# Sourced before Compose can replace a legacy node container. Never print identity data.
preserve_node_identities() {
  local service identity container mounted project volume image temporary helper host_temporary
  for service in cluster worker; do
    identity=worker-identity
    [[ "$service" == cluster ]] && identity=control-identity
    container=$(docker compose ps -a -q "$service") || return
    [[ -n "$container" ]] || continue
    mounted=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/etc/rancher/node"}}persistent{{end}}{{end}}' "$container") || return
    [[ "$mounted" == persistent ]] && continue
    project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container") || return
    [[ -n "$project" && "$project" != '<no value>' ]] || { printf '%s\n' 'Existing node has no Compose project identity.' >&2; return 1; }
    volume="${project}_${identity}"
    image=$(docker inspect --format '{{.Config.Image}}' "$container") || return
    temporary=$(mktemp -d "${TMPDIR:-/tmp}/flightdeck-identity.XXXXXXXX") || return
    host_temporary="$temporary"
    if command -v cygpath >/dev/null 2>&1; then host_temporary=$(cygpath -w "$temporary"); fi
    helper="${project}-identity-migration-${temporary##*.}"
    (
      set -e
      trap 'docker rm -f -v "$helper" >/dev/null 2>&1 || true; rm -rf -- "$temporary"' EXIT
      printf 'Preserving the existing %s identity...\n' "$service"
      docker cp "${container}:/etc/rancher/node" "$host_temporary/node" || exit 1
      test -s "$temporary/node/password" || exit 1
      docker volume create --label "com.docker.compose.project=$project" --label "com.docker.compose.volume=$identity" "$volume" >/dev/null || exit 1
      docker create --name "$helper" --network none --mount "type=volume,source=$volume,target=/target" --entrypoint sh "$image" -c \
        'set -eu; if [ -s /target/password ] && ! cmp -s /incoming/password /target/password; then echo "Existing identity volume differs; no identity was overwritten." >&2; exit 1; fi; cp -a /incoming/. /target/; test -s /target/password' >/dev/null || exit 1
      docker cp "$host_temporary/node" "$helper:/incoming" || exit 1
      docker start -a "$helper" || exit 1
      test "$(docker inspect --format '{{.State.ExitCode}}' "$helper")" = 0
    ) || { printf '%s\n' 'Identity migration failed. No lab containers were recreated.' >&2; return 1; }
  done
}
