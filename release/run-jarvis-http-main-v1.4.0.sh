#!/bin/sh
set -eu

fail() {
  echo "Jarvis HTTP non avviato: $*" >&2
  exit 75
}

rollout_lock="${JARVIS_ROLLOUT_LOCK:-/home/satellite/jarvis/.jarvis-rollout.lock}"
network_name="${JARVIS_HTTP_DOCKER_NETWORK:-bridge}"
host_port="${JARVIS_HTTP_HOST_PORT:-8765}"
container_port=8000
allowed_hosts="${JARVIS_HTTP_ALLOWED_HOSTS:-127.0.0.1:*,localhost:*}"
allowed_origins="${JARVIS_HTTP_ALLOWED_ORIGINS:-http://127.0.0.1:*,http://localhost:*}"
mcp_allowed_hosts="${JARVIS_MCP_ALLOWED_HOSTS:-127.0.0.1:*,localhost:*}"
http_mcp_enabled="${JARVIS_HTTP_MCP_ENABLED:-false}"
web_note_scope="${JARVIS_WEB_NOTE_SCOPE:-none}"
web_note_password_file="${JARVIS_WEB_NOTE_PASSWORD_FILE:-/home/satellite/jarvis/.jarvis-web-note-password}"
dashboard_totp_secret_file="${JARVIS_DASHBOARD_TOTP_SECRET_FILE:-}"
dashboard_trusted_proxy_peers="${JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS:-}"
container_name="jarvis-main-http-v1"

case "$host_port" in
  ""|*[!0-9]*) fail "JARVIS_HTTP_HOST_PORT deve essere numerica" ;;
esac
if test "$host_port" -lt 1 || test "$host_port" -gt 65535
then
  fail "JARVIS_HTTP_HOST_PORT deve essere compresa tra 1 e 65535"
fi
test -n "$allowed_hosts" || fail "JARVIS_HTTP_ALLOWED_HOSTS non può essere vuota"
test -n "$allowed_origins" || fail "JARVIS_HTTP_ALLOWED_ORIGINS non può essere vuota"
test -n "$mcp_allowed_hosts" || fail "JARVIS_MCP_ALLOWED_HOSTS non può essere vuota"
case "$http_mcp_enabled" in
  true|false) ;;
  *) fail "JARVIS_HTTP_MCP_ENABLED deve essere true o false" ;;
esac
case "$web_note_scope" in
  none) ;;
  panoramas|all-visible-markdown)
    test -f "$web_note_password_file" \
      || fail "file password web assente o non regolare"
    test ! -L "$web_note_password_file" \
      || fail "il file password web non può essere un collegamento simbolico"
    test -r "$web_note_password_file" \
      || fail "file password web non leggibile"
    case "$(stat -c '%a' "$web_note_password_file")" in
      400|600) ;;
      *) fail "il file password web deve avere permessi 400 o 600" ;;
    esac
    ;;
  *) fail "JARVIS_WEB_NOTE_SCOPE non valido" ;;
esac
if test -n "$dashboard_totp_secret_file"
then
  test -f "$dashboard_totp_secret_file" \
    || fail "file segreto TOTP dashboard assente o non regolare"
  test ! -L "$dashboard_totp_secret_file" \
    || fail "il file segreto TOTP dashboard non può essere un collegamento simbolico"
  test -r "$dashboard_totp_secret_file" \
    || fail "file segreto TOTP dashboard non leggibile"
  case "$(stat -c '%a' "$dashboard_totp_secret_file")" in
    400|600) ;;
    *) fail "il file segreto TOTP dashboard deve avere permessi 400 o 600" ;;
  esac
fi

docker network inspect "$network_name" >/dev/null 2>&1 \
  || fail "rete Docker $network_name assente"

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

set --
if test "$web_note_scope" != "none"
then
  set -- \
    --mount "type=bind,src=${web_note_password_file},dst=/run/secrets/jarvis-web-note-password,readonly" \
    --env "JARVIS_WEB_NOTE_PASSWORD_FILE=/run/secrets/jarvis-web-note-password"
fi
if test -n "$dashboard_totp_secret_file"
then
  set -- "$@" \
    --mount "type=bind,src=${dashboard_totp_secret_file},dst=/run/secrets/jarvis-dashboard-totp,readonly" \
    --env "JARVIS_DASHBOARD_TOTP_SECRET_FILE=/run/secrets/jarvis-dashboard-totp"
fi

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
  --env "JARVIS_HTTP_ALLOWED_ORIGINS=${allowed_origins}" \
  --env "JARVIS_MCP_ALLOWED_HOSTS=${mcp_allowed_hosts}" \
  --env "JARVIS_HTTP_MCP_ENABLED=${http_mcp_enabled}" \
  --env "JARVIS_WEB_NOTE_SCOPE=${web_note_scope}" \
  --env "JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS=${dashboard_trusted_proxy_peers}" \
  "$@" \
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
