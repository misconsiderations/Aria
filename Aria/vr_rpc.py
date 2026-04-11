try:
    import discord
    from discord.gateway import DiscordWebSocket
    DISCORD_AVAILABLE = True
    DISCORD_IMPORT_ERROR = None
except Exception as exc:
    discord = None
    DiscordWebSocket = None
    DISCORD_AVAILABLE = False
    DISCORD_IMPORT_ERROR = exc

import datetime
import logging
import asyncio
import threading
import traceback
import time
import importlib
import json


class _RawAuthorizationToken:
    def __init__(self, token):
        self.token = token

    def __radd__(self, other):
        if other == "Bot ":
            return self.token
        return f"{other}{self.token}"

    def __str__(self):
        return self.token

# Suppress discord.py logging spam
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.WARNING)
discord_logger.addHandler(logging.NullHandler())

class VRRPC:
    _identify_patched = False
    _original_identify = None
    _startup_timeout_seconds = 90
    _disconnect_timeout_seconds = 45

    def __init__(self, config):
        self.config = config
        self.client = None
        self.thread = None
        self.supervisor_thread = None
        self.running = False
        self.start_time = datetime.datetime.now(datetime.timezone.utc)
        self.vr_mode = True
        self._desired_running = False
        self._stop_requested = False
        self._last_start_args = None
        self._restart_attempts = 0
        self._last_launch_time = None
        self._last_ready_time = None
        self._last_disconnect_time = None
        self._gateway_connected = False
        self._restart_lock = threading.Lock()
        self._restart_in_progress = False
        self._patch_discord()

    def _mark_gateway_connected(self):
        now = time.time()
        self._gateway_connected = True
        self._last_ready_time = now
        self._last_disconnect_time = None
        self.running = True

    def _mark_gateway_disconnected(self):
        if not self._last_disconnect_time:
            self._last_disconnect_time = time.time()
        self._gateway_connected = False
        self.running = False

    def _close_client(self, timeout=10):
        if not self.client:
            return True

        try:
            connection = getattr(self.client, "_connection", None)
            loop = getattr(connection, "loop", None)
            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self.client.close(), loop)
                future.result(timeout=timeout)
            else:
                asyncio.run(self.client.close())
        except Exception as e:
            print(f"[VR RPC] Warning: client close failed: {e}")
            return False

        return True

    def _restart_client(self, reason):
        if not self._last_start_args or self._stop_requested or not self._desired_running:
            return False

        with self._restart_lock:
            if self._restart_in_progress:
                return False

            self._restart_in_progress = True
            try:
                # Generalize VR config for all users
                self.config = self._load_vr_config()
                self._close_client()
                self._start_client()
            finally:
                self._restart_in_progress = False

    def _load_vr_config(self):
        """Load VR configuration dynamically for hosted users."""
        try:
            with open("vr_config.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"default": "config"}

    def _check_client_health(self):
        if not self._desired_running or self._stop_requested or not self._last_start_args:
            return False, None

        thread_alive = bool(self.thread and self.thread.is_alive())
        if not thread_alive:
            return True, "client thread exited"

        now = time.time()
        if not self._gateway_connected:
            never_connected_since_launch = not self._last_ready_time or (
                self._last_launch_time and self._last_ready_time < self._last_launch_time
            )
            if never_connected_since_launch and self._last_launch_time and now - self._last_launch_time >= self._startup_timeout_seconds:
                return True, "startup timed out waiting for gateway READY"
            if self._last_disconnect_time and now - self._last_disconnect_time >= self._disconnect_timeout_seconds:
                return True, "gateway disconnect exceeded recovery window"

        return False, None

    def _build_activity(self, rpc_name, details, state, large_image, icon_only):
        activity_name = "🥽 In VR" if icon_only else rpc_name
        activity_details = "" if icon_only else (details or "Meta Quest 3")
        activity_state = "🎮 Meta Quest" if not state or state == "Meta Quest" else state

        activity_kwargs = {
            "type": discord.ActivityType.playing,
            "name": activity_name,
            "state": activity_state,
            "details": activity_details,
        }

        if large_image:
            activity_kwargs["assets"] = {
                "large_image": large_image,
                "large_text": "Meta Quest 3 VR",
            }

        try:
            app_id = int(self.config.get('application_id', '0'))
        except Exception:
            app_id = 0
            print(f"[VR RPC] Warning: invalid application_id, using 0")

        if app_id:
            activity_kwargs["application_id"] = app_id

        return discord.Activity(**activity_kwargs)

    def _mode_text(self, rpc_name, details, icon_only):
        return "Icon Only" if icon_only else f"{rpc_name} | {details}"

    def _build_client(self, auth_mode, rpc_name, details, state, large_image, icon_only):
        outer = self

        class VRClient(discord.Client):
            def __init__(self, parent, config, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.parent = parent
                self.config = config
                self.ready_logged = False

            async def login(self, token):
                if getattr(self.http, "_vrrpc_auth_mode", "bot") != "user":
                    return await super().login(token)

                from discord.client import _loop
                from discord.user import ClientUser

                logging.getLogger("discord.client").info("logging in using static token")

                if self.loop is _loop:
                    await self._async_setup_hook()

                if not isinstance(token, str):
                    raise TypeError(f"expected token to be a str, received {token.__class__.__name__} instead")

                token = token.strip()
                data = await self.http.static_login(token)
                self._connection.user = ClientUser(state=self._connection, data=data)
                await self.setup_hook()

            async def setup_hook(self):
                if hasattr(self, "_connection"):
                    setattr(self._connection, "_is_vr_rpc_client", True)
                if hasattr(self, "http"):
                    setattr(self.http, "_is_vr_rpc_client", True)
                    setattr(self.http, "_vrrpc_auth_mode", auth_mode)

            async def _apply_vr_presence(self, announce=False):
                if not self.user:
                    return

                activity = outer._build_activity(rpc_name, details, state, large_image, icon_only)
                await self.change_presence(activity=activity, status=discord.Status.online)

                if announce:
                    mode_text = outer._mode_text(rpc_name, details, icon_only)
                    print(f"[VR RPC] ✓ Presence Updated: {mode_text}")
                    print(f"[VR RPC] ✓ VR Client Status: Active")

            async def on_ready(self):
                try:
                    if not self.ready_logged:
                        print(f"[VR RPC] ✓ Connected to Discord as {self.user}")
                        print(f"[VR RPC] ✓ Identified as VR Meta Quest Client")
                        self.ready_logged = True

                    await self._apply_vr_presence(announce=True)
                    outer._mark_gateway_connected()
                    outer._restart_attempts = 0
                except Exception as e:
                    print(f"[VR RPC] ✗ Error setting activity: {e}")
                    traceback.print_exc()

            async def on_resumed(self):
                try:
                    print("[VR RPC] ✓ Session resumed")
                    await self._apply_vr_presence(announce=True)
                    outer._mark_gateway_connected()
                except Exception as e:
                    print(f"[VR RPC] ✗ Error restoring activity after resume: {e}")
                    traceback.print_exc()

            async def on_disconnect(self):
                outer._mark_gateway_disconnected()
                self.ready_logged = False
                print("[VR RPC] Disconnected from Discord gateway")

            async def on_error(self, event, *args, **kwargs):
                print(f"[VR RPC] Error in event {event}")
                traceback.print_exc()

        intents = discord.Intents.default()
        intents.presences = True

        client = VRClient(self, self.config, intents=intents)
        setattr(client.http, "_is_vr_rpc_client", True)
        setattr(client.http, "_vrrpc_auth_mode", auth_mode)
        original_request = client.http.request

        async def request_vr(route, *, files=None, form=None, **kwargs):
            original_user_agent = client.http.user_agent
            original_token = client.http.token
            client.http.user_agent = (
                "Mozilla/5.0 (Linux; Android 14; Meta Quest 3) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            )
            if auth_mode == "user" and original_token is not None and not isinstance(original_token, _RawAuthorizationToken):
                client.http.token = _RawAuthorizationToken(str(original_token))
            try:
                return await original_request(route, files=files, form=form, **kwargs)
            finally:
                client.http.user_agent = original_user_agent
                client.http.token = original_token

        client.http.request = request_vr
        return client

    def _ensure_supervisor(self):
        if self.supervisor_thread and self.supervisor_thread.is_alive():
            return

        def supervise():
            while self._desired_running and not self._stop_requested:
                restart_needed, reason = self._check_client_health()
                if restart_needed:
                    self._restart_attempts += 1
                    wait_time = min(60, 5 * self._restart_attempts)
                    print(f"[VR RPC] Recovery scheduled in {wait_time}s (attempt {self._restart_attempts}): {reason}")
                    if self._stop_requested or not self._desired_running:
                        break
                    self._wait_with_cancel(wait_time)
                    if self._stop_requested or not self._desired_running:
                        break
                    restarted = self._restart_client(reason)
                    if not restarted:
                        self._wait_with_cancel(5)
                self._wait_with_cancel(5)

        self.supervisor_thread = threading.Thread(target=supervise, daemon=True, name="VRRPCSupervisor")
        self.supervisor_thread.start()

    def _wait_with_cancel(self, seconds):
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self._stop_requested or not self._desired_running:
                break
            time.sleep(0.5)

    def _launch_client_thread(self, token, auth_mode, rpc_name, details, state, large_image, icon_only):
        self.client = self._build_client(auth_mode, rpc_name, details, state, large_image, icon_only)
        self.running = True
        self._gateway_connected = False
        self._last_launch_time = time.time()
        self._last_ready_time = None
        self._last_disconnect_time = None

        def run_client():
            try:
                print(f"[VR RPC] Thread starting, running client.run()...")
                self.client.run(token)
                if not self._stop_requested and self._desired_running:
                    print("[VR RPC] Client thread exited unexpectedly")
            except discord.errors.LoginFailure:
                print(f"[VR RPC] ✗ Authentication failed: Invalid Discord token")
                self._desired_running = False
                self._mark_gateway_disconnected()
            except Exception as e:
                print(f"[VR RPC] ✗ Client error: {e}")
                traceback.print_exc()
                self._mark_gateway_disconnected()
            finally:
                self.running = False
                self._gateway_connected = False

        self.thread = threading.Thread(target=run_client, daemon=True, name="VRRPCClient")
        self.thread.start()

    def _detect_auth_mode(self, token):
        token = (token or "").strip()
        if not token:
            return "bot"

        try:
            from curl_cffi import requests

            raw_response = requests.get(
                "https://discord.com/api/v9/users/@me",
                headers={"Authorization": token},
                timeout=15,
            )
            if raw_response.status_code == 200:
                return "user"

            bot_response = requests.get(
                "https://discord.com/api/v9/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=15,
            )
            if bot_response.status_code == 200:
                return "bot"
        except Exception as exc:
            print(f"[VR RPC] Warning: auth mode detection failed: {exc}")

        return "bot"
    
    def _patch_discord(self):
        """Patch DiscordWebSocket.identify to send VR Meta Quest properties"""
        if not DISCORD_AVAILABLE:
            return

        try:
            from discord import http

            if http.HTTPClient.request.__module__ != "discord.http":
                importlib.reload(http)
        except Exception as e:
            print(f"[VR RPC] Warning: Could not restore HTTP client: {e}")

        # Patch only once globally and gate behavior to VRRPC clients.
        if not VRRPC._identify_patched:
            VRRPC._original_identify = DiscordWebSocket.identify

            async def identify_vr(ws):
                conn = getattr(ws, "_connection", None)
                is_vr_client = getattr(conn, "_is_vr_rpc_client", False)
                if not is_vr_client:
                    return await VRRPC._original_identify(ws)

                payload = {
                    "op": 2,
                    "d": {
                        "token": ws.token,
                        "capabilities": 16381,
                        "properties": {
                            "os": "Meta Quest",
                            "browser": "Discord VR",
                            "device": "Meta Quest 3",
                            "system_locale": "en-US",
                            "browser_version": "Discord VR",
                            "os_version": "Meta Quest OS",
                            "referrer": "",
                            "referring_domain": "",
                            "release_channel": "stable",
                            "client_build_number": 32765,
                            "client_event_source": None,
                        },
                        "compress": True,
                        "large_threshold": 250,
                        "intents": 1 << 0 | 1 << 1 | 1 << 8 | 1 << 9,
                    },
                }
                await ws.send_as_json(payload)

            DiscordWebSocket.identify = identify_vr
            VRRPC._identify_patched = True
    
    def start(self, token, rpc_name="VR", details="In VR", state="Meta Quest", large_image="", icon_only=False):
        """Start VR RPC with the provided settings"""
        if not DISCORD_AVAILABLE:
            return False, f"discord.py import failed: {DISCORD_IMPORT_ERROR}"

        if self.running or (self.thread and self.thread.is_alive()):
            return False, "VR RPC already running"
        
        try:
            app_id_str = self.config.get('application_id', '0')
            print(f"[VR RPC] Starting with app_id: {app_id_str}, icon_only={icon_only}")
            auth_mode = self._detect_auth_mode(token)
            print(f"[VR RPC] Auth mode detected: {auth_mode}")
            
            # Validate token before attempting to start
            if not token or token == "YOUR_BOT_TOKEN":
                self.running = False
                return False, "Invalid or missing Discord bot token"

            self._desired_running = True
            self._stop_requested = False
            self._restart_attempts = 0
            self.start_time = datetime.datetime.now(datetime.timezone.utc)
            self._last_start_args = (token, auth_mode, rpc_name, details, state, large_image, icon_only)
            self._launch_client_thread(*self._last_start_args)
            self._ensure_supervisor()
            
            mode = "Icon only" if icon_only else f"{rpc_name} | {details}"
            print(f"[VR RPC] ✓ Started: {mode} (waiting for client to connect...)")
            return True, f"VR RPC started: {mode}"
        except Exception as e:
            self.running = False
            print(f"[VR RPC] ✗ Init error: {e}")
            traceback.print_exc()
            return False, f"Failed to start VR RPC: {str(e)}"
    
    def stop(self):
        """Stop VR RPC"""
        if not self._desired_running and not self.running and not (self.thread and self.thread.is_alive()):
            return False, "VR RPC not running"
        
        try:
            self._desired_running = False
            self._stop_requested = True
            self._mark_gateway_disconnected()
            self._close_client(timeout=10)

            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=10)

            self.running = False
            self.client = None
            self.thread = None
            self._last_launch_time = None
            print(f"[VR RPC] Stopped")
            return True, "VR RPC stopped"
        except Exception as e:
            print(f"[VR RPC] Stop error: {e}")
            return False, f"Error stopping VR RPC: {str(e)}"
    
    def is_running(self):
        """Check if VR RPC is running"""
        return self._desired_running or self.running or bool(self.thread and self.thread.is_alive())
    
    async def update_presence(self, rpc_name="VR", details="In VR", state="Meta Quest", large_image="", icon_only=False):
        """Update VR presence while running"""
        if not DISCORD_AVAILABLE:
            return False, f"discord.py import failed: {DISCORD_IMPORT_ERROR}"

        if not self.client or not self.running or not self.client.user:
            return False, "VR RPC not active"
        
        try:
            activity_name = "🥽 In VR" if icon_only else rpc_name
            activity_details = "" if icon_only else (details or "Meta Quest 3")
            activity_state = "🎮 Meta Quest" if not state or state == "Meta Quest" else state
            
            activity_kwargs = {
                "type": discord.ActivityType.playing,
                "name": activity_name,
                "state": activity_state,
                "details": activity_details,
            }
            
            if large_image:
                activity_kwargs["assets"] = {
                    "large_image": large_image,
                    "large_text": "Meta Quest 3 VR",
                }
            
            activity = discord.Activity(**activity_kwargs)
            await self.client.change_presence(activity=activity, status=discord.Status.online)
            
            mode_text = "Icon Only" if icon_only else f"{rpc_name} | {details}"
            print(f"[VR RPC] ✓ Presence Updated: {mode_text}")
            return True, f"Presence updated: {mode_text}"
        except Exception as e:
            print(f"[VR RPC] ✗ Error updating presence: {e}")
            return False, f"Error updating presence: {str(e)}"
    
    def get_vr_status(self):
        """Get detailed VR RPC status information"""
        if not self.running:
            return {
                "status": "INACTIVE",
                "client_type": "VR Meta Quest",
                "running": False,
                "user": None
            }
        
        return {
            "status": "ACTIVE",
            "client_type": "VR Meta Quest 3",
            "running": True,
            "user": str(self.client.user) if self.client and self.client.user else "Connecting...",
            "uptime": str(datetime.datetime.now(datetime.timezone.utc) - self.start_time)
        }
