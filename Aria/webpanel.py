from __future__ import annotations

import collections
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
from werkzeug.serving import make_server, WSGIRequestHandler
from mongo_store import get_mongo_store

# Master owner Discord ID — always has admin access
_PANEL_MASTER_ID = "299182971213316107"
_DEFAULT_RPC_APPLICATION_ID = "1494507808329171096"


class _QuietWSGIRequestHandler(WSGIRequestHandler):
    """Reduce noisy localhost polling logs while keeping useful errors visible."""

    def log_request(self, code='-', size='-'):
        path = (self.path or "").split("?", 1)[0]
        try:
            status = int(code)
        except Exception:
            status = 0

        is_local = bool(self.client_address and self.client_address[0] in ("127.0.0.1", "::1"))

        # Suppress routine successful local dashboard poll traffic.
        if status and status < 400 and is_local:
            return

        # Suppress expected unauthorized/forbidden noise while the dashboard is not logged in.
        noisy_auth_paths = {
            "/api/discord/notifications",
            "/api/discord/notifications/mark_read",
            "/api/max/notifications",
            "/api/bot",
            "/api/history",
            "/api/dash/activity",
            "/api/afk",
            "/api/presence",
            "/api/public/stats",
            "/api/max/system-summary",
            "/api/max/system-stats",
            "/api/hosted",
            "/api/analytics",
            "/api/config",
            "/api/dash/me",
            "/api/dash/users",
            "/api/dash/requests",
            "/api/logs",
            "/api/rpc",
            "/api/boost",
        }
        if is_local and status in (401, 403) and (path in noisy_auth_paths or path.startswith("/api/logs")):
            return

        # Suppress known noisy notification probe 404s if old frontend code is still polling.
        if is_local and status == 404 and path in {
            "/api/discord/notifications",
            "/api/discord/notifications/mark_read",
        }:
            return

        super().log_request(code, size)


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

        # Discord notification queue — populated by push_discord_notification()
        # Holds up to 200 events; thread-safe via _notif_lock
        self._discord_notif_queue: collections.deque = collections.deque(maxlen=200)
        self._notif_lock = threading.Lock()
        self._notif_seen_ids: set = set()  # deduplicate by message/event ID

    def start(self):
        """Start the web panel server."""
        try:
            self._server = make_server(self.host, self.port, self.app, request_handler=_QuietWSGIRequestHandler)
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

    # ── Discord notification queue ─────────────────────────────────────────────

    def push_discord_notification(
        self,
        kind: str,
        title: str,
        body: str = "",
        author: str = "",
        author_id: str = "",
        channel_id: str = "",
        guild_id: str = "",
        icon: str = "",
        event_id: str = "",
    ) -> None:
        """
        Push a real Discord event into the dashboard notification center.

        kind — one of: dm, mention, friend_request, friend_accept, guild_join,
                        guild_remove, ban, unban, pin, reaction, call, system
        title — short summary (e.g. "DM from Alice")
        body  — message content / extra detail (truncated to 200 chars)
        """
        notif = {
            "id": event_id or secrets.token_hex(8),
            "kind": str(kind)[:32],
            "title": str(title)[:120],
            "body": str(body)[:200],
            "author": str(author)[:80],
            "author_id": str(author_id)[:32],
            "channel_id": str(channel_id)[:32],
            "guild_id": str(guild_id)[:32],
            "icon": str(icon)[:8],   # emoji
            "ts": int(time.time()),
            "read": False,
        }
        with self._notif_lock:
            # Skip exact duplicate event IDs (e.g. same message processed twice)
            if event_id and event_id in self._notif_seen_ids:
                return
            if event_id:
                self._notif_seen_ids.add(event_id)
                # Prevent unbounded growth
                if len(self._notif_seen_ids) > 2000:
                    self._notif_seen_ids = set(list(self._notif_seen_ids)[-1000:])
            self._discord_notif_queue.appendleft(notif)

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

    def _list_user_hosted_entries(self, user_id: str) -> list[tuple[str, dict[str, Any], bool, dict[str, Any]]]:
        """Return hosted entries for a given dashboard user.

        Each item: (token_id, saved_info, is_active, active_info).
        """
        uid = str(user_id or "").strip()
        if not uid:
            return []
        try:
            from host import host_manager as hm

            saved = dict(getattr(hm, "saved_users", {}) or {})
            active = dict(getattr(hm, "active_tokens", {}) or {})
        except Exception:
            return []

        entries = []
        for token_id, info in saved.items():
            if str(info.get("owner", "")) != uid:
                continue
            active_info = active.get(token_id, {}) if isinstance(active.get(token_id, {}), dict) else {}
            entries.append((token_id, info, token_id in active, active_info))
        return entries

    def _get_primary_user_instance(self, user_id: str) -> Optional[dict[str, Any]]:
        """Pick one hosted instance for a dashboard user (prefer active, then latest)."""
        entries = self._list_user_hosted_entries(user_id)
        if not entries:
            return None

        # Prefer active entries; otherwise keep latest token id.
        entries.sort(key=lambda item: (0 if item[2] else 1, str(item[0])), reverse=False)
        token_id, saved_info, is_active, active_info = entries[0]
        return {
            "token_id": token_id,
            "saved": saved_info,
            "active": is_active,
            "active_info": active_info,
        }

    @staticmethod
    def _fmt_uptime_from_ts(since_ts: int) -> str:
        now = int(time.time())
        elapsed = max(0, now - int(since_ts or 0))
        hours, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}h {mins}m {secs}s"

    def _normalize_rpc_asset_key(self, image_value: str, application_id: str = "") -> str:
        """Convert image URLs to Discord media-proxy keys where possible."""
        value = str(image_value or "").strip()
        if not value:
            return value
        if value.startswith("mp:"):
            return value
        if value.startswith("attachments/"):
            return f"mp:{value}"
        if not value.startswith(("http://", "https://")):
            return value

        b = self.bot
        api = getattr(b, "api", None) if b else None
        app_id = str(application_id or "").strip()
        if not api or not app_id:
            return value

        try:
            resp = api.request(
                "POST",
                f"/applications/{app_id}/external-assets",
                data={"urls": [value]},
            )
            if not resp or resp.status_code not in (200, 201):
                return value
            payload = resp.json()
            if isinstance(payload, dict):
                payload = payload.get("external_assets") or payload.get("assets") or []
            if isinstance(payload, list) and payload:
                path = payload[0].get("external_asset_path") or payload[0].get("asset_path")
                if path:
                    return f"mp:{path}"
        except Exception:
            pass

        # Fallback: upload URL image to self-DM and use attachment media proxy key.
        try:
            uploaded = self._upload_rpc_image_to_self_dm(api, value)
            if uploaded:
                return uploaded
        except Exception:
            pass

        return value

    def _upload_rpc_image_to_self_dm(self, api, image_url: str) -> Optional[str]:
        """Upload an image URL to self-DM and return `mp:attachments/...` key."""
        if not image_url or not api:
            return None

        # Download source image
        resp = api.session.get(image_url, timeout=15)
        if resp.status_code != 200:
            return None
        image_bytes = resp.content
        content_type = (resp.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip()
        ext_map = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        ext = ext_map.get(content_type, "png")
        raw_name = image_url.split("/")[-1].split("?", 1)[0]
        filename = raw_name if ("." in raw_name and len(raw_name) <= 60) else f"rpc_asset.{ext}"

        # Ensure account user id exists
        if not getattr(api, "user_id", None):
            try:
                api.get_user_info(force=False)
            except Exception:
                pass
        user_id = getattr(api, "user_id", None)
        if not user_id:
            return None

        dm = api.create_dm(user_id)
        if not dm or "id" not in dm:
            return None

        headers = api.header_spoofer.get_protected_headers(api.token)
        files = {"file": (filename, image_bytes, content_type)}
        msg_resp = api.session.post(
            f"https://discord.com/api/v9/channels/{dm['id']}/messages",
            headers=headers,
            files=files,
            timeout=20,
        )
        if msg_resp.status_code != 200:
            return None
        data = msg_resp.json() if hasattr(msg_resp, "json") else {}
        attachments = data.get("attachments") if isinstance(data, dict) else []
        if not attachments:
            return None

        url = attachments[0].get("url", "")
        m = re.search(r"https?://(?:cdn\.discordapp\.com|media\.discordapp\.net)/attachments/(\d+)/(\d+)/([^?#]+)", url)
        if not m:
            return None
        channel_id, attachment_id, file_name = m.groups()
        return f"mp:attachments/{channel_id}/{attachment_id}/{file_name}"

    def _resolve_afk_system(self):
        """Return a working AFK system instance from bot ref or module fallback."""
        b = self.bot
        afk_ref = getattr(b, "_afk_system_ref", None) if b else None
        if afk_ref is not None:
            return afk_ref
        try:
            from afk_system import afk_system

            afk_system.load_state()
            return afk_system
        except Exception:
            return None

    def _resolve_afk_identity(self) -> str:
        """Choose AFK identity: bot user id, hosted instance user id, then session user id."""
        b = self.bot
        bot_uid = str(getattr(b, "user_id", "") or "").strip() if b else ""
        if bot_uid:
            return bot_uid

        sess_uid = str(session.get("user_id", "") or "").strip()
        if sess_uid:
            primary = self._get_primary_user_instance(sess_uid)
            if primary:
                hosted_uid = str((primary.get("saved") or {}).get("user_id", "") or "").strip()
                if hosted_uid:
                    return hosted_uid
            return sess_uid
        return ""

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

        # For regular dashboard users, show their own hosted-instance context.
        try:
            if self._require_session() and not self._require_admin():
                requester_id = str(session.get("user_id") or "")
                primary = self._get_primary_user_instance(requester_id)
                if primary:
                    saved = primary.get("saved") or {}
                    active_info = primary.get("active_info") or {}
                    connected = bool(primary.get("active"))
                    user_id = str(saved.get("user_id") or "")
                    username = str(saved.get("username") or "User Instance")
                    avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"
                    connected_at = int(active_info.get("connected_at") or 0)
                    uptime = self._fmt_uptime_from_ts(connected_at) if connected and connected_at else "0h 0m 0s"
                    return {
                        "username": username,
                        "user_id": user_id or "—",
                        "avatar_url": avatar_url,
                        "prefix": str(saved.get("prefix") or "$"),
                        "status": "online" if connected else "offline",
                        "connected": connected,
                        "command_count": 0,
                        "commands_registered": 0,
                        "client_type": str(active_info.get("client_type") or saved.get("client_type") or "hosted"),
                        "available_clients": ["web", "desktop", "mobile", "vr"],
                        "ui_version": "v1",
                        "uptime": uptime,
                        "instance_id": str(primary.get("token_id") or self.instance_id),
                        "owner_restricted": bool(self.owner_id),
                    }
        except Exception:
            pass

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
        """Build command history from runtime logs, with fallback dummy data."""
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
                    if ev.get("command"):  # Only add entries with actual command names
                        log_entries.append(
                            {
                                "command": ev.get("command", ""),
                                "user": ev.get("user", "—"),
                                "guild": ev.get("guild", "—"),
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

        # Fallback: try to load from history_data.json but only if it contains command history
        try:
            raw = self._store.load_document("history_data", None)
            if raw is None:
                path = os.path.join(self._base_dir, "history_data.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
            
            # Filter to only command history entries (not profile data)
            if isinstance(raw, list) and raw:
                # Check if entries have command field
                history_entries = [e for e in raw if isinstance(e, dict) and ("command" in e or "cmd" in e)]
                if history_entries:
                    entries = history_entries[-20:]
                    return {"entries": entries, "total": len(history_entries)}
            elif isinstance(raw, dict):
                # If dict structure, try to extract command history
                if "commands" in raw:
                    entries = raw["commands"] if isinstance(raw["commands"], list) else list(raw["commands"].values())[-20:]
                    return {"entries": entries, "total": len(entries)}
        except Exception:
            pass
        
        # Final fallback: empty history
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
            try:
                cpu = psutil.cpu_percent(interval=0.2)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage("/").percent
                net = psutil.net_io_counters()
                net_usage = {'sent': net.bytes_sent, 'recv': net.bytes_recv}
                return jsonify({"ok": True, "cpu": cpu, "ram": ram, "disk": disk, "net": net_usage})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.get("/api/max/version-info")
        def api_max_version_info():
            """Return app version and git revision details for UI badges."""
            version = "v1.1.0"
            git_ref = "unknown"
            try:
                from formatter import VERSION as _VERSION
                if isinstance(_VERSION, str) and _VERSION.strip():
                    version = _VERSION.strip()
            except Exception:
                pass

            try:
                head_ref = os.popen("git rev-parse --short HEAD 2>/dev/null").read().strip()
                if head_ref:
                    git_ref = head_ref
            except Exception:
                pass

            return jsonify({"ok": True, "version": version, "git": git_ref})

        @self.app.get("/api/max/python-env")
        def api_max_python_env():
            """Return Python runtime information for environment badges."""
            return jsonify({
                "ok": True,
                "python": platform.python_version(),
                "platform": f"{platform.system()} {platform.release()}",
                "runtime": os.path.basename(sys.executable or "python"),
            })

        @self.app.get("/api/max/motd")
        def api_max_motd():
            """Return rotating dashboard message of the day."""
            motds = [
                "Operator surface online. Keep the session cold and precise.",
                "Low noise. Fast actions. Full control over the runtime.",
                "Live telemetry, mask control, and command flow in one view.",
                "Dark glass, sharp signals, clean execution.",
            ]
            idx = int(time.time() // 3600) % len(motds)
            return jsonify({"ok": True, "motd": motds[idx]})

        @self.app.get("/api/max/user-profile")
        def api_max_user_profile():
            """Return the live bot identity used for avatar/name surfaces."""
            bot_d = self._bot_data()
            return jsonify({
                "ok": True,
                "username": bot_d.get("username", "Aria"),
                "user_id": bot_d.get("user_id", ""),
                "avatar_url": bot_d.get("avatar_url", ""),
            })

        @self.app.get("/api/max/system-summary")
        def api_max_system_summary():
            """Return high-level overview metrics for dashboard cards."""
            bot_d = self._bot_data()
            analytics = self._analytics_data()
            users = self._load_dashboard_users()

            hosted_total = 0
            hosted_active = 0
            try:
                from host import host_manager as hm
                saved = dict(getattr(hm, "saved_users", {}) or {})
                active = dict(getattr(hm, "active_tokens", {}) or {})
                hosted_total = len(saved)
                hosted_active = len(active)
            except Exception:
                pass

            return jsonify({
                "ok": True,
                "summary": {
                    "connected": bool(bot_d.get("connected", False)),
                    "uptime": bot_d.get("uptime", "-"),
                    "commands_total": int(bot_d.get("command_count", 0) or 0),
                    "success_rate": float(analytics.get("success_rate", 100.0) or 0.0),
                    "avg_response_ms": float(analytics.get("avg_response_ms", 0.0) or 0.0),
                    "users_registered": len(users) if isinstance(users, dict) else 0,
                    "hosted_total": int(hosted_total),
                    "hosted_active": int(hosted_active),
                },
            })

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

        @self.app.get("/api/discord/notifications")
        @self.app.get("/api/discord/notifications/<int:since_ts>")
        def api_discord_notifications(since_ts: int = 0):
            """Return real Discord notifications (DMs, mentions, etc.) newest-first.

            Optional ?since=<unix_ts> query param to fetch only new events.
            Optional ?mark_read=1 to mark all returned events as read.
            """
            if not session.get("authenticated"):
                return jsonify({"ok": False, "error": "unauthenticated"}), 401
            since = since_ts or int(request.args.get("since", 0))
            mark_read = request.args.get("mark_read") == "1"
            with self._notif_lock:
                events = list(self._discord_notif_queue)
            if since:
                events = [e for e in events if e["ts"] > since]
            if mark_read:
                for e in events:
                    e["read"] = True
            return jsonify({"ok": True, "notifications": events, "total": len(events)})

        @self.app.post("/api/discord/notifications/mark_read")
        def api_discord_notifications_mark_read():
            """Mark all (or specific) notifications as read."""
            if not session.get("authenticated"):
                return jsonify({"ok": False, "error": "unauthenticated"}), 401
            data = request.get_json(silent=True) or {}
            nid = data.get("id")  # if provided, mark only that one
            with self._notif_lock:
                for e in self._discord_notif_queue:
                    if nid is None or e["id"] == nid:
                        e["read"] = True
            return jsonify({"ok": True})

        @self.app.delete("/api/discord/notifications")
        def api_discord_notifications_clear():
            """Clear all notifications."""
            if not session.get("authenticated"):
                return jsonify({"ok": False, "error": "unauthenticated"}), 401
            with self._notif_lock:
                self._discord_notif_queue.clear()
                self._notif_seen_ids.clear()
            return jsonify({"ok": True})

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

            if role != "admin":
                primary = self._get_primary_user_instance(user_id)
                if primary:
                    session["host_token_id"] = str(primary.get("token_id") or "")
                else:
                    return redirect("/connect-instance")
            return redirect(next_url)

        @self.app.get("/connect-instance")
        def connect_instance_get() -> Any:
            if not self._require_session():
                return redirect("/login?next=/connect-instance")
            if self._require_admin():
                return redirect("/dashboard")

            # If user already has an instance, send them to dashboard.
            requester_id = str(session.get("user_id") or "")
            primary = self._get_primary_user_instance(requester_id)
            if primary:
                session["host_token_id"] = str(primary.get("token_id") or "")
                return redirect("/dashboard")

            error = str(request.args.get("error", "")).strip()
            try:
                html = self._read_raw_template("connect_instance_template.html")
                error_block = f'<div class="alert alert-error">{error}</div>' if error else ""
                html = html.replace("__ERROR_BLOCK__", error_block)
                return html, 200, {"Content-Type": "text/html; charset=utf-8"}
            except Exception:
                return (
                    """<!DOCTYPE html><html><head><title>Connect Instance</title></head><body>
                    <h2>Connect Your Instance</h2>
                    <form method='post' action='/connect-instance'>
                    <input name='token' placeholder='Discord token' required />
                    <input name='prefix' placeholder='$' maxlength='5' />
                    <button type='submit'>Connect</button>
                    </form></body></html>""",
                    200,
                    {"Content-Type": "text/html; charset=utf-8"},
                )

        @self.app.post("/connect-instance")
        def connect_instance_post() -> Any:
            if not self._require_session():
                return redirect("/login?next=/connect-instance")
            if self._require_admin():
                return redirect("/dashboard")

            requester_id = str(session.get("user_id") or "")
            token = str(request.form.get("token", "")).strip()
            prefix = str(request.form.get("prefix", "$")).strip()[:5] or "$"
            if not token:
                return redirect("/connect-instance?error=Token+is+required")

            try:
                from host import host_manager as hm

                valid, account = hm.validate_token_api(token)
                if not valid:
                    return redirect("/connect-instance?error=Invalid+token")

                account_id = str((account or {}).get("id") or "")
                account_name = str((account or {}).get("username") or "")
                discrim = str((account or {}).get("discriminator") or "")
                if discrim and discrim != "0":
                    account_name = f"{account_name}#{discrim}"

                ok, msg = hm.host_token(
                    owner_id=requester_id,
                    token_input=token,
                    prefix=prefix,
                    user_id=account_id,
                    username=account_name or requester_id,
                )
                if not ok:
                    return redirect(f"/connect-instance?error={msg or 'Failed+to+connect+token'}")

                primary = self._get_primary_user_instance(requester_id)
                if primary:
                    session["host_token_id"] = str(primary.get("token_id") or "")
                self._record_user_activity(requester_id, "host_connect", f"Connected token for {account_name or account_id or 'account'}", request.remote_addr or "")
                return redirect("/dashboard")
            except Exception as e:
                return redirect(f"/connect-instance?error={str(e)}")

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

            if not self._require_admin():
                requester_id = str(session.get("user_id") or "")
                primary = self._get_primary_user_instance(requester_id)
                if not primary:
                    return redirect("/connect-instance")
                session["host_token_id"] = str(primary.get("token_id") or "")

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
            
            # Normalize activity structure for Discord API compatibility
            try:
                # Process assets: handle both single image keys and nested asset object
                if "large_image" in activity or "small_image" in activity or "large_text" in activity or "small_text" in activity:
                    assets = activity.pop("assets", {}) if isinstance(activity.get("assets"), dict) else {}
                    if "large_image" in activity:
                        assets["large_image"] = activity.pop("large_image")
                    if "small_image" in activity:
                        assets["small_image"] = activity.pop("small_image")
                    if "large_text" in activity:
                        assets["large_text"] = activity.pop("large_text")
                    if "small_text" in activity:
                        assets["small_text"] = activity.pop("small_text")
                    if assets:
                        activity["assets"] = assets
                
                # Process buttons: convert from old format {label, url} to Discord format (buttons + metadata.button_urls)
                if "buttons" in activity:
                    buttons_data = activity.get("buttons", [])
                    # If it's a list of objects with label/url, convert to proper Discord format
                    if buttons_data and isinstance(buttons_data[0], dict):
                        button_labels = [b.get("label", "Button") for b in buttons_data if isinstance(b, dict)]
                        button_urls = [b.get("url", "https://discord.com") for b in buttons_data if isinstance(b, dict)]
                        activity["buttons"] = button_labels if button_labels else None
                        if "metadata" not in activity:
                            activity["metadata"] = {}
                        activity["metadata"]["button_urls"] = button_urls
                    # If already list of strings, keep as is (already in Discord format)
                    elif buttons_data and isinstance(buttons_data[0], str):
                        # buttons are already labels, just ensure metadata is set if needed
                        metadata = activity.get("metadata", {})
                        if isinstance(metadata, dict) and "button_urls" not in metadata and "metadata" not in data:
                            # No URLs provided, use Discord's default
                            pass

                # Force a stable app id for RPC image assets so external URLs can resolve in Discord.
                app_id = str(activity.get("application_id") or _DEFAULT_RPC_APPLICATION_ID).strip()
                activity["application_id"] = app_id
                assets = activity.get("assets") if isinstance(activity.get("assets"), dict) else {}
                if assets:
                    li = assets.get("large_image")
                    si = assets.get("small_image")
                    if isinstance(li, str) and li:
                        assets["large_image"] = self._normalize_rpc_asset_key(li, app_id)
                    if isinstance(si, str) and si:
                        assets["small_image"] = self._normalize_rpc_asset_key(si, app_id)
                    activity["assets"] = assets
                
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
            if not self._require_session():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
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

                requester_id = str(session.get("user_id") or "")
                is_admin = self._require_admin()
                result = []
                for tid, info in saved.items():
                    owner = str(info.get("owner", ""))
                    if not is_admin and owner != requester_id:
                        continue

                    is_active = tid in active
                    active_info = active.get(tid, {}) if isinstance(active.get(tid, {}), dict) else {}
                    result.append({
                        "token_id": tid[:8] + "...",
                        "token_ref": tid,
                        "owner": owner or "—",
                        "user_id": str(info.get("user_id", "—")),
                        "prefix": str(info.get("prefix", "$")),
                        "username": str(info.get("username", "—")),
                        "client_type": str(active_info.get("client_type") or info.get("client_type") or "unknown"),
                        "active": is_active,
                        "connected_at": int(active_info.get("connected_at") or 0),
                    })
                active_count = sum(1 for item in result if item.get("active"))
                return jsonify({"ok": True, "hosted": result, "total": len(result), "active_count": active_count, "is_admin": is_admin})
            except Exception as e:
                return jsonify({"ok": True, "hosted": [], "total": 0, "active_count": 0, "note": str(e)})

        @self.app.post("/api/hosted/connect")
        def api_hosted_connect() -> Any:
            if not self._require_session():
                return jsonify({"ok": False, "error": "Unauthorized"}), 403
            data = request.get_json(force=True) or {}
            token = str(data.get("token", "")).strip()
            prefix = str(data.get("prefix", "$")).strip()[:5] or "$"
            if not token:
                return jsonify({"ok": False, "error": "token required"}), 400

            requester_id = str(session.get("user_id") or "")
            requester_name = requester_id
            users = self._load_dashboard_users()
            if isinstance(users, dict):
                entry = users.get(requester_id) or {}
                requester_name = str(entry.get("username") or requester_id)

            try:
                from host import host_manager as hm
                valid, account = hm.validate_token_api(token)
                if not valid:
                    return jsonify({"ok": False, "error": "Invalid token"}), 400

                account_id = str((account or {}).get("id") or "")
                account_name = str((account or {}).get("username") or "")
                discrim = str((account or {}).get("discriminator") or "")
                if discrim and discrim != "0":
                    account_name = f"{account_name}#{discrim}"

                ok, msg = hm.host_token(
                    owner_id=requester_id,
                    token_input=token,
                    prefix=prefix,
                    user_id=account_id,
                    username=account_name or requester_name,
                )
                if not ok:
                    return jsonify({"ok": False, "error": msg or "Failed to connect token"}), 400

                primary = self._get_primary_user_instance(requester_id)
                if primary:
                    session["host_token_id"] = str(primary.get("token_id") or "")
                self._record_user_activity(requester_id, "host_connect", f"Connected token for {account_name or account_id or 'account'}", request.remote_addr or "")
                return jsonify({"ok": True, "message": "Instance connected"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

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

        @self.app.post("/api/hosted/restart")
        def api_hosted_restart():
            if not self._require_admin():
                return jsonify({"ok": False, "error": "Admin only"}), 403
            data = request.get_json(force=True) or {}
            token_id = str(data.get("token_id", "")).strip()
            if not token_id:
                return jsonify({"ok": False, "error": "token_id required"}), 400
            try:
                from host import host_manager as hm
                restarted = 0
                if hasattr(hm, "restart_hosts"):
                    restarted = hm.restart_hosts(selectors=[token_id], all_hosts=True)
                if restarted:
                    self._record_user_activity(session.get("user_id", ""), "host_restart", f"Restarted {token_id[:8]}...", request.remote_addr or "")
                    return jsonify({"ok": True})
                return jsonify({"ok": False, "error": "Could not restart hosted user"}), 400
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
            try:
                afk_ref = self._resolve_afk_system()
                uid = self._resolve_afk_identity()
                if afk_ref and uid:
                    active = bool(afk_ref.is_afk(uid))
                    message = ""
                    info = afk_ref.get_afk_info(uid) if hasattr(afk_ref, "get_afk_info") else {}
                    if isinstance(info, dict):
                        message = str(info.get("reason") or "")
                    return jsonify({"ok": True, "active": active, "message": message or ""})
            except Exception:
                pass
            return jsonify({"ok": True, "active": False, "message": ""})

        @self.app.post("/api/afk")
        def api_afk_set() -> Any:
            data = request.get_json(force=True) or {}
            try:
                afk_ref = self._resolve_afk_system()
                uid = self._resolve_afk_identity()
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
            """Return real-time public statistics for the Aria panel."""
            bot_d = self._bot_data()
            users = self._load_dashboard_users()

            hosted_total = 0
            hosted_active = 0
            total_commands = 0
            success_rate = 99.9
            avg_latency = 12
            
            try:
                from host import host_manager as hm
                saved = dict(getattr(hm, "saved_users", {}) or {})
                active = dict(getattr(hm, "active_tokens", {}) or {})
                hosted_total = len(saved)
                hosted_active = len(active)
            except Exception:
                pass

            try:
                total_commands = int(bot_d.get("command_count", 0))
                success_rate = float(bot_d.get("success_rate", 99.9))
                avg_latency = int(bot_d.get("avg_response_ms", 12))
            except (ValueError, TypeError):
                pass

            platform_status = {
                "cpu_healthy": True,
                "memory_healthy": True,
                "disk_healthy": True,
                "connected": bot_d.get("connected", False),
            }

            return jsonify({
                "ok": True,
                "stats": {
                    "connected": bot_d.get("connected", False),
                    "command_count": total_commands,
                    "uptime": bot_d.get("uptime", "—"),
                    "instance": self.instance_id,
                    "total_hosted": hosted_total,
                    "connected_count": hosted_active,
                    "total_registered": len(users) if isinstance(users, dict) else 0,
                    "success_rate": success_rate,
                    "avg_response_ms": avg_latency,
                    "status": "operational",
                    "platform": platform_status,
                    "version": "2.1.0",
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
