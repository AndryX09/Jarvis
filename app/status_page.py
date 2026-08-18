STATUS_PAGE_HTML = """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Core</title>
  <style>
    :root {
      color-scheme: dark;
      --background: #0b0d10;
      --surface: #13171c;
      --surface-raised: #191f26;
      --border: #29313a;
      --text: #edf2f7;
      --muted: #8e9aa7;
      --accent: #e2b714;
      --success: #61d095;
      --danger: #ff7b72;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 15% 0%, rgba(226, 183, 20, 0.09), transparent 34rem),
        var(--background);
      color: var(--text);
      font: 15px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    main {
      width: min(960px, calc(100% - 32px));
      margin: 0 auto;
      padding: 56px 0 72px;
    }

    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 28px;
    }

    .eyebrow {
      margin: 0 0 6px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: clamp(32px, 6vw, 52px);
      line-height: 1;
      letter-spacing: -0.04em;
    }

    .connection {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-height: 36px;
      padding: 7px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(19, 23, 28, 0.88);
      color: var(--muted);
      white-space: nowrap;
    }

    .header-actions { display: flex; align-items: center; gap: 10px; }
    .notes-link {
      display: none;
      min-height: 36px;
      padding: 7px 12px;
      border: 1px solid var(--accent);
      border-radius: 999px;
      color: var(--accent);
      text-decoration: none;
      white-space: nowrap;
    }
    .notes-link.available { display: inline-flex; align-items: center; }

    .connection-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(226, 183, 20, 0.12);
    }

    .connection.online { color: var(--success); }
    .connection.online .connection-dot {
      background: var(--success);
      box-shadow: 0 0 0 4px rgba(97, 208, 149, 0.12);
    }

    .connection.offline { color: var(--danger); }
    .connection.offline .connection-dot {
      background: var(--danger);
      box-shadow: 0 0 0 4px rgba(255, 123, 114, 0.12);
    }

    .hero,
    .card {
      border: 1px solid var(--border);
      background: linear-gradient(145deg, rgba(25, 31, 38, 0.96), rgba(19, 23, 28, 0.96));
      box-shadow: 0 18px 55px rgba(0, 0, 0, 0.2);
    }

    .hero {
      display: grid;
      grid-template-columns: 1.5fr 1fr 1fr;
      overflow: hidden;
      border-radius: 18px;
      margin-bottom: 18px;
    }

    .hero-item { padding: 24px; }
    .hero-item + .hero-item { border-left: 1px solid var(--border); }

    .label {
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .value {
      display: block;
      font-size: 25px;
      font-weight: 720;
      letter-spacing: -0.02em;
      overflow-wrap: anywhere;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .card {
      min-height: 112px;
      padding: 20px;
      border-radius: 14px;
    }

    .card .value { font-size: 18px; }
    .boolean-true { color: var(--success); }
    .boolean-false { color: var(--muted); }

    .error {
      padding: 18px 20px;
      border: 1px solid rgba(255, 123, 114, 0.35);
      border-radius: 14px;
      background: rgba(255, 123, 114, 0.08);
      color: var(--danger);
    }

    footer {
      margin-top: 24px;
      color: var(--muted);
      font-size: 13px;
    }

    code { color: var(--accent); }

    @media (max-width: 680px) {
      main { padding-top: 34px; }
      header { align-items: flex-start; flex-direction: column; }
      .hero { grid-template-columns: 1fr; }
      .hero-item + .hero-item {
        border-top: 1px solid var(--border);
        border-left: 0;
      }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Stato del server</p>
        <h1>Jarvis Core</h1>
      </div>
      <div class="header-actions">
        <a class="notes-link available" href="/dashboard/console">Console</a>
        <a class="notes-link" id="dashboard-link" href="/dashboard">Dashboard</a>
        <a class="notes-link" id="notes-link" href="/notes">Leggi note</a>
        <div class="connection" id="connection-state" role="status" aria-live="polite">
          <span class="connection-dot" aria-hidden="true"></span>
          <span id="connection-label">Connessione…</span>
        </div>
      </div>
    </header>

    <section class="hero" aria-label="Riepilogo Jarvis">
      <div class="hero-item">
        <span class="label">Servizio</span>
        <span class="value" id="service">—</span>
      </div>
      <div class="hero-item">
        <span class="label">Versione</span>
        <span class="value" id="version">—</span>
      </div>
      <div class="hero-item">
        <span class="label">Note visibili</span>
        <span class="value" id="note-count">—</span>
      </div>
    </section>

    <section class="grid" id="status-grid" aria-label="Dati di Jarvis Core"></section>
    <footer>I dati provengono in tempo reale da <code>/api/status</code>.</footer>
  </main>

  <script>
    const fields = [
      ["Modalità vault", "vault_mode"],
      ["Modalità sessioni", "session_mode"],
      ["Eventi di audit", "audit_event_count"],
      ["Coda di acquisizione", "ingestion_available"],
      ["Originali preservati", "raw_material_is_preserved"],
      ["Policy transizioni", "capture_status_transition_policy_enforced"],
      ["Cancellazione disponibile", "delete_tool_available"],
      ["Rete richiesta", "network_required"]
    ];

    function displayValue(value) {
      if (value === true) return "Sì";
      if (value === false) return "No";
      if (value === null || value === undefined || value === "") return "—";
      return String(value);
    }

    function setText(id, value) {
      document.getElementById(id).textContent = displayValue(value);
    }

    function renderCards(data) {
      const grid = document.getElementById("status-grid");
      grid.replaceChildren();

      for (const [label, key] of fields) {
        const card = document.createElement("article");
        card.className = "card";

        const labelElement = document.createElement("span");
        labelElement.className = "label";
        labelElement.textContent = label;

        const valueElement = document.createElement("span");
        valueElement.className = "value";
        if (typeof data[key] === "boolean") {
          valueElement.classList.add(data[key] ? "boolean-true" : "boolean-false");
        }
        valueElement.textContent = displayValue(data[key]);

        card.append(labelElement, valueElement);
        grid.append(card);
      }
    }

    function setConnection(state, label) {
      const connection = document.getElementById("connection-state");
      connection.classList.remove("online", "offline");
      connection.classList.add(state);
      document.getElementById("connection-label").textContent = label;
    }

    async function loadStatus() {
      try {
        const response = await fetch("/api/status", {
          headers: { "Accept": "application/json" },
          cache: "no-store"
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        if (data.error) throw new Error(data.error);

        setText("service", data.service);
        setText("version", data.version);
        setText("note-count", data.note_count);
        if (data.web_note_reading_available) {
          document.getElementById("notes-link").classList.add("available");
        }
        if (data.dashboard_available) {
          document.getElementById("dashboard-link").classList.add("available");
        }
        renderCards(data);
        setConnection("online", "Connesso");
      } catch (error) {
        const grid = document.getElementById("status-grid");
        const message = document.createElement("p");
        message.className = "error";
        message.textContent = `Impossibile leggere lo stato: ${error.message}`;
        grid.replaceChildren(message);
        setConnection("offline", "Non raggiungibile");
      }
    }

    loadStatus();
  </script>
</body>
</html>
"""
