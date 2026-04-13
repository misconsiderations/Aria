from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from flask import Flask, jsonify, redirect, send_from_directory, request


class WebPanel:
    """Lightweight web panel wired to the new WebUI assets with instance isolation."""

    def __init__(self, api=None, bot=None, host: str = "127.0.0.1", port: int = 5001, instance_id: str = "main", owner_id: str = None):
        self.api = api
        self.bot = bot
        self.host = host
        self.port = int(port)
        self.instance_id = instance_id
        self.owner_id = owner_id  # Owner of this bot instance
        self._start_time = time.time()

        self._thread: threading.Thread | None = None
        self._last_start_error = ""

        base_dir = os.path.dirname(__file__)
        self._webui_templates = os.path.join(base_dir, "web_ui", "templates")
        self._webui_static = os.path.join(base_dir, "web_ui", "static")
        self._base_dir = base_dir

        # Flask serves /static/* from the new web_ui/static directory.
        self.app = Flask(__name__, static_folder=self._webui_static, static_url_path="/static")
        self.app.secret_key = os.getenv("ARIA_WEBPANEL_SECRET", f"aria-webpanel-{instance_id}-{owner_id}")

        self._setup_routes()

    def _require_owner(self, f):
        """Decorator to ensure only owner can access this endpoint."""
        def wrapper(*args, **kwargs):
            # Check Authorization header for instance verification
            auth = request.headers.get("Authorization", "")
            if not self._verify_auth(auth):
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper

    def _verify_auth(self, auth_token: str) -> bool:
        """Verify that the request is from the owner."""
        if not self.owner_id:
            return True  # Main bot instance, allow all
        # Token format: "Bearer <owner_id>_<instance_id>"
        if not auth_token.startswith("Bearer "):
            return False
        token_parts = auth_token[7:].split("_")
        if len(token_parts) != 2:
            return False
        token_owner, token_instance = token_parts
        return token_owner == str(self.owner_id) and token_instance == self.instance_id

    def _template_path(self, name: str) -> str:
        return os.path.join(self._webui_templates, name)

    def _read_template(self, name: str) -> str:
        path = self._template_path(name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _render_dashboard(self) -> str:
        try:
            return self._read_template("dashboard.html")
        except Exception:
            return "<h1>Dashboard unavailable</h1><p>Missing web_ui/templates/dashboard.html</p>"

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _bot_data(self) -> dict:
        """Collect live data from the bot instance."""
        b = self.bot
        if b is None:
            return {}
        uptime_secs = int(time.time() - self._start_time)
        hours, rem = divmod(uptime_secs, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hours}h {mins}m {secs}s"

        return {
            "username": getattr(b, "username", None) or "—",
            "user_id": getattr(b, "user_id", None) or "—",
            "prefix": getattr(b, "prefix", None) or "$",
            "status": getattr(b, "_current_status", "online"),
            "connected": getattr(b, "connection_active", False),
            "command_count": getattr(b, "command_count", 0),
            "commands_registered": len(getattr(b, "commands", {})),
            "uptime": uptime_str,
            "instance_id": self.instance_id,
            "owner_restricted": bool(self.owner_id),
        }

    def _analytics_data(self) -> dict:
        """Read analytics.json if available."""
        path = os.path.join(self._base_dir, "analytics.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            metrics = data.get("performance_metrics", {})
            patterns = data.get("command_patterns", {})
            daily = data.get("daily_data", {})

            total_cmds = sum(v.get("commands", 0) for v in daily.values())
            top_cmds = sorted(patterns.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:5]

            times = metrics.get("response_times", [])
            avg_time = round(sum(times) / len(times), 3) if times else 0

            return {
                "total_commands": total_cmds,
                "success_rate": metrics.get("success_rate", 100.0),
                "avg_response_ms": avg_time,
                "top_commands": [{"name": k, "count": v.get("count", 0)} for k, v in top_cmds],
            }
        except Exception:
            return {"total_commands": 0, "success_rate": 100.0, "avg_response_ms": 0, "top_commands": []}

    def _history_data(self) -> dict:
        """Read history_data.json if available."""
        path = os.path.join(self._base_dir, "history_data.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Normalise: can be a list or a dict
            if isinstance(raw, list):
                entries = raw[-20:]
            elif isinstance(raw, dict):
                entries = list(raw.values())[-20:]
            else:
                entries = []
            return {"entries": entries, "total": len(raw) if isinstance(raw, (list, dict)) else 0}
        except Exception:
            return {"entries": [], "total": 0}

    def _boost_data(self) -> dict:
        """Read boost_state.json if available."""
        path = os.path.join(self._base_dir, "boost_state.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        @self.app.get("/")
        @self.app.get("/home")
        def home() -> Any:
            return redirect("/dashboard")

        @self.app.get("/dashboard")
        def dashboard() -> Any:
            return self._render_dashboard()

        @self.app.get("/status")
        def status() -> Any:
            return jsonify(
                {
                    "ok": True,
                    "host": self.host,
                    "port": self.port,
                    "instance": self.instance_id,
                    "owner_restricted": bool(self.owner_id),
                    "running": bool(self._thread and self._thread.is_alive()),
                }
            )

        @self.app.get("/api/bot")
        def api_bot() -> Any:
            if self.owner_id and not self._verify_auth(request.headers.get("Authorization", "")):
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._bot_data()})

        @self.app.get("/api/analytics")
        def api_analytics() -> Any:
            if self.owner_id and not self._verify_auth(request.headers.get("Authorization", "")):
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._analytics_data()})

        @self.app.get("/api/history")
        def api_history() -> Any:
            if self.owner_id and not self._verify_auth(request.headers.get("Authorization", "")):
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._history_data()})

        @self.app.get("/api/boost")
        def api_boost() -> Any:
            if self.owner_id and not self._verify_auth(request.headers.get("Authorization", "")):
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._boost_data()})

        @self.app.get("/api/public/stats")
        def public_stats() -> Any:
            bot_d = self._bot_data()
            return jsonify({
                "ok": True,
                "stats": {
                    "connected": bot_d.get("connected", False),
                    "command_count": bot_d.get("command_count", 0),
                    "uptime": bot_d.get("uptime", "—"),
                    "instance": self.instance_id,
                },
            })

        @self.app.get("/favicon.ico")
        def favicon() -> Any:
            return "", 204

        @self.app.get("/static/<path:asset_path>")
        def static_assets(asset_path: str) -> Any:
            return send_from_directory(self._webui_static, asset_path)

    def run(self) -> None:
        try:
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            self._last_start_error = str(e)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False

        self._last_start_error = ""
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

        # Allow startup errors (for example, port in use) to surface quickly.
        time.sleep(0.35)
        if not self._thread.is_alive():
            if not self._last_start_error:
                self._last_start_error = "webpanel startup thread exited"
            return False
        return True

    def get_last_start_error(self) -> str:
        return str(self._last_start_error or "")
