NOTES_PAGE_HTML = """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Note consentite — Jarvis Core</title>
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
      --danger: #ff7b72;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--background);
      color: var(--text);
      font: 15px/1.55 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      width: min(1200px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }
    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 22px;
    }
    .eyebrow {
      margin: 0 0 5px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    h1 { margin: 0; font-size: clamp(28px, 5vw, 44px); line-height: 1.05; }
    a { color: var(--accent); }
    .layout {
      display: grid;
      grid-template-columns: minmax(240px, 0.7fr) minmax(0, 2fr);
      min-height: 68vh;
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      background: var(--surface);
    }
    aside {
      padding: 18px;
      border-right: 1px solid var(--border);
      background: rgba(25, 31, 38, 0.72);
    }
    .scope {
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
    }
    #note-list { display: grid; gap: 8px; }
    .note-button {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 9px;
      background: var(--surface);
      color: var(--text);
      font: inherit;
      text-align: left;
      overflow-wrap: anywhere;
      cursor: pointer;
    }
    .note-button:hover,
    .note-button:focus-visible { border-color: var(--accent); outline: none; }
    .pagination { display: flex; gap: 8px; margin-top: 14px; }
    .pagination button {
      flex: 1;
      padding: 8px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
    }
    .pagination button:disabled { color: var(--muted); cursor: default; opacity: 0.55; }
    article { min-width: 0; padding: 24px; }
    #note-path {
      margin: 0 0 15px;
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    #note-content {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: 14px/1.65 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
    }
    .message { color: var(--muted); }
    .error { color: var(--danger); }
    @media (max-width: 760px) {
      header { align-items: start; flex-direction: column; }
      .layout { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--border); }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Lettura protetta</p>
        <h1>Note consentite</h1>
      </div>
      <a href="/">Torna allo stato</a>
    </header>

    <section class="layout">
      <aside>
        <p class="scope" id="scope-label">Caricamento allowlist…</p>
        <nav id="note-list" aria-label="Note disponibili"></nav>
        <div class="pagination" aria-label="Paginazione note">
          <button type="button" id="previous-page" disabled>Precedenti</button>
          <button type="button" id="next-page" disabled>Successive</button>
        </div>
      </aside>
      <article>
        <p id="note-path">Seleziona una nota.</p>
        <pre id="note-content" class="message">Il contenuto resterà in sola lettura.</pre>
      </article>
    </section>
  </main>

  <script>
    const listElement = document.getElementById("note-list");
    const pathElement = document.getElementById("note-path");
    const contentElement = document.getElementById("note-content");
    const scopeElement = document.getElementById("scope-label");
    const previousPageElement = document.getElementById("previous-page");
    const nextPageElement = document.getElementById("next-page");
    let currentOffset = 0;
    let pageSize = 500;
    let nextOffset = null;

    async function loadNote(path) {
      pathElement.textContent = path;
      contentElement.className = "message";
      contentElement.textContent = "Lettura…";
      try {
        const response = await fetch(`/api/note?path=${encodeURIComponent(path)}`, {
          headers: { "Accept": "application/json" },
          credentials: "same-origin",
          cache: "no-store"
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const note = await response.json();
        contentElement.className = "";
        contentElement.textContent = note.content;
      } catch (error) {
        contentElement.className = "error";
        contentElement.textContent = `Impossibile leggere la nota: ${error.message}`;
      }
    }

    async function loadNotes(offset = 0) {
      try {
        const response = await fetch(`/api/notes?offset=${offset}`, {
          headers: { "Accept": "application/json" },
          credentials: "same-origin",
          cache: "no-store"
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        currentOffset = data.offset;
        pageSize = data.page_size;
        nextOffset = data.next_offset;
        previousPageElement.disabled = currentOffset === 0;
        nextPageElement.disabled = nextOffset === null;
        const firstNumber = data.notes.length ? currentOffset + 1 : 0;
        const lastNumber = currentOffset + data.notes.length;
        scopeElement.textContent = `Scope: ${data.scope} · note ${firstNumber}–${lastNumber}`;
        listElement.replaceChildren();
        for (const note of data.notes) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "note-button";
          button.textContent = note.path;
          button.addEventListener("click", () => loadNote(note.path));
          listElement.append(button);
        }
        if (data.notes.length === 0) {
          scopeElement.textContent = "Nessuna nota consentita dallo scope corrente.";
        }
      } catch (error) {
        scopeElement.className = "scope error";
        scopeElement.textContent = `Impossibile leggere l’elenco: ${error.message}`;
      }
    }

    previousPageElement.addEventListener("click", () => {
      loadNotes(Math.max(0, currentOffset - pageSize));
    });
    nextPageElement.addEventListener("click", () => {
      if (nextOffset !== null) loadNotes(nextOffset);
    });
    loadNotes();
  </script>
</body>
</html>
"""
