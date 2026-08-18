from __future__ import annotations

import html
from typing import Iterable


def render_triage_page(captures: Iterable[dict[str, object]]) -> str:
    items = list(captures)
    if items:
        capture_cards = "\n".join(
            _render_capture_card(item) for item in items
        )
    else:
        capture_cards = (
            '<article class="empty"><h2>Nessuna capture pending</h2>'
            '<p>Il watcher non ha materiale in coda da triagiare in questo momento.</p></article>'
        )

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
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: radial-gradient(circle at 10% 0%, rgba(226, 183, 20, 0.12), transparent 28rem), var(--background);
      color: var(--text);
      font: 15px/1.6 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 72px; }}
    header {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 24px; }}
    .eyebrow {{ margin: 0 0 8px; color: var(--accent); font-size: 12px; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(28px, 6vw, 44px); line-height: 1; letter-spacing: -.04em; }}
    .lede, .muted {{ color: var(--muted); }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ display: inline-flex; align-items: center; min-height: 38px; padding: 8px 14px; border: 1px solid var(--border); border-radius: 999px; color: var(--text); text-decoration: none; background: rgba(19, 23, 28, .88); }}
    .pill.accent {{ border-color: var(--accent); color: var(--accent); }}
    .summary {{ margin-bottom: 18px; padding: 18px 20px; border: 1px solid rgba(97, 208, 149, .25); border-radius: 16px; background: rgba(97, 208, 149, .06); }}
    .summary strong {{ color: var(--success); }}
    .stack {{ display: grid; gap: 16px; }}
    .capture, .empty {{ padding: 20px; border: 1px solid var(--border); border-radius: 16px; background: linear-gradient(145deg, rgba(25, 31, 38, .96), rgba(19, 23, 28, .96)); }}
    .capture h2, .empty h2 {{ margin: 0 0 8px; font-size: 22px; }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 8px 12px; margin: 14px 0 0; }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; }}
    .badges {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .badge {{ padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); color: var(--accent); background: rgba(226, 183, 20, .08); font-size: 13px; }}
    code {{ color: var(--accent); word-break: break-all; }}
    @media (max-width: 760px) {{ header {{ flex-direction: column; }} dl {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Jarvis Console</p>
        <h1>Triage capture</h1>
        <p class="lede">Coda capture.</p>
      </div>
      <nav class="actions" aria-label="Azioni rapide">
        <a class="pill accent" href="/console">Console</a>
        <a class="pill" href="/dashboard">Dashboard</a>
        <a class="pill" href="/">Stato</a>
      </nav>
    </header>

    <section class="summary" aria-label="Stato triage" data-endpoint="/api/console/triage/captures">
      <strong>Capture pending:</strong> {len(items)}
    </section>

    <section class="stack" aria-label="Capture pending">
      {capture_cards}
    </section>
  </main>
</body>
</html>
"""


def _render_capture_card(capture: dict[str, object]) -> str:
    title = html.escape(str(capture.get("title", "Capture senza titolo")))
    capture_id = html.escape(str(capture.get("capture_id", "")))
    source_kind = html.escape(str(capture.get("source_kind", "")))
    created = html.escape(str(capture.get("created_utc", "")))
    status = html.escape(str(capture.get("status", "")))
    record_sha = html.escape(str(capture.get("record_sha256", "")))
    summary = html.escape(str(capture.get("summary", ""))) or "—"
    labels = capture.get("labels", [])
    if isinstance(labels, list) and labels:
        label_html = "".join(
            f'<span class="badge">{html.escape(str(label))}</span>' for label in labels
        )
    else:
        label_html = '<span class="badge">nessuna etichetta</span>'
    return f"""
      <article class="capture" data-capture-id="{capture_id}">
        <h2>{title}</h2>
        <p class="muted"><code>/api/console/triage/captures/{capture_id}</code></p>
        <dl>
          <dt>Capture ID</dt><dd><code>{capture_id}</code></dd>
          <dt>Stato</dt><dd>{status}</dd>
          <dt>Sorgente</dt><dd>{source_kind}</dd>
          <dt>Creata</dt><dd>{created}</dd>
          <dt>Summary</dt><dd>{summary}</dd>
          <dt>Record SHA</dt><dd><code>{record_sha}</code></dd>
        </dl>
        <div class="badges" aria-label="Etichette capture">{label_html}</div>
      </article>
    """
