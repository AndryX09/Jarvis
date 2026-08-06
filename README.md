# Jarvis Core v1.4.0

Personal MCP server for a synchronized Obsidian vault.

## Tools

- `jarvis_status`
- `list_notes`
- `search_notes`
- `read_note`
- `list_versions`
- `read_version`
- `list_tasks`
- `recent_notes`
- `ingestion_status`
- `read_ingestion_policy`
- `read_organization_policy`
- `capture_material`
- `list_captures`
- `read_capture`
- `read_pending_captures`
- `update_capture_status`
- `create_note`
- `create_inbox_note`
- `append_to_note`
- `update_note`
- `restore_version`
- `move_note`
- `recent_activity`

There is deliberately no delete tool.

## Separate policy sources

Jarvis Core exposes two independent, user-editable policy notes:

- `read_ingestion_policy` reads `Sistema — Acquisizione e triage.md`;
- `read_organization_policy` reads `Sistema — Gestione automatica delle note.md`.

There is no silent fallback between them. If the requested policy is absent, the tool
returns an error. `ingestion_status` reports the availability, path, and hash of the
acquisition and triage policy.

## Ingestion and triage workflow

1. `capture_material` preserves raw text in `/state/captures`. Exact source/content
   duplicates are returned as the existing capture rather than stored twice.
2. Before triage, call `read_ingestion_policy`. Triage changes capture states only;
   it does not create, update, or move vault notes.
3. `read_pending_captures` returns a bounded batch of up to 20 raw captures without
   changing their state.
4. `update_capture_status` requires a fresh `record_sha256` from `read_capture` and a
   non-empty summary of at most 2,000 characters.
5. The server enforces these ordinary transitions:

   - `pending → ready`
   - `pending → skipped`
   - `ready → processed`
   - `ready → skipped`
   - `skipped → pending`
   - `skipped → ready`

   Same-state transitions, direct `pending → processed`, `skipped → processed`, and
   transitions out of `processed` are rejected.
6. A `processed` capture must reference between 1 and 20 existing Markdown output
   notes. Other states cannot contain output paths.
7. Raw capture content is never deleted or rewritten by an MCP tool.

### Client compatibility

The mandatory `summary`, exact 2,000-character input limit, and stricter transition
matrix are intentionally compatibility-breaking for MCP clients that relied on the
older permissive behavior. Clients must read a fresh `record_sha256`, send a non-empty
summary, and follow the transition matrix above.

For conversation and note organization, call `read_organization_policy`, search and
read relevant notes, and follow its confirmation rules before using versioned note
mutation tools. Jarvis Core validates revision hashes but cannot observe or enforce a
word such as "confermo" in a client conversation.

Google Keep Takeout ZIP archives can be imported with `/app/import_keep.py`. The
importer reads JSON directly without extracting the archive, preserves the original ZIP
under `/state/imports/google-keep`, and converts note text, lists, labels, timestamps,
and attachment references into captures. Use `--dry-run` first and `--limit 5` for an
initial sample. Re-importing the same archive is deduplicated.

## Streamable HTTP transport

The default transport remains `stdio`, preserving the existing Smart Composer over SSH
path. Set these variables to run the same 23-tool MCP contract over Streamable HTTP:

```
JARVIS_TRANSPORT=streamable-http
JARVIS_HTTP_HOST=127.0.0.1
JARVIS_HTTP_PORT=8765
JARVIS_HTTP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*
JARVIS_HTTP_ALLOWED_ORIGINS=http://127.0.0.1:*,http://localhost:*
JARVIS_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*
JARVIS_HTTP_MCP_ENABLED=false
```

