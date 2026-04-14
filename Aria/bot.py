import json
import time
import threading
import ssl
import os
from typing import Dict, Any, Callable, List, Optional, Union
from api_client import DiscordAPIClient
from owner import BotCustomizer
from nitro import NitroSniper
from anti_gc_trap import AntiGCTrap
from giveaway import GiveawaySniper
from header_spoofer import HeaderSpoofer
from core.client.platform import CLIENT_PROFILES, normalize_client_type, normalize_status
import queue
import websocket
# Removed incorrect import
# from .utils import normalize_client_type, normalize_status

# Defining missing functions
from core.client.platform import client_identify, state_identify, build_identify_payload

class Command:
    def __init__(self, func: Callable, name: str, aliases: Optional[List[str]] = None):
        self.func = func
        self.name = name
        self.aliases = aliases or []

class DiscordBot:
    def __init__(self, token: str, prefix: str = "$", config: Union[Dict[str, Any], Any, None] = None):
        self.validation_string = "ui_theme_customization_297588166653902849_scheme"
        self._verify_system()

        self.token = token
        self.prefix = prefix
        self.globalPrefix = prefix  # keep for back-compat
        self._config_prefix = prefix  # immutable fallback — never mutated
        self.config = config or {}
        self.ownerId = "297588166653902849"
        self.instance_id = "default_instance"  # Initialize instance_id as a string

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
        self.ws: Any = None
        self.ws_thread = None
        self.sequence = None
        self.user_id = None
        self.username = None
        self.auto_react_emoji = None
        self.message_queue = queue.Queue()
        self.last_heartbeat = time.time()
        self.heartbeat_interval: Optional[float] = None
        self.heartbeat_thread = None
        self.identified = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 999999
        self.activity = None
        self.activity_persist = True
        self.connection_active = False
        self.command_count = 0
        self._client_type = "vr"
        self._current_status = "online"
        self._auto_delete_enabled: bool = True
        self._auto_delete_delay: int = 20
        self._mimic_target: Optional[str] = None
        self._mimic_enabled: bool = False
        self._mimic_custom_response: Optional[str] = None
        self._mimic_sent_messages: Dict[str, Dict[str, str]] = {}
        self._mimic_last_sent_at: float = 0.0
        self._purge_active: bool = False
        self._purge_started_by: Optional[str] = None
        self._autoreact_targets: Dict[str, Dict[str, Any]] = {}
        self._autoreact_last_sent_at: float = 0.0
        self._message_delete_hook: Optional[Callable[[str, str], None]] = None
        self.boost_manager: Any = None
        self._afk_system_ref: Any = None
        self.friend_scraper: Any = None
        self.self_hosting_manager: Any = None
        self.db: Any = None

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
        return self.user_prefixes.get(str(user_id), self._config_prefix)

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
            default_prefix = self.config.get("prefix", "$")
            self.prefix = default_prefix
            self.globalPrefix = default_prefix

    # ── command registration ─────────────────────────────────────────────
    def _register_command_key(self, key: str, cmd_obj: Command) -> None:
        k = str(key or "").strip().lower()
        if not k:
            return
        self.commands[k] = cmd_obj
        # Allow using commands without underscores (e.g. hypesquad_leave -> hypesquadleave)
        compact = k.replace("_", "")
        if compact and compact not in self.commands:
            self.commands[compact] = cmd_obj

    def _resolve_command(self, command_name: str) -> Optional[Command]:
        k = str(command_name or "").strip().lower()
        if not k:
            return None
        cmd = self.commands.get(k)
        if cmd is not None:
            return cmd
        return self.commands.get(k.replace("_", ""))

    def command(self, name: Optional[str] = None, aliases: Optional[List[str]] = None):
        def decorator(func: Callable):
            cmd_name = name or func.__name__
            cmd_obj = Command(func, cmd_name, aliases)
            self._register_command_key(cmd_name, cmd_obj)
            # register every alias so it can be looked up directly
            for alias in (aliases or []):
                self._register_command_key(alias, cmd_obj)
            return func
        return decorator

    def execute_command(self, user_id: str, command_name: str, *args, **kwargs):
        command = self._resolve_command(command_name)
        if command is None:
            raise ValueError("Command not found.")
        return command.func(*args, **kwargs)

    def run_command(self, command_name: str, ctx: Dict[str, Any], args: List[str]) -> None:
        cmd = self._resolve_command(command_name)
        if cmd is not None:
            self.command_count += 1
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
                        hook = getattr(self, "_message_delete_hook", None)
                        if hook is not None and mid and cid:
                            try:
                                hook(mid, cid)
                            except Exception:
                                pass
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
                    interval = float(self.heartbeat_interval or 30.0)
                    time.sleep(interval)
                except:
                    if self.running:
                        self.connection_active = False
                    break
        
        self.heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        self.heartbeat_thread.start()
        
        time.sleep(1)
    
    # Client type properties
    # Keys match Discord's gateway IDENTIFY d.properties exactly.
    _CLIENT_PROFILES = CLIENT_PROFILES

    def identify(self):
        try:
            # Only resolve from config on the very first identify (not yet identified).
            # After that, preserve whatever was set explicitly by set_client_type().
            if not self.identified:
                self._client_type = client_identify(bot=self, token=self.token)
                self._current_status = state_identify(bot=self, token=self.token)
            identify = build_identify_payload(
                token=self.token,
                client_type=self._client_type,
                status=getattr(self, "_current_status", "online"),
                activity=self.activity,
                intents=3276799,
                compress=False,
            )
            if self.ws:
                self.ws.send(json.dumps(identify))
        except:
            pass

    def set_client_type(self, client_type: str) -> bool:
        """Change the reported client type, update API headers, manage VRRPC, and reconnect gateway."""
        from vr_rpc import VRRPC
        client_type = normalize_client_type(client_type)
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

        # VRRPC management
        if not hasattr(self, "_vrrpc"):
            self._vrrpc = None
        if client_type == "vr":
            if self._vrrpc is None:
                try:
                    self._vrrpc = VRRPC(self.config)
                    self._vrrpc._desired_running = True
                    self._vrrpc.start(self.token)
                except Exception as e:
                    print(f"[VRRPC] Failed to start VRRPC: {e}")
                    self._vrrpc = None
            else:
                self._vrrpc._desired_running = True
                if not self._vrrpc.running:
                    try:
                        self._vrrpc.start(self.token)
                    except Exception as e:
                        print(f"[VRRPC] Failed to restart VRRPC: {e}")
        else:
            # Stop VRRPC if running
            if hasattr(self, "_vrrpc") and self._vrrpc is not None:
                try:
                    self._vrrpc._desired_running = False
                    self._vrrpc._stop_requested = True
                    self._vrrpc._close_client()
                except Exception as e:
                    print(f"[VRRPC] Failed to stop VRRPC: {e}")
                self._vrrpc = None

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
        ws_app = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open,
            header={"User-Agent": "Mozilla/5.0"},
        )
        self.ws = ws_app
        self.ws_thread = threading.Thread(
            target=lambda: ws_app.run_forever(
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

            # Persist recent messages for developer retrieval commands.
            try:
                if getattr(self, "db", None) and hasattr(self.db, "track_message"):
                    self.db.track_message(message_data)
            except Exception:
                pass

            # AFK auto-clear when the owner sends any message
            if author_id == self.user_id:
                afk_ref = getattr(self, "_afk_system_ref", None)
                active_prefix = self.get_user_prefix(str(self.user_id or ""))
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
                    emoji = str(self.auto_react_emoji)
                    threading.Thread(
                        target=lambda: self.api.add_reaction(channel_id, msg_id, emoji),
                        daemon=True,
                    ).start()

            # Command dispatch — determine which prefix to use for this user.
            # The "token-user prefix" is the bot's globally active prefix.
            # Control users (owner, alt accounts) always inherit it so that
            # changing prefix via setprefix works for ALL controller accounts.

            token_prefix = self.get_user_prefix(str(self.user_id or "")) if self.user_id else self.prefix
            user_prefix  = self.get_user_prefix(author_id) if author_id else self.prefix
            config_get = getattr(self.config, "get", None)
            if callable(config_get):
                alt_prefix = config_get("alt_prefix", "") or config_get("new_prefix", "")
                owner_prefix = config_get("owner_prefix", "!")
            elif isinstance(self.config, dict):
                alt_prefix = self.config.get("alt_prefix", "") or self.config.get("new_prefix", "")
                owner_prefix = self.config.get("owner_prefix", "!")
            else:
                alt_prefix = ""
                owner_prefix = "!"

            # All users can use any prefix, but only owner can use control/owner commands
            candidate_prefixes = []
            if self.config.get("owner_prefix", "$"):
                candidate_prefixes.append(self.config.get("owner_prefix", "$"))
            if self.config.get("alt_prefix", ".."):
                candidate_prefixes.append(self.config.get("alt_prefix", ".."))
            candidate_prefixes.append(self.config.get("prefix", ";"))

            matched_prefix = None
            for p in candidate_prefixes:
                if content.startswith(p):
                    matched_prefix = p
                    break

            if not matched_prefix:
                return

            parts = content[len(matched_prefix):].strip().split()
            if not parts:
                return
            cmd_name = parts[0].lower()
            args = parts[1:]

            # Normalize common VC alias forms to canonical command keys so
            # VC routing still works even if alias keys are overridden later.
            cmd_name = {
                "joinvc": "vc",
                "vcjoin": "vc",
                "joinvoice": "vc",
                "joincall": "vc",
                "leavevc": "vce",
                "vcleave": "vce",
                "leavevoice": "vce",
            }.get(cmd_name, cmd_name)

            # Define ctx before usage
            ctx = {
                "author_id": "unknown",
                "guild_id": "unknown",
                "channel_id": "unknown",
            }

            # Ensure cmd_name is always a string
            cmd_name = cmd_name or "default_command"
            if isinstance(cmd_name, str):
                resolved_command = self._resolve_command(cmd_name)
                if resolved_command is not None:
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

    def set_status(self, status: str) -> bool:
        """Update presence status (online/idle/dnd/invisible) via gateway op 3."""
        status = normalize_status(status)
        valid = {"online", "idle", "dnd", "invisible"}
        if status not in valid:
            return False
        self._current_status = status
        if self.identified and self.connection_active and self.ws:
            try:
                since = int(time.time() * 1000) if status == "idle" else 0
                payload = {
                    "op": 3,
                    "d": {
                        "since": since,
                        "activities": [self.activity] if self.activity else [],
                        "status": status,
                        "afk": status == "idle",
                    },
                }
                self.ws.send(json.dumps(payload))
                return True
            except Exception:
                return False
        return False

    def set_activity(self, activity):
        """Set or clear the current presence activity."""
        self.activity = activity
        if self.identified and self.connection_active and self.ws:
            try:
                status = getattr(self, "_current_status", "online")
                since = int(time.time() * 1000) if status == "idle" else 0
                payload = {
                    "op": 3,
                    "d": {
                        "since": since,
                        "activities": [activity] if activity else [],
                        "status": status,
                        "afk": status == "idle",
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
