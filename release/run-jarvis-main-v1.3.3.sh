#!/bin/sh
set -eu

rollout_lock="${JARVIS_ROLLOUT_LOCK:-/home/satellite/jarvis/.jarvis-rollout.lock}"
exec 9>"$rollout_lock"
if ! flock -s -n 9
then
  echo "Jarvis non disponibile: rollout in corso." >&2
  exit 75
fi

host_uid="$(id -u)"
host_gid="$(id -g)"
session_name="jarvis-main-v1-session-$(date +%s)-$$"

cleanup() {
  docker stop --timeout 5 "${session_name}" >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM

docker run --rm -i \
  --name "${session_name}" \
  --label jarvis.service=main-v1 \
  --label jarvis.session=true \
  --network none \
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