When explicitly enabled, the loopback MCP endpoint is `http://127.0.0.1:8765/mcp`; a
reverse proxy may expose that endpoint over HTTPS. The port must be between 1 and 65535.
Unknown transports and an empty HTTP host allowlist are rejected before startup.
DNS rebinding protection is enabled by FastMCP. `JARVIS_HTTP_ALLOWED_HOSTS` controls the
read-only browser routes, while the narrower `JARVIS_MCP_ALLOWED_HOSTS` independently
controls the write-capable `/mcp` endpoint. `JARVIS_HTTP_MCP_ENABLED` is `false` by
default and makes `/mcp` reject every request regardless of how a proxy rewrites Host;
stdio remains available. A public hostname may be added to the browser allowlist without
adding it to the MCP allowlist or enabling MCP over HTTP.

Enabling HTTP MCP requires `JARVIS_MCP_BEARER_TOKEN_FILE`. Jarvis refuses to start if
HTTP MCP is enabled without it. The credential is read only from a small regular file
containing one Bearer token of at least 32 bytes. Generate the file on the server without
putting the token in shell history:

```bash
python3 scripts/generate_mcp_bearer_token.py \
  --output /home/satellite/jarvis/.jarvis-mcp-token
```

The generator refuses to overwrite an existing file, creates it with mode `600`, and
shows the sensitive token once. Keep that value out of Git, Docker environment variables,
launcher arguments, logs, screenshots, documentation, and chat.

For the reviewed public HTTPS client, add the public hostname to the independent MCP Host
allowlist and pass only the host-side token-file path to the launcher:

```bash
JARVIS_HTTP_MCP_ENABLED=true \
JARVIS_MCP_BEARER_TOKEN_FILE=/home/satellite/jarvis/.jarvis-mcp-token \
JARVIS_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,jarvis.dvdbnc.dpdns.org \
./run-jarvis-http-main-v1.4.0.sh
```

Requests to `https://jarvis.dvdbnc.dpdns.org/mcp` without the exact
`Authorization: Bearer …` credential still receive `401`. Dashboard TOTP sessions do not
authorize MCP. In Hermes, add a second connection before removing the disabled one:

```powershell
hermes mcp add JarvisAuthenticated --url https://jarvis.dvdbnc.dpdns.org/mcp --auth header
```

Enter the `Authorization` header and `Bearer <token>` only in the local interactive
prompt, test it with `hermes mcp test JarvisAuthenticated`, then restart Hermes Desktop
so the authenticated tools are discovered.

The same HTTP server exposes a dependency-free, read-only status interface at `/` and
its JSON data source at `/api/status`. The page displays the safe operational metadata
returned by `jarvis_status`; it does not expose note contents, capture contents, or
mutation controls. Host and Origin validation still applies, but `/mcp` has the separate
Host allowlist and Bearer authentication described above. Set
`JARVIS_HTTP_MCP_ENABLED=true` only with the external token file and an explicitly
reviewed client Host entry in `JARVIS_MCP_ALLOWED_HOSTS`.

### TOTP-protected process dashboard

The optional `/dashboard` interface displays allowlisted operational metadata for Jarvis
Core, the ingestion queue, audit counts, and recent action names. It has no mutation
routes, process controls, Docker access, shell access, note paths, note titles, hashes, or
note contents. Its JSON source is `/api/dashboard/status`.

The dashboard is disabled unless `JARVIS_DASHBOARD_TOTP_SECRET_FILE` names an external
Base32 secret file. Generate that file on the server and pair it with a TOTP authenticator:

```bash
python scripts/generate_dashboard_totp.py \
  --output /home/satellite/jarvis/.jarvis-dashboard-totp \
  --issuer Jarvis \
  --account andry
```

The command refuses to overwrite an existing file, creates a random 160-bit secret with
mode `600`, and prints the sensitive `otpauth://` pairing URI once. Import that URI into an
authenticator such as Aegis, 2FAS, or Google Authenticator without copying it into the
repository or chat. The six-digit code changes every 30 seconds; the underlying secret
does not rotate on every login.

Enable the dashboard by passing only the host-side file path to the launcher:

