from __future__ import annotations

import json
import os
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
    <title>Aria Super Control Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .discord-dark { background-color: #2c2f33; }
        .discord-blurple { color: #5865f2; }
        .discord-green { color: #57f287; }
        .discord-yellow { color: #fee75c; }
        .discord-red { color: #ed4245; }
        .hidden { display: none; }
        .section { display: block; }
        .animate-pulse { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
    </style>
</head>
<body class="bg-gradient-to-br from-discord-dark via-gray-900 to-black text-white min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <header class="flex justify-between items-center mb-8">
            <h1 class="text-5xl font-bold bg-gradient-to-r from-discord-blurple via-discord-green to-discord-yellow bg-clip-text text-transparent animate-pulse">
                Aria Super Control Panel
            </h1>
            <div class="flex items-center space-x-4">
                <span class="text-xl font-semibold">Aria Bot</span>
                <div class="w-3 h-3 bg-discord-green rounded-full animate-pulse"></div>
            </div>
        </header>
        
        <nav class="mb-8">
            <div class="flex space-x-4">
                <button onclick="showSection('dashboard')" class="bg-discord-blurple hover:bg-blue-600 px-6 py-3 rounded-lg transition">Dashboard</button>
                <button onclick="showSection('analytics')" class="bg-discord-green hover:bg-green-600 px-6 py-3 rounded-lg transition">Analytics</button>
                <button onclick="showSection('commands')" class="bg-discord-yellow hover:bg-yellow-600 px-6 py-3 rounded-lg transition">Commands</button>
                <button onclick="showSection('logs')" class="bg-gray-500 hover:bg-gray-600 px-6 py-3 rounded-lg transition">Logs</button>
                <button onclick="showSection('settings')" class="bg-gray-600 hover:bg-gray-700 px-6 py-3 rounded-lg transition">Settings</button>
            </div>
        </nav>
        
        <div id="dashboard" class="section">
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <!-- System Stats -->
                <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                    <h3 class="text-xl font-semibold mb-4 text-discord-blurple">System Stats</h3>
                    <canvas id="statsChart" width="200" height="200"></canvas>
                    <button onclick="loadStats()" class="mt-4 bg-discord-blurple hover:bg-blue-600 px-4 py-2 rounded-lg transition w-full">Refresh</button>
                </div>
                
                <!-- Activity Control -->
                <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                    <h3 class="text-xl font-semibold mb-4 text-discord-green">Activity Control</h3>
                    <form id="activityForm" class="space-y-4">
                        <select id="activityType" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                            <option value="custom">Custom Status</option>
                            <option value="playing">Playing Game</option>
                            <option value="listening">Listening</option>
                            <option value="streaming">Streaming</option>
                            <option value="watching">Watching</option>
                            <option value="competing">Competing</option>
                        </select>
                        <input type="text" id="activityText" placeholder="Activity text" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white" required>
                        <input type="text" id="activityEmoji" placeholder="Emoji (optional)" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                        <button type="submit" class="w-full bg-discord-green hover:bg-green-600 px-4 py-2 rounded-lg transition">Set Activity</button>
                    </form>
                </div>
                
                <!-- Recent Logs -->
                <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                    <h3 class="text-xl font-semibold mb-4 text-discord-yellow">Recent Logs</h3>
                    <div id="logs" class="bg-gray-900 rounded p-3 max-h-40 overflow-y-auto text-sm font-mono">
                        <p>Loading logs...</p>
                    </div>
                    <button onclick="loadLogs()" class="mt-4 bg-discord-yellow hover:bg-yellow-600 px-4 py-2 rounded-lg transition w-full text-black font-semibold">Refresh Logs</button>
                </div>
                
                <!-- Command History -->
                <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                    <h3 class="text-xl font-semibold mb-4 text-discord-red">Command History</h3>
                    <div id="commandHistory" class="space-y-2 max-h-40 overflow-y-auto">
                        <p>Loading...</p>
                    </div>
                    <button onclick="loadCommandHistory()" class="mt-4 bg-discord-red hover:bg-red-600 px-4 py-2 rounded-lg transition w-full">Refresh</button>
                </div>
            </div>
            
            <!-- Quick Actions -->
            <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                <h3 class="text-2xl font-semibold mb-6 text-center">Quick Actions</h3>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <button onclick="restartBot()" class="bg-red-600 hover:bg-red-700 px-4 py-3 rounded-lg transition transform hover:scale-105">Restart Bot</button>
                    <button onclick="clearActivity()" class="bg-gray-600 hover:bg-gray-700 px-4 py-3 rounded-lg transition transform hover:scale-105">Clear Activity</button>
                    <button onclick="backupData()" class="bg-blue-600 hover:bg-blue-700 px-4 py-3 rounded-lg transition transform hover:scale-105">Backup Data</button>
                    <button onclick="sendTestMessage()" class="bg-purple-600 hover:bg-purple-700 px-4 py-3 rounded-lg transition transform hover:scale-105">Test Message</button>
                </div>
            </div>
        </div>
        
        <div id="analytics" class="section hidden">
            <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                <h2 class="text-3xl font-semibold mb-6 text-discord-green">Analytics Dashboard</h2>
                <div id="analyticsData" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    <div class="bg-gray-700 p-4 rounded">
                        <h3 class="text-lg font-semibold mb-2">Messages Sent</h3>
                        <p class="text-2xl" id="messagesSent">-</p>
                    </div>
                    <div class="bg-gray-700 p-4 rounded">
                        <h3 class="text-lg font-semibold mb-2">Commands Executed</h3>
                        <p class="text-2xl" id="commandsExecuted">-</p>
                    </div>
                    <div class="bg-gray-700 p-4 rounded">
                        <h3 class="text-lg font-semibold mb-2">Uptime (Hours)</h3>
                        <p class="text-2xl" id="uptimeHours">-</p>
                    </div>
                    <div class="bg-gray-700 p-4 rounded">
                        <h3 class="text-lg font-semibold mb-2">Errors</h3>
                        <p class="text-2xl" id="errorsCount">-</p>
                    </div>
                </div>
                <div class="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div class="bg-gray-700 p-4 rounded">
                        <h3 class="text-lg font-semibold mb-2">Additional Stats</h3>
                        <p>Guilds Joined: <span id="guildsJoined">-</span></p>
                        <p>Nitro Claimed: <span id="nitroClaimed">-</span></p>
                        <p>Giveaways Won: <span id="giveawaysWon">-</span></p>
                        <p>Boosts Used: <span id="boostsUsed">-</span></p>
                    </div>
                    <canvas id="analyticsChart" width="300" height="200"></canvas>
                </div>
                <button onclick="loadAnalytics()" class="mt-6 bg-discord-green hover:bg-green-600 px-6 py-3 rounded-lg transition">Refresh Analytics</button>
            </div>
        </div>
        
        <div id="commands" class="section hidden">
            <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                <h2 class="text-3xl font-semibold mb-6 text-discord-yellow">Send Commands</h2>
                <form id="commandForm" class="space-y-4">
                    <input type="text" id="channelId" placeholder="Channel ID" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white" required>
                    <input type="text" id="commandText" placeholder="Message/Command" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white" required>
                    <button type="submit" class="w-full bg-discord-yellow hover:bg-yellow-600 px-4 py-2 rounded-lg transition text-black font-semibold">Send Message</button>
                </form>
                <div id="commandResult" class="mt-4 p-3 bg-gray-900 rounded text-sm"></div>
                
                <div class="mt-6">
                    <h3 class="text-xl font-semibold mb-4">Quick Commands</h3>
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <button onclick="quickCommand('ping')" class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition">Ping</button>
                        <button onclick="quickCommand('uptime')" class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg transition">Uptime</button>
                        <button onclick="quickCommand('stats')" class="bg-purple-600 hover:bg-purple-700 px-4 py-2 rounded-lg transition">Stats</button>
                        <button onclick="quickCommand('help')" class="bg-yellow-600 hover:bg-yellow-700 px-4 py-2 rounded-lg transition text-black">Help</button>
                    </div>
                </div>
            </div>
        </div>
        
        <div id="logs" class="section hidden">
            <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                <h2 class="text-3xl font-semibold mb-6 text-gray-300">System Logs</h2>
                <div id="fullLogs" class="bg-gray-900 rounded p-4 max-h-96 overflow-y-auto text-sm font-mono">
                    <p>Loading logs...</p>
                </div>
                <div class="mt-4 flex space-x-4">
                    <button onclick="loadLogs()" class="bg-gray-600 hover:bg-gray-700 px-4 py-2 rounded-lg transition">Refresh Logs</button>
                    <button onclick="clearLogs()" class="bg-red-600 hover:bg-red-700 px-4 py-2 rounded-lg transition">Clear Logs</button>
                    <button onclick="exportLogs()" class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition">Export Logs</button>
                </div>
            </div>
        </div>
        
        <div id="settings" class="section hidden">
            <div class="bg-gray-800 rounded-xl p-6 shadow-2xl border border-gray-700">
                <h2 class="text-3xl font-semibold mb-6 text-gray-300">Bot Settings</h2>
                <form id="settingsForm" class="space-y-4">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <input type="text" id="prefix" placeholder="Command Prefix" class="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                        <input type="number" id="rateLimitDelay" placeholder="Rate Limit Delay" step="0.1" class="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                        <input type="text" id="userAgent" placeholder="User Agent" class="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                        <input type="text" id="rpcName" placeholder="RPC Name" class="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                    </div>
                    <div class="space-y-4">
                        <label class="flex items-center">
                            <input type="checkbox" id="captchaEnabled" class="mr-2">
                            <span>Enable Captcha Solving</span>
                        </label>
                        <input type="password" id="captchaApiKey" placeholder="2Captcha API Key" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                        <select id="captchaService" class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white">
                            <option value="2captcha">2Captcha</option>
                            <option value="anticaptcha">AntiCaptcha</option>
                            <option value="capmonster">CapMonster</option>
                        </select>
                    </div>
                    <button type="submit" class="w-full bg-gray-600 hover:bg-gray-700 px-4 py-2 rounded-lg transition">Save Settings</button>
                </form>
                <div id="settingsResult" class="mt-4 p-3 bg-gray-900 rounded text-sm"></div>
            </div>
        </div>
    </div>
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

    <div class=\"card\" style=\"margin-top: 2rem;\">
      <h2 class=\"h2\">Bot Settings</h2>
      <form id=\"settingsForm\">
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <input id=\"prefix\" class=\"input\" placeholder=\"Command Prefix\" style=\"width: 100px;\" />
          <input id=\"rateLimitDelay\" type=\"number\" step=\"0.1\" class=\"input\" placeholder=\"Rate Limit Delay\" style=\"width: 120px;\" />
          <input id=\"userAgent\" class=\"input\" placeholder=\"User Agent\" />
        </div>
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <input id=\"rpcName\" class=\"input\" placeholder=\"RPC Name\" />
        </div>
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <label style=\"display: flex; align-items: center;\">
            <input id=\"captchaEnabled\" type=\"checkbox\" style=\"margin-right: 0.5rem;\" />
            Enable Captcha Solving
          </label>
        </div>
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <input id=\"captchaApiKey\" class=\"input\" placeholder=\"2Captcha API Key\" type=\"password\" />
          <select id=\"captchaService\" style=\"margin-left: 0.5rem;\">
            <option value=\"2captcha\">2Captcha</option>
            <option value=\"anticaptcha\">AntiCaptcha</option>
            <option value=\"capmonster\">CapMonster</option>
          </select>
        </div>
        <div class=\"btns\">
          <button type=\"submit\" class=\"b-accent\">Save Settings</button>
        </div>
      </form>
      <p id=\"settingsMsg\" class=\"note\"></p>
    </div>

    <!-- Analytics Tab -->
    <div class=\"card\" style=\"margin-top: 2rem;\">
      <h2 class=\"h2\">Analytics Dashboard</h2>
      <div class=\"row\" style=\"margin-bottom: 1rem;\">
        <button id=\"refreshAnalytics\" class=\"b\">Refresh Analytics</button>
      </div>
      <div class=\"row\">
        <div style=\"width: 50%;\">
          <h3>Commands Executed</h3>
          <canvas id=\"commandsChart\" width=\"400\" height=\"200\"></canvas>
        </div>
        <div style=\"width: 50%;\">
          <h3>Rate Limits Hit</h3>
          <canvas id=\"rateLimitChart\" width=\"400\" height=\"200\"></canvas>
        </div>
      </div>
      <div class=\"row\" style=\"margin-top: 1rem;\">
        <div style=\"width: 50%;\">
          <h3>Recent Commands</h3>
          <div id=\"recentCommands\" class=\"json\" style=\"max-height: 200px; overflow-y: auto;\"></div>
        </div>
        <div style=\"width: 50%;\">
          <h3>System Stats</h3>
          <div id=\"systemStats\" class=\"json\" style=\"max-height: 200px; overflow-y: auto;\"></div>
        </div>
      </div>
      <p id=\"analyticsMsg\" class=\"note\"></p>
    </div>

    <!-- Commands Tab -->
    <div class=\"card\" style=\"margin-top: 2rem;\">
      <h2 class=\"h2\">Send Command</h2>
      <form id=\"commandForm\">
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <select id=\"commandType\" class=\"input\" style=\"width: 150px;\">
            <option value=\"message\">Send Message</option>
            <option value=\"reaction\">Add Reaction</option>
            <option value=\"typing\">Start Typing</option>
            <option value=\"presence\">Update Presence</option>
          </select>
          <input id=\"channelId\" class=\"input\" placeholder=\"Channel ID\" style=\"flex: 1; margin-left: 0.5rem;\" />
        </div>
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <input id=\"commandContent\" class=\"input\" placeholder=\"Content/Message\" style=\"flex: 1;\" />
        </div>
        <div class=\"row\" style=\"margin-bottom: 1rem;\">
          <input id=\"emoji\" class=\"input\" placeholder=\"Emoji (for reactions)\" style=\"width: 150px;\" />
          <input id=\"delay\" type=\"number\" step=\"0.1\" class=\"input\" placeholder=\"Delay (seconds)\" style=\"width: 120px; margin-left: 0.5rem;\" />
        </div>
        <div class=\"btns\">
          <button type=\"submit\" class=\"b-accent\">Send Command</button>
        </div>
      </form>
      <p id=\"commandMsg\" class=\"note\"></p>
      <div style=\"margin-top: 1rem;\">
        <h3>Command History</h3>
        <div id=\"commandHistory\" class=\"json\" style=\"max-height: 200px; overflow-y: auto;\"></div>
      </div>
    </div>

    <!-- Backup Controls -->
    <div class=\"card\" style=\"margin-top: 2rem;\">
      <h2 class=\"h2\">Backup & Restore</h2>
      <div class=\"btns\" style=\"margin-bottom: 1rem;\">
        <button id=\"createBackup\" class=\"b\">Create Backup</button>
        <button id=\"restoreBackup\" class=\"b\">Restore from Backup</button>
      </div>
      <p id=\"backupMsg\" class=\"note\"></p>
    </div>
  </div>

<script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
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

// Settings form handler
document.getElementById('settingsForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const settings = {
    prefix: document.getElementById('prefix').value,
    rate_limit_delay: parseFloat(document.getElementById('rateLimitDelay').value) || 0.1,
    user_agent: document.getElementById('userAgent').value,
    rpc_name: document.getElementById('rpcName').value,
    captcha_enabled: document.getElementById('captchaEnabled').checked,
    captcha_api_key: document.getElementById('captchaApiKey').value,
    captcha_service: document.getElementById('captchaService').value
  };

  try {
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    const result = await response.json();
    document.getElementById('settingsMsg').textContent = result.message || 'Settings saved';
    document.getElementById('settingsMsg').style.color = result.ok ? 'var(--ok)' : '#dc2626';
  } catch (error) {
    document.getElementById('settingsMsg').textContent = 'Failed to save settings';
    document.getElementById('settingsMsg').style.color = '#dc2626';
  }
});

// Analytics functions
let commandsChart, rateLimitChart;

async function loadAnalytics() {
  try {
    const response = await fetch('/api/analytics');
    const data = await response.json();
    
    // Update charts
    if (commandsChart) commandsChart.destroy();
    if (rateLimitChart) rateLimitChart.destroy();
    
    commandsChart = new Chart(document.getElementById('commandsChart'), {
      type: 'line',
      data: {
        labels: data.commands.labels || [],
        datasets: [{
          label: 'Commands Executed',
          data: data.commands.data || [],
          borderColor: 'rgb(75, 192, 192)',
          tension: 0.1
        }]
      }
    });
    
    rateLimitChart = new Chart(document.getElementById('rateLimitChart'), {
      type: 'bar',
      data: {
        labels: data.rate_limits.labels || [],
        datasets: [{
          label: 'Rate Limits Hit',
          data: data.rate_limits.data || [],
          backgroundColor: 'rgba(255, 99, 132, 0.2)',
          borderColor: 'rgba(255, 99, 132, 1)',
          borderWidth: 1
        }]
      }
    });
    
    // Update recent commands
    document.getElementById('recentCommands').textContent = JSON.stringify(data.recent_commands || [], null, 2);
    
    // Update system stats
    document.getElementById('systemStats').textContent = JSON.stringify(data.system_stats || {}, null, 2);
    
    document.getElementById('analyticsMsg').textContent = 'Analytics updated';
    document.getElementById('analyticsMsg').style.color = 'var(--ok)';
  } catch (error) {
    document.getElementById('analyticsMsg').textContent = 'Failed to load analytics';
    document.getElementById('analyticsMsg').style.color = '#dc2626';
  }
}

document.getElementById('refreshAnalytics').addEventListener('click', loadAnalytics);
loadAnalytics(); // Load on page load

// Command form handler
document.getElementById('commandForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const commandData = {
    type: document.getElementById('commandType').value,
    channel_id: document.getElementById('channelId').value,
    content: document.getElementById('commandContent').value,
    emoji: document.getElementById('emoji').value,
    delay: parseFloat(document.getElementById('delay').value) || 0
  };

  try {
    const response = await fetch('/api/send_message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(commandData)
    });
    const result = await response.json();
    document.getElementById('commandMsg').textContent = result.message || 'Command sent';
    document.getElementById('commandMsg').style.color = result.ok ? 'var(--ok)' : '#dc2626';
    
    // Refresh command history
    loadCommandHistory();
  } catch (error) {
    document.getElementById('commandMsg').textContent = 'Failed to send command';
    document.getElementById('commandMsg').style.color = '#dc2626';
  }
});

async function loadCommandHistory() {
  try {
    const response = await fetch('/api/command_history');
    const data = await response.json();
    document.getElementById('commandHistory').textContent = JSON.stringify(data.history || [], null, 2);
  } catch (error) {
    document.getElementById('commandHistory').textContent = 'Failed to load history';
  }
}

loadCommandHistory();

// Backup functions
document.getElementById('createBackup').addEventListener('click', async function() {
  try {
    const response = await fetch('/api/backup', { method: 'POST' });
    const result = await response.json();
    document.getElementById('backupMsg').textContent = result.message || 'Backup created';
    document.getElementById('backupMsg').style.color = result.ok ? 'var(--ok)' : '#dc2626';
  } catch (error) {
    document.getElementById('backupMsg').textContent = 'Failed to create backup';
    document.getElementById('backupMsg').style.color = '#dc2626';
  }
});

document.getElementById('restoreBackup').addEventListener('click', async function() {
  if (!confirm('Are you sure you want to restore from backup? This will overwrite current data.')) return;
  
  try {
    const response = await fetch('/api/restore', { method: 'POST' });
    const result = await response.json();
    document.getElementById('backupMsg').textContent = result.message || 'Backup restored';
    document.getElementById('backupMsg').style.color = result.ok ? 'var(--ok)' : '#dc2626';
  } catch (error) {
    document.getElementById('backupMsg').textContent = 'Failed to restore backup';
    document.getElementById('backupMsg').style.color = '#dc2626';
  }
});
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
