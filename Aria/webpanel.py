from __future__ import annotations

import json
import os
import threading
import time
import hashlib
import secrets
import base64
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, redirect, request, session, url_for


class UserManager:
    """Manages user accounts and authentication for multi-user dashboard."""
    
    def __init__(self, db_path: str = "dashboard_users.json"):
        self.db_path = db_path
        self.users = self._load_users()
    
    def _load_users(self) -> Dict[str, Any]:
        """Load users from database."""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r") as f:
                    return json.load(f)
            except: pass
        return {}
    
    def _save_users(self) -> None:
        """Save users to database."""
        with open(self.db_path, "w") as f:
            json.dump(self.users, f, indent=2)
    
    def _hash_password(self, password: str, salt: str = None) -> tuple:
        """Hash password with salt."""
        if not salt:
            salt = secrets.token_hex(16)
        ph = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return salt, ph.hex()
    
    def register(self, user_id: str, username: str, password: str, bot_token: str = "") -> tuple:
        """Register new user. Returns (success, message)."""
        if user_id in self.users:
            return False, "User ID already exists"
        if username in [u.get("username") for u in self.users.values()]:
            return False, "Username already taken"
        if len(password) < 6:
            return False, "Password must be at least 6 characters"
        
        salt, pw_hash = self._hash_password(password)
        self.users[user_id] = {
            "username": username,
            "password_salt": salt,
            "password_hash": pw_hash,
            "bot_token": bot_token,
            "created": int(time.time()),
            "last_login": 0,
            "settings": {},
            "dashboard_profile": {
                "email_alias": "",
                "bio_link": "",
                "gun_link": "",
                "live_connect_url": "",
                "extra_link_1": "",
                "extra_link_2": "",
            },
        }
        self._save_users()
        return True, "Registration successful"
    
    def login(self, user_id: str, password: str) -> tuple:
        """Login user. Returns (success, message)."""
        if user_id not in self.users:
            return False, "User not found"
        user = self.users[user_id]
        salt = user.get("password_salt", "")
        stored_hash = user.get("password_hash", "")
        _, input_hash = self._hash_password(password, salt)
        if input_hash != stored_hash:
            return False, "Invalid password"
        self.users[user_id]["last_login"] = int(time.time())
        self._save_users()
        return True, "Login successful"
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user data."""
        return self.users.get(user_id)
    
    def _normalize_alias(self, alias: str) -> str:
        alias = str(alias or "").lower().strip()
        alias = "".join(c if c.isalnum() else "-" for c in alias)
        while "--" in alias:
            alias = alias.replace("--", "-")
        alias = alias.strip("-")
        return alias[:48]

    def _alias_exists(self, alias: str, exclude_user: Optional[str] = None) -> bool:
        if not alias:
            return False
        for uid, data in self.users.items():
            if exclude_user and uid == exclude_user:
                continue
            profile = data.get("dashboard_profile", {})
            if str(profile.get("email_alias", "")) == alias:
                return True
        return False

    def set_email_alias(self, user_id: str, alias: str) -> tuple:
        if user_id not in self.users:
            return False, "User not found"
        candidate = self._normalize_alias(alias)
        if not candidate:
            return False, "Alias must contain letters or numbers"
        base = candidate
        count = 1
        while self._alias_exists(candidate, exclude_user=user_id):
            candidate = f"{base}-{count}"
            count += 1
        profile = self.users[user_id].setdefault("dashboard_profile", {})
        profile["email_alias"] = candidate
        self._save_users()
        return True, candidate

    def generate_email_alias(self, user_id: str, desired: str = "") -> tuple:
        if user_id not in self.users:
            return False, "User not found"
        desired = desired.strip() or self.users[user_id].get("username", "") or user_id
        return self.set_email_alias(user_id, desired)

    def get_dashboard_profile(self, user_id: str) -> Dict[str, Any]:
        if user_id not in self.users:
            return {}
        return self.users[user_id].get("dashboard_profile", {})

    def update_dashboard_profile(self, user_id: str, profile_data: Dict[str, Any]) -> tuple:
        if user_id not in self.users:
            return False, "User not found"
        profile = self.users[user_id].setdefault("dashboard_profile", {
            "email_alias": "",
            "bio_link": "",
            "gun_link": "",
            "live_connect_url": "",
            "extra_link_1": "",
            "extra_link_2": "",
        })
        if "email_alias" in profile_data:
            ok, alias_or_msg = self.set_email_alias(user_id, profile_data.get("email_alias", ""))
            if not ok:
                return ok, alias_or_msg
            profile["email_alias"] = alias_or_msg
        for key in ["bio_link", "gun_link", "live_connect_url", "extra_link_1", "extra_link_2"]:
            if key in profile_data:
                profile[key] = str(profile_data.get(key, "")).strip()
        self._save_users()
        return True, "Dashboard profile updated"

    def update_bot_token(self, user_id: str, bot_token: str) -> bool:
        """Update user's bot token."""
        if user_id in self.users:
            self.users[user_id]["bot_token"] = bot_token
            self._save_users()
            return True
        return False
    
    def update_settings(self, user_id: str, settings: Dict) -> bool:
        """Update user settings."""
        if user_id in self.users:
            self.users[user_id]["settings"].update(settings)
            self._save_users()
            return True
        return False