```bash
JARVIS_DASHBOARD_TOTP_SECRET_FILE=/home/satellite/jarvis/.jarvis-dashboard-totp \
JARVIS_HTTP_ALLOWED_ORIGINS=https://jarvis.dvdbnc.dpdns.org \
JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS=VERIFIED_PROXY_PEER_IP \
JARVIS_DASHBOARD_UI_DIR=/home/satellite/jarvis/jarvis-core-v1.4.0-http/app/dashboard_ui \
./run-jarvis-http-main-v1.4.0.sh
```

Replace `VERIFIED_PROXY_PEER_IP` with the socket peer address actually used by the local
Cloudflare/Docker proxy. Only requests from that exact peer may use Cloudflare's
`CF-Connecting-IP` header for per-client login limiting; all other peers are keyed by their
socket address and cannot spoof the header. Do not add broad subnets or public addresses.

The launcher validates permissions and mounts the file read-only at
`/run/secrets/jarvis-dashboard-totp`. A successful TOTP login creates an eight-hour
`Secure`, `HttpOnly`, `SameSite=Strict`, `__Host-` session cookie. Each accepted TOTP time
counter is single-use, so replaying the same temporary code cannot create another session.
Repeated login failures are limited
to five attempts per client per five-minute window. Host and Origin checks run before authentication,
and protected responses use `Cache-Control: no-store`.

The bundled launcher starts one Jarvis server process, matching the in-memory limiter and
TOTP replay state. Do not add multiple HTTP workers without first replacing those stores
with a shared deterministic backend.

The failure limiter and used-TOTP counters reset when the process restarts. Dashboard
sessions are stateless: logout removes the browser cookie but cannot revoke a token that
was copied beforehand. Rotating the external TOTP secret invalidates every existing
session when immediate global revocation is required.

#### Fast dashboard UI workflow

The visual dashboard is stored in `app/dashboard_ui/dashboard.html`. Jarvis reads this
file for every authenticated `/dashboard` request instead of caching it at startup. The
production launcher can mount the `app/dashboard_ui` directory read-only by setting
`JARVIS_DASHBOARD_UI_DIR`; mounting the directory rather than one file keeps atomic Git
file replacements visible to the running container.

For local visual work on Windows, start the loopback-only preview server from PowerShell:

```powershell
python scripts/preview_dashboard.py
```

Open `http://127.0.0.1:8877`, edit `app/dashboard_ui/dashboard.html`, save, and refresh.
The preview uses explicit demo metadata and never reads the vault, state directory, TOTP
secret, Docker, or the production API.

The watcher console in preview is also simulated. Its `run-cycle`, `pause`, and `resume`
buttons call a loopback-only preview route, keep state only in memory, and never start a
process or mutate Jarvis data. The production server does not expose this route; commands
remain disabled there until a separately reviewed deterministic watcher backend exists.

After committing and pushing a change that modifies only
`app/dashboard_ui/dashboard.html`, update the server with:

```bash
python3 scripts/update_dashboard_ui.py
```

The updater fetches the configured branch, refuses non-fast-forward history, verifies that
the only changed path is the dashboard HTML, validates its size, UTF-8 encoding, and
required read-only hooks, confirms the production container's read-only UI mount, and then
fast-forwards the checkout. A failed post-update validation or public health check restores
the previous commit automatically. No image build or container restart occurs. If Python,
Dockerfile, launcher, or any other path changed, it stops and requires the normal full
deployment workflow.

### Password-protected note reading

The optional `/notes` page and its `/api/notes` and `/api/note` data sources expose
visible Markdown in read-only mode. They use HTTP Basic authentication with username
`jarvis`; the password is read from a small regular file mounted read-only into the
container and must contain at least 12 bytes. The password value must never be stored in
the repository or passed as a Docker environment variable. The note list is paginated in
pages of at most 500 entries; filtering for panoramas happens before pagination.

