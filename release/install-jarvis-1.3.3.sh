#!/bin/sh
set -eu

archive="/home/satellite/jarvis-core-v1.3.3.tar.gz"
uploaded_launcher="/home/satellite/run-jarvis-main-v1.3.3.sh"
uploaded_verifier="/home/satellite/verify-jarvis-release-v1.3.3.py"
project_parent="/home/satellite/jarvis"
project_dir="$project_parent/jarvis-core-v1.3.3"
installed_launcher="$project_parent/run-jarvis-main-v1.3.3.sh"
active_launcher="$project_parent/run-jarvis-main-v1.sh"
rollback_launcher="$project_parent/run-jarvis-main-v1.3.2.sh"
pinned_rollback_launcher="$project_parent/run-jarvis-main-v1.3.2-pinned.sh"
rollout_lock="$project_parent/.jarvis-rollout.lock"
vault_dir="$project_parent/vault-main"
state_dir="$project_parent/core-state-main-v1"
backups_dir="$project_parent/backups-main"
backup_script="$project_parent/backup-main.sh"
organization_policy="$vault_dir/Sistema — Gestione automatica delle note.md"
ingestion_policy="$vault_dir/Sistema — Acquisizione e triage.md"

expected_archive="ARCHIVE_SHA256_PLACEHOLDER"
expected_launcher="LAUNCHER_SHA256_PLACEHOLDER"
expected_verifier="VERIFIER_SHA256_PLACEHOLDER"
expected_manifest="MANIFEST_SHA256_PLACEHOLDER"
expected_rollback_launcher="39ecbe79e9e0db5477152d4b6c37896aea841956ece26708b2d39456f70351ea"
expected_rollback_image_id="sha256:a12644a9cca5a874b87f7c7fc10eaa389380003a136d25feb6b3a2d9bd242ed4"

file_hash() {
  sha256sum "$1" | awk '{print $1}'
}

abort() {
  echo "ERRORE: $1" >&2
  exit 1
}

echo "===== 1. INPUT E STAGING PRIVATO ====="
test -f "$archive" || abort "archivio 1.3.3 non trovato"
test -f "$uploaded_launcher" || abort "template launcher 1.3.3 non trovato"
test -f "$uploaded_verifier" || abort "verificatore 1.3.3 non trovato"
test "$(file_hash "$archive")" = "$expected_archive" || abort "hash archivio non valido"
test "$(file_hash "$uploaded_launcher")" = "$expected_launcher" || abort "hash template launcher non valido"
test "$(file_hash "$uploaded_verifier")" = "$expected_verifier" || abort "hash verificatore non valido"

staging="$(mktemp -d "$project_parent/.release-1.3.3.XXXXXX")"
chmod 0700 "$staging"
staged_archive="$staging/jarvis-core-v1.3.3.tar.gz"
staged_launcher_template="$staging/run-jarvis-main-v1.3.3.sh"
verifier="$staging/verify-jarvis-release-v1.3.3.py"
install -m 0400 "$archive" "$staged_archive"
install -m 0400 "$uploaded_launcher" "$staged_launcher_template"
install -m 0500 "$uploaded_verifier" "$verifier"
test "$(file_hash "$staged_archive")" = "$expected_archive" || abort "copia archivio non valida"
test "$(file_hash "$staged_launcher_template")" = "$expected_launcher" || abort "copia template launcher non valida"
test "$(file_hash "$verifier")" = "$expected_verifier" || abort "copia verificatore non valida"
sh -n "$staged_launcher_template" || abort "sintassi template launcher non valida"
echo "Input copiati e verificati in staging privato: $staging"

echo
echo "===== 2. PREREQUISITI E IDENTITÀ ROLLBACK ====="
test -d "$vault_dir" || abort "vault server non trovato"
test -d "$state_dir" || abort "stato Jarvis non trovato"
test -d "$backups_dir" || abort "directory backup Jarvis non trovata"
test -f "$backup_script" || abort "script backup Jarvis non trovato"
test -f "$organization_policy" || abort "politica organizzativa non sincronizzata"
test -f "$ingestion_policy" || abort "politica acquisizione e triage non sincronizzata"
test ! -e "$project_dir" || abort "directory 1.3.3 già presente"
systemctl is-active --quiet jarvis-main-backup.timer || abort "timer backup Jarvis non attivo"
command -v flock >/dev/null 2>&1 || abort "flock non disponibile"
available_kb="$(df -Pk "$project_parent" | awk 'NR == 2 {print $4}')"
test -n "$available_kb" || abort "spazio libero non rilevabile"
test "$available_kb" -ge 1048576 || abort "meno di 1 GiB libero"
rollback_image_id="$(docker image inspect --format '{{.Id}}' jarvis-core:1.3.2)"
test "$rollback_image_id" = "$expected_rollback_image_id" \
  || abort "il tag 1.3.2 non indica l'immagine rollback pinzata"
