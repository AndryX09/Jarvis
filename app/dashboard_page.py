LOGIN_PAGE_HTML = """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Accesso — Jarvis</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #090b10; color: #f4f5f7; }
    main { width: min(100%, 420px); padding: 32px; border: 1px solid #252a35; border-radius: 18px; background: #11141b; box-shadow: 0 24px 80px #0008; }
    .eyebrow { margin: 0 0 10px; color: #77e6b6; font-size: 12px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
    h1 { margin: 0 0 10px; font-size: 30px; }
    p { margin: 0 0 24px; color: #a8afbd; line-height: 1.55; }
    label { display: block; margin-bottom: 8px; font-size: 14px; font-weight: 650; }
    input { width: 100%; padding: 14px 16px; border: 1px solid #343b49; border-radius: 11px; background: #090b10; color: #fff; font: inherit; font-size: 22px; letter-spacing: .2em; text-align: center; }
    input:focus { outline: 2px solid #77e6b6; outline-offset: 2px; }
    button { width: 100%; margin-top: 16px; padding: 13px 18px; border: 0; border-radius: 11px; background: #77e6b6; color: #07110d; font: inherit; font-weight: 800; cursor: pointer; }
    a { display: inline-block; margin-top: 22px; color: #a8afbd; text-decoration: none; }
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">Jarvis Core</p>
    <h1>Dashboard privata</h1>
    <p>Inserisci il codice temporaneo generato dal tuo autenticatore.</p>
    <form action="/login" method="post">
      <label for="code">Codice a 6 cifre</label>
      <input id="code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required autofocus>
      <button type="submit">Entra</button>
    </form>
    <a href="/">Torna allo stato pubblico</a>
  </main>
</body>
</html>
"""


