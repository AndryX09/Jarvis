# Jarvis Core

Jarvis Core is a local-first MCP server for working with a synchronized Markdown vault.
It exposes a small set of tools for reading notes, preserving captured material,
versioning mutations, and reporting operational status without requiring the core service
to use AI.

The project is designed for personal or small-team knowledge bases where safety matters:
original material is preserved, note mutations are versioned, and potentially ambiguous
organization work is kept behind explicit review steps.

## What Jarvis Core provides

- MCP tools for reading, searching, creating, updating, moving, and versioning Markdown
  notes.
- A capture pipeline for preserving raw material before it is triaged.
- A deterministic filesystem watcher that can monitor an inbox folder and queue captured
  material without interpreting it semantically.
- Optional HTTP transport for MCP clients, protected by explicit allowlists and a Bearer
  token.
- Optional authenticated status pages for operational visibility.
- Versioned note mutations and append-only audit metadata.

## Design principles

- **No silent deletion:** the public tool surface deliberately does not expose a delete
  operation.
- **No hidden AI dependency in the core:** the watcher and server enforce deterministic
  rules. AI clients may help with triage, but the core service does not need AI to run.
- **Preserve originals:** captured material is kept in protected state before any later
  processing decision.
- **Confirm ambiguous work:** triage and organization are separate steps. A capture being
  ready does not automatically authorize note creation, updates, or moves.
- **Fail closed:** missing policy, stale hashes, invalid transitions, unsafe paths, and
  broken state stop the operation instead of guessing.
- **Keep secrets out of Git:** tokens, passwords, TOTP secrets, host-specific paths, and
  deployment-specific domains belong outside the repository.

## MCP tool groups

### Status and discovery

- `jarvis_status`
- `list_notes`
- `search_notes`
- `read_note`
- `recent_notes`
- `recent_activity`
- `list_tasks`

### Versioning and mutation

- `create_note`
- `create_inbox_note`
- `append_to_note`
- `update_note`
- `move_note`
- `list_versions`
- `read_version`
- `restore_version`

All note mutations require current revision information and preserve previous contents in
protected state before applying changes.

### Capture and triage

- `ingestion_status`
- `read_ingestion_policy`
- `read_organization_policy`
- `capture_material`
- `list_captures`
- `read_capture`
- `read_pending_captures`
- `update_capture_status`

Capture state transitions are intentionally strict. Raw capture content is preserved and
is not deleted or rewritten by MCP tools.

## Policy model

Jarvis Core uses two independent, user-editable policy notes:

- an acquisition and triage policy;
- a note-organization policy.

The policies are separate on purpose. The acquisition policy governs capture states and
raw material preservation. The organization policy governs whether and how vault notes may
be created, changed, or moved.

There is no silent fallback between the two. If a required policy is missing or if a
request is ambiguous, Jarvis should stop instead of applying an unsafe default.

## Capture workflow

A typical capture flow is:

1. Preserve raw material as a capture.
2. Leave the capture in `pending` until reviewed.
3. During triage, mark the capture as `ready` or `skipped`.
4. Only after explicit confirmation, mark a `ready` capture as `processed` and reference
   the existing Markdown notes that were updated.

Allowed ordinary transitions:

- `pending → ready`
- `pending → skipped`
- `ready → processed`
- `ready → skipped`
- `skipped → pending`
- `skipped → ready`

Rejected transitions include same-state transitions, direct `pending → processed`, direct
`skipped → processed`, and any transition out of `processed`.

A processed capture must include a meaningful summary and reference existing Markdown
output paths. Other states must not contain output paths.

## HTTP transport

Jarvis can run over stdio or Streamable HTTP. HTTP mode is optional and should be enabled
only for trusted clients behind explicit Host/Origin allowlists.

Example local-only configuration:

```text
JARVIS_TRANSPORT=streamable-http
JARVIS_HTTP_HOST=127.0.0.1
JARVIS_HTTP_PORT=8765
JARVIS_HTTP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*
JARVIS_HTTP_ALLOWED_ORIGINS=http://127.0.0.1:*,http://localhost:*
JARVIS_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*
JARVIS_HTTP_MCP_ENABLED=false
JARVIS_MCP_BEARER_TOKEN_FILE=/path/outside/repository/mcp-token
```

When HTTP MCP is enabled, requests to `/mcp` require a Bearer token loaded from an
external file. Never store the token value in Git, logs, command history, screenshots, or
Markdown documentation.

## Authenticated status pages

The server can expose read-only operational pages for status and process visibility. These
pages should show allowlisted metadata only: service state, counts, recent action names,
and watcher health.

They must not expose:

- note contents;
- capture contents;
- secrets;
- shell access;
- process-control buttons;
- unrestricted filesystem paths;
- token or TOTP values.

Use external secret files for dashboard authentication material and keep them outside the
repository.

## Deterministic vault watcher

`app/watcher_service.py` runs as a separate deterministic process. It scans visible
Markdown files, requires stable observations before accepting a transition, and detects
changes that occurred while it was stopped.

The watcher does not use AI and does not write, move, or delete vault notes.

Accepted content is preserved by SHA-256 before the durable snapshot advances. Events are
recorded in append-only watcher audit state and unacknowledged events are kept in a durable
outbox for replay after crashes.

Changes under an inbox folder can create deduplicated `pending` captures. Other visible
Markdown changes are treated conservatively as review-required events rather than being
interpreted semantically.

Operational requirements:

- keep `VAULT_ROOT` and `STATE_ROOT` separate and non-overlapping;
- run only one watcher instance for a given state root;
- keep watcher state outside the synchronized vault;
- preserve content before acknowledging events;
- report only aggregate watcher state in dashboards.

Example interval setting:

```text
JARVIS_WATCHER_INTERVAL_SECONDS=1.0
```

## Optional read-only note browsing

Jarvis can optionally expose read-only note browsing routes. These should be disabled by
default or limited to an explicit scope. If enabled publicly, protect them with HTTPS at
the reverse proxy and with credentials stored outside the repository.

Supported deployment modes may choose scopes such as:

- no note-reading route;
- only overview/panorama notes;
- all visible Markdown notes.

Hidden paths, symlinks, and paths outside the configured vault must remain inaccessible.

## Safety contract

- Only visible Markdown files inside the configured vault are accessible.
- Hidden paths and symbolic links are rejected.
- Create and move operations never overwrite existing destinations.
- Append, update, move, and restore operations require fresh hashes.
- Previous note contents are versioned before mutation.
- Capture contents are stored in protected state.
- Capture status changes require a current `record_sha256` and a valid transition.
- Audit records store mutation metadata, not note contents.
- Runtime secrets are external files, not repository files.
- The service should run with the smallest practical filesystem and network access.

## Local tests

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Some platform-specific tests may be skipped on non-Linux hosts. Run Linux-specific safety
checks on Linux before enabling production watcher behavior.

## Runtime paths

At runtime, configure explicit external paths for:

- the synchronized vault;
- protected Jarvis state;
- Bearer token files;
- dashboard/TOTP secret files;
- optional note-reading password files.

Keep those paths environment-specific and outside Git. This README intentionally avoids
real hostnames, usernames, domains, token paths, and personal vault details.