test -f "$active_launcher" || abort "launcher attivo non trovato"
test "$(file_hash "$active_launcher")" = "$expected_rollback_launcher" \
  || abort "launcher attivo non è la 1.3.2 attesa"
if test -f "$rollback_launcher"
then
  test "$(file_hash "$rollback_launcher")" = "$expected_rollback_launcher" \
    || abort "launcher rollback inatteso"
else
  install -m 0750 "$active_launcher" "$rollback_launcher"
fi

echo
echo "===== 3. GATE 1.3.2 E LOCK ESCLUSIVO ====="
gate_launcher="$staging/run-jarvis-main-v1.3.2-pinned.sh"
gate_active=0
transaction_success=0

finish_transaction() {
  status=$?
  trap - EXIT HUP INT TERM
  if test "$gate_active" -eq 1 && test "$transaction_success" -ne 1
  then
    echo "Ripristino atomico del launcher-gate 1.3.2..." >&2
    status=1
    if ! "$verifier" restore-launcher \
      "$pinned_rollback_launcher" \
      "$gate_hash" \
      "$expected_rollback_image_id" \
      "$active_launcher"
    then
      echo "ERRORE: ripristino launcher-gate fallito; staging conservato: $staging" >&2
    elif ! "$verifier" verify-launcher \
      "$active_launcher" \
      "$gate_hash" \
      "$expected_rollback_image_id"
    then
      echo "ERRORE: verifica launcher-gate ripristinato fallita; staging conservato: $staging" >&2
    elif ! docker image inspect "$expected_rollback_image_id" >/dev/null 2>&1
    then
      echo "ERRORE: immagine rollback pinzata non disponibile; staging conservato: $staging" >&2
    else
      echo "Launcher-gate 1.3.2 ripristinato e verificato; staging: $staging" >&2
    fi
  fi
  exit "$status"
}

trap finish_transaction EXIT HUP INT TERM
gate_hash="$(
  "$verifier" render-launcher \
    "$staged_launcher_template" \
    "$expected_launcher" \
    "$expected_rollback_image_id" \
    "$gate_launcher"
)" || abort "generazione launcher rollback pinzato fallita"
sh -n "$gate_launcher" || abort "sintassi launcher rollback pinzato non valida"
"$verifier" activate \
  "$gate_launcher" \
  "$gate_hash" \
  "$rollback_launcher" \
  "$expected_rollback_launcher" \
  "$pinned_rollback_launcher" \
  "$active_launcher" \
  || abort "attivazione gate rollback fallita"
gate_active=1

if docker ps --filter label=jarvis.service=main-v1 --format '{{.Names}}' | grep -q .
then
  abort "esiste ancora una sessione Jarvis avviata prima del gate"
fi
exec 9>"$rollout_lock"
flock -x -n 9 || abort "impossibile acquisire il lock esclusivo di rollout"
if docker ps --filter label=jarvis.service=main-v1 --format '{{.Names}}' | grep -q .
then
  abort "una sessione Jarvis è attiva; rollout bloccato"
fi
echo "Gate 1.3.2 attivo e lock esclusivo acquisito"

echo
echo "===== 4. SMOKE TEST ROLLBACK IMMUTABILE ====="
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --volume "$vault_dir:/vault:ro" \
  --volume "$state_dir:/state:ro" \
  --entrypoint python \
  "$expected_rollback_image_id" \
  -c "from pathlib import Path; from vault_core import vault_status; assert vault_status(Path('/vault'), Path('/state'))['version'] == '1.3.2'" \
  || abort "smoke test immagine rollback 1.3.2 fallito"
echo "Rollback verificato: $expected_rollback_image_id"

