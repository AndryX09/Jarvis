CONSOLE_PAGE_HTML = """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Console</title>
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
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 10% 0%, rgba(226, 183, 20, 0.12), transparent 28rem),
        var(--background);
      color: var(--text);
      font: 15px/1.6 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 48px 0 72px;
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 26px;
      align-items: flex-start;
    }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(32px, 6vw, 52px);
      line-height: 1;
      letter-spacing: -0.04em;
    }
    p { margin: 0; }
    .lede {
      max-width: 64ch;
      color: var(--muted);
      font-size: 16px;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 8px 14px;
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--text);
      text-decoration: none;
      background: rgba(19, 23, 28, 0.88);
      white-space: nowrap;
    }
    .pill.accent {
      border-color: var(--accent);
      color: var(--accent);
    }
    .summary {
      margin-bottom: 22px;
      padding: 18px 20px;
      border: 1px solid rgba(97, 208, 149, 0.25);
      border-radius: 16px;
      background: rgba(97, 208, 149, 0.06);
      color: #d9f7e7;
    }
    .summary strong { color: var(--success); }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .card {
      padding: 22px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: linear-gradient(145deg, rgba(25, 31, 38, 0.96), rgba(19, 23, 28, 0.96));
      box-shadow: 0 18px 55px rgba(0, 0, 0, 0.18);
    }
    .card h2 {
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.1;
    }
    .card p {
      color: var(--muted);
      margin-bottom: 14px;
    }
    ul {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 8px;
    }
    li::marker { color: var(--accent); }
    .hint {
      margin-top: 14px;
      color: #cfd8e3;
      font-size: 14px;
    }
    code { color: var(--accent); }
    footer {
      margin-top: 28px;
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 760px) {
      header { flex-direction: column; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Interfaccia operativa</p>
        <h1>Jarvis Console</h1>
        <p class="lede">Questa console non duplica Obsidian e non duplica il sito di stato: serve per guidare i flussi che Jarvis gestisce meglio del solo vault, a partire da cattura, organizzazione, scrittura confermata e triage.</p>
      </div>
      <nav class="actions" aria-label="Azioni rapide">
        <a class="pill accent" href="/dashboard">Apri dashboard</a>
        <a class="pill" href="/notes">Leggi note consentite</a>
        <a class="pill" href="/">Torna allo stato</a>
      </nav>
    </header>

    <section class="summary" aria-label="Posizionamento">
      <strong>Ruoli separati:</strong> il watcher resta un backend silenzioso che preserva materiale ed eventi; la Jarvis Console è il punto in cui l’utente sceglie il flusso giusto senza ricordare parole magiche.
    </section>

    <section class="grid" aria-label="Modalità operative Jarvis">
      <article class="card">
        <h2>Cattura</h2>
        <p>Serve a non perdere spunti. Qui il testo resta grezzo o in incubazione, senza diventare subito una decisione o una nota definitiva.</p>
        <ul>
          <li>salvare un’idea veloce</li>
          <li>conservare il testo originale</li>
          <li>marcare il materiale come da valutare</li>
        </ul>
        <p class="hint">Esempio: <code>questa è un’idea buona</code> → capture o incubazione, non pubblicazione automatica.</p>
      </article>

      <article class="card">
        <h2>Organizzazione</h2>
        <p>Serve a capire dove va il contenuto seguendo la policy <code>Sistema - gestione delle note</code>, cercando duplicati e pagine già pertinenti.</p>
        <ul>
          <li>valutare se aggiornare una nota esistente</li>
          <li>proporre una nuova nota solo quando ha senso</li>
          <li>mantenere separate Natura e Stato</li>
        </ul>
        <p class="hint">Obiettivo: meno note duplicate, più collocazione corretta.</p>
      </article>

      <article class="card">
        <h2>Scrittura</h2>
        <p>Qui Jarvis applica davvero le modifiche confermate, usando hash/versioning e senza trasformare idee in decisioni da solo.</p>
        <ul>
          <li>aggiungere contenuto alla nota giusta</li>
          <li>creare una nuova nota solo se la policy lo giustifica</li>
          <li>preservare la formulazione originale dell’utente</li>
        </ul>
        <p class="hint">Questa modalità tocca il vault; le altre possono fermarsi alla proposta.</p>
      </article>

      <article class="card">
        <h2>Triage</h2>
        <p>Qui si gestiscono coda di acquisizione, capture pending/ready/processed e gli eventi del watcher senza affidarsi a una chat agentica continua.</p>
        <ul>
          <li>leggere capture e stato pipeline</li>
          <li>cambiare stato con summary esplicito</li>
          <li>controllare watcher e audit</li>
        </ul>
        <p class="hint">Questo è il pezzo più utile quando vuoi Jarvis operativo anche senza AI.</p>
        <p class="hint"><a class="pill accent" href="/console/triage">Apri il workbench di triage</a></p>
      </article>
    </section>

    <footer>Prima fetta: questa pagina definisce i flussi. I prossimi step possono agganciare azioni reali, starting dal triage manuale delle capture.</footer>
  </main>
</body>
</html>
"""
