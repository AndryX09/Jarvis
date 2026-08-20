from __future__ import annotations

import html


def render_organization_page(
    *,
    captures: list[dict[str, object]],
    selected_capture: dict[str, object] | None,
    selected_capture_id: str,
    console_path: str,
    dashboard_path: str,
    triage_path: str,
    policy_path: str,
    policy_excerpt: str,
    candidates: list[dict[str, str]],
    suggested_output_path: str,
    action_path: str,
    flash_message: str = "",
    flash_error: str = "",
) -> str:
    capture_cards = "\n".join(
        _render_capture_card(item, selected_capture_id=selected_capture_id)
        for item in captures
    )
    if not capture_cards:
        capture_cards = (
            '<article class="empty"><h2>Nessuna capture ready</h2>'
            '<p>Niente da organizzare.</p></article>'
        )

    detail_panel = _render_detail_panel(
        selected_capture=selected_capture,
        policy_path=policy_path,
        policy_excerpt=policy_excerpt,
        candidates=candidates,
        suggested_output_path=suggested_output_path,
        action_path=action_path,
    )

    flash_html = ""
    if flash_message:
        flash_html = f'<section class="flash success">{html.escape(flash_message)}</section>'
    elif flash_error:
        flash_html = f'<section class="flash error">{html.escape(flash_error)}</section>'

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Console — Organizzazione</title>
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
    main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 72px; }}
    header {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 24px; }}
    .eyebrow {{ margin: 0 0 8px; color: var(--accent); font-size: 12px; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(28px, 6vw, 44px); line-height: 1; letter-spacing: -.04em; }}
    .lede, .muted {{ color: var(--muted); }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ display: inline-flex; align-items: center; min-height: 38px; padding: 8px 14px; border: 1px solid var(--border); border-radius: 999px; color: var(--text); text-decoration: none; background: rgba(19, 23, 28, .88); }}
    .pill.accent {{ border-color: var(--accent); color: var(--accent); }}
    .workspace {{ display: grid; gap: 18px; grid-template-columns: minmax(0, 0.9fr) minmax(420px, 1.1fr); align-items: start; }}
    .stack {{ display: grid; gap: 16px; }}
    .capture, .empty, .detail, .panel {{ padding: 20px; border: 1px solid var(--border); border-radius: 16px; background: linear-gradient(145deg, rgba(25, 31, 38, .96), rgba(19, 23, 28, .96)); }}
    .capture.selected {{ border-color: var(--accent); box-shadow: 0 0 0 1px rgba(226, 183, 20, .24) inset; }}
    .capture h2, .empty h2, .detail h2, .panel h2 {{ margin: 0 0 8px; font-size: 22px; }}
    .capture-title-row, .detail-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
    .select-link {{ color: var(--accent); text-decoration: none; font-size: 14px; white-space: nowrap; }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 8px 12px; margin: 14px 0 0; }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; }}
    .detail-grid {{ display: grid; gap: 16px; }}
    .flash {{ margin: 0 0 18px; padding: 14px 18px; border-radius: 14px; border: 1px solid transparent; }}
    .flash.success {{ background: rgba(97, 208, 149, .08); border-color: rgba(97, 208, 149, .35); color: #d9f7e7; }}
    .flash.error {{ background: rgba(239, 107, 115, .08); border-color: rgba(239, 107, 115, .35); color: #ffd8db; }}
    .policy, pre {{ margin: 0; padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: rgba(11, 13, 16, .7); white-space: pre-wrap; word-break: break-word; }}
    code {{ color: var(--accent); word-break: break-all; }}
    ul {{ margin: 0; padding-left: 18px; display: grid; gap: 10px; }}
    li::marker {{ color: var(--accent); }}
    .hint {{ margin-top: 12px; color: #cfd8e3; font-size: 13px; }}
    .apply-form {{ display: grid; gap: 10px; margin-top: 14px; }}
    label {{ display: grid; gap: 6px; font-size: 13px; color: var(--muted); }}
    input, textarea {{ padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: #0b0d10; color: var(--text); font: inherit; }}
    textarea {{ min-height: 96px; resize: vertical; }}
    button {{ padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px; background: #151921; color: var(--text); font: inherit; cursor: pointer; }}
    button.primary {{ border-color: var(--success); color: var(--success); }}
    @media (max-width: 1080px) {{ .workspace {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 760px) {{ header, .capture-title-row, .detail-head {{ flex-direction: column; align-items: flex-start; }} dl {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Dashboard privata</p>
        <h1>Organizzazione</h1>
        <p class="lede">Review proposta.</p>
      </div>
      <nav class="actions" aria-label="Azioni rapide">
        <a class="pill accent" href="{triage_path}">Triage</a>
        <a class="pill" href="{console_path}">Console</a>
        <a class="pill" href="{dashboard_path}">Dashboard</a>
      </nav>
    </header>

    {flash_html}

    <section class="workspace">
      <section class="stack" aria-label="Capture ready">
        {capture_cards}
      </section>
      {detail_panel}
    </section>
  </main>
</body>
</html>
"""


def _render_capture_card(capture: dict[str, object], *, selected_capture_id: str) -> str:
    capture_id = html.escape(str(capture.get("capture_id", "")))
    title = html.escape(str(capture.get("title", "Capture senza titolo")))
    summary = html.escape(str(capture.get("summary", ""))) or "—"
    selected_class = " selected" if str(capture.get("capture_id", "")) == selected_capture_id else ""
    return f"""
      <article class="capture{selected_class}" data-capture-id="{capture_id}">
        <div class="capture-title-row">
          <h2>{title}</h2>
          <a class="select-link" href="/dashboard/organize?selected={capture_id}">Apri</a>
        </div>
        <dl>
          <dt>Capture ID</dt><dd><code>{capture_id}</code></dd>
          <dt>Summary</dt><dd>{summary}</dd>
        </dl>
      </article>
    """


def _render_detail_panel(
    *,
    selected_capture: dict[str, object] | None,
    policy_path: str,
    policy_excerpt: str,
    candidates: list[dict[str, str]],
    suggested_output_path: str,
    action_path: str,
) -> str:
    if not selected_capture:
        return '<aside class="detail"><h2>Dettaglio</h2><p class="muted">Seleziona una capture ready.</p></aside>'

    capture_id = html.escape(str(selected_capture.get("capture_id", "")))
    record_sha = html.escape(str(selected_capture.get("record_sha256", "")))
    title = html.escape(str(selected_capture.get("title", "Capture senza titolo")))
    content = html.escape(str(selected_capture.get("content", "")))
    summary_value = str(selected_capture.get("summary", "")).strip()
    summary = html.escape(summary_value) or "—"
    suggested = html.escape(suggested_output_path)
    initial_output = html.escape(candidates[0]["path"]) if candidates else ""
    candidate_html = "".join(
        f'<li><strong>{html.escape(item["path"])}</strong><br><span class="muted">{html.escape(item["reason"])}</span></li>'
        for item in candidates
    ) or '<li>Nessuna nota candidata.</li>'
    summary_field = html.escape(summary_value)
    return f"""
      <aside class="detail">
        <div class="detail-grid">
          <section class="panel">
            <div class="detail-head">
              <div>
                <h2>{title}</h2>
                <p class="muted">Proposal-first</p>
              </div>
              <code>{capture_id}</code>
            </div>
            <dl>
              <dt>Summary</dt><dd>{summary}</dd>
              <dt>Output proposto</dt><dd><code>{suggested}</code></dd>
              <dt>Policy</dt><dd><code>{html.escape(policy_path)}</code></dd>
            </dl>
            <p class="hint">Nessuna scrittura eseguita.</p>
            <form class="apply-form" method="post" action="{html.escape(action_path)}">
              <input type="hidden" name="capture_id" value="{capture_id}">
              <input type="hidden" name="expected_record_sha256" value="{record_sha}">
              <label>
                Azione
                <select name="write_mode">
                  <option value="">Solo collega output</option>
                  <option value="append_note">Aggiorna nota esistente</option>
                  <option value="create_note">Crea nuova nota</option>
                </select>
              </label>
              <label>
                Percorso nota
                <input name="output_path" value="{initial_output or suggested}" placeholder="Percorso nota" required>
              </label>
              <label>
                Summary
                <textarea name="summary" placeholder="Esito sintetico" required>{summary_field}</textarea>
              </label>
              <button class="primary" type="submit">Segna processed</button>
            </form>
          </section>

          <section class="panel">
            <h2>Note candidate</h2>
            <ul>{candidate_html}</ul>
          </section>

          <section class="panel">
            <h2>Policy</h2>
            <p class="policy">{html.escape(policy_excerpt)}</p>
          </section>

          <section class="panel">
            <h2>Raw</h2>
            <pre>{content}</pre>
          </section>
        </div>
      </aside>
    """
