from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, request


class WebPanel:
    """Lightweight dashboard for bot status and RPC controls."""

    def __init__(self, api=None, bot=None, host: str = "127.0.0.1", port: int = 5001):
        self.api = api
        self.bot = bot
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self._thread = None

        self.activity_setter: Optional[Callable[..., bool]] = None
        self.activity_getter: Optional[Callable[[], Dict[str, Any]]] = None

        self.last_command: Dict[str, Any] = {
            "mode": "none",
            "text": "",
            "emoji": "",
            "activity_type": "custom",
            "timestamp": int(time.time()),
            "result": "idle",
            "transport": "idle",
            "requested_payload": {},
        }
        self._last_transport = "idle"

        if bot is not None or api is not None:
            self.set_activity_hooks(self._default_activity_setter)

        self._setup_routes()

    def set_activity_hooks(
        self,
        setter: Callable[..., bool],
        getter: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self.activity_setter = setter
        self.activity_getter = getter

    def _safe_apply_activity(
        self,
        text: str,
        emoji: str = "",
        activity_type: str = "custom",
        mode: str = "custom",
    ) -> bool:
        requested_payload = {
            "text": text,
            "emoji": emoji,
            "activity_type": activity_type,
        }
        if not self.activity_setter:
            self.last_command = {
                "mode": mode,
                "text": text,
                "emoji": emoji,
                "activity_type": activity_type,
                "timestamp": int(time.time()),
                "result": "no-setter",
                "transport": "none",
                "requested_payload": requested_payload,
            }
            return False

        try:
            ok = bool(self.activity_setter(text, emoji_name=emoji, activity_type=activity_type))
            self.last_command = {
                "mode": mode,
                "text": text,
                "emoji": emoji,
                "activity_type": activity_type,
                "timestamp": int(time.time()),
                "result": "ok" if ok else "failed",
                "transport": self._last_transport,
                "requested_payload": requested_payload,
            }
            return ok
        except Exception:
            self.last_command = {
                "mode": mode,
                "text": text,
                "emoji": emoji,
                "activity_type": activity_type,
                "timestamp": int(time.time()),
                "result": "error",
                "transport": "exception",
                "requested_payload": requested_payload,
            }
            return False

    def _default_activity_setter(
        self,
        text: str,
        emoji_name: str = "",
        activity_type: str = "custom",
    ) -> bool:
      if not text.strip():
        cleared = False

        if self.bot is not None and hasattr(self.bot, "set_activity"):
          try:
            self.bot.set_activity(None)
            cleared = True
            self._last_transport = "bot.set_activity(clear)"
          except Exception:
            pass

        if self.api is not None:
          try:
            payload = {
              "custom_status": {
                "text": "",
                "emoji_name": None,
                "emoji_id": None,
              }
            }
            resp = self.api.request("PATCH", "/users/@me/settings", data=payload)
            if resp is not None and resp.status_code == 200:
              cleared = True
              self._last_transport = "api.custom_status(clear)"
          except Exception:
            pass

        return cleared

      if activity_type == "custom" and self.api is not None:
        try:
          payload = {
            "custom_status": {
              "text": text,
              "emoji_name": emoji_name or None,
              "emoji_id": None,
            }
          }
          resp = self.api.request("PATCH", "/users/@me/settings", data=payload)
          if resp is not None and resp.status_code == 200:
            self._last_transport = "api.custom_status"
            return True
        except Exception:
          pass

      if self.bot is not None and hasattr(self.bot, "set_activity"):
        try:
          activity_map = {
            "playing": 0,
            "streaming": 1,
            "listening": 2,
            "watching": 3,
            "competing": 5,
            "custom": 4,
          }
          activity = {
            "type": activity_map.get(activity_type, 4),
            "name": text,
            "state": text,
          }
          self.bot.set_activity(activity)
          self._last_transport = "bot.set_activity"
          return True
        except Exception:
          return False

      return False

    def _current_activity(self) -> Dict[str, Any]:
        if self.activity_getter:
            try:
                state = self.activity_getter() or {}
                return {
                    "text": str(state.get("text", "")),
                    "emoji": str(state.get("emoji", "")),
                    "activity_type": str(state.get("activity_type", "custom")),
                    "updated": int(state.get("updated", int(time.time()))),
                }
            except Exception:
                pass

        return {
            "text": str(self.last_command.get("text", "")),
            "emoji": str(self.last_command.get("emoji", "")),
            "activity_type": str(self.last_command.get("activity_type", "custom")),
            "updated": int(self.last_command.get("timestamp", int(time.time()))),
        }

    def _setup_routes(self) -> None:
        @self.app.get("/")
        def index() -> str:
            return self._render_index()

        @self.app.get("/status")
        def status() -> Any:
            return jsonify(
                {
                    "ok": True,
                    "host": self.host,
                    "port": self.port,
                    "rpc_enabled": bool(self.activity_setter),
                    "current_activity": self._current_activity(),
                    "last_command": self.last_command,
                    "last_transport": self._last_transport,
                }
            )

        @self.app.get("/api/rpc/preview")
        def rpc_preview() -> Any:
            return jsonify(
                {
                    "ok": True,
                    "activity": self._current_activity(),
                    "last_command": self.last_command,
              "last_transport": self._last_transport,
                }
            )

        @self.app.post("/api/rpc/apply")
        def rpc_apply() -> Any:
            payload = request.get_json(silent=True) or {}
            text = str(payload.get("text", "")).strip()
            emoji = str(payload.get("emoji", "")).strip()
            activity_type = str(payload.get("activity_type", "custom")).strip().lower() or "custom"

            if not text:
                return jsonify({"ok": False, "error": "text is required"}), 400

            if activity_type not in {"custom", "playing", "streaming", "listening", "watching", "competing"}:
                activity_type = "custom"

            ok = self._safe_apply_activity(text, emoji=emoji, activity_type=activity_type, mode="custom")
            return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

        @self.app.post("/api/rpc/preset")
        def rpc_preset() -> Any:
            payload = request.get_json(silent=True) or {}
            preset = str(payload.get("preset", "")).strip().lower()

            presets = {
                "vrchat": {"text": "In VRChat", "emoji": "vr", "activity_type": "playing"},
                "beat": {"text": "Beat Saber session", "emoji": "notes", "activity_type": "playing"},
                "chill": {"text": "VR lounge chill", "emoji": "sparkles", "activity_type": "custom"},
                "world": {"text": "Building a VR world", "emoji": "tools", "activity_type": "competing"},
            }

            if preset not in presets:
                return jsonify({"ok": False, "error": "unknown preset"}), 400

            data = presets[preset]
            ok = self._safe_apply_activity(
                data["text"],
                emoji=data["emoji"],
                activity_type=data["activity_type"],
                mode=f"preset:{preset}",
            )
            return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

        @self.app.post("/api/rpc/clear")
        def rpc_clear() -> Any:
            ok = self._safe_apply_activity("", emoji="", activity_type="custom", mode="clear")
            return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

    def _render_index(self) -> str:
        return """<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>Aria Control Panel</title>
<style>
:root {
  --bg: #f6f3ee;
  --ink: #1f2937;
  --panel: #ffffff;
  --line: #d6cec2;
  --accent: #1f7a8c;
  --accent-2: #bf6f45;
  --ok: #2f855a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: \"IBM Plex Sans\", \"Segoe UI\", sans-serif;
  color: var(--ink);
  background:
    radial-gradient(circle at 20% -10%, #f3e9dc 0%, transparent 40%),
    radial-gradient(circle at 100% 0%, #dbe9ee 0%, transparent 30%),
    var(--bg);
}
.wrap {
  max-width: 980px;
  margin: 2rem auto;
  padding: 0 1rem 2rem;
}
.hero {
  display: grid;
  gap: 0.75rem;
  margin-bottom: 1.2rem;
}
.h1 {
  margin: 0;
  font-size: clamp(1.5rem, 4vw, 2.3rem);
  letter-spacing: 0.02em;
  font-family: \"Space Grotesk\", \"IBM Plex Sans\", sans-serif;
}
.sub {
  margin: 0;
  opacity: 0.85;
}
.grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 1rem;
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 1rem;
  box-shadow: 0 6px 26px rgba(31, 41, 55, 0.07);
}
.left { grid-column: span 7; }
.right { grid-column: span 5; }
@media (max-width: 900px) {
  .left, .right { grid-column: span 12; }
}
.h2 {
  margin: 0 0 0.6rem;
  font-size: 1.05rem;
  font-family: \"Space Grotesk\", \"IBM Plex Sans\", sans-serif;
}
.row {
  display: grid;
  gap: 0.65rem;
  margin-bottom: 0.65rem;
}
.input, select {
  width: 100%;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 10px;
  padding: 0.6rem 0.72rem;
  font: inherit;
}
.btns {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
button {
  border: 0;
  border-radius: 10px;
  padding: 0.58rem 0.9rem;
  font: inherit;
  cursor: pointer;
  transition: transform 120ms ease, filter 120ms ease;
}
button:hover { transform: translateY(-1px); filter: brightness(0.97); }
.b-accent { background: var(--accent); color: #fff; }
.b-muted { background: #e8ecef; color: #12202b; }
.b-warm { background: var(--accent-2); color: #fff; }
.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
}
@media (max-width: 640px) {
  .preset-grid { grid-template-columns: 1fr; }
}
.preview {
  border: 1px dashed var(--line);
  background: #fffdfa;
  border-radius: 12px;
  padding: 0.85rem;
}
.kv {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 0.35rem 0.65rem;
  font-size: 0.95rem;
}
.tag {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: #e7f4f7;
  color: #0b5563;
  font-size: 0.8rem;
}
.ok { color: var(--ok); font-weight: 600; }
.note { font-size: 0.88rem; opacity: 0.8; }
.json {
  margin-top: 0.65rem;
  max-height: 180px;
  overflow: auto;
  background: #f6f8fb;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.55rem;
  font-size: 0.82rem;
}
</style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"hero\">
      <h1 class=\"h1\">Aria RPC Dashboard</h1>
      <p class=\"sub\">Apply VR-style presence presets, set custom activity, and watch live preview updates.</p>
    </div>

    <div class=\"grid\">
      <section class=\"card left\">
        <h2 class=\"h2\">Quick Presets</h2>
        <div class=\"preset-grid\">
          <button class=\"b-accent\" onclick=\"applyPreset('vrchat')\">VRChat</button>
          <button class=\"b-accent\" onclick=\"applyPreset('beat')\">Beat Saber</button>
          <button class=\"b-warm\" onclick=\"applyPreset('chill')\">VR Chill</button>
          <button class=\"b-warm\" onclick=\"applyPreset('world')\">World Builder</button>
        </div>

        <h2 class=\"h2\" style=\"margin-top:1rem;\">Custom RPC</h2>
        <div class=\"row\">
          <input id=\"text\" class=\"input\" placeholder=\"Status text (required)\" />
          <input id=\"emoji\" class=\"input\" placeholder=\"Emoji name (optional)\" />
          <select id=\"atype\">
            <option value=\"custom\">custom</option>
            <option value=\"playing\">playing</option>
            <option value=\"streaming\">streaming</option>
            <option value=\"listening\">listening</option>
            <option value=\"watching\">watching</option>
            <option value=\"competing\">competing</option>
          </select>
        </div>
        <div class=\"btns\">
          <button class=\"b-accent\" onclick=\"applyCustom()\">Apply Custom</button>
          <button class=\"b-muted\" onclick=\"clearRpc()\">Clear</button>
          <button class=\"b-muted\" onclick=\"refreshPreview()\">Refresh</button>
        </div>
        <p class=\"note\">This panel only updates activity through your running bot process hooks.</p>
      </section>

      <section class=\"card right\">
        <h2 class=\"h2\">Live Preview <span class=\"tag\">auto-refresh</span></h2>
        <div class=\"preview\">
          <div class=\"kv\">
            <div>Text</div><div id=\"pv-text\">-</div>
            <div>Emoji</div><div id=\"pv-emoji\">-</div>
            <div>Type</div><div id=\"pv-type\">-</div>
            <div>Updated</div><div id=\"pv-updated\">-</div>
            <div>Last cmd</div><div id=\"pv-cmd\">-</div>
            <div>Result</div><div id=\"pv-result\">-</div>
            <div>Transport</div><div id=\"pv-transport\">-</div>
          </div>
          <pre class=\"json\" id=\"pv-json\">{}</pre>
        </div>
        <p id=\"msg\" class=\"note\"></p>
      </section>
    </div>
  </div>

<script>
async function postJSON(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function setMsg(text, ok) {
  const el = document.getElementById('msg');
  el.textContent = text || '';
  el.className = ok ? 'ok' : 'note';
}

function stamp(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}

function fillPreview(payload) {
  const a = (payload && payload.activity) || {};
  const c = (payload && payload.last_command) || {};
  document.getElementById('pv-text').textContent = a.text || '-';
  document.getElementById('pv-emoji').textContent = a.emoji || '-';
  document.getElementById('pv-type').textContent = a.activity_type || '-';
  document.getElementById('pv-updated').textContent = stamp(a.updated);
  document.getElementById('pv-cmd').textContent = c.mode || '-';
  document.getElementById('pv-result').textContent = c.result || '-';
  document.getElementById('pv-transport').textContent = c.transport || payload.last_transport || '-';
  document.getElementById('pv-json').textContent = JSON.stringify(c.requested_payload || {}, null, 2);
}

async function applyPreset(name) {
  const { data } = await postJSON('/api/rpc/preset', { preset: name });
  fillPreview(data);
  setMsg(data.ok ? 'Preset applied.' : ('Failed: ' + (data.error || 'unknown error')), !!data.ok);
}

async function applyCustom() {
  const text = document.getElementById('text').value.trim();
  const emoji = document.getElementById('emoji').value.trim();
  const activity_type = document.getElementById('atype').value;
  const { data } = await postJSON('/api/rpc/apply', { text, emoji, activity_type });
  fillPreview(data);
  setMsg(data.ok ? 'Custom activity applied.' : ('Failed: ' + (data.error || 'unknown error')), !!data.ok);
}

async function clearRpc() {
  const { data } = await postJSON('/api/rpc/clear', {});
  fillPreview(data);
  setMsg(data.ok ? 'Activity cleared.' : ('Failed to clear activity.'), !!data.ok);
}

async function refreshPreview() {
  const res = await fetch('/api/rpc/preview');
  const data = await res.json().catch(() => ({}));
  fillPreview(data);
}

setInterval(refreshPreview, 2500);
refreshPreview();
</script>
</body>
</html>
"""

    def run(self) -> None:
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return True