class WebPanel:
    """Lightweight dashboard for bot status and RPC controls."""

    def __init__(self, api=None, bot=None, host: str = "127.0.0.1", port: int = 5001):
        self.api = api
        self.bot = bot
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self.app.secret_key = os.getenv("ARIA_WEBPANEL_SECRET", "aria-webpanel-auth-secret")
        self._thread = None

        self.dashboard_auth_path = "dashboard_authed_users.json"
        self.dashboard_block_path = "dashboard_blocked_users.json"
        self.panel_access_checker: Optional[Callable[[str], bool]] = None
        self.panel_block_checker: Optional[Callable[[str], bool]] = None
        self.owner_overview_getter: Optional[Callable[[], Dict[str, Any]]] = None
        self.email_domain = os.getenv("ARIA_EMAIL_DOMAIN", "stackss.lol")
        
        # Initialize multi-user system
        self.user_manager = UserManager("dashboard_users.json")
        
        self._login_username = "Misconsideration"
        self._login_password = "Stackss123"

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

    def set_access_controls(
        self,
        allowed_checker: Optional[Callable[[str], bool]] = None,
        blocked_checker: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.panel_access_checker = allowed_checker
        self.panel_block_checker = blocked_checker

    def set_owner_overview_getter(self, getter: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        self.owner_overview_getter = getter

    def _load_id_set_file(self, path: str) -> set:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return set(str(x) for x in data)
        except Exception:
            pass
        return set()

    def _is_panel_user_blocked(self, user_id: str) -> bool:
        uid = str(user_id or "")
        if not uid:
            return True
        if self._is_admin_session():
            return False

        if self.panel_block_checker:
            try:
                return bool(self.panel_block_checker(uid))
            except Exception:
                pass

        return uid in self._load_id_set_file(self.dashboard_block_path)

    def _is_panel_user_allowed(self, user_id: str) -> bool:
        uid = str(user_id or "")
        if not uid:
            return False
        if self._is_admin_session():
            return True
        if self._is_panel_user_blocked(uid):
            return False

        if self.panel_access_checker:
            try:
                return bool(self.panel_access_checker(uid))
            except Exception:
                pass

        return uid in self._load_id_set_file(self.dashboard_auth_path)

    def _owner_overview(self) -> Dict[str, Any]:
        if self.owner_overview_getter:
            try:
                data = self.owner_overview_getter() or {}
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        hosted = {}
        try:
            if os.path.exists("hosted_users.json"):
                with open("hosted_users.json", "r") as f:
                    hosted = json.load(f) or {}
        except Exception:
            hosted = {}

        hosted_list = []
        if isinstance(hosted, dict):
            for token_id, entry in hosted.items():
                e = entry or {}
                hosted_list.append(
                    {
                        "token_id": str(token_id),
                        "uid": str(e.get("uid", token_id)),
                        "owner": str(e.get("owner", "")),
                        "username": str(e.get("username", "Unknown")),
                        "user_id": str(e.get("user_id", "")),
                    }
                )

        users = []
        for uid, data in self.user_manager.users.items():
            users.append(
                {
                    "user_id": uid,
                    "username": data.get("username", ""),
                    "last_login": int(data.get("last_login", 0)),
                }
            )

        users.sort(key=lambda x: x.get("last_login", 0), reverse=True)
        now = int(time.time())
        connected = [u for u in users if now - int(u.get("last_login", 0) or 0) <= 1800]
        authed = self._load_id_set_file(self.dashboard_auth_path)
        blocked = self._load_id_set_file(self.dashboard_block_path)

        return {
            "total_registered": len(self.user_manager.users),
            "total_authed": len(authed),
            "total_blocked": len(blocked),
            "total_hosted": len(hosted_list),
            "connected_users": connected,
            "connected_count": len(connected),
            "hosted_users": hosted_list,
            "hosted_uids": [h.get("uid", "") for h in hosted_list],
        }

    def _instance_logs_path(self) -> str:
        return "webpanel_instance_logs.json"

    def _append_instance_log(self, user_id: str, event: str, detail: str = "") -> None:
        uid = str(user_id or "unknown")
        entry = {
            "ts": int(time.time()),
            "user_id": uid,
            "event": str(event or "event"),
            "detail": str(detail or "")[:600],
        }

        logs = []
        path = self._instance_logs_path()
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    logs = json.load(f) or []
        except Exception:
            logs = []

        if not isinstance(logs, list):
            logs = []

        logs.append(entry)
        logs = logs[-5000:]

        try:
            with open(path, "w") as f:
                json.dump(logs, f, indent=2)
        except Exception:
            pass

    def _get_instance_logs(self, user_id: Optional[str] = None, limit: int = 200) -> list:
        path = self._instance_logs_path()
        logs = []
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    logs = json.load(f) or []
        except Exception:
            logs = []

        if not isinstance(logs, list):
            return []

        if user_id:
            uid = str(user_id)
            logs = [x for x in logs if str(x.get("user_id", "")) == uid]

        return list(reversed(logs[-max(1, int(limit)):]))

    def _encode_image_data_url(self, image_url: str) -> Optional[str]:
        """Download and encode image URL into data URI for Discord profile endpoints."""
        if not self.api or not image_url:
            return None

        try:
            response = self.api.session.get(image_url, timeout=10)
            if response.status_code != 200:
                return None
            content_type = (response.headers.get("Content-Type", "") or "").lower()
            if "gif" in content_type:
                ext = "gif"
            elif "jpeg" in content_type or "jpg" in content_type:
                ext = "jpeg"
            elif "webp" in content_type:
                ext = "webp"
            else:
                ext = "png"
            encoded = base64.b64encode(response.content).decode()
            return f"data:image/{ext};base64,{encoded}"
        except Exception:
            return None

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

    def _client_profiles(self) -> Dict[str, Any]:
        profiles = getattr(self.bot, "_CLIENT_PROFILES", {}) if self.bot is not None else {}
        if isinstance(profiles, dict):
            return profiles
        return {}

    def _current_client_type(self) -> str:
        if self.bot is None:
            return "unknown"
        return str(getattr(self.bot, "_client_type", "unknown"))

    def _is_admin_session(self) -> bool:
        return str(session.get("user_id", "")) == "admin"

    def _activate_user_context(self, user_id: str) -> bool:
        """Apply a user's saved bot token to the active bot/api context."""
        if not user_id or user_id == "admin":
            return False

        user = self.user_manager.get_user(user_id)
        if not user:
            return False

        token = str(user.get("bot_token", "")).strip()
        if not token:
            return False

        if self.api is not None and hasattr(self.api, "token"):
            self.api.token = token

        if self.bot is not None:
            if hasattr(self.bot, "token"):
                self.bot.token = token
            bot_api = getattr(self.bot, "api", None)
            if bot_api is not None and hasattr(bot_api, "token"):
                bot_api.token = token

        return True

    def _build_rpc_mode_payload(self, mode: str, payload: Dict[str, Any]) -> Dict[str, str]:
        """Normalize UI RPC mode payloads into activity text/type/emoji."""
        m = (mode or "").strip().lower()

        track = str(payload.get("track", "")).strip()
        artist = str(payload.get("artist", "")).strip()
        album = str(payload.get("album", "")).strip()
        title = str(payload.get("title", "")).strip()
        channel = str(payload.get("channel", "")).strip()
        episode = str(payload.get("episode", "")).strip()
        details = str(payload.get("details", "")).strip()
        state = str(payload.get("state", "")).strip()
        name = str(payload.get("name", "")).strip()

        apps = {
            "spotify": ("listening", "spotify", "Spotify"),
            "youtube_music": ("listening", "music", "YouTube Music"),
            "applemusic": ("listening", "music", "Apple Music"),
            "soundcloud": ("listening", "cloud", "SoundCloud"),
            "deezer": ("listening", "music", "Deezer"),
            "tidal": ("listening", "music", "TIDAL"),
            "twitch": ("streaming", "live", "Twitch"),
            "kick": ("streaming", "live", "Kick"),
            "youtube": ("watching", "play", "YouTube"),
            "netflix": ("watching", "tv", "Netflix"),
            "disneyplus": ("watching", "sparkles", "Disney+"),
            "primevideo": ("watching", "film", "Prime Video"),
            "plex": ("watching", "film", "Plex"),
            "jellyfin": ("watching", "film", "Jellyfin"),
            "crunchyroll": ("watching", "tv", "Crunchyroll"),
            "vscode": ("playing", "code", "VS Code"),
            "browser": ("playing", "globe", "Browser"),
            "vrchat": ("playing", "vr", "VRChat"),
            "beat": ("playing", "notes", "Beat Saber"),
            "chill": ("custom", "sparkles", "VR Chill"),
            "world": ("competing", "tools", "World Builder"),
        }

        if m in {"playing", "streaming", "listening", "watching", "competing"}:
            text = details or title or track or name or "Active"
            if state:
                text = f"{text} | {state}"
            return {"text": text, "emoji": "", "activity_type": m}

        if m in apps:
            activity_type, emoji, app_label = apps[m]
            if m in {"spotify", "youtube_music", "applemusic", "soundcloud", "deezer", "tidal"}:
                main = track or title or "Unknown Track"
                by = artist or state or "Unknown Artist"
                extra = f" ({album})" if album else ""
                return {
                    "text": f"{app_label}: {main} - {by}{extra}",
                    "emoji": emoji,
                    "activity_type": activity_type,
                }
            if m in {"twitch", "kick", "youtube"}:
                main = title or details or "Live"
                ch = channel or state or "Channel"
                return {
                    "text": f"{app_label}: {main} ({ch})",
                    "emoji": emoji,
                    "activity_type": activity_type,
                }
            if m in {"netflix", "disneyplus", "primevideo", "plex", "jellyfin", "crunchyroll"}:
                main = title or details or "Watching"
                ep = episode or state
                suffix = f" - {ep}" if ep else ""
                return {
                    "text": f"{app_label}: {main}{suffix}",
                    "emoji": emoji,
                    "activity_type": activity_type,
                }

            main = title or details or name or app_label
            return {
                "text": f"{app_label}: {main}",
                "emoji": emoji,
                "activity_type": activity_type,
            }

        fallback_text = details or title or track or name or "Custom Activity"
        return {"text": fallback_text, "emoji": "", "activity_type": "custom"}

    def _rpc_catalog(self) -> Dict[str, Any]:
        # Web panel catalog used by UI and API clients.
        return {
            "presets": [
                {"id": "vrchat", "label": "VRChat", "activity_type": "playing"},
                {"id": "beat", "label": "Beat Saber", "activity_type": "playing"},
                {"id": "chill", "label": "VR Chill", "activity_type": "custom"},
                {"id": "world", "label": "World Builder", "activity_type": "competing"},
            ],
            "advanced": [
                "spotify", "youtube_music", "applemusic", "soundcloud", "deezer", "tidal",
                "twitch", "kick", "youtube",
                "netflix", "disneyplus", "primevideo", "plex", "jellyfin", "crunchyroll",
                "vscode", "browser", "playing", "streaming", "listening", "watching", "competing",
                "vrchat", "beat", "chill", "world",
            ],
        }

    def _help_sections(self) -> Dict[str, Any]:
        return {
            "web": [
                "web - start panel",
                "web reload - reload webpanel module (restart bot if panel already running)",
            ],
            "rpc": [
                "status <online|idle|dnd|invisible>",
                "rpc commands are available through your command engine in main.py",
            ],
            "clients": [
                "Switch client profile from Web Panel > VR Clients",
                "Available profiles are discovered from bot._CLIENT_PROFILES",
            ],
        }

    def _setup_routes(self) -> None:
        @self.app.before_request
        def require_auth() -> Any:
            path = request.path or "/"
            if path.startswith("/static") or path == "/favicon.ico":
                return None
            if path in {"/", "/home", "/tos", "/privacy", "/login", "/logout", "/access-pending", "/api/public/stats"}:
                return None

            if session.get("webpanel_authenticated"):
                user_id = str(session.get("user_id") or "")
                if self._is_panel_user_allowed(user_id):
                    return None

                if path.startswith("/api/"):
                    return jsonify(
                        {
                            "ok": False,
                            "error": "Dashboard access denied. Contact @misconsiderations for authorisation.",
                        }
                    ), 403

                return redirect(url_for("access_pending"))

            if path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required"}), 401

            return redirect(url_for("login", next=path))

        @self.app.route("/login", methods=["GET", "POST"])
        def login() -> Any:
            error = ""
            next_path = request.args.get("next", "/dashboard")
            mode = request.args.get("mode", "login")  # login or register

            if request.method == "POST":
                user_input = str(request.form.get("user_id", "")).strip()
                password = str(request.form.get("password", "")).strip()
                next_path = str(request.form.get("next", "/dashboard") or "/dashboard")
                
                if mode == "register":
                    # Registration mode
                    username = str(request.form.get("username", "")).strip()
                    bot_token = str(request.form.get("bot_token", "")).strip()
                    
                    if not user_input or not username or not password:
                        error = "User ID, username, and password are required"
                    else:
                        ok, msg = self.user_manager.register(user_input, username, password, bot_token)
                        if ok:
                            session["user_id"] = user_input
                            session["webpanel_authenticated"] = True
                            self._activate_user_context(user_input)
                            self._append_instance_log(user_input, "register", "registered via dashboard")
                            return redirect(next_path if next_path.startswith("/") else "/dashboard")
                        error = msg
                else:
                    # Login mode
                    # Try multi-user login first
                    if user_input and password:
                        ok, msg = self.user_manager.login(user_input, password)
                        if ok:
                            session["user_id"] = user_input
                            session["webpanel_authenticated"] = True
                            self._activate_user_context(user_input)
                            self._append_instance_log(user_input, "login", "logged in via dashboard")
                            return redirect(next_path if next_path.startswith("/") else "/dashboard")
                    
                    # Fallback to admin single-user auth for backwards compatibility
                    if user_input == self._login_username and password == self._login_password:
                        session["user_id"] = "admin"
                        session["webpanel_authenticated"] = True
                        self._append_instance_log("admin", "login", "admin login")
                        return redirect(next_path if next_path.startswith("/") else "/dashboard")
                    
                    error = "Invalid user ID or password"

            return self._render_login(error=error, next_path=next_path, mode=mode)

        @self.app.route("/register", methods=["GET", "POST"])
        def register() -> Any:
            # Redirect to login with register mode
            return redirect(url_for("login", mode="register"))

        @self.app.get("/logout")
        def logout() -> Any:
            self._append_instance_log(str(session.get("user_id") or "unknown"), "logout", "logged out")
            session.pop("user_id", None)
            session.pop("webpanel_authenticated", None)
            return redirect(url_for("login"))

        @self.app.get("/access-pending")
        def access_pending() -> str:
            return self._render_access_pending()

        @self.app.get("/api/user/profile")
        def user_profile() -> Any:
            """Get current user's profile."""
            user_id = session.get("user_id")
            if user_id == "admin":
                return jsonify({
                    "ok": True,
                    "user_id": "admin",
                    "username": "Admin",
                    "created": 0,
                    "last_login": int(time.time()),
                    "bot_token": "managed by runtime",
                    "settings": {},
                    "is_admin": True,
                })

            user = self.user_manager.get_user(user_id) if user_id else None
            if not user:
                return jsonify({"ok": False, "error": "User not found"}), 404
            return jsonify({
                "ok": True,
                "user_id": user_id,
                "username": user.get("username", ""),
                "created": user.get("created", 0),
                "last_login": user.get("last_login", 0),
                "bot_token": "***" if user.get("bot_token") else "not set",
                "settings": user.get("settings", {}),
                "dashboard_profile": self.user_manager.get_dashboard_profile(user_id),
                "is_admin": False,
            })

        @self.app.post("/api/user/token")
        def set_user_token() -> Any:
            """Update user's bot token."""
            user_id = session.get("user_id")
            if not user_id:
                return jsonify({"ok": False, "error": "Not authenticated"}), 401

            payload = request.get_json(silent=True) or {}
            bot_token = str(payload.get("bot_token", "")).strip()

            if not bot_token:
                return jsonify({"ok": False, "error": "bot_token is required"}), 400

            if self.user_manager.update_bot_token(user_id, bot_token):
                self._activate_user_context(user_id)
                self._append_instance_log(str(user_id), "token_update", "updated user bot token")
                return jsonify({"ok": True, "message": "Token updated"})
            return jsonify({"ok": False, "error": "Failed to update token"}), 500

        @self.app.post("/api/user/settings")
        def user_settings() -> Any:
            """Update user settings."""
            user_id = session.get("user_id")
            if not user_id:
                return jsonify({"ok": False, "error": "Not authenticated"}), 401
            
            payload = request.get_json(silent=True) or {}
            if self.user_manager.update_settings(user_id, payload):
                self._append_instance_log(str(user_id), "settings_update", "updated dashboard settings")
                return jsonify({"ok": True, "message": "Settings updated"})
            return jsonify({"ok": False, "error": "Failed to update settings"}), 500

        @self.app.post("/api/user/dashboard_profile")
        def dashboard_profile_update() -> Any:
            user_id = str(session.get("user_id") or "")
            if not user_id:
                return jsonify({"ok": False, "error": "Not authenticated"}), 401
            payload = request.get_json(silent=True) or {}
            result, message = self.user_manager.update_dashboard_profile(user_id, payload)
            if result:
                self._append_instance_log(user_id, "dashboard_profile_update", "updated email/link profile")
                return jsonify(
                    {
                        "ok": True,
                        "message": message,
                        "dashboard_profile": self.user_manager.get_dashboard_profile(user_id),
                    }
                )
            return jsonify({"ok": False, "error": message}), 400

        @self.app.get("/api/user/instance_logs")
        def user_instance_logs() -> Any:
            user_id = str(session.get("user_id") or "")
            if not user_id:
                return jsonify({"ok": False, "error": "Not authenticated"}), 401
            return jsonify({"ok": True, "logs": self._get_instance_logs(user_id=user_id, limit=200)})

        @self.app.get("/api/admin/instance_logs")
        def admin_instance_logs() -> Any:
            if not self._is_admin_session():
                return jsonify({"ok": False, "error": "Admin access required"}), 403
            return jsonify({"ok": True, "logs": self._get_instance_logs(user_id=None, limit=1000)})

        @self.app.post("/api/profile/update")
        def update_discord_profile() -> Any:
            user_id = str(session.get("user_id") or "")
            if not user_id:
                return jsonify({"ok": False, "error": "Not authenticated"}), 401
            if not self.api:
                return jsonify({"ok": False, "error": "Discord API not available"}), 400

            payload = request.get_json(silent=True) or {}
            user_patch = {}
            profile_patch = {}

            global_name = str(payload.get("global_name", "")).strip()
            bio = str(payload.get("bio", "")).strip()
            pronouns = str(payload.get("pronouns", "")).strip()
            avatar_url = str(payload.get("avatar_url", "")).strip()
            banner_url = str(payload.get("banner_url", "")).strip()
            deco_id = str(payload.get("avatar_decoration_id", "")).strip()
            effect_id = str(payload.get("profile_effect_id", "")).strip()

            if global_name:
                user_patch["global_name"] = global_name
            if bio:
                profile_patch["bio"] = bio
            if pronouns:
                profile_patch["pronouns"] = pronouns
            if deco_id:
                profile_patch["avatar_decoration_id"] = deco_id
            if effect_id:
                profile_patch["profile_effect_id"] = effect_id

            if avatar_url:
                encoded_avatar = self._encode_image_data_url(avatar_url)
                if not encoded_avatar:
                    return jsonify({"ok": False, "error": "Failed to encode avatar image URL"}), 400
                user_patch["avatar"] = encoded_avatar

            if banner_url:
                encoded_banner = self._encode_image_data_url(banner_url)
                if not encoded_banner:
                    return jsonify({"ok": False, "error": "Failed to encode banner image URL"}), 400
                user_patch["banner"] = encoded_banner

            if not user_patch and not profile_patch:
                return jsonify({"ok": False, "error": "No profile fields provided"}), 400

            results = {}
            if user_patch:
                resp = self.api.request("PATCH", "/users/@me", data=user_patch)
                results["users_me"] = resp.status_code if resp is not None else None

            if profile_patch:
                resp = self.api.request("PATCH", "/users/@me/profile", data=profile_patch)
                results["users_me_profile"] = resp.status_code if resp is not None else None

            ok = any(code in (200, 201, 204) for code in results.values() if code is not None)
            self._append_instance_log(user_id, "profile_update", f"fields={','.join(list(user_patch.keys()) + list(profile_patch.keys()))}")
            return jsonify({"ok": ok, "results": results, "message": "Profile update attempted"})

        @self.app.get("/api/admin/users")
        def admin_users() -> Any:
            if not self._is_admin_session():
                return jsonify({"ok": False, "error": "Admin access required"}), 403

            users = []
            for uid, data in self.user_manager.users.items():
                users.append(
                    {
                        "user_id": uid,
                        "username": data.get("username", ""),
                        "created": int(data.get("created", 0)),
                        "last_login": int(data.get("last_login", 0)),
                        "has_token": bool(str(data.get("bot_token", "")).strip()),
                    }
                )

            users.sort(key=lambda u: u["created"], reverse=True)
            return jsonify({"ok": True, "users": users, "count": len(users)})

        @self.app.get("/api/admin/overview")
        def admin_overview() -> Any:
            if not self._is_admin_session():
                return jsonify({"ok": False, "error": "Admin access required"}), 403
            return jsonify({"ok": True, "overview": self._owner_overview()})

        @self.app.post("/api/admin/users/delete")
        def admin_delete_user() -> Any:
            if not self._is_admin_session():
                return jsonify({"ok": False, "error": "Admin access required"}), 403

            payload = request.get_json(silent=True) or {}
            user_id = str(payload.get("user_id", "")).strip()
            if not user_id:
                return jsonify({"ok": False, "error": "user_id is required"}), 400

            if user_id not in self.user_manager.users:
                return jsonify({"ok": False, "error": "User not found"}), 404

            del self.user_manager.users[user_id]
            self.user_manager._save_users()
            return jsonify({"ok": True, "message": f"Deleted user {user_id}"})

        @self.app.get("/")
        @self.app.get("/home")
        def public_home() -> str:
            return self._render_public_home()

        @self.app.get("/tos")
        def tos() -> str:
            return self._render_tos_page()

        @self.app.get("/privacy")
        def privacy() -> str:
            return self._render_privacy_page()

        @self.app.get("/api/public/stats")
        def public_stats() -> Any:
            overview = self._owner_overview()
            return jsonify(
                {
                    "ok": True,
                    "stats": {
                        "total_hosted": int(overview.get("total_hosted", 0)),
                        "connected_count": int(overview.get("connected_count", 0)),
                        "total_registered": int(overview.get("total_registered", 0)),
                    },
                }
            )

        @self.app.get("/dashboard")
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
            uid = str(session.get("user_id") or "")
            last_mode = str(self.last_command.get("mode", "none"))
            updated = int(self.last_command.get("timestamp", int(time.time())))
            return jsonify(
                {
                    "ok": True,
                    "activity": self._current_activity(),
                    "last_command": self.last_command,
                    "last_transport": self._last_transport,
                    "preview_ids": {
                        "session_user_id": uid or "guest",
                        "mode_id": last_mode,
                        "command_ts": updated,
                        "transport_id": str(self._last_transport),
                    },
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
            self._append_instance_log(str(session.get("user_id") or "unknown"), "rpc_apply", f"type={activity_type}")
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

        @self.app.post("/api/rpc/mode")
        def rpc_mode() -> Any:
            payload = request.get_json(silent=True) or {}
            mode = str(payload.get("mode", "")).strip().lower()
            if not mode:
                return jsonify({"ok": False, "error": "mode is required"}), 400

            rpc_payload = self._build_rpc_mode_payload(mode, payload)
            text = str(rpc_payload.get("text", "")).strip()
            emoji = str(rpc_payload.get("emoji", "")).strip()
            activity_type = str(rpc_payload.get("activity_type", "custom")).strip().lower() or "custom"

            if not text:
                return jsonify({"ok": False, "error": "generated activity text is empty"}), 400

            if activity_type not in {"custom", "playing", "streaming", "listening", "watching", "competing"}:
                activity_type = "custom"

            ok = self._safe_apply_activity(text, emoji=emoji, activity_type=activity_type, mode=f"mode:{mode}")
            self._append_instance_log(str(session.get("user_id") or "unknown"), "rpc_mode", mode)
            return jsonify(
                {
                    "ok": ok,
                    "mode": mode,
                    "applied": {"text": text, "emoji": emoji, "activity_type": activity_type},
                    "activity": self._current_activity(),
                    "last_command": self.last_command,
                }
            )

        @self.app.post("/api/rpc/clear")
        def rpc_clear() -> Any:
            ok = self._safe_apply_activity("", emoji="", activity_type="custom", mode="clear")
            self._append_instance_log(str(session.get("user_id") or "unknown"), "rpc_clear", "cleared activity")
            return jsonify({"ok": ok, "activity": self._current_activity(), "last_command": self.last_command})

        @self.app.get("/api/rpc/catalog")
        def rpc_catalog() -> Any:
          return jsonify({"ok": True, "catalog": self._rpc_catalog()})

        @self.app.get("/api/vr/clients")
        def get_vr_clients() -> Any:
          profiles = self._client_profiles()
          return jsonify(
            {
              "ok": True,
              "current": self._current_client_type(),
              "profiles": list(profiles.keys()),
              "profile_data": profiles,
            }
          )

        @self.app.post("/api/vr/clients/set")
        def set_vr_client() -> Any:
          payload = request.get_json(silent=True) or {}
          client_type = str(payload.get("client_type", "")).strip().lower()
          if not client_type:
            return jsonify({"ok": False, "error": "client_type is required"}), 400

          if self.bot is None or not hasattr(self.bot, "set_client_type"):
            return jsonify({"ok": False, "error": "bot client switching is not available"}), 400

          try:
            ok = bool(self.bot.set_client_type(client_type))
            if not ok:
              return jsonify({"ok": False, "error": "invalid client type"}), 400
            return jsonify(
              {
                "ok": True,
                "current": self._current_client_type(),
                "profiles": list(self._client_profiles().keys()),
              }
            )
          except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.get("/api/help")
        def get_help() -> Any:
          return jsonify({"ok": True, "sections": self._help_sections()})

        @self.app.post("/api/settings")
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
                self._append_instance_log(str(session.get("user_id") or "unknown"), "send_message", f"type={command_type}")
                
                return jsonify({"ok": True, "message": f"{command_type.title()} command executed successfully"})
                
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.post("/api/backup")
        def trigger_backup() -> Any:
            try:
                from backup import BackupManager
                backup_mgr = BackupManager(self.api)
                backup_file = backup_mgr.create_full_backup()
                return jsonify({"ok": bool(backup_file), "message": f"Backup created: {backup_file}" if backup_file else "Backup failed"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)})

        @self.app.post("/api/restore")
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
    <title>Aria Premium Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        :root {
            --primary: #ec4899;
            --secondary: #8b5cf6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --dark: #0f172a;
            --darker: #020617;
            --text: #e5e7eb;
            --text-muted: #9ca3af;
            --border: #334155;
        }
        body {
            background: linear-gradient(135deg, var(--dark) 0%, #1e1b4b 50%, var(--dark) 100%);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
        }
        .navbar {
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(10px);
            border-bottom: 1px solid var(--border);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .navbar-brand {
            font-size: 1.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .navbar-user {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .user-badge {
            background: rgba(236, 72, 153, 0.1);
            border: 1px solid var(--primary);
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.9rem;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border);
            overflow-x: auto;
        }
        .tab-btn {
            padding: 0.75rem 1.5rem;
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-weight: 600;
            border-bottom: 3px solid transparent;
            transition: all 0.3s;
        }
        .tab-btn.active {
            color: var(--primary);
            border-color: var(--primary);
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .section {
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            backdrop-filter: blur(10px);
        }
        .section-title {
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 1rem;
            color: var(--primary);
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1rem;
        }
        .card {
            background: rgba(30, 27, 75, 0.5);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1.25rem;
            transition: all 0.3s;
        }
        .card:hover {
            border-color: var(--primary);
            background: rgba(30, 27, 75, 0.8);
        }
        .card-icon {
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }
        .card-title {
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        .card-value {
            font-size: 1.5rem;
            color: var(--primary);
            font-weight: 600;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--text-muted);
        }
        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 0.75rem;
            background: #0b1220;
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-family: inherit;
            transition: all 0.3s;
        }
        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
            border-color: var(--primary);
            background: #0f172a;
            outline: none;
            box-shadow: 0 0 0 3px rgba(236, 72, 153, 0.1);
        }
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
        }
        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 0.95rem;
        }
        .btn-primary {
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(236, 72, 153, 0.3);
        }
        .btn-secondary {
            background: var(--border);
            color: var(--text);
        }
        .btn-secondary:hover {
            background: #475569;
        }
        .btn-group {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        .badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            background: rgba(236, 72, 153, 0.2);
            border: 1px solid var(--primary);
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .status-online {
            color: var(--success);
        }
        .status-offline {
            color: var(--danger);
        }
        .rpc-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 0.75rem;
        }
        .rpc-btn {
            padding: 0.75rem;
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid var(--secondary);
            border-radius: 8px;
            color: var(--secondary);
            cursor: pointer;
            font-weight: 600;
            font-size: 0.85rem;
            transition: all 0.3s;
            text-align: center;
        }
        .rpc-btn:hover {
            background: rgba(139, 92, 246, 0.3);
            transform: translateY(-2px);
        }
        .profile-card {
            display: grid;
            grid-template-columns: 1fr;
            gap: 1rem;
        }
        .profile-info {
            display: grid;
            gap: 0.75rem;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border);
        }
        .info-label {
            color: var(--text-muted);
            font-weight: 600;
        }
        .info-value {
            color: var(--text);
            font-weight: 600;
        }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .alert-success {
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid var(--success);
            color: var(--success);
        }
        .alert-error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid var(--danger);
            color: var(--danger);
        }
        @media (max-width: 768px) {
            .navbar { padding: 1rem; }
            .container { padding: 1rem; }
            .tabs { flex-wrap: wrap; }
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="navbar-brand">🎮 ARIA Dashboard</div>
        <div class="navbar-user">
            <div class="user-badge">
                <span id="user-display">Loading...</span>
            </div>
            <a href="/logout" style="color: var(--text-muted); text-decoration: none;">Logout</a>
        </div>
    </div>

    <div class="container">
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('dashboard')">Dashboard</button>
            <button class="tab-btn" onclick="switchTab('rpc')">RPC Control</button>
            <button class="tab-btn" onclick="switchTab('commands')">Commands</button>
            <button class="tab-btn" onclick="switchTab('settings')">Settings</button>
            <button class="tab-btn" onclick="switchTab('profile')">Profile</button>
            <button class="tab-btn" id="admin-tab-btn" onclick="switchTab('admin')" style="display:none;">Admin</button>
        </div>

        <!-- Dashboard Tab -->
        <div id="dashboard" class="tab-content active">
            <div class="grid">
                <div class="card">
                    <div class="card-icon">📊</div>
                    <div class="card-title">Bot Status</div>
                    <div class="card-value status-online">🟢 Online</div>
                </div>
                <div class="card">
                    <div class="card-icon">⏱️</div>
                    <div class="card-title">Uptime</div>
                    <div class="card-value" id="uptime-display">Loading...</div>
                </div>
                <div class="card">
                    <div class="card-icon">📨</div>
                    <div class="card-title">Commands Executed</div>
                    <div class="card-value" id="commands-count">0</div>
                </div>
                <div class="card">
                    <div class="card-icon">🎮</div>
                    <div class="card-title">Current Activity</div>
                    <div class="card-value" id="current-activity">None</div>
                </div>
            </div>

            <div class="section" style="margin-top: 1.5rem;">
                <div class="section-title">Quick Actions</div>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="clearActivity()">Clear Activity</button>
                    <button class="btn btn-secondary" onclick="refreshDashboard()">Refresh Stats</button>
                </div>
            </div>
        </div>

        <!-- RPC Control Tab -->
        <div id="rpc" class="tab-content">
            <div class="section">
                <div class="section-title">🎵 Music Platforms</div>
                <div class="rpc-grid">
                    <button class="rpc-btn" onclick="setRpcMode('spotify')">Spotify</button>
                    <button class="rpc-btn" onclick="setRpcMode('youtube_music')">YouTube Music</button>
                    <button class="rpc-btn" onclick="setRpcMode('applemusic')">Apple Music</button>
                    <button class="rpc-btn" onclick="setRpcMode('soundcloud')">SoundCloud</button>
                    <button class="rpc-btn" onclick="setRpcMode('deezer')">Deezer</button>
                    <button class="rpc-btn" onclick="setRpcMode('tidal')">TIDAL</button>
                </div>

                <div class="form-group" style="margin-top: 1rem;">
                    <label>Song Details</label>
                    <div class="form-row">
                        <input type="text" id="music-track" placeholder="Track Name">
                        <input type="text" id="music-artist" placeholder="Artist">
                        <input type="text" id="music-album" placeholder="Album">
                    </div>
                    <div class="form-row" style="margin-top: 0.5rem;">
                        <input type="number" id="music-elapsed" placeholder="Elapsed (min)" step="0.1" min="0">
                        <input type="number" id="music-total" placeholder="Total (min)" step="0.1" min="0">
                    </div>
                    <button class="btn btn-primary" onclick="applyMusicRpc()" style="margin-top: 0.5rem;">Apply Music RPC</button>
                </div>
            </div>

            <div class="section">
                <div class="section-title">🎮 Streaming & Gaming</div>
                <div class="rpc-grid">
                    <button class="rpc-btn" onclick="setRpcMode('twitch')">Twitch</button>
                    <button class="rpc-btn" onclick="setRpcMode('kick')">Kick</button>
                    <button class="rpc-btn" onclick="setRpcMode('youtube')">YouTube</button>
                    <button class="rpc-btn" onclick="setRpcMode('playing')">Playing</button>
                    <button class="rpc-btn" onclick="setRpcMode('streaming')">Streaming</button>
                    <button class="rpc-btn" onclick="setRpcMode('competing')">Competing</button>
                </div>

                <div class="form-group" style="margin-top: 1rem;">
                    <label>Stream/Game Details</label>
                    <div class="form-row">
                        <input type="text" id="stream-title" placeholder="Game/Stream Title">
                        <input type="text" id="stream-channel" placeholder="Channel">
                    </div>
                    <button class="btn btn-primary" onclick="applyStreamRpc()" style="margin-top: 0.5rem;">Apply Stream RPC</button>
                </div>
            </div>

            <div class="section">
                <div class="section-title">🎬 Video Platforms</div>
                <div class="rpc-grid">
                    <button class="rpc-btn" onclick="setRpcMode('netflix')">Netflix</button>
                    <button class="rpc-btn" onclick="setRpcMode('disneyplus')">Disney+</button>
                    <button class="rpc-btn" onclick="setRpcMode('primevideo')">Prime Video</button>
                    <button class="rpc-btn" onclick="setRpcMode('plex')">Plex</button>
                    <button class="rpc-btn" onclick="setRpcMode('jellyfin')">Jellyfin</button>
                    <button class="rpc-btn" onclick="setRpcMode('crunchyroll')">Crunchyroll</button>
                </div>

                <div class="form-group" style="margin-top: 1rem;">
                    <label>Video Details</label>
                    <div class="form-row">
                        <input type="text" id="video-title" placeholder="Show/Movie Title">
                        <input type="text" id="video-episode" placeholder="Episode" />
                    </div>
                    <button class="btn btn-primary" onclick="applyVideoRpc()" style="margin-top: 0.5rem;">Apply Video RPC</button>
                </div>
            </div>

            <div class="section">
                <div class="section-title">💻 Coding & Other</div>
                <div class="rpc-grid">
                    <button class="rpc-btn" onclick="setRpcMode('vscode')">VS Code</button>
                    <button class="rpc-btn" onclick="setRpcMode('browser')">Browser</button>
                    <button class="rpc-btn" onclick="setRpcMode('listening')">Listening</button>
                    <button class="rpc-btn" onclick="setRpcMode('watching')">Watching</button>
                </div>

                <div class="form-group" style="margin-top: 1rem;">
                    <label>Custom Activity Text</label>
                    <input type="text" id="custom-text" placeholder="Activity text...">
                    <button class="btn btn-primary" onclick="applyCustomRpc()" style="margin-top: 0.5rem;">Apply Custom</button>
                </div>
            </div>

            <div class="section">
                <div class="section-title">🥽 VR Mode</div>
                <div class="form-row">
                    <input type="text" id="vr-name" placeholder="VR App Name" value="VR">
                    <input type="text" id="vr-details" placeholder="Details" value="In VR">
                </div>
                <div class="form-row" style="margin-top: 0.5rem;">
                    <input type="text" id="vr-state" placeholder="State" value="Meta Quest">
                    <input type="text" id="vr-image" placeholder="Large Image URL">
                </div>
                <div class="form-group" style="margin-top: 0.5rem;">
                    <label>
                        <input type="checkbox" id="vr-icon-only"> Icon Only Mode
                    </label>
                </div>
                <button class="btn btn-primary" onclick="applyVrRpc()" style="width: 100%;">Apply VR RPC</button>
            </div>

            <div class="section">
                <div class="section-title">📋 Live Preview</div>
                <div class="profile-info" id="rpc-preview">
                    <div class="info-row">
                        <span class="info-label">Activity:</span>
                        <span class="info-value" id="preview-activity">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Type:</span>
                        <span class="info-value" id="preview-type">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Status:</span>
                        <span class="info-value" id="preview-status">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Session User ID:</span>
                        <span class="info-value" id="preview-user-id">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Mode ID:</span>
                        <span class="info-value" id="preview-mode-id">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Transport ID:</span>
                        <span class="info-value" id="preview-transport-id">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Command Timestamp:</span>
                        <span class="info-value" id="preview-command-ts">-</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Commands Tab -->
        <div id="commands" class="tab-content">
            <div class="section">
                <div class="section-title">Send Command</div>
                <div class="form-row">
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label>Command Type</label>
                        <select id="cmd-type" onchange="updateCommandFields()">
                            <option value="message">Send Message</option>
                            <option value="reaction">Add Reaction</option>
                            <option value="typing">Start Typing</option>
                            <option value="presence">Update Presence</option>
                        </select>
                    </div>
                </div>

                <div class="form-group">
                    <label>Channel ID</label>
                    <input type="text" id="cmd-channel" placeholder="Channel ID">
                </div>

                <div id="cmd-message-field" class="form-group">
                    <label>Message Content</label>
                    <textarea id="cmd-content" placeholder="Enter message..." rows="3"></textarea>
                </div>

                <div id="cmd-reaction-field" class="form-group" style="display: none;">
                    <label>Emoji</label>
                    <input type="text" id="cmd-emoji" placeholder="emoji name or Unicode">
                </div>

                <div class="form-group">
                    <label>Delay (seconds)</label>
                    <input type="number" id="cmd-delay" placeholder="0" min="0" step="0.1">
                </div>

                <button class="btn btn-primary" onclick="sendCommand()" style="width: 100%;">Send</button>
                <div id="cmd-result" style="margin-top: 1rem;"></div>
            </div>

            <div class="section">
                <div class="section-title">Command History</div>
                <div id="cmd-history" style="max-height: 300px; overflow-y: auto; font-size: 0.9rem; color: var(--text-muted);">
                    No commands sent yet
                </div>
            </div>
        </div>

        <!-- Settings Tab -->
        <div id="settings" class="tab-content">
            <div class="section">
                <div class="section-title">Bot Configuration</div>
                <form id="settings-form">
                    <div class="form-row">
                        <div class="form-group">
                            <label>Bot Token</label>
                            <input type="password" id="bot-token" placeholder="Your bot token">
                        </div>
                        <div class="form-group">
                            <label>Command Prefix</label>
                            <input type="text" id="prefix" placeholder="e.g., !" value="!">
                        </div>
                    </div>

                    <div class="form-row">
                        <div class="form-group">
                            <label>Rate Limit Delay</label>
                            <input type="number" id="rate-limit" placeholder="0.1" step="0.1" min="0.1" value="0.1">
                        </div>
                        <div class="form-group">
                            <label>RPC Name</label>
                            <input type="text" id="rpc-name" placeholder="Your RPC Name">
                        </div>
                    </div>

                    <div class="form-group">
                        <label>User Agent</label>
                        <input type="text" id="user-agent" placeholder="User agent string">
                    </div>

                    <div style="margin-top: 1rem;">
                        <label>
                            <input type="checkbox" id="captcha-enabled"> Enable Captcha Solving
                        </label>
                    </div>

                    <div class="form-row" style="margin-top: 0.5rem;">
                        <div class="form-group">
                            <label>Captcha API Key</label>
                            <input type="password" id="captcha-key" placeholder="2Captcha API Key">
                        </div>
                        <div class="form-group">
                            <label>Captcha Service</label>
                            <select id="captcha-service">
                                <option value="2captcha">2Captcha</option>
                                <option value="anticaptcha">AntiCaptcha</option>
                                <option value="capmonster">CapMonster</option>
                            </select>
                        </div>
                    </div>

                    <button type="submit" class="btn btn-primary" onclick="saveSettings(); return false;" style="width: 100%; margin-top: 1rem;">Save Settings</button>
                </form>
                <div id="settings-result" style="margin-top: 1rem;"></div>
            </div>
        </div>

        <!-- Profile Tab -->
        <div id="profile" class="tab-content">
            <div class="section">
                <div class="section-title">User Profile</div>
                <div class="profile-info">
                    <div class="info-row">
                        <span class="info-label">Username:</span>
                        <span class="info-value" id="profile-username">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">User ID:</span>
                        <span class="info-value" id="profile-userid">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Member Since:</span>
                        <span class="info-value" id="profile-created">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Last Login:</span>
                        <span class="info-value" id="profile-lastlogin">-</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Account Status:</span>
                        <span class="info-value status-online">🟢 Active</span>
                    </div>
                </div>
            </div>

            <div class="section">
                <div class="section-title">Subscription & Limits</div>
                <div class="grid">
                    <div class="card">
                        <div class="card-title">Tier</div>
                        <div class="card-value" style="font-size: 1.2rem;">🎖️ Premium</div>
                    </div>
                    <div class="card">
                        <div class="card-title">Bot Instances</div>
                        <div class="card-value" style="font-size: 1.2rem;">1/1</div>
                    </div>
                    <div class="card">
                        <div class="card-title">API Calls/Hour</div>
                        <div class="card-value" style="font-size: 1.2rem;">1000/1000</div>
                    </div>
                </div>
            </div>

            <div class="section">
                <div class="section-title">Account Actions</div>
                <div class="btn-group">
                    <button class="btn btn-secondary" onclick="changePassword()">Change Password</button>
                    <button class="btn btn-secondary" onclick="downloadData()">Download Data</button>
                    <button class="btn btn-primary" onclick="logout()">Logout</button>
                </div>
            </div>

            <div class="section">
                <div class="section-title">Discord Profile Editor</div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Global Display Name</label>
                        <input type="text" id="profile-global-name" placeholder="Global display name">
                    </div>
                    <div class="form-group">
                        <label>Pronouns</label>
                        <input type="text" id="profile-pronouns" placeholder="e.g. she/her">
                    </div>
                </div>
                <div class="form-group">
                    <label>Bio</label>
                    <textarea id="profile-bio" placeholder="Profile bio" rows="3"></textarea>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Avatar URL</label>
                        <input type="text" id="profile-avatar-url" placeholder="https://...">
                    </div>
                    <div class="form-group">
                        <label>Banner URL</label>
                        <input type="text" id="profile-banner-url" placeholder="https://...">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Avatar Decoration ID</label>
                        <input type="text" id="profile-decoration-id" placeholder="Decoration ID">
                    </div>
                    <div class="form-group">
                        <label>Profile Effect ID</label>
                        <input type="text" id="profile-effect-id" placeholder="Effect ID">
                    </div>
                </div>
                <button class="btn btn-primary" onclick="saveDiscordProfile()" style="width: 100%;">Apply Profile Changes</button>
                <div id="profile-edit-result" style="margin-top: 1rem;"></div>
            </div>

            <div class="section">
                <div class="section-title">My Instance Logs</div>
                <div class="btn-group" style="margin-bottom: 1rem;">
                    <button class="btn btn-secondary" onclick="loadUserInstanceLogs()">Refresh My Logs</button>
                </div>
                <div id="user-instance-logs" style="display: grid; gap: 0.5rem; font-size: 0.9rem;"></div>
            </div>
        </div>

        <!-- Admin Tab -->
        <div id="admin" class="tab-content">
            <div class="section">
                <div class="section-title">Owner Overview</div>
                <div id="admin-overview" class="grid" style="margin-bottom: 1rem;"></div>
                <div id="admin-uids" class="profile-info" style="margin-top: 0.5rem;"></div>
            </div>

            <div class="section">
                <div class="section-title">Admin User Management</div>
                <div class="btn-group" style="margin-bottom: 1rem;">
                    <button class="btn btn-secondary" onclick="refreshAdminPanel()">Refresh Owner Panel</button>
                </div>
                <div id="admin-users" style="display: grid; gap: 0.75rem;"></div>
            </div>

            <div class="section">
                <div class="section-title">All Instance Logs</div>
                <div id="admin-instance-logs" style="display: grid; gap: 0.5rem; font-size: 0.9rem;"></div>
            </div>
        </div>
    </div>

    <script>
        let selectedRpcMode = 'spotify';
        let isAdminUser = false;

        async function apiJson(url, options = {}) {
            const response = await fetch(url, options);
            const data = await response.json();
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || 'Request failed');
            }
            return data;
        }

        function switchTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabName).classList.add('active');
            const target = (window.event && window.event.target) ? window.event.target : document.querySelector('.tab-btn');
            if (target) {
                target.classList.add('active');
            }
            if (tabName === 'admin' && isAdminUser) {
                refreshAdminPanel();
            }
        }

        function markRpcSelection(mode) {
            selectedRpcMode = mode;
            document.querySelectorAll('.rpc-btn').forEach(btn => btn.style.boxShadow = 'none');
            const activeBtn = Array.from(document.querySelectorAll('.rpc-btn')).find(btn => (btn.getAttribute('onclick') || '').includes(`setRpcMode('${mode}')`));
            if (activeBtn) {
                activeBtn.style.boxShadow = '0 0 0 2px var(--primary) inset';
            }
        }

        function setRpcMode(mode) {
            markRpcSelection(mode);
            showAlert('RPC mode selected: ' + mode, 'success');
        }

        async function applyRpcMode(payload) {
            try {
                const data = await apiJson('/api/rpc/mode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
                showAlert(data.ok ? `Applied ${payload.mode} RPC` : 'Failed to apply RPC', data.ok ? 'success' : 'error');
                await refreshRpcPreview();
            } catch (e) {
                showAlert(e.message || 'Failed to apply RPC', 'error');
            }
        }

        function applyMusicRpc() {
            applyRpcMode({
                mode: selectedRpcMode,
                track: document.getElementById('music-track').value,
                artist: document.getElementById('music-artist').value,
                album: document.getElementById('music-album').value,
            });
        }

        function applyStreamRpc() {
            applyRpcMode({
                mode: selectedRpcMode,
                title: document.getElementById('stream-title').value,
                channel: document.getElementById('stream-channel').value,
            });
        }

        function applyVideoRpc() {
            applyRpcMode({
                mode: selectedRpcMode,
                title: document.getElementById('video-title').value,
                episode: document.getElementById('video-episode').value,
            });
        }

        async function applyCustomRpc() {
            const text = document.getElementById('custom-text').value.trim();
            if (!text) {
                showAlert('Custom text is required', 'error');
                return;
            }
            try {
                await apiJson('/api/rpc/apply', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text, activity_type: selectedRpcMode}),
                });
                showAlert('Custom RPC applied', 'success');
                await refreshRpcPreview();
            } catch (e) {
                showAlert(e.message || 'Failed to apply custom RPC', 'error');
            }
        }

        function applyVrRpc() {
            applyRpcMode({
                mode: 'vrchat',
                title: document.getElementById('vr-name').value,
                details: document.getElementById('vr-details').value,
                state: document.getElementById('vr-state').value,
            });
        }

        function updateCommandFields() {
            const type = document.getElementById('cmd-type').value;
            document.getElementById('cmd-message-field').style.display = type === 'message' ? 'block' : 'none';
            document.getElementById('cmd-reaction-field').style.display = type === 'reaction' ? 'block' : 'none';
        }

        async function sendCommand() {
            const payload = {
                type: document.getElementById('cmd-type').value,
                channel_id: document.getElementById('cmd-channel').value,
                content: document.getElementById('cmd-content').value,
                emoji: document.getElementById('cmd-emoji').value,
                delay: parseFloat(document.getElementById('cmd-delay').value || '0') || 0,
            };

            try {
                const data = await apiJson('/api/send_message', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
                document.getElementById('cmd-result').innerHTML = `<div class="alert alert-success">${data.message || 'Command executed'}</div>`;
                showAlert('Command sent', 'success');
                loadCommandHistory();
            } catch (e) {
                document.getElementById('cmd-result').innerHTML = `<div class="alert alert-error">${e.message || 'Command failed'}</div>`;
                showAlert(e.message || 'Command failed', 'error');
            }
        }

        async function clearActivity() {
            try {
                await apiJson('/api/rpc/clear', {method: 'POST'});
                showAlert('Activity cleared', 'success');
                await refreshRpcPreview();
            } catch (e) {
                showAlert(e.message || 'Failed to clear activity', 'error');
            }
        }

        async function refreshRpcPreview() {
            try {
                const data = await apiJson('/api/rpc/preview');
                const activity = data.activity || {};
                const last = data.last_command || {};
                const ids = data.preview_ids || {};
                document.getElementById('preview-activity').textContent = activity.text || 'None';
                document.getElementById('preview-type').textContent = activity.activity_type || '-';
                document.getElementById('preview-status').textContent = last.result || '-';
                document.getElementById('preview-user-id').textContent = ids.session_user_id || '-';
                document.getElementById('preview-mode-id').textContent = ids.mode_id || '-';
                document.getElementById('preview-transport-id').textContent = ids.transport_id || '-';
                document.getElementById('preview-command-ts').textContent = ids.command_ts ? new Date(ids.command_ts * 1000).toLocaleString() : '-';
                document.getElementById('current-activity').textContent = activity.text || 'None';
            } catch (_) {
            }
        }

        async function refreshDashboard() {
            try {
                const status = await apiJson('/status');
                const activity = status.current_activity || {};
                document.getElementById('current-activity').textContent = activity.text || 'None';
            } catch (_) {
            }

            try {
                const analytics = await apiJson('/api/analytics');
                const stats = analytics.system_stats || {};
                document.getElementById('uptime-display').textContent = `${stats.uptime || 0}h`;
                document.getElementById('commands-count').textContent = String(stats.messages_sent || 0);
            } catch (_) {
            }

            await refreshRpcPreview();
        }

        async function saveSettings() {
            const settings = {
                prefix: document.getElementById('prefix').value,
                rate_limit_delay: parseFloat(document.getElementById('rate-limit').value),
                user_agent: document.getElementById('user-agent').value,
                rpc_name: document.getElementById('rpc-name').value,
                captcha_enabled: document.getElementById('captcha-enabled').checked,
                captcha_api_key: document.getElementById('captcha-key').value,
                captcha_service: document.getElementById('captcha-service').value,
            };

            const token = document.getElementById('bot-token').value.trim();
            try {
                if (token) {
                    await apiJson('/api/user/token', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({bot_token: token}),
                    });
                }

                const data = await apiJson('/api/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(settings),
                });

                const resultEl = document.getElementById('settings-result');
                resultEl.innerHTML = `<div class="alert alert-success">${data.message || 'Settings saved'}</div>`;
                showAlert('Settings saved', 'success');
            } catch (e) {
                const resultEl = document.getElementById('settings-result');
                resultEl.innerHTML = `<div class="alert alert-error">${e.message || 'Failed to save settings'}</div>`;
                showAlert(e.message || 'Failed to save settings', 'error');
            }
        }

        function changePassword() {
            showAlert('Password reset endpoint can be added next', 'success');
        }

        function downloadData() {
            showAlert('Data export feature coming soon', 'success');
        }

        function logout() {
            if (confirm('Are you sure you want to logout?')) {
                window.location.href = '/logout';
            }
        }

        function showAlert(message, type = 'success') {
            const alertClass = type === 'success' ? 'alert-success' : 'alert-error';
            const alert = document.createElement('div');
            alert.className = `alert ${alertClass}`;
            alert.textContent = message;
            alert.style.position = 'fixed';
            alert.style.top = '80px';
            alert.style.right = '20px';
            alert.style.zIndex = '1000';
            alert.style.minWidth = '300px';
            document.body.appendChild(alert);
            setTimeout(() => alert.remove(), 3000);
        }

        async function loadUserProfile() {
            try {
                const user = await apiJson('/api/user/profile');
                isAdminUser = !!user.is_admin;

                document.getElementById('user-display').textContent = user.username || user.user_id || 'User';
                document.getElementById('profile-username').textContent = user.username || '-';
                document.getElementById('profile-userid').textContent = user.user_id || '-';
                document.getElementById('profile-created').textContent = user.created ? new Date(user.created * 1000).toLocaleDateString() : '-';
                document.getElementById('profile-lastlogin').textContent = user.last_login ? new Date(user.last_login * 1000).toLocaleString() : 'Now';

                if (isAdminUser) {
                    document.getElementById('admin-tab-btn').style.display = 'inline-block';
                    refreshAdminPanel();
                }
            } catch (_) {
                document.getElementById('user-display').textContent = 'User';
            }
        }

        async function loadCommandHistory() {
            try {
                const data = await apiJson('/api/command_history');
                const rows = (data.history || []).slice().reverse();
                const el = document.getElementById('cmd-history');
                if (!rows.length) {
                    el.textContent = 'No commands yet';
                    return;
                }
                el.innerHTML = rows.map(item => `<div style="padding: 6px 0; border-bottom: 1px solid var(--border);">${item.timestamp || ''} :: ${item.command || ''} :: ${item.result || ''}</div>`).join('');
            } catch (_) {
            }
        }

        async function loadAdminUsers() {
            if (!isAdminUser) {
                return;
            }
            const container = document.getElementById('admin-users');
            container.innerHTML = 'Loading users...';
            try {
                const data = await apiJson('/api/admin/users');
                const users = data.users || [];
                if (!users.length) {
                    container.innerHTML = '<div class="card">No users found</div>';
                    return;
                }

                container.innerHTML = users.map(u => {
                    const created = u.created ? new Date(u.created * 1000).toLocaleDateString() : '-';
                    const last = u.last_login ? new Date(u.last_login * 1000).toLocaleString() : '-';
                    const token = u.has_token ? 'set' : 'missing';
                    return `<div class="card"><div class="card-title">${u.username || u.user_id}</div><div style="color: var(--text-muted); font-size: 0.9rem;">ID: ${u.user_id} | Created: ${created} | Last Login: ${last} | Token: ${token}</div><div style="margin-top: 0.75rem;"><button class="btn btn-secondary" onclick="deleteUser('${u.user_id}')">Delete</button></div></div>`;
                }).join('');
            } catch (e) {
                container.innerHTML = `<div class="alert alert-error">${e.message || 'Failed to load users'}</div>`;
            }
        }

        async function loadAdminOverview() {
            if (!isAdminUser) {
                return;
            }
            try {
                const data = await apiJson('/api/admin/overview');
                const overview = data.overview || {};
                const cards = [
                    {label: 'Total Registered', value: overview.total_registered || 0},
                    {label: 'Total Hosted', value: overview.total_hosted || 0},
                    {label: 'Connected Users', value: overview.connected_count || 0},
                    {label: 'Authed UIDs', value: overview.total_authed || 0},
                ];

                document.getElementById('admin-overview').innerHTML = cards.map(c => `<div class="card"><div class="card-title">${c.label}</div><div class="card-value">${c.value}</div></div>`).join('');

                const uidList = overview.hosted_uids || [];
                const users = overview.connected_users || [];
                const uidRows = [];
                uidRows.push(`<div class="info-row"><span class="info-label">Hosted UIDs</span><span class="info-value">${uidList.length || 0}</span></div>`);
                uidRows.push(`<div class="info-row"><span class="info-label">UID List</span><span class="info-value">${uidList.join(', ') || '-'}</span></div>`);
                uidRows.push(`<div class="info-row"><span class="info-label">Connected User IDs</span><span class="info-value">${users.map(u => u.user_id).join(', ') || '-'}</span></div>`);
                document.getElementById('admin-uids').innerHTML = uidRows.join('');
            } catch (e) {
                document.getElementById('admin-overview').innerHTML = `<div class="alert alert-error">${e.message || 'Failed to load owner overview'}</div>`;
            }
        }

        async function loadUserInstanceLogs() {
            try {
                const data = await apiJson('/api/user/instance_logs');
                const logs = data.logs || [];
                const box = document.getElementById('user-instance-logs');
                if (!logs.length) {
                    box.innerHTML = '<div class="card">No instance logs yet</div>';
                    return;
                }
                box.innerHTML = logs.slice(0, 120).map(x => {
                    const t = x.ts ? new Date(x.ts * 1000).toLocaleString() : '-';
                    return `<div class="card"><div style="font-weight:700;">${x.event || '-'}</div><div style="color:var(--text-muted);">${t} :: ${x.detail || ''}</div></div>`;
                }).join('');
            } catch (e) {
                document.getElementById('user-instance-logs').innerHTML = `<div class="alert alert-error">${e.message || 'Failed to load logs'}</div>`;
            }
        }

        async function loadAdminInstanceLogs() {
            if (!isAdminUser) {
                return;
            }
            try {
                const data = await apiJson('/api/admin/instance_logs');
                const logs = data.logs || [];
                const box = document.getElementById('admin-instance-logs');
                if (!logs.length) {
                    box.innerHTML = '<div class="card">No instance logs yet</div>';
                    return;
                }
                box.innerHTML = logs.slice(0, 200).map(x => {
                    const t = x.ts ? new Date(x.ts * 1000).toLocaleString() : '-';
                    return `<div class="card"><div style="font-weight:700;">${x.user_id || 'unknown'} :: ${x.event || '-'}</div><div style="color:var(--text-muted);">${t} :: ${x.detail || ''}</div></div>`;
                }).join('');
            } catch (e) {
                document.getElementById('admin-instance-logs').innerHTML = `<div class="alert alert-error">${e.message || 'Failed to load all logs'}</div>`;
            }
        }

        async function refreshAdminPanel() {
            if (!isAdminUser) {
                return;
            }
            await Promise.all([loadAdminOverview(), loadAdminUsers(), loadAdminInstanceLogs()]);
        }

        async function saveDiscordProfile() {
            const payload = {
                global_name: document.getElementById('profile-global-name').value,
                pronouns: document.getElementById('profile-pronouns').value,
                bio: document.getElementById('profile-bio').value,
                avatar_url: document.getElementById('profile-avatar-url').value,
                banner_url: document.getElementById('profile-banner-url').value,
                avatar_decoration_id: document.getElementById('profile-decoration-id').value,
                profile_effect_id: document.getElementById('profile-effect-id').value,
            };

            try {
                const data = await apiJson('/api/profile/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
                document.getElementById('profile-edit-result').innerHTML = `<div class="alert alert-success">${data.message || 'Profile update sent'}</div>`;
                showAlert('Profile update sent', 'success');
                loadUserInstanceLogs();
            } catch (e) {
                document.getElementById('profile-edit-result').innerHTML = `<div class="alert alert-error">${e.message || 'Profile update failed'}</div>`;
                showAlert(e.message || 'Profile update failed', 'error');
            }
        }

        async function deleteUser(userId) {
            if (!confirm(`Delete user ${userId}?`)) {
                return;
            }
            try {
                await apiJson('/api/admin/users/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId}),
                });
                showAlert(`Deleted ${userId}`, 'success');
                loadAdminUsers();
            } catch (e) {
                showAlert(e.message || 'Delete failed', 'error');
            }
        }

        updateCommandFields();
        markRpcSelection(selectedRpcMode);
        loadUserProfile();
        refreshDashboard();
        loadCommandHistory();
        loadUserInstanceLogs();
        setInterval(refreshRpcPreview, 5000);
    </script>