Web note reading is disabled by default. The launcher accepts these scopes:

- `JARVIS_WEB_NOTE_SCOPE=none`: expose no note-reading route;
- `JARVIS_WEB_NOTE_SCOPE=panoramas`: expose only notes named `00 — Panoramica.md`;
- `JARVIS_WEB_NOTE_SCOPE=all-visible-markdown`: expose every visible Markdown note.

For the initial restricted deployment, create a host-side password file without putting
the password in shell history, then start with the panorama scope:

```bash
install -m 600 /dev/null /home/satellite/jarvis/.jarvis-web-note-password
read -r -s JARVIS_WEB_NOTE_PASSWORD_VALUE
printf '%s' "$JARVIS_WEB_NOTE_PASSWORD_VALUE" > /home/satellite/jarvis/.jarvis-web-note-password
unset JARVIS_WEB_NOTE_PASSWORD_VALUE

JARVIS_WEB_NOTE_SCOPE=panoramas \
JARVIS_WEB_NOTE_PASSWORD_FILE=/home/satellite/jarvis/.jarvis-web-note-password \
./run-jarvis-http-main-v1.4.0.sh
```

Changing only the scope to `all-visible-markdown` expands future access to all visible
Markdown while retaining password protection, hidden-path rejection, vault confinement,
and read-only HTTP methods. Public use requires HTTPS at the reverse proxy because Basic
credentials accompany each protected request.

TLS is deliberately not terminated by Jarvis. A reverse proxy such as Cloudflare may
terminate public HTTPS and forward to this loopback HTTP origin. The `/mcp` endpoint
contains write-capable tools, so HTTP MCP remains disabled by default. Enabling it requires
both the external Bearer token file and an explicit MCP Host allowlist entry; missing or
incorrect credentials receive `401`. Jarvis 1.4.0 does not change Cloudflare or open a
router port.

## Safety contract

- Only visible Markdown files inside the configured vault are accessible.
- Hidden paths such as `.obsidian` and symbolic links are rejected.
- Create and move operations never overwrite an existing destination.
- Append, update, and move require the current `sha256` returned by `read_note`.
- Previous note contents are copied to `/state/versions` before mutation.
- Restores require fresh hashes for both the current note and selected saved version.
- Restoring a version first preserves the current note as another saved version.
- Mutation metadata is appended to `/state/audit.jsonl`; note contents are not logged.
- Capture contents are stored only in the protected state directory. Capture lists and
  audit tools return metadata, not raw contents.
- Capture status changes require a current `record_sha256` and follow the enforced
  transition matrix described above.
- The HTTP container uses Docker's bridge network but publishes its MCP port only on
  `127.0.0.1`; it has no Linux capabilities, uses a read-only root filesystem, applies
  CPU/memory/process limits, and only the vault and state mounts are writable.
- The launcher runs the container as the invoking Linux user so synchronized files
  retain the correct ownership.
- The HTTP service uses one constrained container. Multiple clients can read concurrently,
  while `/state/.jarvis-mutation.lock` serializes mutations.
- The launcher stops only its own session container after disconnect or termination.

## Local tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

On Windows, the POSIX file-mode test is intentionally skipped. It must run on Ubuntu
before activation.

## Release verification

`scripts/release_helpers.py` provides fail-closed commands used by the installer. It
validates the complete archive inventory and hashes in memory before manually writing
verified files, rejects traversal, links and undeclared members, verifies that the
backup command created one new checksum-valid snapshot, and restores the 1.3.2
launcher if post-activation verification fails. The helper itself is delivered as a
separate SHA-256-pinned artifact so it can verify the archive before extraction.

## Runtime paths

The restricted launcher mounts:

- the synchronized vault as `/vault`;
- protected Jarvis state as `/state`;
- when web note reading is enabled, the password file read-only as
  `/run/secrets/jarvis-web-note-password`.

The existing stdio transport remains available alongside the HTTP transport.
