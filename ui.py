from __future__ import annotations

from fastapi import HTTPException, Request


def require_ui_token(request: Request, expected_token: str) -> None:
    supplied = request.headers.get("x-jarvis-token") or request.query_params.get("token")
    if supplied != expected_token:
        raise HTTPException(status_code=401, detail="Jarvis UI token required.")


def ui_shell_html(token: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Jarvis Console</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07100d; --panel:#10201a; --line:#24483d; --text:#e8fff8; --muted:#9bc6bb; --accent:#39d1a6; --blue:#34a9ff; }}
    body {{ margin:0; font-family: ui-sans-serif, Segoe UI, sans-serif; background: radial-gradient(circle at 20% 0%, #123428, #07100d 42%); color:var(--text); }}
    main {{ max-width:1100px; margin:0 auto; padding:28px; display:grid; gap:18px; }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; }}
    h1 {{ font-size:28px; margin:0; letter-spacing:0; }}
    section {{ border:1px solid var(--line); background:color-mix(in srgb, var(--panel) 88%, transparent); border-radius:8px; padding:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
    textarea,input,button {{ border-radius:6px; border:1px solid var(--line); background:#07130f; color:var(--text); padding:10px; }}
    textarea {{ min-height:90px; resize:vertical; width:100%; box-sizing:border-box; }}
    button {{ background:linear-gradient(135deg,var(--accent),var(--blue)); color:#04100c; font-weight:700; cursor:pointer; }}
    pre {{ white-space:pre-wrap; color:var(--muted); margin:0; }}
  </style>
</head>
<body>
  <main>
    <header><h1>Jarvis Console</h1><span id="mode">loading</span></header>
    <section>
      <textarea id="prompt" placeholder="Ask Jarvis..."></textarea>
      <button id="send">Send</button>
      <button id="speak">Speak Output</button>
    </section>
    <div class="grid">
      <section><h2>Response</h2><pre id="response"></pre></section>
      <section><h2>Presence</h2><pre id="presence"></pre></section>
      <section><h2>Recommendations</h2><pre id="recs"></pre></section>
    </div>
  </main>
  <script>
    const token = {token!r};
    async function getJson(url, opts={{}}) {{
      opts.headers = Object.assign({{'Content-Type':'application/json','x-jarvis-token': token}}, opts.headers || {{}});
      const res = await fetch(url, opts);
      return await res.json();
    }}
    async function refresh() {{
      const presence = await getJson('/v2/presence/state');
      document.getElementById('presence').textContent = JSON.stringify(presence, null, 2);
      document.getElementById('mode').textContent = presence.state.mode;
      const recs = await getJson('/v2/recommendations/next');
      document.getElementById('recs').textContent = JSON.stringify(recs.recommendations, null, 2);
    }}
    document.getElementById('send').onclick = async () => {{
      const user_text = document.getElementById('prompt').value;
      const data = await getJson('/v2/chat', {{method:'POST', body:JSON.stringify({{session_id:'ui', user_text}})}});
      document.getElementById('response').textContent = data.message || JSON.stringify(data, null, 2);
    }};
    document.getElementById('speak').onclick = async () => {{
      const text = document.getElementById('response').textContent || 'Ready.';
      await getJson('/v2/voice/output', {{method:'POST', body:JSON.stringify({{session_id:'ui', text, voice:'clear', speak_locally:true}})}});
    }};
    refresh(); setInterval(refresh, 10000);
  </script>
</body>
</html>"""


def screensaver_html(token: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Jarvis Screensaver</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#05070d; color:#dff; font-family:Segoe UI, sans-serif; overflow:hidden; }}
    .wave {{ position:absolute; width:120vmax; height:120vmax; border:2px solid #1fd5a244; border-radius:50%; animation:pulse 8s linear infinite; }}
    .wave:nth-child(2) {{ animation-delay:-3s; border-color:#1ea5ff44; }}
    .panel {{ position:relative; text-align:center; display:grid; gap:12px; }}
    .clock {{ font-size:clamp(42px, 9vw, 120px); }}
    .muted {{ color:#86cfc4; }}
    @keyframes pulse {{ from {{ transform:scale(.25); opacity:.75; }} to {{ transform:scale(1); opacity:.05; }} }}
  </style>
</head>
<body>
  <div class="wave"></div><div class="wave"></div>
  <div class="panel">
    <div class="clock" id="clock"></div>
    <div class="muted" id="weather"></div>
    <div id="reminder"></div>
    <div class="muted" id="status"></div>
  </div>
  <script>
    const token = {token!r};
    async function tick() {{
      document.getElementById('clock').textContent = new Date().toLocaleTimeString([], {{hour:'2-digit', minute:'2-digit'}});
      const res = await fetch('/v2/presence/state', {{headers:{{'x-jarvis-token': token}}}});
      const data = await res.json();
      const widgets = data.screensaver_render.widgets;
      document.getElementById('weather').textContent = widgets.weather || '';
      document.getElementById('reminder').textContent = widgets.top_reminder || '';
      document.getElementById('status').textContent = widgets.status || data.state.mode;
    }}
    tick(); setInterval(tick, 5000);
  </script>
</body>
</html>"""
