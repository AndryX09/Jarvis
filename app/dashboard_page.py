import os
from pathlib import Path
import stat


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





DASHBOARD_PAGE_MAX_BYTES = 256 * 1024
DEFAULT_DASHBOARD_PAGE_PATH = (
    Path(__file__).resolve().parent / "dashboard_ui" / "dashboard.html"
)


def load_dashboard_page_html(path_text: str = "") -> str:
    path = Path(path_text) if path_text else DEFAULT_DASHBOARD_PAGE_PATH
    if path.is_symlink():
        raise ValueError("dashboard UI file must not be a symbolic link")
    resolved = path.resolve(strict=True)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(resolved, flags)
    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            raise ValueError("dashboard UI path must name a regular file")
        if file_status.st_size > DASHBOARD_PAGE_MAX_BYTES:
            raise ValueError("dashboard UI file is too large")

        chunks = []
        remaining = DASHBOARD_PAGE_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > DASHBOARD_PAGE_MAX_BYTES:
            raise ValueError("dashboard UI file is too large")
    finally:
        os.close(descriptor)
    return content.decode("utf-8")