echo
echo "===== 5. SNAPSHOT NUOVO, LIVE E VERIFICATO ====="
before_snapshots="$staging/before-snapshots.txt"
"$verifier" snapshot-list "$backups_dir" > "$before_snapshots" \
  || abort "inventario snapshot precedente fallito"
sh "$backup_script" || abort "snapshot pre-aggiornamento fallito"
new_snapshot="$(
  "$verifier" verify-new-snapshot \
    "$backups_dir" \
    "$before_snapshots" \
    "$vault_dir" \
    "$state_dir"
)" || abort "nuovo snapshot non corrispondente ai dati live"
echo "Snapshot verificato contro i dati live: $new_snapshot"

echo
echo "===== 6. ESTRAZIONE SICURA ====="
"$verifier" extract \
  "$staged_archive" \
  "$expected_archive" \
  "$expected_manifest" \
  "$project_parent" \
  "jarvis-core-v1.3.3" \
  || abort "verifica o estrazione sorgente fallita"
test -d "$project_dir" || abort "directory sorgente 1.3.3 assente"

echo
echo "===== 7. TEST UBUNTU ====="
(
  cd "$project_dir"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
) || abort "test 1.3.3 falliti"

echo
echo "===== 8. BUILD E IDENTITÀ 1.3.3 ====="
(
  cd "$project_dir"
  docker build --tag jarvis-core:1.3.3 .
) || abort "build immagine 1.3.3 fallita"
new_image_id="$(docker image inspect --format '{{.Id}}' jarvis-core:1.3.3)"
test "$new_image_id" != "$expected_rollback_image_id" \
  || abort "l'immagine nuova coincide con il rollback"
test "$(docker image inspect --format '{{.Id}}' jarvis-core:1.3.2)" = "$expected_rollback_image_id" \
  || abort "l'identità rollback 1.3.2 è cambiata"
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --volume "$vault_dir:/vault:ro" \
  --volume "$state_dir:/state:ro" \
  --entrypoint python \
  "$new_image_id" \
  -c 'from pathlib import Path; import vault_core as v; assert v.vault_status(Path("/vault"), Path("/state"))["version"] == "1.3.3"; assert v.INGESTION_POLICY_NOTE_PATH == "Sistema — Acquisizione e triage.md"; assert v.ORGANIZATION_POLICY_NOTE_PATH == "Sistema — Gestione automatica delle note.md"; assert v.CAPTURE_STATUS_TRANSITIONS["processed"] == set()' \
  || abort "smoke test immagine 1.3.3 fallito"

echo
echo "===== 9. ATTIVAZIONE TRANSAZIONALE ====="
rendered_launcher="$staging/run-jarvis-main-v1.3.3-rendered.sh"
rendered_launcher_hash="$(
  "$verifier" render-launcher \
    "$staged_launcher_template" \
    "$expected_launcher" \
    "$new_image_id" \
    "$rendered_launcher"
)" || abort "generazione launcher 1.3.3 pinzato fallita"
sh -n "$rendered_launcher" || abort "sintassi launcher 1.3.3 non valida"
"$verifier" activate \
  "$rendered_launcher" \
  "$rendered_launcher_hash" \
  "$pinned_rollback_launcher" \
  "$gate_hash" \
  "$installed_launcher" \
  "$active_launcher" \
  || abort "attivazione fallita; il gate 1.3.2 è stato ripristinato"

"$verifier" verify-launcher \
  "$active_launcher" \
  "$rendered_launcher_hash" \
  "$new_image_id" \
  || abort "verifica finale launcher 1.3.3 fallita"
docker image inspect "$new_image_id" >/dev/null 2>&1 \
  || abort "immagine 1.3.3 pinzata non disponibile alla verifica finale"
test "$(docker image inspect --format '{{.Id}}' jarvis-core:1.3.2)" = "$expected_rollback_image_id" \
  || abort "identità rollback cambiata dopo l'attivazione"
transaction_success=1
echo "Launcher 1.3.3 attivato con image ID: $new_image_id"
echo "Launcher rollback pinzato conservato: $pinned_rollback_launcher"
echo "Snapshot verificato: $new_snapshot"
echo "Staging conservato per audit: $staging"
echo "Il lock esclusivo verrà rilasciato all'uscita dell'installer"
echo "JARVIS CORE 1.3.3 ATTIVATO"
