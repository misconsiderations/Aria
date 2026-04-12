from __future__ import annotations

import os
import threading
import time
from typing import Any

from flask import Flask, jsonify, redirect, request, send_from_directory


class WebPanel:
    """Lightweight web panel wired to the new WebUI assets."""

    def __init__(self, api=None, bot=None, host: str = "127.0.0.1", port: int = 5001):
        self.api = api
        self.bot = bot
        self.host = host
        self.port = int(port)

        self._thread: threading.Thread | None = None
        self._last_start_error = ""

        base_dir = os.path.dirname(__file__)
        self._webui_templates = os.path.join(base_dir, "web_ui", "templates")
        self._webui_static = os.path.join(base_dir, "web_ui", "static")

        # Flask serves /static/* from the new web_ui/static directory.
        self.app = Flask(__name__, static_folder=self._webui_static, static_url_path="/static")
        self.app.secret_key = os.getenv("ARIA_WEBPANEL_SECRET", "aria-webpanel-auth-secret")

        self._setup_routes()

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
                    "running": bool(self._thread and self._thread.is_alive()),
                    "webui_template": self._template_path("dashboard.html"),
                    "webui_static": self._webui_static,
                }
            )

        @self.app.get("/api/public/stats")
        def public_stats() -> Any:
            return jsonify({"ok": True, "stats": {"total_hosted": 0, "connected_count": 0, "total_registered": 0}})

        @self.app.get("/favicon.ico")
        def favicon() -> Any:
            return "", 204

        @self.app.get("/static/<path:asset_path>")
        def static_assets(asset_path: str) -> Any:
            # Explicit route for clarity; Flask static route also handles this path.
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