DASHBOARD_PAGE_HTML = """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Processi Jarvis</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #090b10; color: #f4f5f7; }
    header, main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 30px 0 22px; }
    .header-copy { display: grid; gap: 10px; }
    .eyebrow { margin: 0 0 7px; color: #77e6b6; font-size: 12px; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(28px, 5vw, 44px); }
    .nav { display: flex; gap: 10px; flex-wrap: wrap; }
    .nav a { display: inline-flex; align-items: center; min-height: 36px; padding: 8px 12px; border: 1px solid #343b49; border-radius: 999px; color: #cbd0da; text-decoration: none; }
    .nav a.active { border-color: #77e6b6; color: #77e6b6; }
    .readonly { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid #2c493d; border-radius: 999px; background: #10251d; color: #8bf0c3; font-size: 13px; font-weight: 750; }
    .readonly::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #77e6b6; box-shadow: 0 0 14px #77e6b6; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 14px; padding-bottom: 28px; }
    .card { grid-column: span 4; min-height: 150px; padding: 20px; border: 1px solid #252a35; border-radius: 16px; background: #11141b; }
    .wide { grid-column: span 8; }
    .full { grid-column: 1 / -1; }
    h2 { margin: 0 0 17px; font-size: 14px; color: #a8afbd; letter-spacing: .04em; }
    .metric { margin: 0; font-size: 32px; font-weight: 820; }
    .muted { color: #858d9c; }
    dl { display: grid; grid-template-columns: 1fr auto; gap: 10px 18px; margin: 0; }
    dt { color: #929aaa; } dd { margin: 0; font-weight: 720; }
    ul { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
    li { display: flex; justify-content: space-between; gap: 14px; padding-top: 9px; border-top: 1px solid #222733; color: #c7ccd5; }
    footer { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 0 0 34px; color: #858d9c; font-size: 13px; }
    button { padding: 9px 13px; border: 1px solid #343b49; border-radius: 9px; background: transparent; color: #cbd0da; font: inherit; cursor: pointer; }
    @media (max-width: 760px) { .card, .wide { grid-column: 1 / -1; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body data-dashboard="read-only">
  <header>
    <div class="header-copy"><div><p class="eyebrow">Jarvis Core</p><h1>Processi Jarvis</h1></div><nav class="nav" aria-label="Navigazione dashboard"><a class="active" href="/dashboard">Dashboard</a><a href="/dashboard/console">Console</a><a href="/dashboard/triage">Triage</a></nav></div>
    <span class="readonly">Sola lettura</span>
  </header>
  <main class="grid">
    <section class="card"><h2>Core</h2><p class="metric" id="core-state">—</p><p class="muted" id="core-version">In caricamento</p></section>
    <section class="card"><h2>Note indicizzate</h2><p class="metric" id="note-count">—</p><p class="muted">Solo metadati; nessun contenuto esposto</p></section>
    <section class="card"><h2>Eventi audit</h2><p class="metric" id="audit-count">—</p><p class="muted">Registro delle operazioni Jarvis</p></section>
    <section class="card wide"><h2>Pipeline di acquisizione</h2><dl><dt>Totale</dt><dd id="capture-total">—</dd><dt>In attesa</dt><dd id="capture-pending">—</dd><dt>Pronte</dt><dd id="capture-ready">—</dd><dt>Elaborate</dt><dd id="capture-processed">—</dd></dl></section>
    <section class="card wide"><h2>Watcher deterministico</h2><dl><dt>Stato</dt><dd id="watcher-state">—</dd><dt>Eventi</dt><dd id="watcher-events">—</dd><dt>Catture create</dt><dd id="watcher-captures">—</dd><dt>Da revisionare</dt><dd id="watcher-review">—</dd><dt>Errori</dt><dd id="watcher-errors">—</dd></dl></section>
    <section class="card"><h2>Sicurezza</h2><dl><dt>MCP HTTP</dt><dd id="mcp-http-state">In verifica</dd><dt>Cancellazione automatica</dt><dd>Assente</dd><dt>Dashboard</dt><dd>Read-only</dd></dl></section>
    <section class="card full"><h2>Attività recente</h2><ul id="activity"><li><span>Caricamento</span><time>—</time></li></ul></section>
  </main>
  <footer>
    <span id="updated">Aggiornamento in corso</span>
    <form action="/logout" method="post"><button type="submit">Esci</button></form>
  </footer>
  <script>
    const setText = (id, value) => { document.getElementById(id).textContent = String(value ?? "—"); };
    async function refresh() {
      try {
        const response = await fetch("/api/dashboard/status", { cache: "no-store", credentials: "same-origin" });
        if (response.status === 401) { location.assign("/login"); return; }
        if (!response.ok) throw new Error("status unavailable");
        const data = await response.json();
        setText("core-state", data.core.service || "Online");
        setText("core-version", `Versione ${data.core.version}`);
        setText("note-count", data.core.note_count);
        setText("audit-count", data.core.audit_event_count);
        setText("capture-total", data.ingestion.captures.total);
        setText("capture-pending", data.ingestion.captures.pending);
        setText("capture-ready", data.ingestion.captures.ready);
        setText("capture-processed", data.ingestion.captures.processed);
        setText("watcher-state", data.watcher.service);
        setText("watcher-events", data.watcher.events_processed);
        setText("watcher-captures", data.watcher.captures_created);
        setText("watcher-review", data.watcher.review_required);
        setText("watcher-errors", data.watcher.errors);
        setText("mcp-http-state", data.security.http_mcp_enabled ? "Abilitato" : "Bloccato");
        const activity = document.getElementById("activity");
        activity.replaceChildren();
        for (const event of data.activity) {
          const item = document.createElement("li");
          const action = document.createElement("span");
          const when = document.createElement("time");
          action.textContent = event.action || "Evento Jarvis";
          when.textContent = event.timestamp_utc || "—";
          item.append(action, when);
          activity.append(item);
        }
        if (!data.activity.length) {
          const item = document.createElement("li");
          item.textContent = "Nessuna attività registrata";
          activity.append(item);
        }
        setText("updated", `Aggiornato ${new Date().toLocaleTimeString("it-IT")}`);
      } catch (error) {
        setText("core-state", "Non disponibile");
        setText("updated", "Aggiornamento non riuscito");
      }
    }
    refresh();
    setInterval(refresh, 15000);
  </script>
</body>
</html>
"""
