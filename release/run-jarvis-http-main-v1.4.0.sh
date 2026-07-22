#!/bin/sh
set -eu

fail() {
  echo "Jarvis HTTP non avviato: $*" >&2
  exit 75
}

rollout_lock="${JARVIS_ROLLOUT_LOCK:-/home/satellite/jarvis/.jarvis-rollout.lock}"
network_name="${JARVIS_HTTP_DOCKER_NETWORK:-jarvis-http-internal}"
host_port="${JARVIS_HTTP_HOST_PORT:-8765}"
container_port=8000
allowed_hosts="${JARVIS_HTTP_ALLOWED_HOSTS:-127.0.0.1:*,localhost:*}"
container_name="jarvis-main-http-v1"

case "$host_port" in
  ""|*[!0-9]*) fail "JARVIS_HTTP_HOST_PORT deve essere numerica" ;;
esac
if test "$host_port" -lt 1 || test "$host_port" -gt 65535
then
  fail "JARVIS_HTTP_HOST_PORT deve essere compresa tra 1 e 65535"
fi
test -n "$allowed_hosts" || fail "JARVIS_HTTP_ALLOWED_HOSTS non può essere vuota"

network_internal="$(
  docker network inspect --format '{{.Internal}}' "$network_name" 2>/dev/null
)" || fail "rete Docker $network_name assente"
test "$network_internal" = "true" || fail "rete Docker $network_name non interna"

exec 9>"$rollout_lock"
if ! flock -s -n 9
then
  fail "rollout in corso"
fi

if docker container inspect "$container_name" >/dev/null 2>&1
then
  fail "container $container_name già presente"
fi

host_uid="$(id -u)"
host_gid="$(id -g)"

cleanup() {
  docker stop --timeout 10 "$container_name" >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM

docker run --rm \
  --name "$container_name" \
  --label jarvis.service=main-v1-http \
  --label jarvis.transport=streamable-http \
  --network "$network_name" \
  --publish "127.0.0.1:${host_port}:${container_port}" \
  --env "JARVIS_TRANSPORT=streamable-http" \
  --env "JARVIS_HTTP_HOST=0.0.0.0" \
  --env "JARVIS_HTTP_PORT=${container_port}" \
  --env "JARVIS_HTTP_ALLOWED_HOSTS=${allowed_hosts}" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 256m \
  --cpus 0.75 \
  --user "${host_uid}:${host_gid}" \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount type=bind,src=/home/satellite/jarvis/vault-main,dst=/vault \
  --mount type=bind,src=/home/satellite/jarvis/core-state-main-v1,dst=/state \
  IMAGE_ID_PLACEHOLDER