</body>
</html>"""

        def _render_public_home(self) -> str:
                return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Aria - Premium Discord Hosting</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            min-height: 100vh;
            color: #e5e7eb;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: radial-gradient(circle at 10% 10%, #1e1b4b 0%, #0f172a 52%, #020617 100%);
        }
        .top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 18px 24px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.25);
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(6px);
            position: sticky;
            top: 0;
        }
        .brand {
            font-weight: 900;
            font-size: 1.3rem;
            background: linear-gradient(135deg, #ec4899, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .nav { display: flex; gap: 10px; flex-wrap: wrap; }
        .nav a {
            text-decoration: none;
            color: #e5e7eb;
            background: #334155;
            padding: 10px 14px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.92rem;
        }
        .hero {
            max-width: 1160px;
            margin: 0 auto;
            padding: 44px 24px 24px;
            display: grid;
            grid-template-columns: 1.2fr 1fr;
            gap: 26px;
        }
        .title {
            font-size: clamp(1.9rem, 5vw, 3rem);
            font-weight: 900;
            margin-bottom: 12px;
        }
        .subtitle {
            color: #cbd5e1;
            line-height: 1.6;
            margin-bottom: 18px;
        }
        .cta { display: flex; gap: 10px; flex-wrap: wrap; }
        .cta a {
            text-decoration: none;
            padding: 12px 16px;
            border-radius: 12px;
            font-weight: 800;
            color: #fff;
        }
        .cta .primary { background: linear-gradient(135deg, #ec4899, #8b5cf6); }
        .cta .muted { background: #334155; }
        .panel {
            background: rgba(15, 23, 42, 0.94);
            border: 1px solid rgba(148, 163, 184, 0.3);
            border-radius: 14px;
            padding: 18px;
        }
        .stats {
            display: grid;
            gap: 12px;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        }
        .stat {
            background: rgba(30, 27, 75, 0.55);
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 12px;
        }
        .k { color: #94a3b8; font-size: 0.85rem; margin-bottom: 4px; }
        .v { color: #f472b6; font-size: 1.55rem; font-weight: 900; }
        .content {
            max-width: 1160px;
            margin: 0 auto;
            padding: 0 24px 30px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 14px;
        }
        .card {
            background: rgba(15, 23, 42, 0.94);
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 12px;
            padding: 16px;
        }
        .card h3 { color: #f9a8d4; margin-bottom: 8px; }
        .card p { color: #cbd5e1; line-height: 1.55; font-size: 0.95rem; }
        .footer {
            max-width: 1160px;
            margin: 0 auto;
            padding: 0 24px 30px;
            color: #94a3b8;
            font-size: 0.92rem;
        }
        @media (max-width: 900px) {
            .hero { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="top">
        <div class="brand">ARIA - Premium Discord Hosting</div>
        <div class="nav">
            <a href="/login">Dashboard Login</a>
            <a href="/tos">TOS</a>
            <a href="/privacy">Privacy</a>
        </div>
    </div>

    <section class="hero">
        <div>
            <div class="title">Aria Premium Discord Hosting</div>
            <p class="subtitle">
                Multi-user selfbot hosting with per-user dashboard access, RPC automation, owner moderation,
                and managed instance operations. Track connected users, hosted IDs, and live status in one panel.
            </p>
            <div class="cta">
                <a class="primary" href="/login">Open Dashboard</a>
                <a class="muted" href="/access-pending">Authorisation Info</a>
            </div>
        </div>

        <div class="panel">
            <h3 style="margin-bottom: 12px; color: #f9a8d4;">Live Instance Stats</h3>
            <div id="public-stats" class="stats">
                <div class="stat"><div class="k">Hosted Instances</div><div class="v">-</div></div>
                <div class="stat"><div class="k">Connected Users</div><div class="v">-</div></div>
                <div class="stat"><div class="k">Registered Accounts</div><div class="v">-</div></div>
            </div>
        </div>
    </section>

    <section class="content">
        <div class="card">
            <h3>Managed Instances</h3>
            <p>Each hosted user can keep their own token context and settings, with owner visibility over active and hosted UIDs.</p>
        </div>
        <div class="card">
            <h3>Live RPC Control</h3>
            <p>Premium RPC dashboard includes live preview and mode/transport IDs so you can verify exactly what is applied in real time.</p>
        </div>
        <div class="card">
            <h3>Owner Tools</h3>
            <p>Admin panel shows connected users, hosted totals, user management, and cross-instance activity logs for moderation.</p>
        </div>
        <div class="card">
            <h3>Policy & Privacy</h3>
            <p>Review terms of service and privacy policy before onboarding users. Access controls and authorisation gating are enforced.</p>
        </div>
    </section>

    <div class="footer">
        Aria Premium Panel | Hosting access managed by owner/admin authorisation.
    </div>

    <script>
        fetch('/api/public/stats').then(r => r.json()).then(data => {
            if (!data.ok) return;
            const s = data.stats || {};
            const box = document.getElementById('public-stats');
            box.innerHTML = `
                <div class="stat"><div class="k">Hosted Instances</div><div class="v">${s.total_hosted ?? 0}</div></div>
                <div class="stat"><div class="k">Connected Users</div><div class="v">${s.connected_count ?? 0}</div></div>
                <div class="stat"><div class="k">Registered Accounts</div><div class="v">${s.total_registered ?? 0}</div></div>
            `;
        }).catch(() => {});
    </script>
</body>
</html>"""

        def _render_tos_page(self) -> str:
                return """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Aria - Terms of Service</title>
<style>
body{background:#0f172a;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:24px;line-height:1.65}
.wrap{max-width:900px;margin:0 auto;background:#111827;border:1px solid #334155;border-radius:14px;padding:24px}
h1{color:#f472b6;margin-bottom:14px} h2{color:#a78bfa;margin-top:16px;margin-bottom:8px}
a{color:#93c5fd;text-decoration:none}
</style></head><body><div class="wrap">
<h1>Terms of Service</h1>
<p>By using Aria Premium Discord Hosting, you agree to follow owner/admin rules, access policies, and platform restrictions.</p>
<h2>Account Access</h2>
<p>Dashboard access may be approved, denied, or revoked by owner/admin at any time.</p>
<h2>Usage Responsibility</h2>
<p>Users are responsible for their own Discord account behavior, token safety, and command usage.</p>
<h2>Service Changes</h2>
<p>Features, plans, access limits, and instance controls can be modified without prior notice.</p>
<p><a href="/home">Back to Home</a></p>
</div></body></html>"""

        def _render_privacy_page(self) -> str:
                return """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Aria - Privacy Policy</title>
<style>
body{background:#020617;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:24px;line-height:1.65}
.wrap{max-width:900px;margin:0 auto;background:#111827;border:1px solid #334155;border-radius:14px;padding:24px}
h1{color:#f472b6;margin-bottom:14px} h2{color:#a78bfa;margin-top:16px;margin-bottom:8px}
a{color:#93c5fd;text-decoration:none}
</style></head><body><div class="wrap">
<h1>Privacy Policy</h1>
<p>Aria stores account and dashboard operational data required for hosting and moderation (for example user IDs, settings, and instance logs).</p>
<h2>Data Collected</h2>
<p>Login account metadata, hosted-user records, instance activity logs, and dashboard settings.</p>
<h2>Data Access</h2>
<p>Owner/admin accounts can view operational logs and hosted account summaries for management and abuse prevention.</p>
<h2>Data Retention</h2>
<p>Logs may be retained for stability/security; removal is at owner/admin discretion.</p>
<p><a href="/home">Back to Home</a></p>
</div></body></html>"""

    def _render_access_pending(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Aria Dashboard - Access Pending</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: radial-gradient(circle at 20% 20%, #1e1b4b, #0f172a 55%, #020617 100%);
            color: #e5e7eb;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 24px;
        }
        .card {
            width: min(680px, 100%);
            background: rgba(15, 23, 42, 0.96);
            border: 1px solid rgba(236, 72, 153, 0.35);
            border-radius: 16px;
            padding: 28px;
            box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
        }
        h1 {
            color: #ec4899;
            font-size: 30px;
            margin-bottom: 8px;
        }
        p {
            color: #cbd5e1;
            line-height: 1.55;
            margin-bottom: 14px;
        }
        .note {
            background: rgba(139, 92, 246, 0.12);
            border: 1px solid rgba(139, 92, 246, 0.35);
            border-radius: 10px;
            padding: 12px;
            margin-top: 10px;
            color: #e2e8f0;
        }
        .actions {
            margin-top: 18px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        a {
            text-decoration: none;
            padding: 10px 14px;
            border-radius: 10px;
            color: #fff;
            font-weight: 700;
        }
        .btn-primary { background: linear-gradient(135deg, #ec4899, #8b5cf6); }
        .btn-muted { background: #334155; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Access Pending</h1>
        <p>Your account is logged in but is not authorised to open the full dashboard yet.</p>
        <p>If you are a newly created user, ask an owner/admin to run auth/whitelist for your Discord user ID.</p>
        <div class="note">Contact @misconsiderations to be authorised for panel access.</div>
        <div class="actions">
            <a class="btn-primary" href="/logout">Log Out</a>
            <a class="btn-muted" href="/home">Back to Home</a>
        </div>
    </div>
</body>
</html>"""

    def _render_login(self, error: str = "", next_path: str = "/dashboard", mode: str = "login") -> str:
        safe_next = next_path if isinstance(next_path, str) and next_path.startswith("/") else "/dashboard"
        error_html = (
            f"<p style='color:#fca5a5;margin:0 0 12px 0;font-size:14px;'>{error}</p>"
            if error
            else ""
        )
        
        is_register = mode == "register"
        title = "Create Account" if is_register else "Sign In"
        subtitle = "Join Aria Dashboard" if is_register else "Access your bot dashboard"
        button_text = "Create Account" if is_register else "Sign In"
        toggle_text = "Sign In" if is_register else "Create Account"
        toggle_link = "/login?mode=login" if is_register else "/login?mode=register"
        
        bot_token_field = (
            '<input type="password" name="bot_token" placeholder="Bot Token (optional)" autocomplete="off" />'
            if is_register else ""
        )
        
        username_field = (
            '<input type="text" name="username" placeholder="Username" autocomplete="username" required />'
            if is_register else ""
        )
        
        toggle_text_prefix = "" if is_register else "Don't have an account? "
        
        html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Aria Dashboard - {title}</title>
  <style>
    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }}
    :root {{
      color-scheme: dark;
    }}
    body {{
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      color: #e5e7eb;
    }}
    .container {{
      display: flex;
      gap: 40px;
      width: min(900px, calc(100vw - 32px));
      align-items: center;
    }}
    .branding {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }}
    .logo {{
      font-size: 48px;
      font-weight: 800;
      background: linear-gradient(135deg, #ec4899, #8b5cf6);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .features {{
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .feature {{
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }}
    .check {{
      color: #10b981;
      margin-top: 2px;
    }}
    .card {{
      flex: 0 0 380px;
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 16px;
      padding: 32px;
      box-shadow: 0 20px 60px rgba(2, 6, 23, 0.6);
      backdrop-filter: blur(10px);
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      background: linear-gradient(135deg, #ec4899, #8b5cf6);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .subtitle {{
      margin: 0 0 24px;
      color: #94a3b8;
      font-size: 14px;
    }}
    input {{
      width: 100%;
      margin: 0 0 14px;
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid #334155;
      background: #0b1220;
      color: #e5e7eb;
      font-size: 14px;
      transition: all 0.2s;
    }}
    input:focus {{
      border-color: #8b5cf6;
      outline: none;
      background: #0f172a;
      box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.1);
    }}
    button {{
      width: 100%;
      border: 0;
      border-radius: 10px;
      padding: 12px 14px;
      font-weight: 600;
      cursor: pointer;
      background: linear-gradient(135deg, #ec4899, #8b5cf6);
      color: #fff;
      font-size: 15px;
      margin-top: 8px;
      transition: all 0.2s;
    }}
    button:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(139, 92, 246, 0.4);
    }}
    button:active {{
      transform: translateY(0);
    }}
    .toggle {{
      text-align: center;
      margin-top: 16px;
      font-size: 13px;
      color: #94a3b8;
    }}
    .toggle a {{
      color: #8b5cf6;
      text-decoration: none;
      font-weight: 600;
      transition: color 0.2s;
    }}
    .toggle a:hover {{
      color: #ec4899;
    }}
    .error {{
      color: #fca5a5;
      margin: 0 0 16px;
      font-size: 13px;
      padding: 10px 12px;
      background: rgba(252, 165, 165, 0.1);
      border-radius: 8px;
      border-left: 2px solid #fc8181;
    }}
    @media (max-width: 768px) {{
      .container {{
        flex-direction: column;
        gap: 24px;
      }}
      .branding {{
        display: none;
      }}
      .card {{
        flex: 1;
        width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="branding">
      <div class="logo">ARIA</div>
      <div class="features">
        <div class="feature">
          <span class="check">✓</span>
          <span>Advanced RPC & activity control</span>
        </div>
        <div class="feature">
          <span class="check">✓</span>
          <span>Multi-user dashboard access</span>
        </div>
        <div class="feature">
          <span class="check">✓</span>
          <span>Real-time bot analytics</span>
        </div>
        <div class="feature">
          <span class="check">✓</span>
          <span>Premium bot features</span>
        </div>
      </div>
    </div>
    
    <form class="card" method="post" action="/login?mode={mode}">
      <h1>{title}</h1>
      <p class="subtitle">{subtitle}</p>
      {error_html if error_html else '<div style="height: 6px;"></div>'}
      
      <input type="text" name="user_id" placeholder="User ID" autocomplete="username" required />
      {bot_token_field}
      {username_field}
      <input type="password" name="password" placeholder="Password" autocomplete="current-password" required />
      <input type="hidden" name="next" value="{safe_next}" />
      
      <button type="submit">{button_text}</button>
      
      <div class="toggle">
        {toggle_text_prefix}<a href="{toggle_link}">{toggle_text}</a>
      </div>
    </form>
  </div>
</body>
</html>
"""
        return html

    def run(self) -> None:
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return True
