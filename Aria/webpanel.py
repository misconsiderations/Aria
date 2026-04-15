from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.request
import psutil
import sys
import platform
from typing import Any, Optional

import hashlib
from flask import Flask, jsonify, redirect, send_from_directory, request, session
from werkzeug.serving import make_server
from mongo_store import get_mongo_store

# Master owner Discord ID — always has admin access
_PANEL_MASTER_ID = "299182971213316107"


class WebPanel:
    def __init__(self, api=None, bot=None, host="127.0.0.1", port=8080, instance_id="main", owner_id=None):
        self.api = api
        self.bot = bot
        self.host = host
        self.port = port
        self.instance_id = instance_id
        self.owner_id = owner_id or _PANEL_MASTER_ID
        self._start_time = time.time()
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._last_start_error = ""

        base_dir = os.path.dirname(__file__)
        self._webui_templates = os.path.join(base_dir, "web_ui", "templates")
        self._webui_static = os.path.join(base_dir, "web_ui", "static")
        self._base_dir = base_dir
        self._store = get_mongo_store()

        self.app = Flask(__name__, static_folder=self._webui_static, static_url_path="/static")
        _secret_seed = f"aria-{instance_id}-{self.owner_id}"
        self.app.secret_key = os.getenv("ARIA_WEBPANEL_SECRET", hashlib.sha256(_secret_seed.encode()).hexdigest())

        self._ensure_admin_account()
        self._setup_routes()

    def start(self):
        """Start the web panel server."""
        try:
            self._server = make_server(self.host, self.port, self.app)
            self._thread = threading.Thread(target=self._server.serve_forever)
            self._thread.daemon = True
            self._thread.start()
            return True
        except Exception as e:
            self._last_start_error = str(e)
            self._server = None
            return False

    def stop(self) -> bool:
        """Stop the web panel server if it is currently running."""
        if self._thread is None or not self._thread.is_alive():
            return False
        try:
            if self._server is not None:
                self._server.shutdown()
        except Exception:
            pass
        self._thread.join(timeout=5)
        alive = self._thread.is_alive() if self._thread else False
        self._server = None
        self._thread = None
        return not alive

    def get_last_start_error(self) -> str:
        """Retrieve the last error encountered during start."""
        return self._last_start_error

    # ── Auth helpers ─────────────────────────────────────────────────────────

    def _is_local(self) -> bool:
        """True when request comes from localhost."""
        return request.remote_addr in ("127.0.0.1", "::1", "localhost")

    def _is_admin_session(self) -> bool:
        """True when the logged-in user is the panel admin (master owner)."""
        uid = session.get("user_id", "")
        return bool(uid) and (uid == _PANEL_MASTER_ID or uid == str(self.owner_id))

    def _require_session(self) -> bool:
        """Return True if user is authenticated for this instance."""
        uid  = session.get("user_id", "")
        inst = session.get("instance_id", "")
        if not uid:
            return False
        # Admin can access any instance
        if uid == _PANEL_MASTER_ID or uid == str(self.owner_id):
            return True
        # Regular user must match this instance
        return inst == self.instance_id

    def _require_admin(self) -> bool:
        """Return True only if session belongs to the panel admin."""
        return self._is_admin_session()

    def _verify_auth(self, auth_token: str, remote_addr: str = "127.0.0.1") -> bool:
        """Verify API requests (session or bearer token)."""
        # Session check
        if self._require_session():
            return True
        # Token format: "Bearer <owner_id>_<instance_id>"
        if auth_token.startswith("Bearer "):
            token_parts = auth_token[7:].split("_")
            if len(token_parts) == 2:
                token_owner, token_instance = token_parts
                return token_owner == str(self.owner_id) and token_instance == self.instance_id
        return False

    # ── Dashboard user registry ───────────────────────────────────────────────
    def _dashboard_users_path(self) -> str:
        return os.path.join(self._base_dir, "dashboard_users.json")

    def _load_dashboard_users(self) -> dict:
        stored = self._store.load_document("dashboard_users", None)
        if isinstance(stored, dict):
            return stored
        try:
            with open(self._dashboard_users_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_dashboard_users(self, users: dict) -> None:
        if self._store.save_document("dashboard_users", users):
            return
        with open(self._dashboard_users_path(), "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

    def _record_user_activity(self, user_id: str, action: str, details: str = "", remote_addr: str = "") -> None:
        """Persist a lightweight per-user activity timeline."""
        uid = str(user_id or "").strip()
        act = str(action or "").strip()
        if not uid or not act:
            return
        users = self._load_dashboard_users()
        entry = users.get(uid)
        if not isinstance(entry, dict):
            return

        now = int(time.time())
        entry["last_seen_at"] = now
        if remote_addr:
            entry["last_seen_ip"] = str(remote_addr)

        activity = {
            "ts": now,
            "action": act[:64],
            "details": str(details or "")[:180],
            "ip": str(remote_addr or "")[:64],
        }
        timeline = entry.get("last_actions")
        if not isinstance(timeline, list):
            timeline = []
        timeline.append(activity)
        entry["last_actions"] = timeline[-50:]
        users[uid] = entry
        self._save_dashboard_users(users)

    def _mark_login_success(self, user_id: str, remote_addr: str = "") -> None:
        uid = str(user_id or "").strip()
        if not uid:
            return
        users = self._load_dashboard_users()
        entry = users.get(uid)
        if not isinstance(entry, dict):
            return
        now = int(time.time())
        entry["last_login_at"] = now
        entry["last_seen_at"] = now
        if remote_addr:
            entry["last_login_ip"] = str(remote_addr)
            entry["last_seen_ip"] = str(remote_addr)
        timeline = entry.get("last_actions")
        if not isinstance(timeline, list):
            timeline = []
        timeline.append({"ts": now, "action": "login", "details": "Dashboard sign in", "ip": str(remote_addr or "")[:64]})
        entry["last_actions"] = timeline[-50:]
        users[uid] = entry
        self._save_dashboard_users(users)

    @staticmethod
    def _hash_pw(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def _ensure_admin_account(self) -> None:
        """Create admin account on first run, printing credentials to console."""
        users = self._load_dashboard_users()
        admin_id = str(self.owner_id)
        if admin_id not in users:
            # Generate a random password on first run and print it clearly
            initial_pw = secrets.token_urlsafe(12)
            users[admin_id] = {
                "password_hash": self._hash_pw(initial_pw),
                "instance_id": self.instance_id,
                "username": "admin",
                "role": "admin",
                "created_at": int(time.time()),
            }
            self._save_dashboard_users(users)
            print(f"\n{'='*55}")
            print(f"  Aria WebPanel — Admin Account Created")
            print(f"  User ID  : {admin_id}")
            print(f"  Password : {initial_pw}")
            print(f"  Change it at: /api/dash/change-password")
            print(f"{'='*55}\n")

    # ── Access requests (visitors) ────────────────────────────────────────────
    def _access_requests_path(self) -> str:
        return os.path.join(self._base_dir, "access_requests.json")

    def _load_access_requests(self) -> list:
        stored = self._store.load_document("access_requests", None)
        if isinstance(stored, list):
            return stored
        try:
            with open(self._access_requests_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_access_requests(self, requests_list: list) -> None:
        if self._store.save_document("access_requests", requests_list):
            return
        with open(self._access_requests_path(), "w", encoding="utf-8") as f:
            json.dump(requests_list, f, indent=2)

    # ── Template helpers (reads from Aria/ base dir) ─────────────────────────
    def _read_raw_template(self, name: str) -> str:
        path = os.path.join(self._base_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _render_login(self, title: str, subtitle: str, error: str = "", next_url: str = "/dashboard") -> str:
        html = self._read_raw_template("login_template.html")
        error_block = f'<div class="error">{error}</div>' if error else ""
        replacements = {
            "__TITLE__": title,
            "__SUBTITLE__": subtitle,
            "__ERROR_BLOCK__": error_block,
            "__MODE__": "signin",
            "__USERNAME_FIELD__": "",
            "__BOT_TOKEN_FIELD__": "",
            "__REMEMBER_CHECKED__": "",
            "__SAFE_NEXT__": next_url,
            "__BUTTON_TEXT__": "Sign In",
            "__TOGGLE_PREFIX__": "Read our ",
            "__TOGGLE_LINK__": "/tos",
            "__TOGGLE_TEXT__": "Terms of Service",
        }
        for k, v in replacements.items():
            html = html.replace(k, v)
        return html

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

        user_data = None
        try:
            api = getattr(b, "api", None)
            if api is not None:
                user_data = getattr(api, "user_data", None)
                if not isinstance(user_data, dict):
                    user_data = api.get_user_info(force=False)
        except Exception:
            user_data = None

        user_id = str(getattr(b, "user_id", "") or (user_data or {}).get("id", "") or "")
        username = str(getattr(b, "username", "") or (user_data or {}).get("username", "") or "—")
        avatar_hash = str((user_data or {}).get("avatar") or "").strip()
        avatar_url = ""
        if user_id and avatar_hash:
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
        elif user_id:
            avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"

        available_clients = ["web", "desktop", "mobile", "vr"]
        try:
            from core.client.platform import CLIENT_PROFILES
            available_clients = sorted(list((CLIENT_PROFILES or {}).keys())) or available_clients
        except Exception:
            pass

        uptime_secs = int(time.time() - self._start_time)
        hours, rem = divmod(uptime_secs, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hours}h {mins}m {secs}s"

        return {
            "username": username,
            "user_id": user_id or "—",
            "avatar_url": avatar_url,
            "prefix": getattr(b, "prefix", None) or "$",
            "status": getattr(b, "_current_status", "online"),
            "connected": getattr(b, "connection_active", False),
            "command_count": getattr(b, "command_count", 0),
            "commands_registered": len(getattr(b, "commands", {})),
            "client_type": getattr(b, "_client_type", "mobile"),
            "available_clients": available_clients,
            "ui_version": "v1",
            "uptime": uptime_str,
            "instance_id": self.instance_id,
            "owner_restricted": bool(self.owner_id),
        }

    def _analytics_data(self) -> dict:
        """Read analytics.json if available."""
        try:
            data = self._store.load_document("analytics", None)
            if not isinstance(data, dict):
                path = os.path.join(self._base_dir, "analytics.json")
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
        """Build command history from runtime logs, fallback to history_data.json."""
        log_entries: list[dict[str, Any]] = []
        try:
            log_dir = os.path.join(self._base_dir, "logs")
            from datetime import datetime as _dt

            today = _dt.now().strftime("%Y%m%d")
            log_path = os.path.join(log_dir, f"aria-runtime-{today}.log")
            if not os.path.exists(log_path):
                all_logs = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
                log_path = os.path.join(log_dir, all_logs[0]) if all_logs else ""

            if log_path and os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = [self._strip_ansi(l.rstrip("\n")) for l in f.readlines()[-500:]]
                structured = self._parse_structured_logs(lines)
                for ev in structured.get("events", {}).get("commands", []):
                    log_entries.append(
                        {
                            "command": ev.get("command", ""),
                            "user": ev.get("user", ""),
                            "guild": ev.get("guild", ""),
                            "timestamp": ev.get("time", ""),
                            "duration_ms": ev.get("duration_ms", 0),
                            "status": "success",
                            "source": "runtime_log",
                        }
                    )
        except Exception:
            log_entries = []

        if log_entries:
            return {"entries": log_entries[-50:], "total": len(log_entries)}

        try:
            raw = self._store.load_document("history_data", None)
            if raw is None:
                path = os.path.join(self._base_dir, "history_data.json")
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            if isinstance(raw, list):
                entries = raw[-20:]
                total = len(raw)
            elif isinstance(raw, dict):
                entries = list(raw.values())[-20:]
                total = len(raw)
            else:
                entries = []
                total = 0
            return {"entries": entries, "total": total}
        except Exception:
            return {"entries": [], "total": 0}

    def _boost_data(self) -> dict:
        """Return boost state, preferring live manager data when available."""
        b = self.bot
        bm = getattr(b, "boost_manager", None) if b is not None else None
        if bm is not None:
            try:
                now = time.time()
                last_fetch = float(getattr(bm, "_panel_last_fetch", 0.0) or 0.0)
                if now - last_fetch >= 120:
                    try:
                        bm.fetch_server_boosts()
                    except Exception:
                        pass
                    setattr(bm, "_panel_last_fetch", now)

                detailed = bm.get_detailed_boost_info()
                server_boosts = dict(getattr(bm, "server_boosts", {}) or {})
                vals = [int(v or 0) for v in server_boosts.values()]
                total_boosts = sum(vals)
                boosted_servers = sum(1 for v in vals if v > 0)

                return {
                    "server_boosts": server_boosts,
                    "available_boosts": int(getattr(bm, "available_boosts", 0) or 0),
                    "rotation_servers": list(getattr(bm, "rotation_servers", []) or []),
                    "rotation_hours": int(getattr(bm, "rotation_hours", 24) or 24),
                    "live": {
                        "status": "active" if total_boosts > 0 else "idle",
                        "tracked_servers": len(server_boosts),
                        "boosted_servers": boosted_servers,
                        "total_boosts": total_boosts,
                        "total_slots": int(detailed.get("total_slots", 0) or 0),
                        "slots_available": int(detailed.get("available", 0) or 0),
                        "slots_used": int(detailed.get("used", 0) or 0),
                        "slots_cooldown": int(detailed.get("on_cooldown", 0) or 0),
                        "last_checked": int(time.time()),
                    },
                }
            except Exception:
                pass

        path = os.path.join(self._base_dir, "boost_state.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _commands_data(self) -> dict:
        """Return list of all registered commands from the bot."""
        b = self.bot
        if b is None:
            return {"commands": [], "total": 0}
        cmds = getattr(b, "commands", {}) or {}
        result = []
        for name, cmd in sorted(cmds.items()):
            result.append({
                "name": name,
                "aliases": list(getattr(cmd, "aliases", []) or []),
                "description": str(getattr(cmd, "description", "") or ""),
            })
        return {"commands": result, "total": len(result)}

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Remove ANSI color/control sequences from runtime logs."""
        return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)

    def _parse_structured_logs(self, log_lines: list[str]) -> dict:
        """Build dashboard-friendly structured logs from raw console lines."""
        command_events: list[dict[str, Any]] = []
        sniper_events: list[dict[str, Any]] = []
        gateway_events: list[dict[str, Any]] = []
        error_events: list[dict[str, Any]] = []

        command_re = re.compile(
            r"\[CMD\s*#(?P<num>\d+)\]\s*\[(?P<time>[^\]]+)\]\s*(?P<cmd>[^|]+)\s*\|\s*user=(?P<user>[^|]+)\s*\|\s*guild=(?P<guild>[^|]+)\s*\|\s*(?P<ms>[\d.]+)ms",
            re.IGNORECASE,
        )

        for raw in log_lines:
            line = self._strip_ansi(str(raw or "")).strip()
            if not line:
                continue
            lo = line.lower()

            m = command_re.search(line)
            if m:
                command_events.append(
                    {
                        "number": int(m.group("num")),
                        "time": m.group("time").strip(),
                        "command": m.group("cmd").strip(),
                        "user": m.group("user").strip(),
                        "guild": m.group("guild").strip(),
                        "duration_ms": float(m.group("ms")),
                        "raw": line,
                    }
                )
                continue

            if any(tag in lo for tag in ["[nitro", "[giveaway", "[snipe"]):
                sniper_events.append({"time": "", "type": "sniper", "raw": line})
                continue

            if any(tag in lo for tag in ["[gateway]", "[connected]", "[reconnect]", "session resumed"]):
                gateway_events.append({"time": "", "raw": line})
                continue

            if any(tag in lo for tag in ["[error", "exception", "traceback", "failed"]):
                error_events.append({"time": "", "raw": line})

        bot_d = self._bot_data()
        connected_user = {
            "username": bot_d.get("username", "—"),
            "user_id": bot_d.get("user_id", "—"),
            "connected": bool(bot_d.get("connected", False)),
        }

        command_total = int(bot_d.get("command_count", 0) or 0)
        if not command_total:
            command_total = len(command_events)

        return {
            "summary": {
                "connected_user": connected_user,
                "command_total": command_total,
                "command_events": len(command_events),
                "sniper_events": len(sniper_events),
                "gateway_events": len(gateway_events),
                "error_events": len(error_events),
            },
            "events": {
                "commands": command_events[-50:],
                "snipers": sniper_events[-50:],
                "gateway": gateway_events[-50:],
                "errors": error_events[-50:],
            },
        }

    def _config_data(self) -> dict:
        """Return live bot config values."""
        b = self.bot
        if b is None:
            return {}
        return {
            "prefix": getattr(b, "prefix", "$"),
            "status": getattr(b, "_current_status", "online"),
            "auto_delete_enabled": getattr(b, "_auto_delete_enabled", True),
            "auto_delete_delay": getattr(b, "_auto_delete_delay", 3.0),
            "username": getattr(b, "username", "") or "",
            "user_id": getattr(b, "user_id", "") or "",
            "connected": getattr(b, "connection_active", False),
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        @self.app.get("/")
        def index() -> Any:
            try:
                return self._read_raw_template("home_template.html"), 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception:
                return redirect("/dashboard")

        @self.app.get("/__shutdown__")
        def _shutdown_server() -> Any:
            if not self._is_local():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            if self._server is None:
                return jsonify({"ok": False, "error": "Server not started via make_server"}), 500
            threading.Thread(target=self._server.shutdown, daemon=True).start()
            return jsonify({"ok": True, "message": "Shutting down"}), 200

        # ── Maximalist Dashboard API Endpoints ─────────────────────────────

        @self.app.get("/api/max/system-stats")
        def api_max_system_stats():
            """Return live system resource stats (CPU, RAM, Disk, Network)."""
            import psutil
            try:
                cpu = psutil.cpu_percent(interval=0.2)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage("/").percent
                net = psutil.net_io_counters()
                net_usage = {'sent': net.bytes_sent, 'recv': net.bytes_recv}
                return jsonify({"ok": True, "cpu": cpu, "ram": ram, "disk": disk, "net": net_usage})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.get("/api/max/command-breakdown")
        def api_max_command_breakdown():
            """Return command usage breakdown for pie/bar charts."""
            analytics = self._analytics_data()
            patterns = analytics.get("top_commands", [])
            # Simulate categories for bar chart
            categories = {}
            for cmd in patterns:
                cat = cmd["name"].split("_")[0] if "_" in cmd["name"] else "misc"
                categories[cat] = categories.get(cat, 0) + cmd["count"]
            return jsonify({"ok": True, "pie": patterns, "bar": categories})

        @self.app.get("/api/max/errors")
        def api_max_errors():
            """Return recent error and warning log entries."""
            logs = self._parse_structured_logs([])
            try:
                # Try to get errors from logs
                log_dir = os.path.join(self._base_dir, "logs")
                from datetime import datetime as _dt
                today = _dt.now().strftime("%Y%m%d")
                log_path = os.path.join(log_dir, f"aria-runtime-{today}.log")
                if not os.path.exists(log_path):
                    all_logs = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
                    log_path = os.path.join(log_dir, all_logs[0]) if all_logs else None
                lines = []
                if log_path and os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        all_lines = f.readlines()
                    lines = [self._strip_ansi(l.rstrip("\n")) for l in all_lines[-500:]]
                errors = [l for l in lines if any(tag in l.lower() for tag in ["error", "exception", "traceback", "failed", "warn"])]
                return jsonify({"ok": True, "errors": errors[-30:]})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.get("/api/max/leaderboard")
        def api_max_leaderboard():
            """Return user leaderboard by commands run."""
            users = self._load_dashboard_users()
            leaderboard = []
            for uid, entry in users.items():
                count = 0
                actions = entry.get("last_actions", [])
                for act in actions:
                    if act.get("action", "") == "command":
                        count += 1
                leaderboard.append({
                    "user_id": uid,
                    "username": entry.get("username", uid),
                    "count": count,
                    "last_seen_at": entry.get("last_seen_at", 0)
                })
            leaderboard.sort(key=lambda x: x["count"], reverse=True)
            return jsonify({"ok": True, "leaderboard": leaderboard[:20]})

        @self.app.get("/api/max/server-info")
        def api_max_server_info():
            """Return current guild/server info."""
            b = self.bot
            try:
                guild = getattr(b, "guild", None)
                if not guild:
                    return jsonify({"ok": True, "guild": {}})
                info = {
                    "name": getattr(guild, "name", "—"),
                    "id": getattr(guild, "id", "—"),
                    "members": getattr(guild, "member_count", "—"),
                    "region": getattr(guild, "region", "—"),
                }
                return jsonify({"ok": True, "guild": info})
            except Exception:
                return jsonify({"ok": True, "guild": {}})

        @self.app.get("/api/max/activity-map")
        def api_max_activity_map():
            """Return timeline and heatmap data for activity."""
            hist = self._history_data().get("entries", [])
            timeline = [0]*24
            heatmap = [[0]*7 for _ in range(24)]
            import datetime
            for entry in hist:
                ts = int(entry.get("timestamp", 0) or 0)
                if ts > 1e12:
                    ts = ts//1000
                dt = datetime.datetime.utcfromtimestamp(ts)
                hour = dt.hour
                dow = dt.weekday()
                timeline[hour] += 1
                heatmap[hour][dow] += 1
            return jsonify({"ok": True, "timeline": timeline, "heatmap": heatmap})

        @self.app.get("/api/max/notifications")
        def api_max_notifications():
            """Return recent dashboard activity events (logins, RPC, status, errors, etc)."""
            users = self._load_dashboard_users()
            events = []
            for uid, entry in users.items():
                acts = entry.get("last_actions", [])
                for act in acts[-10:]:
                    events.append({"user": entry.get("username", uid), **act})
            events.sort(key=lambda x: x.get("ts", 0), reverse=True)
            return jsonify({"ok": True, "events": events[:30]})

        @self.app.get("/api/max/advanced-analytics")
        def api_max_advanced_analytics():
            """Return advanced analytics: success/failure rates, latency, etc."""
            analytics = self._analytics_data()
            hist = self._history_data().get("entries", [])
            failures = [h for h in hist if h.get("status", "success") != "success"]
            latencies = [h.get("duration_ms", 0) for h in hist if h.get("duration_ms")]
            longest = max(latencies) if latencies else 0
            return jsonify({
                "ok": True,
                "success_rate": analytics.get("success_rate", 100.0),
                "avg_latency": analytics.get("avg_response_ms", 0),
                "failures": len(failures),
                "longest_cmd": longest
            })

        @self.app.get("/api/max/widgets")
        def api_max_widgets():
            """Return available widgets (placeholder)."""
            return jsonify({"ok": True, "widgets": [
                {"name": "System Stats", "id": "system"},
                {"name": "Command Breakdown", "id": "cmdbreakdown"},
                {"name": "Errors", "id": "errors"},
                {"name": "Leaderboard", "id": "leaderboard"},
                {"name": "Server Info", "id": "serverinfo"},
                {"name": "Activity Map", "id": "activitymap"},
                {"name": "Notifications", "id": "notifications"},
                {"name": "Advanced Analytics", "id": "advanced-analytics"},
            ]})

        @self.app.get("/home")
        def home() -> Any:
            try:
                return self._read_raw_template("home_template.html"), 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception:
                return redirect("/dashboard")

        @self.app.get("/tos")
        @self.app.get("/terms")
        def tos() -> Any:
            try:
                return self._read_raw_template("tos_template.html"), 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception:
                return "Terms of Service not found.", 404

        @self.app.get("/privacy")
        def privacy() -> Any:
            try:
                return self._read_raw_template("privacy_template.html"), 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception:
                return "Privacy Policy not found.", 404

        @self.app.get("/login")
        def login_get() -> Any:
            if self._require_session():
                return redirect(request.args.get("next") or "/dashboard")
            next_url = request.args.get("next", "/dashboard")
            error = request.args.get("error", "")
            try:
                html = self._render_login("Sign In", "Access your Aria dashboard", error, next_url)
                return html, 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception as e:
                return f"<h1>Login</h1><p>Template unavailable: {e}</p>"

        @self.app.post("/login")
        def login_post() -> Any:
            form = request.form
            user_id = str(form.get("user_id", "")).strip()
            password = str(form.get("password", "")).strip()
            remember = bool(form.get("remember_me"))
            next_url = str(form.get("next") or "/dashboard")
            # Basic safety: only allow relative paths
            if not next_url.startswith("/"):
                next_url = "/dashboard"
            if not user_id or not password:
                return redirect(f"/login?error=User+ID+and+password+required&next={next_url}")
            # Always require real credentials — no localhost bypass
            users = self._load_dashboard_users()
            entry = users.get(user_id)
            if not entry or entry.get("password_hash") != self._hash_pw(password):
                return redirect(f"/login?error=Invalid+user+ID+or+password&next={next_url}")
            # Admin can log in from any instance; regular users must match this instance
            role = entry.get("role", "user")
            inst = entry.get("instance_id", "")
            if role != "admin" and inst != self.instance_id:
                return redirect(f"/login?error=Account+not+registered+on+this+instance&next={next_url}")
            session.permanent = remember
            session["user_id"] = user_id
            session["instance_id"] = self.instance_id
            session["role"] = role
            self._mark_login_success(user_id, request.remote_addr or "")
            return redirect(next_url)

        @self.app.get("/request-access")
        @self.app.get("/access-pending")
        def request_access_get() -> Any:
            """Visitor access request form."""
            try:
                html = self._read_raw_template("access_pending_template.html")
                html = html.replace("__MODE__", "request")
                error = str(request.args.get("error", "")).strip()
                success = str(request.args.get("success", "")).strip()
                error_block = f'<div class="alert alert-error">{error}</div>' if error else ""
                success_block = f'<div class="alert alert-success">{success}</div>' if success else ""
                html = html.replace("__ERROR_BLOCK__", error_block)
                html = html.replace("__SUCCESS_BLOCK__", success_block)
                return html, 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception:
                # Inline fallback form
                return """<!DOCTYPE html><html><head><title>Request Access</title></head>
<body style="background:#030712;color:#f1f5f9;font-family:sans-serif;display:grid;place-items:center;min-height:100vh">
<form method="post" style="background:#0f172a;border-radius:12px;padding:32px;max-width:400px;width:100%">
  <h2 style="margin-bottom:16px">Request Access</h2>
  <label>Name<br/><input name="username" required style="width:100%;margin:4px 0 12px;padding:8px;background:#1e293b;border:1px solid #334155;border-radius:6px;color:#f1f5f9"/></label>
  <label>Reason<br/><textarea name="reason" required rows="3" style="width:100%;margin:4px 0 12px;padding:8px;background:#1e293b;border:1px solid #334155;border-radius:6px;color:#f1f5f9"></textarea></label>
  <button type="submit" style="width:100%;padding:10px;background:linear-gradient(135deg,#ec4899,#8b5cf6);border:none;border-radius:8px;color:#fff;font-weight:700;cursor:pointer">Request Access</button>
</form></body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}

        @self.app.post("/request-access")
        def request_access_post() -> Any:
            """Submit visitor access request."""
            form = request.form
            username = str(form.get("username", "")).strip()[:64]
            reason   = str(form.get("reason", "")).strip()[:512]
            if not username:
                return redirect("/request-access?error=Name+is+required")
            if not reason:
                return redirect("/request-access?error=Reason+is+required")
            reqs = self._load_access_requests()
            req_id = secrets.token_hex(8)
            reqs.append({
                "id": req_id,
                "username": username,
                "reason": reason,
                "remote_addr": request.remote_addr,
                "timestamp": int(time.time()),
                "status": "pending",
            })
            self._save_access_requests(reqs)
            return redirect("/request-access?success=Request+sent+to+admin")

        @self.app.get("/logout")
        def logout() -> Any:
            session.clear()
            return redirect("/login")

        @self.app.get("/dashboard")
        def dashboard() -> Any:
            if not self._require_session():
                return redirect("/login?next=/dashboard")
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
            if not self._require_session():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._bot_data()})

        @self.app.get("/api/analytics")
        def api_analytics() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._analytics_data()})

        @self.app.get("/api/history")
        def api_history() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._history_data()})

        @self.app.get("/api/boost")
        def api_boost() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            return jsonify({"ok": True, "data": self._boost_data()})

        @self.app.get("/api/commands")
        def api_commands() -> Any:
            return jsonify({"ok": True, "data": self._commands_data()})

        @self.app.get("/api/config")
        def api_config_get() -> Any:
            return jsonify({"ok": True, "data": self._config_data()})

        @self.app.post("/api/config")
        def api_config_set() -> Any:
            data = request.get_json(force=True) or {}
            b = self.bot
            if b is None:
                return jsonify({"ok": False, "error": "No bot instance"}), 400
            changed = []
            if "prefix" in data:
                new_prefix = str(data["prefix"])[:5].strip()
                if new_prefix:
                    b.prefix = new_prefix
                    if hasattr(b, "globalPrefix"):
                        b.globalPrefix = new_prefix
                    if isinstance(getattr(b, "config", None), dict):
                        b.config["prefix"] = new_prefix
                    changed.append("prefix")
            if "auto_delete_delay" in data:
                try:
                    delay = int(data["auto_delete_delay"])
                    if 1 <= delay <= 600:
                        b._auto_delete_delay = delay
                        changed.append("auto_delete_delay")
                except (ValueError, TypeError):
                    pass
            if "auto_delete_enabled" in data:
                b._auto_delete_enabled = bool(data["auto_delete_enabled"])
                changed.append("auto_delete_enabled")
            return jsonify({"ok": True, "changed": changed, "data": self._config_data()})

        # ── RPC ───────────────────────────────────────────────────────────
        @self.app.get("/api/rpc")
        def api_rpc_get() -> Any:
            b = self.bot
            activity = getattr(b, "activity", None) if b else None
            runtime_rpc: dict = {}
            try:
                rp = os.path.join(self._base_dir, "runtime_state.json")
                with open(rp, "r", encoding="utf-8") as f:
                    runtime_rpc = json.load(f).get("rpc", {})
            except Exception:
                pass
            runtime_activity = runtime_rpc.get("activity") if isinstance(runtime_rpc, dict) else None
            final_activity = activity if isinstance(activity, dict) else runtime_activity if isinstance(runtime_activity, dict) else None
            return jsonify({
                "ok": True,
                "active": bool(final_activity),
                "activity": final_activity,
                "mode": runtime_rpc.get("mode", "none"),
                "saved_at": runtime_rpc.get("saved_at"),
                "version": "v2",
                "available_types": [0, 1, 2, 3, 5],
            })

        @self.app.post("/api/rpc")
        def api_rpc_set() -> Any:
            data = request.get_json(force=True) or {}
            b = self.bot
            if b is None:
                return jsonify({"ok": False, "error": "No bot instance"}), 400
            action = data.get("action", "set")
            if action == "stop":
                try:
                    b.set_activity(None)
                except Exception as e:
                    return jsonify({"ok": False, "error": str(e)}), 500
                return jsonify({"ok": True, "action": "stopped"})
            # action == "set"
            activity = data.get("activity")
            if not isinstance(activity, dict):
                return jsonify({"ok": False, "error": "activity must be a dict"}), 400
            try:
                b.set_activity(activity)
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            return jsonify({"ok": True, "action": "set", "activity": activity})

        # ── Presence Status ───────────────────────────────────────────────
        @self.app.get("/api/presence")
        def api_presence_get() -> Any:
            b = self.bot
            return jsonify({
                "ok": True,
                "status": getattr(b, "_current_status", "online") if b else "unknown",
            })

        @self.app.get("/api/client")
        def api_client_get() -> Any:
            b = self.bot
            if b is None:
                return jsonify({"ok": False, "error": "No bot instance"}), 400
            available_clients = ["web", "desktop", "mobile", "vr"]
            try:
                from core.client.platform import CLIENT_PROFILES
                if isinstance(CLIENT_PROFILES, dict) and CLIENT_PROFILES:
                    available_clients = sorted(CLIENT_PROFILES.keys())
            except Exception:
                pass
            return jsonify({
                "ok": True,
                "client_type": getattr(b, "_client_type", "mobile"),
                "available_clients": available_clients,
            })

        @self.app.post("/api/client")
        def api_client_set() -> Any:
            b = self.bot
            if b is None:
                return jsonify({"ok": False, "error": "No bot instance"}), 400
            data = request.get_json(force=True) or {}
            client_type = str(data.get("client_type", "")).strip().lower()
            if not client_type:
                return jsonify({"ok": False, "error": "client_type required"}), 400
            try:
                ok = bool(b.set_client_type(client_type))
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            if not ok:
                return jsonify({"ok": False, "error": "Invalid client type"}), 400
            return jsonify({"ok": True, "client_type": getattr(b, "_client_type", client_type)})

        @self.app.post("/api/presence")
        def api_presence_set() -> Any:
            data = request.get_json(force=True) or {}
            b = self.bot
            if b is None:
                return jsonify({"ok": False, "error": "No bot instance"}), 400
            new_status = str(data.get("status", "")).lower()
            valid = {"online", "idle", "dnd", "invisible"}
            if new_status not in valid:
                return jsonify({"ok": False, "error": f"status must be one of {sorted(valid)}"}), 400
            try:
                ok = b.set_status(new_status)
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            return jsonify({"ok": bool(ok), "status": new_status})

        # ── Hosted users ──────────────────────────────────────────────────
        @self.app.get("/api/hosted")
        def api_hosted() -> Any:
            try:
                from host import host_manager as hm
                active = {}
                saved = {}
                try:
                    active = dict(getattr(hm, "active_tokens", {}) or {})
                except Exception:
                    pass
                try:
                    saved = dict(getattr(hm, "saved_users", {}) or {})
                except Exception:
                    pass
                result = []
                for tid, info in saved.items():
                    is_active = tid in active
                    active_info = active.get(tid, {}) if isinstance(active.get(tid, {}), dict) else {}
                    result.append({
                        "token_id": tid[:8] + "...",  # truncate for safety
                        "owner": str(info.get("owner", "—")),
                        "prefix": str(info.get("prefix", "$")),
                        "username": str(info.get("username", "—")),
                        "client_type": str(active_info.get("client_type") or info.get("client_type") or "unknown"),
                        "active": is_active,
                    })
                return jsonify({"ok": True, "hosted": result, "total": len(result), "active_count": len(active)})
            except Exception as e:
                return jsonify({"ok": True, "hosted": [], "total": 0, "active_count": 0, "note": str(e)})

        @self.app.post("/api/hosted/disconnect")
        def api_hosted_disconnect():
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            data = request.get_json(force=True) or {}
            token_id = str(data.get("token_id", "")).replace("...", "")
            if not token_id:
                return jsonify({"ok": False, "error": "token_id required"}), 400
            try:
                from host import host_manager as hm
                # Use remove_hosts to disconnect hosted user by token_id
                removed = 0
                if hasattr(hm, "remove_hosts"):
                    removed = hm.remove_hosts(selectors=[token_id])
                if removed:
                    return jsonify({"ok": True})
                else:
                    return jsonify({"ok": False, "error": "Could not disconnect hosted user"}), 400
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        # ── Logs ──────────────────────────────────────────────────────────
        @self.app.get("/api/logs")
        def api_logs() -> Any:
            lines_param = request.args.get("lines", "100")
            try:
                n = max(10, min(500, int(lines_param)))
            except (ValueError, TypeError):
                n = 100
            log_dir = os.path.join(self._base_dir, "logs")
            lines: list = []
            try:
                from datetime import datetime as _dt
                today = _dt.now().strftime("%Y%m%d")
                log_path = os.path.join(log_dir, f"aria-runtime-{today}.log")
                if not os.path.exists(log_path):
                    # Fall back to most recent log file
                    all_logs = sorted(
                        [f for f in os.listdir(log_dir) if f.endswith(".log")],
                        reverse=True,
                    )
                    log_path = os.path.join(log_dir, all_logs[0]) if all_logs else None
                if log_path and os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        all_lines = f.readlines()
                    lines = [self._strip_ansi(l.rstrip("\n")) for l in all_lines[-n:]]
            except Exception as e:
                lines = [f"[log read error] {e}"]
            structured = self._parse_structured_logs(lines)
            return jsonify({"ok": True, "lines": lines, "count": len(lines), **structured})

        # ── AFK ───────────────────────────────────────────────────────────
        @self.app.get("/api/afk")
        def api_afk_get() -> Any:
            b = self.bot
            try:
                afk_ref = getattr(b, "_afk_system_ref", None) if b else None
                uid = str(getattr(b, "user_id", "") or "")
                if afk_ref and uid:
                    active = bool(afk_ref.is_afk(uid))
                    message = afk_ref.get_afk_message(uid) if hasattr(afk_ref, "get_afk_message") else ""
                    return jsonify({"ok": True, "active": active, "message": message or ""})
            except Exception:
                pass
            return jsonify({"ok": True, "active": False, "message": ""})

        @self.app.post("/api/afk")
        def api_afk_set() -> Any:
            data = request.get_json(force=True) or {}
            b = self.bot
            if b is None:
                return jsonify({"ok": False, "error": "No bot instance"}), 400
            try:
                afk_ref = getattr(b, "_afk_system_ref", None)
                uid = str(getattr(b, "user_id", "") or "")
                if not afk_ref or not uid:
                    return jsonify({"ok": False, "error": "AFK system unavailable"}), 400
                action = data.get("action", "toggle")
                if action == "enable" or (action == "toggle" and not afk_ref.is_afk(uid)):
                    msg = str(data.get("message", "AFK")).strip() or "AFK"
                    afk_ref.set_afk(uid, msg)
                    afk_ref.save_state()
                    return jsonify({"ok": True, "active": True, "message": msg})
                else:
                    afk_ref.remove_afk(uid)
                    afk_ref.save_state()
                    return jsonify({"ok": True, "active": False})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        # ── Public stats ──────────────────────────────────────────────────
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

        # ── Dashboard user management (admin-only) ────────────────────────
        @self.app.post("/api/dash/register")
        def api_dash_register() -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            data = request.get_json(force=True) or {}
            uid = str(data.get("user_id", "")).strip()
            pw = str(data.get("password", "")).strip()
            if not uid or not pw:
                return jsonify({"ok": False, "error": "user_id and password required"}), 400
            users = self._load_dashboard_users()
            users[uid] = {
                "password_hash": self._hash_pw(pw),
                "instance_id": self.instance_id,
                "username": str(data.get("username", uid)),
                "role": "user",
                "created_at": int(time.time()),
                "last_login_at": 0,
                "last_seen_at": 0,
                "last_actions": [],
            }
            self._save_dashboard_users(users)
            self._record_user_activity(session.get("user_id", ""), "account_create", f"Created user {uid}", request.remote_addr or "")
            return jsonify({"ok": True, "user_id": uid, "instance_id": self.instance_id})

        @self.app.delete("/api/dash/register/<user_id>")
        def api_dash_unregister(user_id: str) -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            users = self._load_dashboard_users()
            if user_id in users:
                del users[user_id]
                self._save_dashboard_users(users)
                self._record_user_activity(session.get("user_id", ""), "account_remove", f"Removed user {user_id}", request.remote_addr or "")
                return jsonify({"ok": True, "removed": user_id})
            return jsonify({"ok": False, "error": "User not found"}), 404

        @self.app.get("/api/dash/users")
        def api_dash_users() -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            users = self._load_dashboard_users()
            safe = [
                {"user_id": uid, "username": v.get("username", uid), "instance_id": v.get("instance_id", ""), "role": v.get("role", "user"), "created_at": v.get("created_at", 0)}
                for uid, v in users.items()
            ]
            return jsonify({"ok": True, "users": safe, "total": len(safe)})

        @self.app.post("/api/dash/change-password")
        def api_dash_change_password() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Not logged in"}), 403
            data = request.get_json(force=True) or {}
            uid = session.get("user_id", "")
            old_pw = str(data.get("old_password", "")).strip()
            new_pw = str(data.get("new_password", "")).strip()
            if not old_pw or not new_pw or len(new_pw) < 8:
                return jsonify({"ok": False, "error": "old_password and new_password (min 8 chars) required"}), 400
            users = self._load_dashboard_users()
            entry = users.get(uid)
            if not entry or entry.get("password_hash") != self._hash_pw(old_pw):
                return jsonify({"ok": False, "error": "Current password incorrect"}), 403
            entry["password_hash"] = self._hash_pw(new_pw)
            self._save_dashboard_users(users)
            self._record_user_activity(uid, "password_change", "Changed dashboard password", request.remote_addr or "")
            return jsonify({"ok": True})

        @self.app.get("/api/dash/me")
        def api_dash_me() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Not logged in"}), 403

            uid = str(session.get("user_id", "") or "")
            users = self._load_dashboard_users()
            entry = users.get(uid, {}) if isinstance(users, dict) else {}
            role = str(session.get("role") or entry.get("role") or "user")
            profile = {
                "user_id": uid,
                "username": str(entry.get("username", uid) or uid),
                "role": role,
                "instance_id": str(entry.get("instance_id", self.instance_id) or self.instance_id),
                "created_at": int(entry.get("created_at", 0) or 0),
                "last_login_at": int(entry.get("last_login_at", 0) or 0),
                "last_seen_at": int(entry.get("last_seen_at", 0) or 0),
                "is_admin": bool(self._require_admin()),
            }

            summary = {
                "total_users": len(users) if isinstance(users, dict) else 0,
                "pending_requests": 0,
                "total_requests": 0,
            }
            if profile["is_admin"]:
                reqs = self._load_access_requests()
                if isinstance(reqs, list):
                    summary["total_requests"] = len(reqs)
                    summary["pending_requests"] = sum(1 for r in reqs if str((r or {}).get("status", "pending")).lower() == "pending")

            return jsonify({"ok": True, "profile": profile, "summary": summary})

        @self.app.get("/api/dash/activity")
        def api_dash_activity() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Not logged in"}), 403
            uid = str(session.get("user_id", "") or "")
            users = self._load_dashboard_users()
            entry = users.get(uid, {}) if isinstance(users, dict) else {}
            actions = entry.get("last_actions") if isinstance(entry, dict) else []
            if not isinstance(actions, list):
                actions = []
            actions = actions[-30:]
            return jsonify({
                "ok": True,
                "timeline": actions,
                "last_login_at": int((entry or {}).get("last_login_at", 0) or 0),
                "last_seen_at": int((entry or {}).get("last_seen_at", 0) or 0),
            })

        @self.app.post("/api/dash/activity")
        def api_dash_activity_record() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Not logged in"}), 403
            data = request.get_json(force=True) or {}
            action = str(data.get("action", "")).strip()
            details = str(data.get("details", "")).strip()
            if not action:
                return jsonify({"ok": False, "error": "action required"}), 400
            uid = str(session.get("user_id", "") or "")
            self._record_user_activity(uid, action, details, request.remote_addr or "")
            return jsonify({"ok": True})

        # ── Visitor access requests (admin-only management) ───────────────
        @self.app.get("/api/dash/requests")
        def api_dash_requests_list() -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            reqs = self._load_access_requests()
            return jsonify({"ok": True, "requests": reqs, "total": len(reqs)})

        @self.app.post("/api/dash/requests/<req_id>/approve")
        def api_dash_request_approve(req_id: str) -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            reqs = self._load_access_requests()
            req = next((r for r in reqs if r["id"] == req_id), None)
            if not req:
                return jsonify({"ok": False, "error": "Request not found"}), 404
            data = request.get_json(force=True) or {}
            # Generate a random user_id and password for the new visitor account
            new_uid = data.get("user_id") or f"visitor_{secrets.token_hex(4)}"
            new_pw  = data.get("password") or secrets.token_urlsafe(10)
            users = self._load_dashboard_users()
            users[str(new_uid)] = {
                "password_hash": self._hash_pw(new_pw),
                "instance_id": self.instance_id,
                "username": req.get("username", str(new_uid)),
                "role": "visitor",
                "created_at": int(time.time()),
                "approved_from_request": req_id,
                "last_login_at": 0,
                "last_seen_at": 0,
                "last_actions": [{"ts": int(time.time()), "action": "approved", "details": f"Approved from request {req_id}", "ip": str(request.remote_addr or "")[:64]}],
            }
            self._save_dashboard_users(users)
            req["status"] = "approved"
            req["approved_uid"] = str(new_uid)
            self._save_access_requests(reqs)
            self._record_user_activity(session.get("user_id", ""), "request_approve", f"Approved {req_id} as {new_uid}", request.remote_addr or "")
            return jsonify({"ok": True, "user_id": str(new_uid), "password": new_pw})

        @self.app.post("/api/dash/requests/<req_id>/deny")
        def api_dash_request_deny(req_id: str) -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            reqs = self._load_access_requests()
            req = next((r for r in reqs if r["id"] == req_id), None)
            if not req:
                return jsonify({"ok": False, "error": "Request not found"}), 404
            req["status"] = "denied"
            self._save_access_requests(reqs)
            self._record_user_activity(session.get("user_id", ""), "request_deny", f"Denied request {req_id}", request.remote_addr or "")
            return jsonify({"ok": True})

        @self.app.post("/api/dash/requests/approve-all-pending")
        def api_dash_requests_approve_all_pending() -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            reqs = self._load_access_requests()
            users = self._load_dashboard_users()
            approved = []
            now = int(time.time())
            for req in reqs:
                if str((req or {}).get("status", "pending")).lower() != "pending":
                    continue
                req_id = str(req.get("id", "") or "")
                new_uid = f"visitor_{secrets.token_hex(4)}"
                while str(new_uid) in users:
                    new_uid = f"visitor_{secrets.token_hex(4)}"
                new_pw = secrets.token_urlsafe(10)
                users[str(new_uid)] = {
                    "password_hash": self._hash_pw(new_pw),
                    "instance_id": self.instance_id,
                    "username": req.get("username", str(new_uid)),
                    "role": "visitor",
                    "created_at": now,
                    "approved_from_request": req_id,
                    "last_login_at": 0,
                    "last_seen_at": 0,
                    "last_actions": [{"ts": now, "action": "approved", "details": f"Approved from request {req_id}", "ip": str(request.remote_addr or "")[:64]}],
                }
                req["status"] = "approved"
                req["approved_uid"] = str(new_uid)
                approved.append({"request_id": req_id, "user_id": str(new_uid), "password": new_pw})

            self._save_dashboard_users(users)
            self._save_access_requests(reqs)
            self._record_user_activity(session.get("user_id", ""), "request_bulk_approve", f"Bulk approved {len(approved)} requests", request.remote_addr or "")
            return jsonify({"ok": True, "approved": approved, "approved_count": len(approved)})

        @self.app.post("/api/dash/requests/deny-all-pending")
        def api_dash_requests_deny_all_pending() -> Any:
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            reqs = self._load_access_requests()
            denied_count = 0
            for req in reqs:
                if str((req or {}).get("status", "pending")).lower() == "pending":
                    req["status"] = "denied"
                    denied_count += 1
            self._save_access_requests(reqs)
            self._record_user_activity(session.get("user_id", ""), "request_bulk_deny", f"Bulk denied {denied_count} requests", request.remote_addr or "")
            return jsonify({"ok": True, "denied_count": denied_count})

        # ── RPC control (POST /rpc) ────────────────────────────────────────
        @self.app.post("/rpc")
        def rpc_control_route() -> Any:
            return self.rpc_control()

        @self.app.get("/favicon.ico")
        def favicon() -> Any:
            local_fallback = "/static/images/aria-favicon.svg"
            cfg = getattr(self.bot, "config", {}) if self.bot is not None else {}
            favicon_url = ""
            if isinstance(cfg, dict):
                favicon_url = str(cfg.get("favicon_url") or cfg.get("brand_image_url") or "").strip()
            return redirect(favicon_url or local_fallback, code=302)

        @self.app.get("/brand-image")
        def brand_image() -> Any:
            """Stable image endpoint used by dashboard image elements."""
            cfg = getattr(self.bot, "config", {}) if self.bot is not None else {}
            brand_url = ""
            if isinstance(cfg, dict):
                brand_url = str(cfg.get("brand_image_url") or cfg.get("favicon_url") or "").strip()
            return redirect(brand_url or "/static/images/aria-favicon.svg", code=302)

        @self.app.get("/static/<path:asset_path>")
        def static_assets(asset_path: str) -> Any:
            return send_from_directory(self._webui_static, asset_path)

    def run(self) -> None:
        try:
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            self._last_start_error = str(e)

    def rpc_control(self):
        """Handle RPC updates via POST requests."""
        try:
            data = request.json
            action = data.get("action")
            details = data.get("details", "")
            state = data.get("state", "")
            large_image = data.get("large_image", "")
            small_image = data.get("small_image", "")

            # Example: Update RPC state (requires bot integration)
            if self.bot and hasattr(self.bot, "update_rpc"):
                self.bot.update_rpc(
                    action=action,
                    details=details,
                    state=state,
                    large_image=large_image,
                    small_image=small_image,
                )

            return jsonify({"status": "success", "message": "RPC updated successfully."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
