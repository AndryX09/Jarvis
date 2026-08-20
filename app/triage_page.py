from __future__ import annotations

import html
from typing import Iterable


def render_triage_page(
    captures: Iterable[dict[str, object]],
    *,
    console_path: str,
    dashboard_path: str,
    status_path: str,
    listing_endpoint: str,
    detail_endpoint_prefix: str,
    action_path: str,
    active_status: str,
    selected_capture: dict[str, object] | None = None,
    selected_capture_id: str = "",
    flash_message: str = "",
    flash_error: str = "",
) -> str:
    items = list(captures)
    effective_selected_id = selected_capture_id or str(
        (selected_capture or {}).get("capture_id", "")
    )
    if items:
        capture_cards = "\n".join(
            _render_capture_card(
                item,
                detail_endpoint_prefix=detail_endpoint_prefix,
                action_path=action_path,
                active_status=active_status,
                selected_capture_id=effective_selected_id,
            )
            for item in items
        )
    else:
        label = html.escape(active_status)
        capture_cards = (
            f'<article class="empty"><h2>Nessuna capture {label}</h2>'
            '<p>Il watcher non ha materiale in questa coda.</p></article>'
        )

    flash_html = ""
    if flash_message:
        flash_html = (
            '<section class="flash success" aria-live="polite">'
            f"{html.escape(flash_message)}"
            "</section>"
        )
    elif flash_error:
        flash_html = (
            '<section class="flash error" aria-live="polite">'
            f"{html.escape(flash_error)}"
            "</section>"
        )

    detail_panel = _render_detail_panel(selected_capture, detail_endpoint_prefix=detail_endpoint_prefix)

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Console — Triage capture</title>
  <style>
    :root {{
      color-scheme: dark;
      --background: #0b0d10;
      --surface: #13171c;
      --surface-raised: #191f26;
      --border: #29313a;
      --text: #edf2f7;
      --muted: #8e9aa7;
      --accent: #e2b714;
      --success: #61d095;
      --danger: #ef6b73;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: radial-gradient(circle at 10% 0%, rgba(226, 183, 20, 0.12), transparent 28rem), var(--background);
      color: var(--text);
      font: 15px/1.6 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ width: min(1240px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 72px; }}
    header {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 24px; }}
    .eyebrow {{ margin: 0 0 8px; color: var(--accent); font-size: 12px; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(28px, 6vw, 44px); line-height: 1; letter-spacing: -.04em; }}
    .lede, .muted {{ color: var(--muted); }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ display: inline-flex; align-items: center; min-height: 38px; padding: 8px 14px; border: 1px solid var(--border); border-radius: 999px; color: var(--text); text-decoration: none; background: rgba(19, 23, 28, .88); }}
    .pill.accent {{ border-color: var(--accent); color: var(--accent); }}
    .summary {{ margin-bottom: 18px; padding: 18px 20px; border: 1px solid rgba(97, 208, 149, .25); border-radius: 16px; background: rgba(97, 208, 149, .06); }}
    .summary strong {{ color: var(--success); }}
    .filters {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 18px; }}
    .filters a {{ display: inline-flex; align-items: center; min-height: 36px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); text-decoration: none; }}
    .filters a.active {{ border-color: var(--accent); color: var(--accent); }}
    .flash {{ margin-bottom: 18px; padding: 14px 18px; border-radius: 14px; border: 1px solid transparent; }}
    .flash.success {{ background: rgba(97, 208, 149, .08); border-color: rgba(97, 208, 149, .35); color: #d9f7e7; }}
    .flash.error {{ background: rgba(239, 107, 115, .08); border-color: rgba(239, 107, 115, .35); color: #ffd8db; }}
    .workspace {{ display: grid; gap: 18px; grid-template-columns: minmax(0, 1.2fr) minmax(340px, .8fr); align-items: start; }}
    .stack {{ display: grid; gap: 16px; }}
    .capture, .empty, .detail {{ padding: 20px; border: 1px solid var(--border); border-radius: 16px; background: linear-gradient(145deg, rgba(25, 31, 38, .96), rgba(19, 23, 28, .96)); }}
    .capture.selected {{ border-color: var(--accent); box-shadow: 0 0 0 1px rgba(226, 183, 20, .24) inset; }}
    .capture h2, .empty h2, .detail h2 {{ margin: 0 0 8px; font-size: 22px; }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 8px 12px; margin: 14px 0 0; }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; }}
    .badges {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .badge {{ padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); color: var(--accent); background: rgba(226, 183, 20, .08); font-size: 13px; }}
    .pipeline-note {{ margin-top: 12px; color: #cfd8e3; font-size: 13px; }}
    .capture-body {{ display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr) 320px; align-items: start; }}
    .capture-title-row {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
    .select-link {{ color: var(--accent); text-decoration: none; font-size: 14px; white-space: nowrap; }}
    .capture-form {{ display: grid; gap: 10px; padding: 14px; border: 1px solid var(--border); border-radius: 14px; background: rgba(11, 13, 16, .45); }}
    label {{ display: grid; gap: 6px; font-size: 13px; color: var(--muted); }}
    textarea {{ min-height: 96px; resize: vertical; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: #0b0d10; color: var(--text); font: inherit; }}
    .form-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    button {{ padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px; background: #151921; color: var(--text); font: inherit; cursor: pointer; }}
    button.primary {{ border-color: var(--success); color: var(--success); }}
    button.danger {{ border-color: var(--danger); color: var(--danger); }}
    .detail-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 14px; }}
    .detail pre {{ margin: 12px 0 0; padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: rgba(11, 13, 16, .7); color: var(--text); white-space: pre-wrap; word-break: break-word; font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    code {{ color: var(--accent); word-break: break-all; }}
    @media (max-width: 1080px) {{ .workspace {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 880px) {{ .capture-body {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 760px) {{ header {{ flex-direction: column; }} dl {{ grid-template-columns: 1fr; }} .capture-title-row, .detail-head {{ flex-direction: column; align-items: flex-start; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Dashboard privata</p>
        <h1>Triage capture</h1>
        <p class="lede">Coda capture.</p>
      </div>
      <nav class="actions" aria-label="Azioni rapide">
        <a class="pill accent" href="{console_path}">Console</a>
        <a class="pill" href="{dashboard_path}">Dashboard</a>
        <a class="pill" href="{status_path}">Stato</a>
      </nav>
    </header>

    <section class="summary" aria-label="Stato triage" data-endpoint="{listing_endpoint}">
      <strong>Capture {html.escape(active_status)}:</strong> {len(items)}
    </section>

    {flash_html}

    <nav class="filters" aria-label="Filtri capture">
      {_render_filter('/dashboard/triage?status=pending', 'pending', active_status)}
      {_render_filter('/dashboard/triage?status=ready', 'ready', active_status)}
      {_render_filter('/dashboard/triage?status=processed', 'processed', active_status)}
      {_render_filter('/dashboard/triage?status=skipped', 'skipped', active_status)}
    </nav>

    <section class="workspace" data-selected-capture="{html.escape(effective_selected_id)}">
      <section class="stack" aria-label="Capture {html.escape(active_status)}">
        {capture_cards}
      </section>
      {detail_panel}
    </section>
  </main>
</body>
</html>
"""


def _render_capture_card(
    capture: dict[str, object], *, detail_endpoint_prefix: str, action_path: str, active_status: str, selected_capture_id: str
) -> str:
    title = html.escape(str(capture.get("title", "Capture senza titolo")))
    capture_id = html.escape(str(capture.get("capture_id", "")))
    source_kind = html.escape(str(capture.get("source_kind", "")))
    created = html.escape(str(capture.get("created_utc", "")))
    status = html.escape(str(capture.get("status", "")))
    record_sha = html.escape(str(capture.get("record_sha256", "")))
    summary = html.escape(str(capture.get("summary", ""))) or "—"
    pipeline_note = _pipeline_note(capture)
    labels = capture.get("labels", [])
    if isinstance(labels, list) and labels:
        label_html = "".join(
            f'<span class="badge">{html.escape(str(label))}</span>' for label in labels
        )
    else:
        label_html = '<span class="badge">nessuna etichetta</span>'
    action_form = _render_action_form(capture_id, record_sha, status, action_path, active_status)
    selected_class = " selected" if str(capture.get("capture_id", "")) == selected_capture_id else ""
    select_href = f"/dashboard/triage?status={html.escape(active_status)}&selected={capture_id}"
    return f"""
      <article class="capture{selected_class}" data-capture-id="{capture_id}">
        <div class="capture-title-row">
          <h2>{title}</h2>
          <a class="select-link" href="{select_href}">Apri</a>
        </div>
        <p class="muted"><code>{detail_endpoint_prefix}{capture_id}</code></p>
        <div class="capture-body">
          <div>
            <dl>
              <dt>Capture ID</dt><dd><code>{capture_id}</code></dd>
              <dt>Stato</dt><dd>{status}</dd>
              <dt>Sorgente</dt><dd>{source_kind}</dd>
              <dt>Creata</dt><dd>{created}</dd>
              <dt>Summary</dt><dd>{summary}</dd>
              <dt>Record SHA</dt><dd><code>{record_sha}</code></dd>
            </dl>
            <div class="badges" aria-label="Etichette capture">{label_html}</div>
            <p class="pipeline-note">{pipeline_note}</p>
          </div>
          {action_form}
        </div>
      </article>
    """


def _render_action_form(
    capture_id: str, record_sha: str, current_status: str, action_path: str, active_status: str
) -> str:
    organize_link = ""
    if current_status == "pending":
        actions = (
            '<button class="primary" type="submit" name="status" value="ready">Segna ready</button>'
            '<button class="danger" type="submit" name="status" value="skipped">Salta</button>'
        )
    elif current_status == "ready":
        actions = (
            '<button class="danger" type="submit" name="status" value="skipped">Riporta skipped</button>'
        )
        organize_link = (
            f'<a class="select-link" href="/dashboard/organize?selected={capture_id}">Organizza</a>'
        )
    else:
        actions = '<p class="muted">Nessuna azione rapida.</p>'
    return f"""
      <form class="capture-form" method="post" action="{action_path}">
        <input type="hidden" name="capture_id" value="{capture_id}">
        <input type="hidden" name="expected_record_sha256" value="{record_sha}">
        <input type="hidden" name="return_status" value="{html.escape(active_status)}">
        <label>
          Summary
          <textarea name="summary" placeholder="Esito sintetico" required></textarea>
        </label>
        {organize_link}
        <div class="form-actions">{actions}</div>
      </form>
    """


def _render_detail_panel(
    selected_capture: dict[str, object] | None, *, detail_endpoint_prefix: str
) -> str:
    if not selected_capture:
        return (
            '<aside class="detail"><h2>Dettaglio</h2><p class="muted">Seleziona una capture.</p></aside>'
        )
    capture_id = html.escape(str(selected_capture.get("capture_id", "")))
    title = html.escape(str(selected_capture.get("title", "Capture senza titolo")))
    status = html.escape(str(selected_capture.get("status", "")))
    source_kind = html.escape(str(selected_capture.get("source_kind", "")))
    created = html.escape(str(selected_capture.get("created_utc", "")))
    summary = html.escape(str(selected_capture.get("summary", ""))) or "—"
    pipeline_note = _pipeline_note(selected_capture)
    content = html.escape(str(selected_capture.get("content", "")))
    output_paths = selected_capture.get("output_paths", [])
    if isinstance(output_paths, list) and output_paths:
        outputs = "".join(f'<span class="badge">{html.escape(str(path))}</span>' for path in output_paths)
    else:
        outputs = '<span class="badge">nessun output</span>'
    return f"""
      <aside class="detail">
        <div class="detail-head">
          <div>
            <h2>Dettaglio</h2>
            <p class="muted">{title}</p>
          </div>
          <code>{detail_endpoint_prefix}{capture_id}</code>
        </div>
        <dl>
          <dt>Capture ID</dt><dd><code>{capture_id}</code></dd>
          <dt>Stato</dt><dd>{status}</dd>
          <dt>Sorgente</dt><dd>{source_kind}</dd>
          <dt>Creata</dt><dd>{created}</dd>
          <dt>Summary</dt><dd>{summary}</dd>
        </dl>
        <div class="badges" aria-label="Output capture">{outputs}</div>
        <p class="pipeline-note">{pipeline_note}</p>
        <pre>{content}</pre>
      </aside>
    """


def _pipeline_note(capture: dict[str, object]) -> str:
    status = str(capture.get("status", "")).strip()
    output_paths = capture.get("output_paths", [])
    output_count = len(output_paths) if isinstance(output_paths, list) else 0
    if status == "processed":
        return f"Output {output_count}"
    if status == "ready":
        return "Attende output"
    if status == "skipped":
        return "Esclusa dalla pipeline"
    return "In triage"


def _render_filter(path: str, label: str, active_status: str) -> str:
    active = " active" if label == active_status else ""
    return f'<a class="{active.strip()}" href="{path}">{html.escape(label)}</a>'
