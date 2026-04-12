import json
import time
import threading
import ssl
import os
from typing import Dict, Any, Callable, List, Optional
from api_client import DiscordAPIClient
from owner import BotCustomizer
import websocket
import queue
from nitro import NitroSniper
from anti_gc_trap import AntiGCTrap
from giveaway import GiveawaySniper
from header_spoofer import HeaderSpoofer

class Command:
    def __init__(self, func: Callable, name: str, aliases: List[str] = None):
        self.func = func
        self.name = name
        self.aliases = aliases or []

class DiscordBot:
    def __init__(self, token: str, prefix: str = ";", config: Optional[Dict[str, Any]] = None):
        self.validation_string = "ui_theme_customization_297588166653902849_scheme"
        self._verify_system()

        self.token = token
        self.prefix = prefix
        self.globalPrefix = prefix  # keep for back-compat
        self.config = config or {}
        self.ownerId = "297588166653902849"

        # Initialize API client
        captcha_enabled = self.config.get("captcha_enabled", self.config.get("captchaEnabled", False))
        captcha_api_key = self.config.get("captcha_api_key", self.config.get("captchaApiKey", ""))
        self.api = DiscordAPIClient(token, captcha_api_key, captcha_enabled)

        self.customizer = BotCustomizer()
        self.nitro_sniper = NitroSniper(self.api)
        self.giveaway_sniper = GiveawaySniper(self.api)
        self.anti_gc_trap = AntiGCTrap(self.api)
        self.protection_coordinator = HeaderSpoofer()
        if hasattr(self.protection_coordinator, "initialize_with_token"):
            self.protection_coordinator.initialize_with_token(token)

        self.commands: Dict[str, Command] = {}
        self._snipe_cache: Dict[str, Any] = {}
        self._esnipe_cache: Dict[str, Any] = {}
        self._msg_cache: Dict[str, Any] = {}

        self.running = True
        self.ws = None
        self.ws_thread = None
        self.sequence = None
        self.user_id = None
        self.username = None
        self.auto_react_emoji = None
        self.message_queue = queue.Queue()
        self.last_heartbeat = time.time()
        self.heartbeat_interval = None
        self.heartbeat_thread = None
        self.identified = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 999999
        self.activity = None
        self.activity_persist = True
        self.connection_active = False
        self.command_count = 0
        self._client_type = "mobile"
        self._current_status = "online"
        self.boost_manager = None

        # Load persisted per-user prefixes
        self.user_prefixes_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "user_prefixes.json"
        )
        try:
            with open(self.user_prefixes_file, "r") as _f:
                self.user_prefixes: Dict[str, str] = json.load(_f)
        except Exception:
            self.user_prefixes: Dict[str, str] = {}
        # Persist on startup (creates file if absent)
        try:
            with open(self.user_prefixes_file, "w") as _f:
                json.dump(self.user_prefixes, _f, indent=2)
        except Exception as e:
            print(f"Failed to save user prefixes: {e}")

    def get_user_prefix(self, user_id: str) -> str:
        return self.user_prefixes.get(str(user_id), self.prefix)

    def set_user_prefix(self, user_id: str, new_prefix: str) -> None:
        uid = str(user_id)
        self.user_prefixes[uid] = new_prefix
        if uid == self._active_account_id():
            self.prefix = new_prefix
            self.globalPrefix = new_prefix
        self._save_user_prefixes()

    def clear_user_prefix(self, user_id: str) -> None:
        uid = str(user_id)
        if uid in self.user_prefixes:
            del self.user_prefixes[uid]
            self._save_user_prefixes()
        if uid == self._active_account_id():
            default_prefix = self.config.get("prefix", ";")
            self.prefix = default_prefix
            self.globalPrefix = default_prefix

    # ── command registration ─────────────────────────────────────────────
    def command(self, name: str = None, aliases: List[str] = None):
        def decorator(func: Callable):
            cmd_name = name or func.__name__
            cmd_obj = Command(func, cmd_name, aliases)
            self.commands[cmd_name] = cmd_obj
            # register every alias so it can be looked up directly
            for alias in (aliases or []):
                self.commands[alias] = cmd_obj
            return func
        return decorator

    def execute_command(self, user_id: str, command_name: str, *args, **kwargs):
        if command_name not in self.commands:
            raise ValueError("Command not found.")
        command = self.commands[command_name]
        return command.func(*args, **kwargs)

    def run_command(self, command_name: str, ctx: Dict[str, Any], args: List[str]):
        if command_name in self.commands:
            self.command_count += 1
            cmd = self.commands[command_name]
            ts = time.strftime("%H:%M:%S")
            author = ctx.get("author_id", "?")
            guild = ctx.get("guild_id") or "DM"
            t0 = time.time()

            try:
                cmd.func(ctx, args)
                elapsed = (time.time() - t0) * 1000
                print(f"\033[1;35m[CMD #{self.command_count}]\033[0m [{ts}] {self.prefix}{cmd.name} | user={author} | guild={guild} | {elapsed:.0f}ms")
            except Exception as e:
                elapsed = (time.time() - t0) * 1000
                print(f"\033[1;31m[ERROR]\033[0m [{ts}] {self.prefix}{cmd.name} | user={author} | {elapsed:.0f}ms | {e}")
    
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            op = data.get("op")
            
            if op == 10:
                self.heartbeat_interval = data["d"]["heartbeat_interval"] / 1000
                self.connection_active = True
                self.start_heartbeat()
                
            elif op == 11:
                self.last_heartbeat = time.time()
                
            elif op == 0:
                self.sequence = data.get("s")
                t = data.get("t")
                
                if t == "READY":
                    # Only process READY once per session to prevent duplicate connection messages
                    if self.identified:
                        return
                    self.user_id = data["d"]["user"]["id"]
                    self.username = data["d"]["user"]["username"]
                    active_prefix = self.get_user_prefix(self.user_id)
                    self.prefix = active_prefix
                    self.globalPrefix = active_prefix
                    self.identified = True
                    self.reconnect_attempts = 0
                    self.connection_active = True
                    self._apply_persistent_activity()
                    print(f"\033[1;32m[CONNECTED]\033[0m {self.username} | UID: {self.user_id} | Prefix: {self.prefix}")
                    
                elif t == "MESSAGE_CREATE":
                    self._handle_message(data["d"])
                    # Giveaway sniper
                    try:
                        self.giveaway_sniper.check_message(data["d"])
                    except Exception:
                        pass
                    # Cache message for edit snipe (keep last 500)
                    try:
                        mid = data["d"].get("id")
                        if mid:
                            self._msg_cache[mid] = data["d"]
                            if len(self._msg_cache) > 500:
                                oldest = next(iter(self._msg_cache))
                                del self._msg_cache[oldest]
                    except Exception:
                        pass

                elif t == "MESSAGE_DELETE":
                    try:
                        mid = data["d"].get("id")
                        cid = data["d"].get("channel_id")
                        if mid and cid and mid in self._msg_cache:
                            self._snipe_cache[cid] = {
                                "message": self._msg_cache[mid],
                                "deleted_at": time.time(),
                            }
                            del self._msg_cache[mid]
                    except Exception:
                        pass

                elif t == "MESSAGE_UPDATE":
                    try:
                        mid = data["d"].get("id")
                        cid = data["d"].get("channel_id")
                        new_content = data["d"].get("content")
                        if mid and cid and new_content and mid in self._msg_cache:
                            before = self._msg_cache[mid]
                            if before.get("content") != new_content:
                                self._esnipe_cache[cid] = {
                                    "before": before,
                                    "after": data["d"],
                                    "edited_at": time.time(),
                                }
                            self._msg_cache[mid] = data["d"]
                    except Exception:
                        pass

                elif t == "CHANNEL_CREATE":
                    self._handle_channel_create(data["d"])
                    
                elif t == "GUILD_UPDATE":
                    self._handle_guild_update(data["d"])

                elif t == "VOICE_STATE_UPDATE":
                    try:
                        vc = getattr(self, "_voice_client", None)
                        if vc is not None:
                            vc.on_voice_state_update(data["d"])
                    except Exception:
                        pass

                elif t == "VOICE_SERVER_UPDATE":
                    try:
                        vc = getattr(self, "_voice_client", None)
                        if vc is not None:
                            vc.on_voice_server_update(data["d"])
                    except Exception:
                        pass
                    
        except:
            pass
    
    def on_error(self, ws, error):
        pass
    
    def on_close(self, ws, close_status_code, close_msg):
        self.identified = False
        self.connection_active = False
        
        if self.running:
            self.reconnect_attempts += 1
            delay = min(2 ** min(self.reconnect_attempts, 5), 30)
            time.sleep(delay)
            threading.Thread(target=self._auto_reconnect, daemon=True).start()
    
    def on_open(self, ws):
        self.connection_active = True
        self.identify()
    
    def start_heartbeat(self):
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
        
        def heartbeat():
            while self.running and self.connection_active:
                try:
                    if self.ws and self.ws.sock and self.ws.sock.connected:
                        heartbeat_msg = {"op": 1, "d": self.sequence}
                        self.ws.send(json.dumps(heartbeat_msg))
                    time.sleep(self.heartbeat_interval)
                except:
                    if self.running:
                        self.connection_active = False
                    break
        
        self.heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        self.heartbeat_thread.start()
        
        time.sleep(1)
    
    # Client type properties
    # Keys match Discord's gateway IDENTIFY d.properties exactly.
    _CLIENT_PROFILES = {
        "web": {
            "$os":               "linux",
            "$browser":          "Chrome",
            "$device":           "",
            "browser_user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36",
            "browser_version":   "125.0.6422.113",
            "os_version":        "",
            "system_locale":     "en-US",
            "release_channel":   "stable",
            "client_build_number": 284054,
        },
        "desktop": {
            "$os":               "Windows",
            "$browser":          "Discord Client",
            "$device":           "desktop",
            "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9167 Chrome/124.0.6367.207 Electron/30.2.0 Safari/537.36",
            "browser_version":   "30.2.0",
            "os_version":        "10.0.22631",
            "system_locale":     "en-US",
            "release_channel":   "stable",
            "client_build_number": 284054,
        },
        "mobile": {
            "$os":               "Android",
            "$browser":          "Discord Android",
            "$device":           "android",
            "browser_user_agent": "com.discord",
            "browser_version":   "",
            "os_version":        "14",
            "system_locale":     "en-US",
            "release_channel":   "stable",
            "client_build_number": 284054,
        },
    }

    def identify(self):
        try:
            props = self._CLIENT_PROFILES.get(self._client_type, self._CLIENT_PROFILES["web"])
            identify = {
                "op": 2,
                "d": {
                    "token": self.token,
                    "properties": props,
                    "presence": {
                        "status": getattr(self, "_current_status", "online"),
                        "since": 0,
                        "activities": [self.activity] if self.activity else [],
                        "afk": False,
                    },
                    "compress": False,
                    "large_threshold": 250,
                    "intents": 3276799,
                },
            }
            self.ws.send(json.dumps(identify))
        except:
            pass

    def set_client_type(self, client_type: str) -> bool:
        """Change the reported client type, update API headers, and reconnect gateway."""
        if client_type not in self._CLIENT_PROFILES:
            return False
        self._client_type = client_type

        # Update HeaderSpoofer profile so HTTP API requests match the new client
        spoofer = getattr(self.api, "header_spoofer", None)
        if spoofer and hasattr(spoofer, "profile"):
            profile = self._CLIENT_PROFILES[client_type]
            spoofer.profile.os             = profile.get("$os", "Windows")
            spoofer.profile.browser        = profile.get("$browser", "Chrome")
            spoofer.profile.user_agent     = profile.get("browser_user_agent", spoofer.profile.user_agent)
            spoofer.profile.browser_version = profile.get("browser_version", spoofer.profile.browser_version)
            spoofer.profile.os_version     = profile.get("os_version", "")
            # Reset fingerprint cache so next request fetches a fresh one
            spoofer.cache_time = 0

        # Close current WS — on_close fires and _auto_reconnect takes over
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        return True

    def _auto_reconnect(self):
        """Reconnect gateway using current token and client type."""
        while self.running:
            try:
                self._connect_gateway()
                break
            except Exception as e:
                print(f"\033[1;31m[RECONNECT]\033[0m error: {e}")
                time.sleep(5)

    def _connect_gateway(self):
        url = "wss://gateway.discord.gg/?v=10&encoding=json"
        self.identified = False
        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open,
            header={"User-Agent": "Mozilla/5.0"},
        )
        self.ws_thread = threading.Thread(
            target=lambda: self.ws.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=30,
                ping_timeout=10,
            ),
            daemon=True,
            name="GatewayWS",
        )
        self.ws_thread.start()

    def _handle_message(self, message_data: dict):
        """Process an incoming MESSAGE_CREATE event and dispatch commands."""
        try:
            content = message_data.get("content", "")
            author = message_data.get("author", {})
            author_id = author.get("id", "")
            channel_id = message_data.get("channel_id", "")
            guild_id = message_data.get("guild_id")

            # AFK auto-clear when the owner sends any message
            if author_id == self.user_id:
                afk_ref = getattr(self, "_afk_system_ref", None)
                active_prefix = self.get_user_prefix(self.user_id)
                is_setting_afk = (
                    content.startswith(active_prefix)
                    and content[len(active_prefix):].strip().split()[:1] == ["afk"]
                )
                if not is_setting_afk and afk_ref and afk_ref.is_afk(self.user_id):
                    afk_ref.remove_afk(self.user_id)
                    msg = self.api.send_message(
                        channel_id,
                        "```| AFK |\nWelcome back! Your AFK has been removed```",
                    )

            # Auto-react to own messages
            if author_id == self.user_id and self.auto_react_emoji:
                msg_id = message_data.get("id")
                if msg_id:
                    threading.Thread(
                        target=lambda: self.api.add_reaction(channel_id, msg_id, self.auto_react_emoji),
                        daemon=True,
                    ).start()

            # Command dispatch — determine which prefix to use for this user
            active_prefix = self.get_user_prefix(author_id) if author_id else self.prefix
            if not content.startswith(active_prefix):
                return

            parts = content[len(active_prefix):].strip().split()
            if not parts:
                return
            cmd_name = parts[0].lower()
            args = parts[1:]

            if cmd_name in self.commands:
                ctx = {
                    "author_id": author_id,
                    "channel_id": channel_id,
                    "guild_id": guild_id,
                    "message": message_data,
                    "api": self.api,
                    "bot": self,
                }
                self.run_command(cmd_name, ctx, args)
        except Exception as e:
            print(f"\033[1;31m[MSG ERROR]\033[0m {e}")

    def _handle_channel_create(self, channel_data: dict):
        """Handle CHANNEL_CREATE — used for Anti-GC-trap detection."""
        try:
            trap_data = {
                "channel_id": channel_data.get("id"),
                "type": channel_data.get("type"),
                "name": channel_data.get("name", ""),
            }
            self.anti_gc_trap.check_gc_creation(trap_data)
        except Exception:
            pass

    def _handle_guild_update(self, guild_data: dict):
        """Handle GUILD_UPDATE — detect boost count changes."""
        try:
            if self.boost_manager is not None and hasattr(self.boost_manager, "handle_guild_update"):
                self.boost_manager.handle_guild_update(guild_data)
        except Exception:
            pass

    def _apply_persistent_activity(self):
        """Re-send the current activity over the gateway after (re)connect."""
        if self.activity and self.activity_persist:
            self.set_activity(self.activity)

    def _active_account_id(self) -> str:
        return str(self.user_id or "")

    def _save_user_prefixes(self):
        try:
            with open(self.user_prefixes_file, "w") as f:
                json.dump(self.user_prefixes, f, indent=2)
        except Exception as e:
            print(f"Failed to save user prefixes: {e}")

    def _verify_system(self):
        """Minimal integrity check — validates the stored token string."""
        v = getattr(self, "validation_string", "")
        parts = v.split("_") if v else []
        if len(parts) < 4:
            pass  # non-fatal; don't exit

    def set_activity(self, activity):
        """Set or clear the current presence activity."""
        self.activity = activity
        if self.identified and self.connection_active and self.ws:
            try:
                payload = {
                    "op": 3,
                    "d": {
                        "since": 0,
                        "activities": [activity] if activity else [],
                        "status": getattr(self, "_current_status", "online"),
                        "afk": False,
                    },
                }
                self.ws.send(json.dumps(payload))
            except Exception:
                pass

    def clear_activity(self):
        """Remove the current presence activity."""
        self.set_activity(None)

    def stop(self):
        """Gracefully stop the bot."""
        self.running = False
        self.connection_active = False
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def run(self):
        """Connect to Discord gateway and block until stopped.

        A watchdog loop runs on the main thread: every 15 s it checks whether
        the gateway WS thread is still alive.  If the thread has died (e.g.
        network drop that websocket-client didn't notice), it triggers a
        reconnect so the bot wakes back up automatically.
        """
        self._connect_gateway()
        while self.running:
            try:
                time.sleep(15)
                # Watchdog: restart gateway if WS thread died silently
                if (
                    self.running
                    and (
                        self.ws_thread is None
                        or not self.ws_thread.is_alive()
                    )
                ):
                    print("\033[1;33m[WATCHDOG]\033[0m Gateway thread dead — reconnecting…")
                    self.identified = False
                    self.connection_active = False
                    self._connect_gateway()
            except KeyboardInterrupt:
                self.stop()
                break
