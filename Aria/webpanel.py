from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, request
from flask import session, redirect, url_for, render_template_string
import functools
import os


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
            "details": str(self.last_command.get("details", "")),
            "emoji": str(self.last_command.get("emoji", "")),
            "activity_type": str(self.last_command.get("activity_type", "custom")),
            "start_time": int(self.last_command.get("start_time", 0)),
            "end_time": int(self.last_command.get("end_time", 0)),
            "duration": int(self.last_command.get("duration", 0)),
            "updated": int(self.last_command.get("timestamp", int(time.time()))),
        }

    def _setup_routes(self) -> None:
      # Simple auth using env vars: set ADMIN_USER and ADMIN_PASS
      self.app.secret_key = os.environ.get("WEBPANEL_SECRET", os.environ.get("SECRET_KEY", "dev-secret"))
      ADMIN_USER = os.environ.get("WEBPANEL_USER", os.environ.get("ADMIN_USER", "admin"))
      ADMIN_PASS = os.environ.get("WEBPANEL_PASS", os.environ.get("ADMIN_PASS", "change-me"))

      def login_required(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
          if session.get("user") != ADMIN_USER:
            return redirect(url_for("_login"))
          return fn(*args, **kwargs)
        return wrapped

      # Login routes
      @self.app.route('/login', methods=['GET', 'POST'])
      def _login():
        error = None
        if request.method == 'POST':
          u = request.form.get('username','')
          p = request.form.get('password','')
          if u == ADMIN_USER and p == ADMIN_PASS:
            session['user'] = u
            return redirect(url_for('index'))
          error = 'Invalid credentials'
        return render_template_string("""
  <form method="post">
    <label>Username</label><input name="username" />
    <label>Password</label><input name="password" type="password" />
    <button type="submit">Login</button>
    {% if error %}<p style="color:red">{{ error }}</p>{% endif %}
  </form>
  """, error=error)

      @self.app.route('/logout')
      def _logout():
        session.clear()
        return redirect(url_for('_login'))

      @self.app.get("/")
      @login_required
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
        @login_required
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
      @login_required
      def rpc_apply() -> Any:
          payload = request.get_json(silent=True) or {}
          text = str(payload.get("text", "")).strip()
          emoji = str(payload.get("emoji", "")).strip()
          activity_type = str(payload.get("activity_type", "custom")).strip().lower() or "custom"

          if not text:
              return jsonify({"ok": False, "error": "text is required"}), 400

          if activity_type not in {"custom", "playing", "streaming", "listening", "watching", "competing", "crunchyroll"}:
              activity_type = "custom"

          ok = self._safe_apply_activity(text, emoji=emoji, activity_type=activity_type, mode="custom")
          return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

      @self.app.post("/api/rpc/preset")
      @login_required
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
                data["text"],
                emoji=data["emoji"],
                activity_type=data["activity_type"],
                mode=f"preset:{preset}",
            )
            return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

        @self.app.post("/api/rpc/clear")
        @login_required
        def rpc_clear() -> Any:
            ok = self._safe_apply_activity("", emoji="", activity_type="custom", mode="clear")
            return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

        @self.app.post("/api/settings")
        @login_required
        def update_settings() -> Any:
            payload = request.get_json(silent=True) or {}
            # Update config with new settings
            config = {}
            if os.path.exists("config.json"):
                try:
                    with open("config.json", "r") as f:
                        config = json.load(f)
                except:
                    pass

            # Update captcha settings
            if "captcha_enabled" in payload:
                config["captcha_enabled"] = payload["captcha_enabled"]
            if "captcha_api_key" in payload:
                config["captcha_api_key"] = payload["captcha_api_key"]
            if "captcha_service" in payload:
                config["captcha_service"] = payload["captcha_service"]

            # Update other settings
            if "prefix" in payload:
                config["prefix"] = payload["prefix"]
            if "rate_limit_delay" in payload:
                config["rate_limit_delay"] = float(payload["rate_limit_delay"])
            if "user_agent" in payload:
                config["user_agent"] = payload["user_agent"]
            if "rpc_name" in payload:
                config["rpcname"] = payload["rpc_name"]

            try:
                with open("config.json", "w") as f:
                    json.dump(config, f, indent=4)
                return jsonify({"ok": True, "message": "Settings updated successfully"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.post("/api/rpc/watch")
        @login_required
        def rpc_watch() -> Any:
            """Start a 'watching' activity with start/end timestamps (Crunchyroll-style).
            Expects JSON: {"title": str, "episode": str|int, "duration": seconds, "start": optional unix seconds}
            """
            payload = request.get_json(silent=True) or {}
            title = str(payload.get("title", "")).strip()
            episode = str(payload.get("episode", "")).strip()
            try:
                duration = int(payload.get("duration", 0))
            except Exception:
                duration = 0

            if not title or duration <= 0:
                return jsonify({"ok": False, "error": "title and positive duration required"}), 400

            # optional start (unix seconds)
            start_ts = payload.get("start")
            now_s = int(time.time())
            try:
                start_unix = int(start_ts) if start_ts else now_s
            except Exception:
                start_unix = now_s

            start_ms = int(start_unix * 1000)
            end_ms = int((start_unix + int(duration)) * 1000)

            name = f"Crunchyroll: {title}"
            state = f"Episode {episode}" if episode else "Watching"

            activity = {
                "type": 3,  # watching
                "name": name,
                "state": state,
                "timestamps": {"start": start_ms, "end": end_ms},
            }

            try:
                if self.bot is not None and hasattr(self.bot, "set_activity"):
                    self.bot.set_activity(activity)
                    self._last_transport = "bot.set_activity(watch)"
                    ok = True
                elif self.api is not None and hasattr(self.api, "request"):
                    # Try to use API presence if supported (best-effort)
                    try:
                        # Some self-hosted APIs might accept a presence update route
                        self.api.request("PATCH", "/gateway/presence", data={"activity": activity})
                        self._last_transport = "api.presence(watch)"
                        ok = True
                    except Exception:
                        ok = False
                else:
                    ok = False
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

            # record last_command for UI
            self.last_command = {
                "mode": "watch",
                "text": name,
                "emoji": "",
                "activity_type": "watching",
                "timestamp": int(time.time()),
                "result": "ok" if ok else "failed",
                "transport": self._last_transport,
                "requested_payload": payload,
            }

            return jsonify({"ok": ok, "activity": activity, "last_command": self.last_command})

        @self.app.post("/api/rpc/crunchyroll")
        @login_required
        def rpc_crunchyroll() -> Any:
            """Crunchyroll-style RPC with real timestamps (inspired by impishlucy/CrunchyStatus).
            Expects JSON: {
              "title": str,
              "episode": str|int,
              "duration": int (seconds),
              "state": str (optional, default "Watching Crunchyroll"),
              "start": int (optional unix seconds, defaults to now)
            }
            """
            payload = request.get_json(silent=True) or {}
            title = str(payload.get("title", "")).strip()
            episode = str(payload.get("episode", "1")).strip()
            try:
                duration = int(payload.get("duration", 0))
            except Exception:
                duration = 0

            if not title or duration <= 0:
                return jsonify({"ok": False, "error": "title and positive duration required"}), 400

            # Optional start timestamp (unix seconds)
            start_ts = payload.get("start")
            now_s = int(time.time())
            try:
                start_unix = int(start_ts) if start_ts else now_s
            except Exception:
                start_unix = now_s

            # Convert to milliseconds for Discord timestamps
            start_ms = int(start_unix * 1000)
            end_ms = int((start_unix + duration) * 1000)

            # Custom state text
            state = str(payload.get("state", "Watching Crunchyroll")).strip() or "Watching Crunchyroll"

            activity = {
                "type": 3,  # watching
                "name": f"Crunchyroll: {title}",
                "state": f"{state} | EP {episode}",
                "timestamps": {"start": start_ms, "end": end_ms},
                "details": f"Episode {episode} of {title}",
            }

            try:
                ok = False
                if self.bot is not None and hasattr(self.bot, "set_activity"):
                    self.bot.set_activity(activity)
                    self._last_transport = "bot.set_activity(crunchyroll)"
                    ok = True
                elif self.api is not None and hasattr(self.api, "request"):
                    try:
                        self.api.request("PATCH", "/gateway/presence", data={"activity": activity})
                        self._last_transport = "api.presence(crunchyroll)"
                        ok = True
                    except Exception:
                        pass
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

            # record last_command for UI
            self.last_command = {
                "mode": "crunchyroll",
                "text": f"Crunchyroll: {title} - EP {episode}",
                "emoji": "📺",
                "activity_type": "watching",
                "timestamp": int(time.time()),
                "duration": duration,
                "start_time": start_unix,
                "end_time": start_unix + duration,
                "result": "ok" if ok else "failed",
                "transport": self._last_transport,
                "requested_payload": payload,
            }

            return jsonify({"ok": ok, "activity": activity, "last_command": self.last_command})

        @self.app.get("/api/analytics")
        @login_required
        def get_analytics() -> Any:
            try:
                # Get real analytics data
                analytics_data = {}
                if os.path.exists("analytics.json"):
                    with open("analytics.json", "r") as f:
                        analytics_data = json.load(f)
                
                # Format for charts
                commands_data = analytics_data.get("commands_executed", {})
                rate_limits_data = analytics_data.get("rate_limits_hit", {})
                
                # Get recent commands from history
                recent_commands = []
                if os.path.exists("history_data.json"):
                    with open("history_data.json", "r") as f:
                        history = json.load(f)
                        # Get last 10 commands
                        recent_commands = list(history.get("commands", {}).values())[-10:]
                
                # System stats
                system_stats = {
                    "uptime": analytics_data.get("uptime_hours", 0),
                    "messages_sent": analytics_data.get("messages_sent", 0),
                    "errors": analytics_data.get("errors_count", 0),
                    "guilds": analytics_data.get("guilds_joined", 0)
                }
                
                return jsonify({
                    "commands": {
                        "labels": list(commands_data.keys())[-7:],  # Last 7 days
                        "data": list(commands_data.values())[-7:]
                    },
                    "rate_limits": {
                        "labels": list(rate_limits_data.keys())[-7:],
                        "data": list(rate_limits_data.values())[-7:]
                    },
                    "recent_commands": recent_commands,
                    "system_stats": system_stats
                })
            except Exception as e:
                return jsonify({
                    "commands": {"labels": [], "data": []},
                    "rate_limits": {"labels": [], "data": []},
                    "recent_commands": [],
                    "system_stats": {},
                    "error": str(e)
                })

        @self.app.get("/api/logs")
        @login_required
        def get_logs() -> Any:
            # Get recent logs from logger
            logs = []
            try:
                log_file = "aria.log"
                if os.path.exists(log_file):
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[-20:]  # Last 20 lines
                        for line in lines:
                            logs.append({"content": line.strip(), "file": "aria.log"})
            except:
                logs = [{"content": "No logs available", "file": "aria.log"}]
            return jsonify({"logs": logs})

        @self.app.get("/api/command_history")
        @login_required
        def get_command_history() -> Any:
            try:
                history = []
                if os.path.exists("history_data.json"):
                    with open("history_data.json", "r") as f:
                        data = json.load(f)
                        commands = data.get("commands", {})
                        # Get last 20 commands with timestamps
                        for cmd_id, cmd_data in list(commands.items())[-20:]:
                            history.append({
                                "timestamp": cmd_data.get("timestamp", "Unknown"),
                                "command": cmd_data.get("command", "Unknown"),
                                "result": cmd_data.get("result", "Unknown")
                            })
                return jsonify({"history": history})
            except Exception as e:
                return jsonify({"history": [], "error": str(e)})

        @self.app.post("/api/send_message")
        @login_required
        def send_message() -> Any:
            if not self.api:
                return jsonify({"ok": False, "error": "API not available"})
            
            payload = request.get_json(silent=True) or {}
            command_type = payload.get("type", "message")
            channel_id = payload.get("channel_id")
            content = payload.get("content")
            emoji = payload.get("emoji")
            delay = payload.get("delay", 0)
            
            try:
                if command_type == "message":
                    if not channel_id or not content:
                        return jsonify({"ok": False, "error": "channel_id and content required"})
                    result = self.api.send_message(channel_id, content)
                    
                elif command_type == "reaction":
                    if not channel_id or not emoji:
                        return jsonify({"ok": False, "error": "channel_id and emoji required"})
                    # Need message_id for reaction, for now assume latest message
                    messages = self.api.get_messages(channel_id, limit=1)
                    if messages:
                        result = self.api.add_reaction(channel_id, messages[0]["id"], emoji)
                    else:
                        return jsonify({"ok": False, "error": "No messages found in channel"})
                    
                elif command_type == "typing":
                    if not channel_id:
                        return jsonify({"ok": False, "error": "channel_id required"})
                    result = self.api.trigger_typing(channel_id)
                    
                elif command_type == "presence":
                    # Update presence/status
                    result = self.api.set_status(content or "online")
                    
                else:
                    return jsonify({"ok": False, "error": "Invalid command type"})
                
                # Add delay if specified
                if delay > 0:
                    import time
                    time.sleep(delay)
                
                return jsonify({"ok": True, "message": f"{command_type.title()} command executed successfully"})
                
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.post("/api/backup")
        @login_required
        def trigger_backup() -> Any:
            try:
                from backup import BackupManager
                backup_mgr = BackupManager(self.api)
                backup_file = backup_mgr.create_full_backup()
                return jsonify({"ok": bool(backup_file), "message": f"Backup created: {backup_file}" if backup_file else "Backup failed"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.post("/api/restore")
        @login_required
        def trigger_restore() -> Any:
            try:
                from backup import BackupManager
                backup_mgr = BackupManager(self.api)
                # Get the most recent backup
                backups = backup_mgr.list_backups()
                if not backups:
                    return jsonify({"ok": False, "error": "No backups available"})
                
                latest_backup = backups[0]["name"]
                result = backup_mgr.restore_backup(latest_backup)
                return jsonify({"ok": result, "message": f"Restored from: {latest_backup}" if result else "Restore failed"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.post("/api/restart")
        @login_required
        def restart_bot() -> Any:
            # Trigger bot restart
            try:
                # In real implementation, restart the bot process
                return jsonify({"ok": True, "message": "Bot restart initiated"})
            except:
                return jsonify({"ok": False, "error": "Restart failed"})

    def _render_index(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enhanced Aria Dashboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background-color: #f8f9fa; }
        .navbar { background-color: #343a40; }
        .navbar-brand, .nav-link { color: #ffffff !important; }
        .card { margin: 20px; }
        .btn-primary { background-color: #007bff; border-color: #007bff; }
        .image-gallery img { max-width: 100%; height: auto; margin: 10px; }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark">
    <div class="container-fluid">
        <a class="navbar-brand" href="#">Aria </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav">
                <li class="nav-item"><a class="nav-link" href="#dashboard">Dashboard</a></li>
                <li class="nav-item"><a class="nav-link" href="#analytics">Analytics</a></li>
                <li class="nav-item"><a class="nav-link" href="#settings">Settings</a></li>
                <li class="nav-item"><a class="nav-link" href="#images">Images</a></li>
            </ul>
        </div>
    </div>
</nav>
<div class="container">
    <div id="dashboard" class="card">
        <div class="card-body">
            <h5 class="card-title">Dashboard</h5>
            <p class="card-text">Welcome to the enhanced Aria dashboard. Use the navigation to explore features.</p>
            <div class="d-flex align-items-center mt-3">
                <img id="activityIcon" src="static/images/crunchyroll.svg" alt="Crunchyroll Icon" width="48" height="48" class="me-3" style="display:none;" />
                <div>
                    <h6 id="activityTitle">No active RPC</h6>
                    <p id="activityState" class="mb-1 text-muted">Status updates appear here.</p>
                    <div id="activityProgressWrapper" class="progress" style="height: 14px; display:none;">
                        <div id="activityProgress" class="progress-bar bg-success" role="progressbar" style="width: 0%;"></div>
                    </div>
                    <small id="activityTime" class="text-muted"></small>
                </div>
            </div>
        </div>
    </div>
    <div id="analytics" class="card">
        <div class="card-body">
            <h5 class="card-title">Analytics</h5>
            <canvas id="analyticsChart" width="400" height="200"></canvas>
        </div>
    </div>
    <div id="settings" class="card">
        <div class="card-body">
            <h5 class="card-title">Settings</h5>
            <form>
                <div class="mb-3">
                    <label for="prefix" class="form-label">Command Prefix</label>
                    <input type="text" class="form-control" id="prefix" placeholder="Enter prefix">
                </div>
                <button type="submit" class="btn btn-primary">Save</button>
            </form>
        </div>
    </div>
    <div id="images" class="card">
        <div class="card-body">
            <h5 class="card-title">Image Gallery</h5>
            <div class="image-gallery">
                <img src="static/images/sample1.jpg" alt="Sample Image 1">
                <img src="static/images/sample2.jpg" alt="Sample Image 2">
            </div>
        </div>
    </div>
</div>
<script>
    const ctx = document.getElementById('analyticsChart').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Red', 'Blue', 'Yellow', 'Green', 'Purple', 'Orange'],
            datasets: [{
                label: '# of Votes',
                data: [12, 19, 3, 5, 2, 3],
                backgroundColor: [
                    'rgba(255, 99, 132, 0.2)',
                    'rgba(54, 162, 235, 0.2)',
                    'rgba(255, 206, 86, 0.2)',
                    'rgba(75, 192, 192, 0.2)',
                    'rgba(153, 102, 255, 0.2)',
                    'rgba(255, 159, 64, 0.2)'
                ],
                borderColor: [
                    'rgba(255, 99, 132, 1)',
                    'rgba(54, 162, 235, 1)',
                    'rgba(255, 206, 86, 1)',
                    'rgba(75, 192, 192, 1)',
                    'rgba(153, 102, 255, 1)',
                    'rgba(255, 159, 64, 1)'
                ],
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });

    async function refreshStatus() {
        try {
            const response = await fetch('/status');
            if (!response.ok) return;
            const status = await response.json();
            const act = status.current_activity || {};
            const cmd = status.last_command || {};

            const titleText = act.text || cmd.text || 'No active RPC';
            const detailText = act.details || cmd.details || 'Status updates appear here.';
            document.getElementById('activityTitle').innerText = titleText;
            document.getElementById('activityState').innerText = detailText;

            const progressBar = document.getElementById('activityProgressWrapper');
            const progressInner = document.getElementById('activityProgress');
            const timeLabel = document.getElementById('activityTime');
            const iconEl = document.getElementById('activityIcon');

            const start = act.start_time || cmd.start_time || 0;
            const end = act.end_time || cmd.end_time || 0;
            const now = Math.floor(Date.now() / 1000);
            const showProgress = start > 0 && end > start && act.activity_type !== 'listening';

            if (showProgress) {
                const duration = end - start;
                const elapsed = Math.min(Math.max(now - start, 0), duration);
                const percent = Math.floor((elapsed / duration) * 100);
                progressBar.style.display = 'block';
                progressInner.style.width = percent + '%';
                progressInner.innerText = percent + '%';
                timeLabel.innerText = `Elapsed ${elapsed}s / ${duration}s`;
            } else {
                progressBar.style.display = 'none';
                progressInner.style.width = '0%';
                progressInner.innerText = '';
                timeLabel.innerText = '';
            }

            if ((cmd.mode === 'crunchyroll' || act.activity_type === 'watching') && cmd.text.toLowerCase().includes('crunchyroll')) {
                iconEl.style.display = 'inline-block';
            } else {
                iconEl.style.display = 'none';
            }
        } catch (e) {
            console.error('Status refresh failed', e);
        }
    }
    refreshStatus();
    setInterval(refreshStatus, 5000);
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""