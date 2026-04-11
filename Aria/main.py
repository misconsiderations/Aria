import sys
import time
import random
import threading
import json
import re
import io
import os
from logger import setup_file_logger

setup_file_logger()

# Suppress "Exception ignored from cffi callback" noise from curl_cffi.
# These fire on Ctrl-C / shutdown when libcurl tries to write to a
# already-dying Python buffer; they cannot be caught with try/except.
class _CffiNoiseSuppressor:
    def __init__(self, real):
        self._real = real
        self._drop = 0
    def write(self, s):
        if "Exception ignored from cffi callback" in s:
            self._drop = 12  # absorb this line + full traceback block
            return
        if self._drop:
            self._drop -= 1
            return
        self._real.write(s)
    def flush(self):
        self._real.flush()
    def __getattr__(self, name):
        return getattr(self._real, name)

sys.stderr = _CffiNoiseSuppressor(sys.stderr)
import aiohttp
import base64
import asyncio
from bot import DiscordBot
from config import Config
from voice import SimpleVoice
from backup import BackupManager
from moderation import ModerationManager
from webpanel import WebPanel
from error_handler import error_guard
from data_engine import data_core
from notification import alert_system
from analytics import insight_tracker
from host import host_manager
from afk_system import afk_system
from anti_gc_trap import AntiGCTrap
from GitHub import GitHubUpdater
from superreact import SuperReactClient, super_react_client
from history_manager import HistoryManager
from account_data_manager import AccountDataManager
from badge_scraper import BadgeScraper
from format_bootstrap import install_global_formatter
from quest import QuestSystem
from developer import DeveloperTools

if os.environ.get('HOSTED_TOKEN') == 'true':
    HOSTED_MODE = True
else:
    HOSTED_MODE = False

def protected_main():
    error_guard.safe_execute(main)

def delete_after_delay(api, channel_id, message_id, delay=20):
    def delete():
        time.sleep(delay)
        api.delete_message(channel_id, message_id)
    threading.Thread(target=delete, daemon=True).start()

def delete_command_message(api, channel_id, message_id):
    try:
        api.delete_message(channel_id, message_id)
    except:
        pass

# Spotify spoofing ID pools — varied so repeated calls look different
_SPOTIFY_TRACKS = [
    "0VjIjW4GlUZAMYd2vXMi3b", "4iJyoBOLtHqaWYs3vyWF1a", "1r9xUipOqoNwggBpENDsvJ",
    "7qiZfU4dY1lWllzX7mPBI3", "0tgVpDi06FyKpA1z0VMD4v", "2takcwOaAZWiXQijPHIx7B",
    "3n3Ppam7vgaVa1iaRUIOKE", "4cOdK2wGLETKBW3PvgPWqT", "1lNuQWb9O3GBK1UhFTMPnP",
]
_SPOTIFY_ALBUMS = [
    "4yP0hdKOZPNshxUOjY0cZj", "0ETFjACtuP2ADo6LFhL6HN", "5ms2BpQWqHnOkx8RQIQW0S",
    "3T4tUhGYeRNVUGevb0wThu", "1RM6MGv6bcl6NvOHSCxfti", "4Gfnly5CzMJQqkUFoAi9h0",
]
_SPOTIFY_ARTISTS = [
    "1Xyo4u8uXC1ZmMpatF05PJ", "3TVXtAsR1Inumwj472S9r4", "1uNFoZAHBGtllmzznpCI3i",
    "06HL4z0CvFAxyc27GXpf02", "4oUHIQIBe0LHzYfvXNW4QM", "3fMbdgg4jU18AjLCKBhRSm",
]

_CDN_RE = re.compile(
    r"https?://(?:cdn\.discordapp\.com|media\.discordapp\.net)/attachments/(\d+)/(\d+)/([^?#]+)"
)
_CT_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/gif": "gif", "image/webp": "webp", "image/avif": "avif",
}

def upload_image_to_discord(api, image_url):
    """Upload an external image to Discord via DM and return an mp:attachments/ asset key."""
    try:
        m = _CDN_RE.search(image_url)
        if m:
            ch, att, fn = m.groups()
            return f"mp:attachments/{ch}/{att}/{fn}"

        response = api.session.get(image_url, timeout=15)
        if response.status_code != 200:
            return None

        image_bytes = response.content
        ct = response.headers.get("Content-Type", "").split(";")[0].strip()
        ct_ext = _CT_EXT.get(ct, "png")
        raw_name = image_url.split("/")[-1].split("?")[0]
        filename = raw_name if ("." in raw_name and len(raw_name) <= 50) else f"asset.{ct_ext}"

        dm = api.create_dm(api.user_id)
        if not dm or "id" not in dm:
            return None

        files = {"file": (filename, image_bytes, ct or "application/octet-stream")}
        headers = api.header_spoofer.get_protected_headers(api.token)

        upload_response = api.session.post(
            f"https://discord.com/api/v9/channels/{dm['id']}/messages",
            headers=headers,
            files=files,
            timeout=20,
        )

        if upload_response.status_code == 200:
            message_data = upload_response.json()
            attachments = message_data.get("attachments", [])
            if attachments:
                m2 = _CDN_RE.search(attachments[0]["url"])
                if m2:
                    ch, att, fn = m2.groups()
                    try:
                        api.delete_message(dm["id"], message_data["id"])
                    except Exception:
                        pass
                    return f"mp:attachments/{ch}/{att}/{fn}"

        return None
    except Exception as e:
        print(f"[upload_image] error: {e}")
        return None

def upload_n_get_asset_key(bot, image_url):
    """Return an mp:attachments/ key for any image URL (CDN fast-path or upload)."""
    return upload_image_to_discord(bot.api, image_url)

def send_spotify_with_spoofing(bot, song_name, artist, album, duration_minutes=3.5, current_position_minutes=0, image_url=None):
    current_ms = int(current_position_minutes * 60 * 1000)
    total_ms = int(duration_minutes * 60 * 1000)
    start_ms = int(time.time() * 1000) - current_ms
    end_ms = start_ms + (total_ms - current_ms)

    track_id = random.choice(_SPOTIFY_TRACKS)
    album_id = random.choice(_SPOTIFY_ALBUMS)
    artist_id = random.choice(_SPOTIFY_ARTISTS)

    activity = {
        "type": 2,
        "name": "Spotify",
        "details": song_name,
        "state": artist,
        "timestamps": {"start": start_ms, "end": end_ms},
        "application_id": "3201606009684",
        "sync_id": track_id,
        "session_id": f"spotify:{os.urandom(8).hex()}",
        "party": {"id": f"spotify:{track_id}", "size": [1, 1]},
        "secrets": {
            "join": f"spotify:{track_id}",
            "spectate": f"spotify:{track_id}",
            "match": f"spotify:{track_id}",
        },
        "instance": True,
        "flags": 48,
        "metadata": {
            "context_uri": f"spotify:album:{album_id}",
            "album_id": album_id,
            "artist_ids": [artist_id],
            "track_id": track_id,
        },
    }

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "spotify",
        "large_text": f"{album} on Spotify",
    }
    bot.set_activity(activity)

def send_listening_activity(bot, name, button_label=None, button_url=None, image_url=None, state=None, details=None):
    activity = {
        "type": 2,
        "name": "Spotify",
        "application_id": "3201606009684",
        "flags": 0,
        "details": details if details else name,
    }
    if state:
        activity["state"] = state

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "spotify",
        "large_text": name,
    }

    if button_label and button_url:
        activity["buttons"] = [button_label]
        activity["metadata"] = {"button_urls": [button_url]}

    bot.set_activity(activity)

def send_streaming_activity(bot, name, button_label=None, button_url=None, image_url=None, state=None, details=None):
    activity = {
        "type": 1,
        "name": "Streaming",
        "url": "https://twitch.tv/kaicenat",
        "application_id": "111299001912",
        "details": details if details else name,
    }
    if state:
        activity["state"] = state

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "youtube",
        "large_text": name,
    }

    if button_label and button_url:
        activity["buttons"] = [button_label]
        activity["metadata"] = {"button_urls": [button_url]}

    bot.set_activity(activity)

def send_playing_activity(bot, name, button_label=None, button_url=None, image_url=None, state=None, details=None):
    activity = {
        "type": 0,
        "name": name,
        "application_id": "367827983903490050",
    }
    if details:
        activity["details"] = details
    if state:
        activity["state"] = state

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "game",
        "large_text": name,
    }

    if button_label and button_url:
        activity["buttons"] = [button_label]
        activity["metadata"] = {"button_urls": [button_url]}

    bot.set_activity(activity)

def send_timer_activity(bot, name, start_time=None, end_time=None, details=None, state=None, image_url=None):
    activity = {
        "type": 0,
        "name": name,
        "application_id": "367827983903490050",
    }
    if start_time and end_time:
        activity["timestamps"] = {"start": int(start_time * 1000), "end": int(end_time * 1000)}
    if details:
        activity["details"] = details
    if state:
        activity["state"] = state

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "game",
        "large_text": name,
    }
    bot.set_activity(activity)

def send_vr_activity(bot, world_name, details=None, state=None, image_url=None, button_label=None, button_url=None):
    activity = {
        "type": 0,
        "name": "VRChat",
        "application_id": "367827983903490050",
        "details": details or f"In {world_name}",
        "state": state or "In VR",
        "assets": {
            "large_image": "game",
            "large_text": world_name,
            "small_image": "game",
            "small_text": "VR Session",
        },
    }
    if image_url:
        asset_key = upload_n_get_asset_key(bot, image_url)
        if asset_key:
            activity["assets"]["large_image"] = asset_key

    if button_label and button_url:
        activity["buttons"] = [button_label]
        activity["metadata"] = {"button_urls": [button_url]}

    bot.set_activity(activity)


def send_vr_headless_status(
    bot,
    oauth_access_token,
    session_token=None,
    activity_name="~~",
    application_id="1417273808645259344",
    platform="meta_quest",
):
    """Create/update a headless session to show the VR indicator."""
    try:
        headers = {
            "Authorization": f"Bearer {oauth_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "activitis": [
                {
                    "application_id": str(application_id),
                    "name": activity_name,
                    "type": 6,
                    "platform": platform,
                    "session_id": None,
                }
            ],
            "token": session_token,
        }
        response = bot.api.session.post(
            "https://discord.com/api/v10/users/@me/headless-sessions",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if response.status_code not in [200, 201]:
            text = response.text[:500] if hasattr(response, "text") else "no response body"
            return False, None, f"HTTP {response.status_code}: {text}"
        data = response.json()
        return True, data.get("token"), "Headless VR session updated"
    except Exception as e:
        return False, None, str(e)


def clear_vr_headless_status(bot, oauth_access_token, session_token):
    """Delete a previously created headless session token."""
    try:
        headers = {
            "Authorization": f"Bearer {oauth_access_token}",
            "Content-Type": "application/json",
        }
        payload = {"token": session_token}
        response = bot.api.session.post(
            "https://discord.com/api/v10/users/@me/headless-sessions/delete",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if response.status_code not in [200, 204]:
            text = response.text[:500] if hasattr(response, "text") else "no response body"
            return False, f"HTTP {response.status_code}: {text}"
        return True, "Headless VR session deleted"
    except Exception as e:
        return False, str(e)

LAST_SERVER_COPY = None
VR_HEADLESS_TOKEN = None
VR_HEADLESS_LOCK = threading.Lock()
VR_HEADLESS_LOOP = {
    "running": False,
    "thread": None,
    "oauth_token": "",
    "activity_name": "~~",
    "platform": "meta_quest",
    "interval": 60,
    "last_update": 0,
    "last_error": "",
}


def start_vr_headless_loop(bot, oauth_token, activity_name="~~", platform="meta_quest", interval=60):
    global VR_HEADLESS_TOKEN

    with VR_HEADLESS_LOCK:
        if VR_HEADLESS_LOOP["running"]:
            return False, "Headless loop already running"

        VR_HEADLESS_LOOP["running"] = True
        VR_HEADLESS_LOOP["oauth_token"] = oauth_token
        VR_HEADLESS_LOOP["activity_name"] = activity_name
        VR_HEADLESS_LOOP["platform"] = platform
        VR_HEADLESS_LOOP["interval"] = max(30, int(interval))
        VR_HEADLESS_LOOP["last_update"] = 0
        VR_HEADLESS_LOOP["last_error"] = ""

    def _worker():
        global VR_HEADLESS_TOKEN
        while VR_HEADLESS_LOOP["running"]:
            try:
                ok, new_token, info = send_vr_headless_status(
                    bot,
                    VR_HEADLESS_LOOP["oauth_token"],
                    session_token=VR_HEADLESS_TOKEN,
                    activity_name=VR_HEADLESS_LOOP["activity_name"],
                    platform=VR_HEADLESS_LOOP["platform"],
                )
                if ok:
                    VR_HEADLESS_TOKEN = new_token or VR_HEADLESS_TOKEN
                    VR_HEADLESS_LOOP["last_update"] = int(time.time())
                    VR_HEADLESS_LOOP["last_error"] = ""
                else:
                    VR_HEADLESS_LOOP["last_error"] = info
            except Exception as e:
                VR_HEADLESS_LOOP["last_error"] = str(e)

            wait_for = VR_HEADLESS_LOOP["interval"]
            for _ in range(wait_for):
                if not VR_HEADLESS_LOOP["running"]:
                    break
                time.sleep(1)

    thread = threading.Thread(target=_worker, daemon=True)
    VR_HEADLESS_LOOP["thread"] = thread
    thread.start()
    return True, "Headless loop started"


def stop_vr_headless_loop():
    with VR_HEADLESS_LOCK:
        if not VR_HEADLESS_LOOP["running"]:
            return False, "Headless loop is not running"
        VR_HEADLESS_LOOP["running"] = False
    return True, "Headless loop stopped"


# ---------------------------------------------------------------------------
# Join-invite helpers (synchronous, used by joininvite command)
# ---------------------------------------------------------------------------

def _ji_handle_verification(api, guild_id, invite_code, headers):
    """Agree to server member-verification rules if present."""
    try:
        r = api.request(
            "GET",
            f"/guilds/{guild_id}/member-verification?with_guild=false&invite_code={invite_code}"
        )
        if r.status_code != 200:
            return None
        data = r.json()
        form_fields = data.get("form_fields", [])
        if not form_fields:
            return None
        response_fields = []
        for field in form_fields:
            if field.get("required", False):
                f = field.copy()
                f["response"] = True
                response_fields.append(f)
        payload = {"version": data.get("version", ""), "form_fields": response_fields}
        r2 = api.request(
            "PUT",
            f"/guilds/{guild_id}/requests/@me",
            data=payload
        )
        if r2.status_code in (200, 201, 204):
            return {"status": True, "num_fields": len(response_fields)}
        if r2.status_code == 410:
            return {"status": True, "num_fields": 0, "already_verified": True}
        return {"status": False, "error": f"HTTP {r2.status_code}"}
    except Exception as e:
        return {"status": False, "error": str(e)[:80]}


def _ji_handle_onboarding(api, guild_id, headers):
    """Submit random onboarding responses if the guild has onboarding enabled."""
    try:
        r = api.request(
            "GET",
            f"/guilds/{guild_id}/onboarding"
        )
        if not r or r.status_code != 200:
            return None
        data = r.json()
        if not data.get("enabled", False):
            return None
        current_ms = int(time.time() * 1000)
        responses, prompts_seen, responses_seen = [], {}, {}
        for prompt in data.get("prompts", []):
            if not prompt.get("in_onboarding", False):
                continue
            options = prompt.get("options", [])
            if not options:
                continue
            pid = prompt["id"]
            if prompt.get("single_select", False):
                sel = [random.choice(options)]
            else:
                sel = random.sample(options, min(random.randint(1, 3), len(options)))
            for opt in sel:
                oid = opt["id"]
                responses.append(oid)
                responses_seen[oid] = current_ms
            prompts_seen[pid] = current_ms
        if not responses:
            return None
        payload = {
            "onboarding_responses": responses,
            "onboarding_prompts_seen": prompts_seen,
            "onboarding_responses_seen": responses_seen,
        }
        r2 = api.request(
            "POST",
            f"/guilds/{guild_id}/onboarding-responses",
            data=payload
        )
        if r2.status_code in (200, 201, 204):
            return {"status": True, "num_responses": len(responses)}
        return {"status": False, "error": f"HTTP {r2.status_code}"}
    except Exception as e:
        return {"status": False, "error": str(e)[:80]}


# ---------------------------------------------------------------------------
# Guild Badge Rotator
# ---------------------------------------------------------------------------

import re as _re

_GUILDBADGE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "guildrotate_config.json")
_GUILDBADGE_BADGES = {0: "Sword", 8: "Skull", 5: "Lightning", 9: "Star", 6: "Moon"}
_GUILDBADGE_DEFAULT_COLORS = [
    ["#ff6b6b","#4ecdc4"],["#45b7d1","#96ceb4"],["#feca57","#48dbfb"],
    ["#ff9ff3","#54a0ff"],["#1dd1a1","#feca57"],["#a29bfe","#fd79a8"],
    ["#6c5ce7","#fdcb6e"],["#00b894","#fdcb6e"],["#e17055","#74b9ff"],
    ["#a29bfe","#55a3ff"],["#ff7675","#74b9ff"],["#fd79a8","#a29bfe"],
    ["#fdcb6e","#6c5ce7"],["#eb4d4b","#6ab04c"],["#130f40","#686de0"],
    ["#3c40c6","#0fbcf9"],["#0fbcf9","#00d8d6"],["#ff5252","#536dfe"],
    ["#ff6b9d","#c44569"],["#feca57","#ff6b9d"],["#48dbfb","#0abde3"],
    ["#5f27cd","#00d2d3"],["#ee5a24","#f79f1f"],["#d980fa","#6ab04c"],
    ["#4b7bec","#a55eea"],["#26de81","#20bf6b"],["#fc5c65","#fed330"],
    ["#45aaf2","#2d98da"],["#4b6584","#778ca3"],
]


class GuildRotator:
    def __init__(self, api_client):
        self.api = api_client
        self.config = {}
        self._thread = None
        self._stop_flag = False
        self._hex_re = _re.compile(r'^#[0-9A-Fa-f]{6}$')
        self._load()

    def _load(self):
        try:
            with open(_GUILDBADGE_CONFIG_PATH, "r") as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = {
                "delay": 180,
                "tag_name": "aria",
                "guilds": [],
                "colors": list(_GUILDBADGE_DEFAULT_COLORS),
            }
            self._save()

    def _save(self):
        with open(_GUILDBADGE_CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=4)

    def _update_guild(self, guild_id, badge_id, primary, secondary):
        headers = self.api.header_spoofer.get_protected_headers(self.api.token)
        payload = {
            "tag": self.config.get("tag_name", "aria"),
            "badge": badge_id,
            "badge_color_primary": primary,
            "badge_color_secondary": secondary,
        }
        try:
            r = self.api.request(
                "PATCH",
                f"/guilds/{guild_id}/profile",
                data=payload
            )
            return r.status_code in (200, 204)
        except Exception:
            return False

    def _run(self):
        badge_ids = list(_GUILDBADGE_BADGES.keys())
        idx = 0
        while not self._stop_flag:
            guilds = self.config.get("guilds", [])
            colors = self.config.get("colors", [])
            if not guilds or not colors:
                time.sleep(60)
                continue
            badge_id = badge_ids[idx % len(badge_ids)]
            primary, secondary = random.choice(colors)
            for guild_id in guilds:
                if self._stop_flag:
                    break
                self._update_guild(guild_id, badge_id, primary, secondary)
                time.sleep(1)
            idx += 1
            for _ in range(self.config.get("delay", 180)):
                if self._stop_flag:
                    break
                time.sleep(1)

    def start(self):
        if self._thread and self._thread.is_alive():
            return False, "Already running"
        self._stop_flag = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True, "Started"

    def stop(self):
        if not self._thread or not self._thread.is_alive():
            return False, "Not running"
        self._stop_flag = True
        self._thread = None
        return True, "Stopped"

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())


def main():
    install_global_formatter()
    config = Config()
    token = config.get("token")
    
    if not token or token == "token here":
        print("Error: No token found in config.json")
        print("Edit config.json and add your token")
        with open("config.json", 'w') as f:
            json.dump({"token": "token here", "prefix": ";"}, f, indent=4)
            print("Created config.json - edit it with your token")
        return
    
    bot = DiscordBot(token, config.get("prefix", ";"), config)
    voice_manager = SimpleVoice(bot.api, token)
    backup_manager = BackupManager(bot.api)
    mod_manager = ModerationManager(bot.api)
    web_panel = WebPanel(bot.api, bot, host='127.0.0.1', port=8080)
    afk_system.load_state()
    bot._afk_system_ref = afk_system
    anti_gc_trap = AntiGCTrap(bot.api)
    github_updater = GitHubUpdater(bot.api, bot)
    # Initialize super react client
    global super_react_client
    super_react_client = SuperReactClient(bot.token)
    
    # Setup boost commands
    from boost_manager import BoostManager
    boost_manager = BoostManager(bot.api)
    history_manager = HistoryManager(bot.api)
    account_data_manager = AccountDataManager(bot.api)
    badge_scraper = BadgeScraper(bot.api, history_manager)
    quest_system = QuestSystem(bot.api)
    guild_rotator = GuildRotator(bot.api)
    developer_tools = DeveloperTools()

    owner_user_id = str(bot.customizer.get_owner_id())
    developer_user_id = str(developer_tools.get_dev_id())

    def is_owner_user(user_id):
        return str(user_id) == owner_user_id

    def is_developer_user(user_id):
        return str(user_id) == developer_user_id

    def is_hosted_user(user_id):
        user_id = str(user_id)
        for entry in host_manager.saved_users.values():
            if str(entry.get("user_id", "")) == user_id:
                return True
        return False

    def is_control_user(user_id):
        user_id = str(user_id)
        return user_id == owner_user_id or user_id == developer_user_id

    def deny_restricted_command(ctx, title, developer_only=False, hosted_only=False):
        if developer_only:
            label = "Developer only"
        elif hosted_only:
            label = "Hosted users only"
        else:
            label = "Owner only"
        msg = ctx["api"].send_message(ctx["channel_id"], f"```| {title} |\n{label}```")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
        return False

    account_data_manager.start_stats_job(900)
    account_data_manager.start_auto_scrape(900, ["all"])

    boost_manager.load_state()
    bot.boost_manager = boost_manager  # Attach to bot for event handling
    
    # Fetch current server boost counts
    boost_manager.fetch_server_boosts()
    
    from boost_commands import setup_boost_commands
    setup_boost_commands(bot, bot.api, delete_after_delay)
    
    # Setup extended commands and new systems
    from extended_commands import setup_extended_commands
    setup_extended_commands(bot, delete_after_delay)
    
    from extended_system_commands import setup_extended_system_commands
    setup_extended_system_commands(bot, delete_after_delay)
    
    # Initialize friend scraper
    from friend_scraper import EnhancedFriendScraper
    friend_scraper = EnhancedFriendScraper(bot.api)
    bot.friend_scraper = friend_scraper
    
    # Initialize self-hosting system
    from self_hosting import self_hosting_manager
    bot.self_hosting_manager = self_hosting_manager
    
    # Print all loaded users summary (once, at the end of initialization)
    # This fixes the duplicate user loading issue
    host_manager.print_loaded_users_summary()
    self_hosting_manager.print_summary()
    

    @bot.command(name="nitro")
    def nitro_cmd(ctx, args):
        if not args:
            status = "ON" if ctx["bot"].nitro_sniper.enabled else "OFF"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Nitro Sniper |\nStatus: {status}\nCodes checked: {len(ctx['bot'].nitro_sniper.used_codes)}\n\n+nitro on/off\n+nitro clear\n+nitro stats```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0] == "on":
            ctx["bot"].nitro_sniper.toggle(True)
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Nitro sniper **enabled**.")
        
        elif args[0] == "off":
            ctx["bot"].nitro_sniper.toggle(False)
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Nitro sniper **disabled**.")
        
        elif args[0] == "clear":
            count = ctx["bot"].nitro_sniper.clear_codes()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Nitro |\nCleared {count} codes```")
        
        elif args[0] == "stats":
            stats = ctx["bot"].nitro_sniper.get_stats()
            status = "ON" if stats["enabled"] else "OFF"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Nitro Stats |\nStatus: {status}\nCodes checked: {stats['used_codes']}```")
        
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="giveaway", aliases=["gw", "gsnipe"])
    def giveaway_cmd(ctx, args):
        gs = ctx["bot"].giveaway_sniper
        sub = args[0].lower() if args else ""

        if sub == "on":
            gs.toggle(True)
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Giveaway sniper **enabled**.")
        elif sub == "off":
            gs.toggle(False)
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Giveaway sniper **disabled**.")
        else:
            s = gs.get_stats()
            status = "ON" if s["enabled"] else "OFF"
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Giveaway Sniper |\nStatus  :: {status}\nEntered :: {s['entered']}\nWon     :: {s['won']}\nFailed  :: {s['failed']}```",
            )

        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="agct", aliases=["antigctrap"])
    def agct_cmd(ctx, args):
        agct = ctx["bot"].anti_gc_trap
        
        if not args:
            status = "ON" if agct.enabled else "OFF"
            block = "ON" if agct.block_creators else "OFF"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Anti-GC Trap |\nStatus: {status}\nBlock Creators: {block}\nWhitelisted: {len(agct.whitelist)}\n\n+agct on/off\n+agct block on/off\n+agct msg <text>\n+agct name <name>\n+agct icon <url>\n+agct webhook <url>\n+agct wl add <user_id>\n+agct wl remove <user_id>\n+agct wl list```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0] == "on":
            agct.enabled = True
            print(f"[AGCT] Enabled: {agct.enabled}")
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Anti-GC Trap enabled**.")
        
        elif args[0] == "off":
            agct.enabled = False
            print(f"[AGCT] Enabled: {agct.enabled}")
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Anti-GC Trap disabled**.")
        
        elif args[0] == "block":
            if len(args) >= 2:
                if args[1] == "on":
                    agct.block_creators = True
                    msg = ctx["api"].send_message(ctx["channel_id"], "> **Block creators enabled**.")
                elif args[1] == "off":
                    agct.block_creators = False
                    msg = ctx["api"].send_message(ctx["channel_id"], "> **Block creators disabled**.")
        
        elif args[0] == "msg" and len(args) >= 2:
            message = " ".join(args[1:])
            agct.leave_message = message
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Anti-GC Trap |\nLeave message set: {message[:50]}...```")
        
        elif args[0] == "name" and len(args) >= 2:
            name = " ".join(args[1:])
            agct.gc_name = name
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Anti-GC Trap |\nGC name set: {name}```")
        
        elif args[0] == "icon" and len(args) >= 2:
            url = args[1]
            agct.gc_icon_url = url
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Anti-GC Trap |\nGC icon URL set```")
        
        elif args[0] == "webhook" and len(args) >= 2:
            url = args[1]
            agct.webhook_url = url
            agct.save_whitelist()
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Anti-GC Trap |\nWebhook set```")
        
        elif args[0] == "wl":
            if len(args) >= 3:
                if args[1] == "add":
                    user_id = args[2]
                    success = agct.add_to_whitelist(user_id)
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Anti-GC Trap |\nAdded {user_id} to whitelist```")
                
                elif args[1] == "remove":
                    user_id = args[2]
                    success = agct.remove_from_whitelist(user_id)
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Anti-GC Trap |\nRemoved {user_id} from whitelist```")
                
                elif args[1] == "list":
                    whitelist = agct.get_whitelist()
                    if whitelist:
                        wl_list = "\n".join([f"• {uid}" for uid in whitelist[:10]])
                        if len(whitelist) > 10:
                            wl_list += f"\n• ... and {len(whitelist) - 10} more"
                        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Whitelist |\n{wl_list}```")
                    else:
                        msg = ctx["api"].send_message(ctx["channel_id"], "```| Anti-GC Trap |\nWhitelist empty```")
        
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="ms", aliases=["ping", "latency", "lat"])
    def ms(ctx, args):
        api = ctx["api"]
        # REST round-trip
        t0 = time.time()
        msg = api.send_message(ctx["channel_id"], "```ansi\n\u001b[1;35mAria\u001b[0m :: Measuring...```")
        rest_ms = (time.time() - t0) * 1000
        # WebSocket heartbeat latency
        ws_ms = None
        try:
            last_hb = getattr(bot, "last_heartbeat", None)
            hb_interval = getattr(bot, "heartbeat_interval", None)
            if last_hb and hb_interval:
                ws_ms = max(0.0, (time.time() - last_hb) % hb_interval * 1000)
        except Exception:
            pass
        ws_str = f"{ws_ms:.0f}ms" if ws_ms is not None else "N/A"
        if msg:
            api.edit_message(
                ctx["channel_id"], msg.get("id"),
                f"```ansi\n\u001b[1;35mAria\u001b[0m :: \u001b[1;34mLinux\u001b[0m :: \u001b[1;32mConsole\u001b[0m\nREST :: {rest_ms:.0f}ms\nWS   :: {ws_str}```",
            )
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    @bot.command(name="afk")
    def afk_cmd(ctx, args):
        reason = " ".join(args) if args else "AFK"
        success = afk_system.set_afk(ctx["author_id"], reason)
        
        if success:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| AFK |\nSet AFK: {reason}```")
            afk_system.save_state()
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| AFK |\nFailed to set AFK```")
        
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="afkwebhook")
    def afk_webhook_cmd(ctx, args):
        if not args:
            current = afk_system.webhook_url or "None"
            display = current if len(current) < 50 else current[:47] + "..."
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| AFK Webhook |\nUsage: +afkwebhook <webhook_url>\nCurrent: {display}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        webhook_url = args[0]
        
        success = afk_system.set_webhook(webhook_url)
        afk_system.save_state()
        
        if success:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| AFK Webhook |\nWebhook set successfully```")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| AFK Webhook |\nFailed to set webhook```")
        
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="afkstatus")
    def afk_status_cmd(ctx, args):
        target_id = args[0] if args else ctx["author_id"]
        
        if afk_system.is_afk(target_id):
            afk_data = afk_system.get_afk_info(target_id)
            afk_since = int(time.time() - afk_data["since"])
            
            hours = afk_since // 3600
            minutes = (afk_since % 3600) // 60
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours}h "
            if minutes > 0 or hours == 0:
                time_str += f"{minutes}m"
            
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| AFK Status |\nUser: {target_id}\nStatus: AFK\nReason: {afk_data['reason']}\nDuration: {time_str}```")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| AFK Status |\nUser: {target_id}\nStatus: Online```")
        
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="spam", aliases=["s"])
    def spam(ctx, args):
        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Spam |\nUsage: {bot.prefix}spam <count> <message>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        try:
            count = min(int(args[0]), 100)
        except ValueError:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Spam |\nCount must be a number```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        text = " ".join(args[1:])
        api = ctx["api"]

        for _ in range(count):
            api.send_message(ctx["channel_id"], text)
            time.sleep(random.uniform(1.5, 3.0))  # Random delay between 1.5-3 seconds
    
    @bot.command(name="purge", aliases=[ "clear", "clean"])
    def purge(ctx, args):
        # Usage: +purge [amount] [user_id]
        amount = 100
        target_user = None
        for arg in (args or []):
            if arg.isdigit() and len(arg) <= 4:
                amount = min(500, max(1, int(arg)))
            elif arg.isdigit():
                target_user = arg

        status = ctx["api"].send_message(
            ctx["channel_id"],
            f"> **Purging** {amount} messages{' for user ' + target_user if target_user else ''}...",
        )
        messages = ctx["api"].get_messages(ctx["channel_id"], amount)
        deleted = 0
        skipped = 0
        for m in messages:
            author_id = m.get("author", {}).get("id", "")
            is_mine = author_id == str(bot.user_id)
            if target_user:
                # Delete any message from target user OR our own status messages
                if author_id != target_user and not is_mine:
                    skipped += 1
                    continue
                if not is_mine:
                    # Can only delete own messages as a user account
                    skipped += 1
                    continue
            else:
                if not is_mine:
                    skipped += 1
                    continue
            ctx["api"].delete_message(ctx["channel_id"], m["id"])
            deleted += 1
            time.sleep(0.3)
        if status:
            ctx["api"].edit_message(
                ctx["channel_id"], status.get("id"),
                f"> **Purge Complete** | Deleted {deleted} messages",
            )
            delete_after_delay(ctx["api"], ctx["channel_id"], status.get("id"))
    
    @bot.command(name="massdm")
    def mass_dm(ctx, args):
        if len(args) >= 2:
            try:
                option = int(args[0])
                message = " ".join(args[1:])
                
                option_names = {1: "DM History", 2: "Friends", 3: "Both"}
                if option not in [1, 2, 3]:
                    msg = ctx["api"].send_message(ctx["channel_id"], "```| DM Sender |\nInvalid option. Use 1, 2, or 3```")
                    if msg:
                        delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                    return
                
                status_msg = ctx["api"].send_message(ctx["channel_id"], f"```| DM Sender |\nMode: {option_names[option]}\nMessage: {message[:30]}...\nFetching targets...```")
                
                dms_response = ctx["api"].request("GET", "/users/@me/channels")
                if not dms_response or dms_response.status_code != 200:
                    ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "```| DM Sender |\nFailed to fetch DMs```")
                    delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
                    return
                
                dm_data = dms_response.json()
                targets = []
                target_names = []
                
                for dm in dm_data:
                    if dm.get("type") == 1 and dm.get("recipients"):
                        recipient = dm["recipients"][0] if dm["recipients"] else {}
                        user_id = recipient.get("id")
                        username = recipient.get("username", "Unknown")
                        if user_id:
                            targets.append((dm["id"], user_id, username))
                            target_names.append(username)
                
                if option == 2 or option == 3:
                    friends_response = ctx["api"].request("GET", "/users/@me/relationships")
                    if friends_response and friends_response.status_code == 200:
                        friends_data = friends_response.json()
                        for friend in friends_data:
                            if friend.get("type") == 1:
                                user = friend.get("user", {})
                                user_id = user.get("id")
                                username = user.get("username", "Unknown")
                                dm_found = False
                                for target in targets:
                                    if target[1] == user_id:
                                        dm_found = True
                                        break
                                if not dm_found:
                                    dm_channel = ctx["api"].create_dm(user_id)
                                    if dm_channel and "id" in dm_channel:
                                        targets.append((dm_channel["id"], user_id, username))
                                        target_names.append(username)
                
                if not targets:
                    ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "```| DM Sender |\nNo targets found```")
                    delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
                    return
                
                sent = 0
                total = len(targets)
                failed = 0
                current_target = ""
                
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| DM Sender |\nMode: {option_names[option]}\nTargets: {total}\nStatus: Starting...\nSent: 0/{total}\nFailed: 0```")
                
                for i, (channel_id, user_id, username) in enumerate(targets):
                    current_target = username
                    result = ctx["api"].send_message(channel_id, message)
                    if result:
                        sent += 1
                    else:
                        failed += 1
                    
                    if (i + 1) % 3 == 0 or i == total - 1:
                        ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| DM Sender |\nMode: {option_names[option]}\nTargets: {total}\nStatus: Sending...\nSent: {sent}/{total}\nFailed: {failed}\nCurrent: {username}```")
                    
                    time.sleep(random.uniform(2.5, 4.0))
                
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| DM Sender |\nMode: {option_names[option]}\nStatus: Complete\nSent: {sent}/{total}\nFailed: {failed}\nTime: {time.strftime('%H:%M:%S')}```")
                delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
                
            except Exception as e:
                print(f"Mass DM error: {e}")
                help_text = """```asciidoc
| DM Sender Options |
1 :: Mass DM all your DM history
2 :: Mass DM all your friends (with existing DMs)
3 :: Both (DM history + friends with existing DMs)

Usage: +massdm <1|2|3> <message>
Example: +massdm 1 Hello everyone!```"""
                msg = ctx["api"].send_message(ctx["channel_id"], help_text)
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="join", aliases=["acceptinvite"])
    def join_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Join |\nUsage: join <invite_code_or_url>```"
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        invite = args[0]
        # Strip full URLs down to just the code
        if "/" in invite:
            invite = invite.rstrip("/").split("/")[-1]

        status = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Join |\nJoining {invite}...```"
        )

        try:
            response = ctx["api"].request(
                "POST",
                f"/invites/{invite}",
                data={"session_id": None}
            )
            if response and response.status_code in (200, 204):
                data = response.json() if response.status_code == 200 else {}
                guild_name = (
                    data.get("guild", {}).get("name")
                    or data.get("guild_id")
                    or invite
                )
                result = f"Joined {guild_name}"
                ok = True
            else:
                code = response.status_code if response else "no response"
                err = ""
                try:
                    err = response.json().get("message", "") if response else ""
                except Exception:
                    pass
                result = f"Failed ({code}){': ' + err if err else ''}"
                ok = False
        except Exception as e:
            result = f"Error: {str(e)[:80]}"
            ok = False

        if status:
            ctx["api"].edit_message(
                ctx["channel_id"], status.get("id"),
                f"```| Join |\n{result}```"
            )
            delete_after_delay(ctx["api"], ctx["channel_id"], status.get("id"))

    @bot.command(name="block", aliases=["blockuser", "bu"])
    def block_user(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Block |\nUsage: {bot.prefix}block <user_id> [user_id2] ...```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)
        blocked = []
        failed = []
        for uid in args:
            try:
                r = api.request(
                    "PUT",
                    f"/users/@me/relationships/{uid}",
                    data={"type": 2}
                )
                if r and r.status_code in (200, 204):
                    blocked.append(uid)
                else:
                    failed.append(uid)
            except Exception:
                failed.append(uid)
            time.sleep(0.3)

        parts = []
        if blocked:
            parts.append(f"Blocked: {', '.join(blocked)}")
        if failed:
            parts.append(f"Failed: {', '.join(failed)}")
        msg = api.send_message(ctx["channel_id"], "```| Block |\n" + " | ".join(parts) + "```")
        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    @bot.command(name="hypesquad", aliases=["changehypesquad", "hs"])
    def hypesquad_cmd(ctx, args):
        houses = {"bravery": 1, "brilliance": 2, "balance": 3}
        house = (args[0].lower() if args else "")
        if house not in houses:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"> **Hypesquad** | Usage: {bot.prefix}hypesquad bravery/brilliance/balance",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        resp = ctx["api"].request(
            "POST",
            "/hypesquad/online",
            data={"house_id": houses[house]}
        )
        if resp and resp.status_code == 204:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Hypesquad** changed to **{house.title()}**")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Hypesquad** failed (HTTP {resp.status_code if resp else 'N/A'})")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="hypesquad_leave", aliases=["leavehypesquad", "hsl"])
    def hypesquad_leave_cmd(ctx, args):
        resp = ctx["api"].request(
            "DELETE",
            "/hypesquad/online"
        )
        if resp and resp.status_code == 204:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Hypesquad** left successfully")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Hypesquad** failed (HTTP {resp.status_code if resp else 'N/A'})")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="status", aliases=["setstatus", "changestatus"])
    def status_cmd(ctx, args):
        valid = {"online", "idle", "dnd", "invisible"}
        status = (args[0].lower() if args else "")
        if status not in valid:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Status |\nUsage: {bot.prefix}status online/idle/dnd/invisible```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        ok = ctx["bot"].set_status(status)
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Status |\n{'Set to ' + status if ok else 'Failed (not connected)'}```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="client", aliases=["clienttype", "ct"])
    def client_cmd(ctx, args):
        valid = {"web", "desktop", "mobile"}
        ctype = (args[0].lower() if args else "")
        if ctype not in valid:
            current = getattr(ctx["bot"], "_client_type", "web")
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Client |\nCurrent :: {current}\nUsage   :: {bot.prefix}client web/desktop/mobile```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        ok = ctx["bot"].set_client_type(ctype)
        labels = {"web": "Web (Chrome)", "desktop": "Discord Desktop", "mobile": "Discord Android"}
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Client |\n{'Switched to ' + labels[ctype] + ' — reconnecting...' if ok else 'Failed'}```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="superreact", aliases=["sr"])
    def superreact_cmd(ctx, args):
        if len(args) >= 2:
            target_arg, emoji = args[0], args[1]
            target_id = target_arg.strip('<@!>')
            if target_id.isdigit():
                super_react_client.add_target(target_id, emoji)
                if not super_react_client.is_running():
                    msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\n✓ Target added. Use +superreactstart to begin reacting.```")
                else:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| SuperReact |\n✓ Enabled for user\nTarget: <@{target_id}>\nEmoji: {emoji}```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="superreactlist", aliases=["srlist"])
    def superreact_list_cmd(ctx, args):
        targets = super_react_client.get_targets()
        msr_targets = super_react_client.get_msr_targets()
        ssr_targets = super_react_client.get_ssr_targets()
        
        if not targets and not msr_targets and not ssr_targets:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\nNo active super-reactions```")
        else:
            response = "```| SuperReact Status |\n"
            if targets:
                response += "\nSingle SuperReactions:\n"
                for target, emoji in targets.items():
                    response += f"• <@{target}> → {emoji}\n"
            
            if msr_targets:
                response += "\nCycle SuperReactions:\n"
                for target, (emojis, idx) in msr_targets.items():
                    response += f"• <@{target}> → {', '.join(emojis)} (current: {emojis[idx]})\n"
            
            if ssr_targets:
                response += "\nMulti SuperReactions:\n"
                for target, emojis in ssr_targets.items():
                    response += f"• <@{target}> → {', '.join(emojis)}\n"
            
            response += "```"
            msg = ctx["api"].send_message(ctx["channel_id"], response)
        
        if 'msg' in locals() and msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    # @bot.command(name="superreactrandom", aliases=["srrandom"])
    # def superreact_random_cmd(ctx, args):
    #     if not args:
    #         msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact Random |\nUsage: +srrandom <message_id>```")
    #         if msg:
    #             delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    #         return
    #     
    #     target_msg_id = args[0].strip()
    #     if not target_msg_id.isdigit():
    #         msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact Random |\nError: Invalid message ID```")
    #         if msg:
    #             delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    #         return
    #     
    #     msg = ctx["api"].send_message(ctx["channel_id"], f"```| SuperReact Random |\nAdding super-reactions to message {target_msg_id}...```")
    #     
    #     added_emojis = []
    #     available_emojis = super_react.emojis.copy()
    #     while len(added_emojis) < 10 and available_emojis:
    #         emoji = random.choice(available_emojis)
    #         available_emojis.remove(emoji)
    #         try:
    #             super_react.send_super_reaction(ctx["channel_id"], target_msg_id, emoji)
    #             added_emojis.append(emoji)
    #             time.sleep(0.7)
    #         except Exception as e:
    #             print(f"[ERROR]: Failed to add {emoji} to {target_msg_id}: {e}")
    #             break
    #     
    #     msg2 = ctx["api"].send_message(ctx["channel_id"], f"```| SuperReact Random |\nComplete!\nMessage: {target_msg_id}\nAdded: {', '.join(added_emojis)}\nTotal: {len(added_emojis)}```")
    #     
    #     if msg:
    #         delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    #     if msg2:
    #         delete_after_delay(ctx["api"], ctx["channel_id"], msg2.get("id"))
    
    @bot.command(name="superreactstart", aliases=["srstart"])
    def superreact_start_cmd(ctx, args):
        if super_react_client and super_react_client.is_running():
            msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\nAlready running```")
        else:
            if super_react_client.start():
                msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\n✓ Started```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\n✗ Failed to start```")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="superreactstop", aliases=["srstop"])
    def superreact_stop_cmd(ctx, args):
        if super_react_client and super_react_client.is_running():
            super_react_client.stop()
            msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\n✗ Stopped```")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\nNot running```")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="guilds")
    def list_guilds(ctx, args):
        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)
        try:
            r = api.request(
                "GET",
                "/users/@me/guilds?with_counts=true"
            )
            guilds = r.json() if (r and r.status_code == 200) else api.get_guilds()
        except Exception:
            guilds = api.get_guilds()

        total = len(guilds)
        page = int(args[0]) if args and args[0].isdigit() else 1
        per = 15
        import math as _m
        pages = max(1, _m.ceil(total / per))
        page = min(page, pages)
        shown = guilds[(page - 1) * per: page * per]

        lines = [f"Guilds {total} total — page {page}/{pages}"]
        for g in shown:
            name = g.get("name", "?")
            gid = g.get("id", "?")
            owner = " [owner]" if g.get("owner") else ""
            mc = g.get("approximate_member_count")
            mc_str = f" | {mc}" if mc else ""
            lines.append(f"> {name}{owner}{mc_str} :: {gid}")

        msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    @bot.command(name="setprefix", aliases=["prefix"])
    def setprefix_cmd(ctx, args):
        if not args:
            user_prefix = bot.get_user_prefix(ctx["author_id"])
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Prefix** | Current: **{user_prefix}** | Usage: {bot.prefix}setprefix <symbol>")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        new_prefix = args[0]
        user_prefix = bot.get_user_prefix(ctx["author_id"])
        old_prefix = user_prefix
        
        # Set user's prefix (persisted to file)
        bot.set_user_prefix(ctx["author_id"], new_prefix)
        
        msg = ctx["api"].send_message(ctx["channel_id"], f"> **Prefix Updated** | Old: **{old_prefix}** → New: **{new_prefix}** | ✓ Saved")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="customize", aliases=["theme", "ui"])
    def customize_cmd(ctx, args):
        if not args:
            help_text = """```yaml
Customization Commands:
  Theme Settings:
    debug_color    - Set debug message color
    theme          - Set UI theme (dark/light)
    font_style     - Set font family
    cursor_style   - Set cursor appearance
    
  Terminal Settings:
    terminal_mode  - Set terminal emulation
    prompt_style   - Set prompt appearance
    time_format    - Set time display (12h/24h)
    
  UI Settings:
    ui_animation   - Toggle animations
    sound_effects  - Toggle sounds
    auto_save      - Toggle auto-save
    
  Color Palette:
    $customize color background #1e1e1e
    $customize color accent #00ff00
    $customize color warning #ff9900

Usage:
  $customize set theme dark
  $customize toggle ui_animation
  $customize list
  $customize reset all```"""
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "palette":
            palette_info = """```yaml
Color Palette Elements:
  background  - Main background color
  foreground  - Text color
  accent      - Primary accent color
  warning     - Warning/alert color
  error       - Error message color
  success     - Success message color
  info        - Information color

Example:
  $customize color accent #ff00ff
  $customize color background #000000```"""
            msg = ctx["api"].send_message(ctx["channel_id"], palette_info)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "terminal":
            terminal_info = """```ansi
\u001b[36mTerminal Modes Available:\u001b[0m
  • unix     - Unix/Linux style
  • windows  - Windows CMD style
  • powershell - PowerShell style
  • retro    - Retro terminal style
  • modern   - Modern terminal style

\u001b[36mPrompt Styles:\u001b[0m
  • arrow    - > 
  • dollar   - $ 
  • hash     - # 
  • custom   - Custom text

Example:
  $customize set terminal_mode retro
  $customize set prompt_style dollar```"""
            msg = ctx["api"].send_message(ctx["channel_id"], terminal_info)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

    @bot.command(name="terminal", aliases=["term", "shell"])
    def terminal_cmd(ctx, args):
        term_active = bot.customizer.terminal_emulation
        if not args:
            status = "✓ Active" if term_active else "✗ Inactive"
            term_info = f"""```ansi
\u001b[33mTerminal Emulation Status:\u001b[0m
  Mode: {status}
  Style: {bot.customizer.get_setting('terminal_mode')}
  Prompt: {bot.customizer.get_setting('prompt_style')}
  Time Format: {bot.customizer.get_setting('time_format')}

\u001b[33mCommands:\u001b[0m
  +terminal toggle  - Toggle terminal mode
  +terminal style   - Show current style
  +terminal time    - Show formatted time```"""
            msg = ctx["api"].send_message(ctx["channel_id"], term_info)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "toggle":
            new_state = bot.customizer.toggle_terminal_mode()
            status = "✓ Enabled" if new_state else "✗ Disabled"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```yaml\nTerminal Emulation:\n  Status: {status}\n  Mode: {bot.customizer.get_setting('terminal_mode')}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "style":
            import datetime
            now = datetime.datetime.now()
            if bot.customizer.get_setting('time_format') == '12h':
                time_str = now.strftime("%I:%M %p")
            else:
                time_str = now.strftime("%H:%M")
            
            style_demo = f"""```ansi
\u001b[32m{bot.customizer.get_setting('prompt_style')}\u001b[0m \u001b[36muser@bot\u001b[0m:\u001b[34m~\u001b[0m$ echo "Terminal Style Demo"
Terminal Style Demo

\u001b[32m{bot.customizer.get_setting('prompt_style')}\u001b[0m \u001b[36muser@bot\u001b[0m:\u001b[34m~\u001b[0m$ date
{now.strftime('%A, %B %d, %Y')} {time_str}

\u001b[32m{bot.customizer.get_setting('prompt_style')}\u001b[0m \u001b[36muser@bot\u001b[0m:\u001b[34m~\u001b[0m$ ```"""
            msg = ctx["api"].send_message(ctx["channel_id"], style_demo)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "time":
            import datetime
            now = datetime.datetime.now()
            
            if bot.customizer.get_setting('time_format') == '12h':
                time_display = now.strftime("%I:%M:%S %p")
            else:
                time_display = now.strftime("%H:%M:%S")
            
            date_display = now.strftime(bot.customizer.get_setting('date_format').replace('dd', '%d').replace('mm', '%m').replace('yyyy', '%Y'))
            
            msg = ctx["api"].send_message(ctx["channel_id"], f"```ansi\n\u001b[35m{date_display} \u001b[33m{time_display}\u001b[0m\nTerminal Mode: {bot.customizer.get_setting('terminal_mode')}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

    @bot.command(name="ui", aliases=["interface", "settings"])
    def ui_cmd(ctx, args):
        if not args:
            settings = bot.customizer.config
            active = bot.customizer.get_active_customizations()
            
            ui_info = """```yaml
UI Configuration:
  Theme: {theme}
  Terminal Mode: {terminal_mode}
  Font: {font_style}
  Cursor: {cursor_style}
  Animations: {ui_animation}
  Sounds: {sound_effects}
  Auto-save: {auto_save}
  Time Format: {time_format}
  Date Format: {date_format}

Active Customizations: {active_count}
  {active_list}
  
Commands:
  +ui colors    - Show color palette
  +ui reset <setting> - Reset setting
  +ui save      - Save configuration```""".format(
                theme=settings['theme'],
                terminal_mode=settings['terminal_mode'],
                font_style=settings['font_style'],
                cursor_style=settings['cursor_style'],
                ui_animation='✓ On' if settings['ui_animation'] else '✗ Off',
                sound_effects='✓ On' if settings['sound_effects'] else '✗ Off',
                auto_save='✓ On' if settings['auto_save'] else '✗ Off',
                time_format=settings['time_format'],
                date_format=settings['date_format'],
                active_count=len(active),
                active_list='\n  '.join([f"• {item}" for item in active]) if active else "None"
            )
            
            msg = ctx["api"].send_message(ctx["channel_id"], ui_info)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "colors":
            palette = bot.customizer.color_palette
            colors_display = """```yaml
Color Palette:
  Background:  {background}
  Foreground:  {foreground}
  Accent:      {accent}
  Warning:     {warning}
  Error:       {error}
  Success:     {success}
  Info:        {info}

Example Usage:
  $customize color accent #ff00ff
  $customize color background #000000```""".format(**palette)
            
            msg = ctx["api"].send_message(ctx["channel_id"], colors_display)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "reset" and len(args) > 1:
            setting = args[1]
            if bot.customizer.reset_customization(setting):
                msg = ctx["api"].send_message(ctx["channel_id"], f"```yaml\nReset Complete:\n  Setting: {setting}\n  Status: ✓ Restored to default```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```yaml\nReset Failed:\n  Setting: {setting}\n  Status: ✗ Setting not found```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0].lower() == "save":
            try:
                import json
                with open("ui_config.json", "w") as f:
                    json.dump(bot.customizer.config, f, indent=2)
                msg = ctx["api"].send_message(ctx["channel_id"], "```yaml\nConfiguration Saved:\n  File: ui_config.json\n  Status: ✓ Success```")
            except:
                msg = ctx["api"].send_message(ctx["channel_id"], "```yaml\nSave Failed:\n  Status: ✗ Error writing file```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
    
    @bot.command(name="autoreact")
    def set_autoreact(ctx, args):
        if args:
            bot.auto_react_emoji = args[0]
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Auto-React |\nSet to: {args[0]}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
        else:
            bot.auto_react_emoji = None
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Auto-React disabled**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="mutualinfo")
    def mutualinfo(ctx, args):
        if not args:
            target_id = ctx["author_id"]
        else:
            target_id = args[0]
        
        user_info = ctx["api"].request("GET", f"/users/{target_id}")
        if not user_info or user_info.status_code != 200:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Mutual Info |\nCould not find user with ID {target_id}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_data = user_info.json()
        username = user_data.get("username", "Unknown")
        discriminator = user_data.get("discriminator", "0000")
        
        guilds_response = ctx["api"].request("GET", f"/users/{target_id}/guilds")
        mutual_guilds = []
        
        if guilds_response and guilds_response.status_code == 200:
            target_guilds = guilds_response.json()
            my_guilds = ctx["api"].get_guilds()
            my_guild_ids = [g["id"] for g in my_guilds]
            
            for guild in target_guilds:
                if guild["id"] in my_guild_ids:
                    mutual_guilds.append(guild["name"])
        
        if mutual_guilds:
            guilds_text = "\n- ".join(mutual_guilds[:10])
            if len(mutual_guilds) > 10:
                guilds_text += f"\n- ... and {len(mutual_guilds) - 10} more"
            
            msg_text = f"**User:** {username}#{discriminator}\nMutual Servers ({len(mutual_guilds)}):\n- {guilds_text}."
        else:
            msg_text = f"**User:** {username}#{discriminator}\nNo mutual servers found."
        
        msg = ctx["api"].send_message(ctx["channel_id"], msg_text)
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="closedms")
    def closedms(ctx, args):
        status_msg = ctx["api"].send_message(ctx["channel_id"], "> **Fetching** DM channels...")
        
        dms_response = ctx["api"].request("GET", "/users/@me/channels")
        if not dms_response or dms_response.status_code != 200:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "> **Failed** to fetch DMs.")
            delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
            return
        
        dm_data = dms_response.json()
        dm_channels = []
        
        for dm in dm_data:
            if dm.get("type") == 1:
                dm_channels.append(dm)
        
        if not dm_channels:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "> No **DM channels** to close.")
            delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
            return
        
        closed_count = 0
        total = len(dm_channels)
        
        ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"> **Closing** {total} DM channels...\nClosed: 0/{total}")
        
        for i, dm in enumerate(dm_channels):
            try:
                result = ctx["api"].request("DELETE", f"/channels/{dm['id']}")
                if result and result.status_code in [200, 204]:
                    closed_count += 1
                
                if (i + 1) % 5 == 0 or i == total - 1:
                    ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"Closing {total} DM channels...\nClosed: {closed_count}/{total}```")
                
                time.sleep(0.5)
            except:
                pass
        
        ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"> **Successfully*** closed {closed_count}/{total} DM channels.")
        delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
    
    @bot.command(name="setpfp")
    def setpfp(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Please** provide an **image URL**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        image_url = args[0]
        
        try:
            response = ctx["api"].session.get(image_url, timeout=10)
            if response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to download image.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            image_bytes = response.content
            content_type = response.headers.get('Content-Type', '')
            
            if 'gif' in content_type:
                image_format = 'gif'
            else:
                image_format = 'png'
            
            image_b64 = base64.b64encode(image_bytes).decode()
            
            data = {
                "avatar": f"data:image/{image_format};base64,{image_b64}"
            }
            
            result = ctx["api"].request("PATCH", "/users/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Successfully** updated profile picture.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Failed** to update PFP: {result.status_code if result else 'No response'}.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"Error: {str(e)}")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="servercopy")
    def servercopy(ctx, args):
        global LAST_SERVER_COPY
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> Please **provide** a **server ID** to copy.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        server_id = args[0]
        
        status_msg = ctx["api"].send_message(ctx["channel_id"], f"> **Fetching** server data for {server_id}...")
        
        guild_response = ctx["api"].request("GET", f"/guilds/{server_id}")
        if not guild_response or guild_response.status_code != 200:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "> **Could** not find **server** or no **access**.")
            delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
            return
        
        guild_data = guild_response.json()
        
        copy_data = {
            "name": guild_data.get("name", "Copied Server"),
            "icon": guild_data.get("icon", None),
            "roles": [],
            "channels": [],
            "categories": [],
            "emojis": []
        }
        
        roles_response = ctx["api"].request("GET", f"/guilds/{server_id}/roles")
        if roles_response and roles_response.status_code == 200:
            roles_data = roles_response.json()
            for role in roles_data:
                if not role.get("managed", False) and role.get("name") != "@everyone":
                    copy_data["roles"].append({
                        "name": role.get("name"),
                        "color": role.get("color", 0),
                        "permissions": role.get("permissions", 0),
                        "hoist": role.get("hoist", False),
                        "mentionable": role.get("mentionable", False),
                        "position": role.get("position", 0)
                    })
        
        channels_response = ctx["api"].request("GET", f"/guilds/{server_id}/channels")
        if channels_response and channels_response.status_code == 200:
            channels_data = channels_response.json()
            for channel in channels_data:
                channel_type = channel.get("type", 0)
                if channel_type == 4:
                    copy_data["categories"].append({
                        "name": channel.get("name"),
                        "position": channel.get("position", 0),
                        "overwrites": channel.get("permission_overwrites", [])
                    })
                elif channel_type == 0:
                    copy_data["channels"].append({
                        "type": "text",
                        "name": channel.get("name"),
                        "topic": channel.get("topic", ""),
                        "nsfw": channel.get("nsfw", False),
                        "position": channel.get("position", 0),
                        "parent_id": channel.get("parent_id"),
                        "overwrites": channel.get("permission_overwrites", [])
                    })
                elif channel_type == 2:
                    copy_data["channels"].append({
                        "type": "voice",
                        "name": channel.get("name"),
                        "bitrate": channel.get("bitrate", 64000),
                        "user_limit": channel.get("user_limit", 0),
                        "position": channel.get("position", 0),
                        "parent_id": channel.get("parent_id"),
                        "overwrites": channel.get("permission_overwrites", [])
                    })
        
        emojis_response = ctx["api"].request("GET", f"/guilds/{server_id}/emojis")
        if emojis_response and emojis_response.status_code == 200:
            emojis_data = emojis_response.json()
            for emoji in emojis_data:
                if emoji.get("available", True):
                    copy_data["emojis"].append({
                        "name": emoji.get("name"),
                        "animated": emoji.get("animated", False),
                        "url": f"https://cdn.discordapp.com/emojis/{emoji['id']}.{'gif' if emoji.get('animated', False) else 'png'}"
                    })
        
        LAST_SERVER_COPY = copy_data
        
        ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"> **Successfully** copied server: {guild_data.get('name', 'Unknown')}\nUse +serverload <target_id> to apply.")
        delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
    
    @bot.command(name="serverload")
    def serverload(ctx, args):
        global LAST_SERVER_COPY
        
        if not LAST_SERVER_COPY:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **No server** data to load. Use **servercopy** first.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> Please **provide** a target server ID.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        target_id = args[0]
        
        status_msg = ctx["api"].send_message(ctx["channel_id"], f"> **Loading** template into server {target_id}...```")
        
        try:
            if LAST_SERVER_COPY.get("icon"):
                icon_response = ctx["api"].session.get(f"https://cdn.discordapp.com/icons/{target_id}/{LAST_SERVER_COPY['icon']}.png", timeout=10)
                if icon_response.status_code == 200:
                    icon_bytes = icon_response.content
                    icon_b64 = base64.b64encode(icon_bytes).decode()
                    icon_data = f"data:image/png;base64,{icon_b64}"
                    
                    update_data = {
                        "name": LAST_SERVER_COPY["name"],
                        "icon": icon_data
                    }
                else:
                    update_data = {"name": LAST_SERVER_COPY["name"]}
            else:
                update_data = {"name": LAST_SERVER_COPY["name"]}
            
            guild_update = ctx["api"].request("PATCH", f"/guilds/{target_id}", data=update_data)
            if not guild_update or guild_update.status_code != 200:
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "> **Failed** to update **server name/icon**.")
                delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
                return
            
            existing_channels = ctx["api"].request("GET", f"/guilds/{target_id}/channels")
            if existing_channels and existing_channels.status_code == 200:
                for channel in existing_channels.json():
                    try:
                        ctx["api"].request("DELETE", f"/channels/{channel['id']}")
                        time.sleep(0.5)
                    except:
                        pass
            
            existing_roles = ctx["api"].request("GET", f"/guilds/{target_id}/roles")
            if existing_roles and existing_roles.status_code == 200:
                for role in existing_roles.json():
                    if not role.get("managed", False) and role.get("name") != "@everyone":
                        try:
                            ctx["api"].request("DELETE", f"/guilds/{target_id}/roles/{role['id']}")
                            time.sleep(0.5)
                        except:
                            pass
            
            role_map = {}
            for role_data in LAST_SERVER_COPY["roles"]:
                try:
                    role_create = {
                        "name": role_data["name"],
                        "color": role_data["color"],
                        "permissions": str(role_data["permissions"]),
                        "hoist": role_data["hoist"],
                        "mentionable": role_data["mentionable"]
                    }
                    
                    role_response = ctx["api"].request("POST", f"/guilds/{target_id}/roles", data=role_create)
                    if role_response and role_response.status_code == 200:
                        role_map[role_data["name"]] = role_response.json()["id"]
                    
                    time.sleep(0.5)
                except:
                    pass
            
            category_map = {}
            for category_data in LAST_SERVER_COPY["categories"]:
                try:
                    category_create = {
                        "name": category_data["name"],
                        "type": 4,
                        "position": category_data["position"]
                    }
                    
                    cat_response = ctx["api"].request("POST", f"/guilds/{target_id}/channels", data=category_create)
                    if cat_response and cat_response.status_code == 200:
                        category_map[category_data["name"]] = cat_response.json()["id"]
                    
                    time.sleep(0.5)
                except:
                    pass
            
            for channel_data in LAST_SERVER_COPY["channels"]:
                try:
                    channel_create = {
                        "name": channel_data["name"],
                        "type": 0 if channel_data["type"] == "text" else 2,
                        "position": channel_data["position"],
                        "parent_id": category_map.get(channel_data.get("parent_id")) if channel_data.get("parent_id") else None
                    }
                    
                    if channel_data["type"] == "text":
                        channel_create["topic"] = channel_data.get("topic", "")
                        channel_create["nsfw"] = channel_data.get("nsfw", False)
                    elif channel_data["type"] == "voice":
                        channel_create["bitrate"] = channel_data.get("bitrate", 64000)
                        channel_create["user_limit"] = channel_data.get("user_limit", 0)
                    
                    chan_response = ctx["api"].request("POST", f"/guilds/{target_id}/channels", data=channel_create)
                    
                    time.sleep(1)
                except:
                    pass
            
            for emoji_data in LAST_SERVER_COPY["emojis"]:
                try:
                    emoji_response = ctx["api"].session.get(emoji_data["url"], timeout=10)
                    if emoji_response.status_code == 200:
                        emoji_bytes = emoji_response.content
                        emoji_b64 = base64.b64encode(emoji_bytes).decode()
                        
                        emoji_create = {
                            "name": emoji_data["name"],
                            "image": f"data:image/{'gif' if emoji_data.get('animated', False) else 'png'};base64,{emoji_b64}"
                        }
                        
                        ctx["api"].request("POST", f"/guilds/{target_id}/emojis", data=emoji_create)
                        
                        time.sleep(0.5)
                except:
                    pass
            
            LAST_SERVER_COPY = None
            
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "> **Successfully** loaded **server* template!")
            delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
            
        except Exception as e:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Server Load |\nError: {str(e)}```")
            delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
    
    @bot.command(name="rpc", aliases=["rich_presence"])
    def rich_presence(ctx, args):
        if not args:
            help_text = """```asciidoc
| RPC Commands |
spotify "Song | Artist | Album | Duration [| image_url]"
listening "Details | State | Name [| image_url] [>> Button Label >> Button URL]"
streaming "Details | State | Name [| image_url] [>> Button Label >> Button URL]"
playing "Details | State | Name [| image_url] [>> Button Label >> Button URL]"
timer "Details | State | Name | Start | End [| image_url]"

Examples:
+rpc spotify "Song Name | Artist Name | Album Name | 3.5 | https://image.url"
+rpc listening "Playing my playlist | 15 tracks | Spotify | https://image.url >> Listen Now >> https://spotify.com"
+rpc streaming "Playing GTA V | In session | Twitch | https://image.url >> Watch Live >> https://twitch.tv"
+rpc playing "Level 85 | Questing | World of Warcraft | https://image.url"
+rpc timer "Workout session | 45 min left | Gym | 1700000000 | 1700003600 | https://image.url"```"""
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        parts = args[0].lower()
        remaining = " ".join(args[1:]) if len(args) > 1 else ""
        
        if parts == "stop":
            bot.set_activity(None)
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Cleared** all **activities**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if not remaining:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Missing** arguments.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        image_url = None
        button_label = None
        button_url = None
        details = None
        state = None
        name = None
        
        main_text = remaining
        
        if ' >> ' in main_text:
            btn_split = main_text.split(' >> ')
            if len(btn_split) >= 3:
                main_text = btn_split[0].strip()
                button_label = btn_split[1].strip()
                button_url = btn_split[2].strip()
            elif len(btn_split) == 2:
                main_text = btn_split[0].strip()
                button_label = btn_split[1].strip()
                button_url = "https://discord.com"
        
        if ' | ' in main_text:
            pipe_parts = [part.strip() for part in main_text.split('|')]
            
            if parts == "spotify":
                if len(pipe_parts) >= 4:
                    song = pipe_parts[0]
                    artist = pipe_parts[1]
                    album = pipe_parts[2]
                    duration = pipe_parts[3]
                    
                    if len(pipe_parts) >= 5:
                        image_url = pipe_parts[4]
                    if len(pipe_parts) >= 6:
                        current_pos = pipe_parts[5]
                    
                    details = song
                    state = artist
                    name = "Spotify"
            
            elif parts in ["listening", "streaming", "playing"]:
                if len(pipe_parts) >= 3:
                    details = pipe_parts[0]
                    state = pipe_parts[1]
                    name = pipe_parts[2]
                    
                    if len(pipe_parts) >= 4:
                        image_url = pipe_parts[3]
            
            elif parts == "timer":
                if len(pipe_parts) >= 5:
                    details = pipe_parts[0]
                    state = pipe_parts[1]
                    name = pipe_parts[2]
                    start_time = pipe_parts[3]
                    end_time = pipe_parts[4]
                    
                    if len(pipe_parts) >= 6:
                        image_url = pipe_parts[5]
        
        if parts == "spotify":
            try:
                if details and state and name:
                    duration_val = float(duration) if duration else 3.5
                    current_pos_val = float(current_pos) if 'current_pos' in locals() else 0
                    send_spotify_with_spoofing(bot, details, state, name, duration_val, current_pos_val, image_url)
                    msg_text = f"```| Spotify RPC |\nSong: {details}\nArtist: {state}\nAlbum: {name}\nDuration: {duration_val}min```"
                    if current_pos_val > 0:
                        msg_text = msg_text.replace("```", f"\nPosition: {current_pos_val}min```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = "```| Spotify RPC |\nFormat: Song | Artist | Album | Duration [| image_url] [| position]\nExample: +rpc spotify \"Song Name | Artist Name | Album Name | 3.5 | https://image.url | 1.5\"```"
            except Exception as e:
                msg_text = f"```| Spotify RPC |\nError: {str(e)}```"

        elif parts == "listening":
            try:
                if name:
                    send_listening_activity(bot, name, button_label, button_url, image_url, state, details)
                    msg_text = f"```| Listening RPC |\nName: {name}```"
                    if details:
                        msg_text = msg_text.replace("```", f"\nDetails: {details}```")
                    if state:
                        msg_text = msg_text.replace("```", f"\nState: {state}```")
                    if button_label:
                        msg_text = msg_text.replace("```", f"\nButton: {button_label}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = "```| Listening RPC |\nFormat: Details | State | Name [| image_url] [>> Button >> URL]\nExample: +rpc listening \"Playing playlist | 15 tracks | Spotify | https://image.url >> Listen Now >> https://spotify.com\"```"
            except Exception as e:
                msg_text = f"```| Listening RPC |\nError: {str(e)}```"

        elif parts == "streaming":
            try:
                if name:
                    send_streaming_activity(bot, name, button_label, button_url, image_url, state, details)
                    msg_text = f"```| Streaming RPC |\nName: {name}```"
                    if details:
                        msg_text = msg_text.replace("```", f"\nDetails: {details}```")
                    if state:
                        msg_text = msg_text.replace("```", f"\nState: {state}```")
                    if button_label:
                        msg_text = msg_text.replace("```", f"\nButton: {button_label}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = "```| Streaming RPC |\nFormat: Details | State | Name [| image_url] [>> Button >> URL]\nExample: +rpc streaming \"Playing GTA V | In session | Twitch | https://image.url >> Watch Live >> https://twitch.tv\"```"
            except Exception as e:
                msg_text = f"```| Streaming RPC |\nError: {str(e)}```"

        elif parts == "playing":
            try:
                if name:
                    send_playing_activity(bot, name, button_label, button_url, image_url, state, details)
                    msg_text = f"```| Playing RPC |\nGame: {name}```"
                    if details:
                        msg_text = msg_text.replace("```", f"\nDetails: {details}```")
                    if state:
                        msg_text = msg_text.replace("```", f"\nState: {state}```")
                    if button_label:
                        msg_text = msg_text.replace("```", f"\nButton: {button_label}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = "```| Playing RPC |\nFormat: Details | State | Name [| image_url] [>> Button >> URL]\nExample: +rpc playing \"Level 85 | Questing | World of Warcraft | https://image.url\"```"
            except Exception as e:
                msg_text = f"```| Playing RPC |\nError: {str(e)}```"

        elif parts == "timer":
            try:
                if name and 'start_time' in locals() and 'end_time' in locals():
                    start_val = float(start_time) if start_time else time.time()
                    end_val = float(end_time) if end_time else time.time() + 3600
                    send_timer_activity(bot, name, start_val, end_val, details, state, image_url)
                    duration_min = int((end_val - start_val) / 60)
                    msg_text = f"```| Timer RPC |\nActivity: {name}\nDuration: {duration_min}min```"
                    if details:
                        msg_text = msg_text.replace("```", f"\nDetails: {details}```")
                    if state:
                        msg_text = msg_text.replace("```", f"\nState: {state}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = "```| Timer RPC |\nFormat: Details | State | Name | Start | End [| image_url]\nExample: +rpc timer \"Workout session | 45 min left | Gym | 1700000000 | 1700003600 | https://image.url\"```"
            except Exception as e:
                msg_text = f"```| Timer RPC |\nError: {str(e)}```"

        else:
            msg_text = "```| RPC |\nInvalid type. Use: spotify, listening, streaming, playing, timer```"

        msg = ctx["api"].send_message(ctx["channel_id"], msg_text)
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="setserverpfp", aliases=["serverspfp", "guildpfp"])
    def setserverpfp(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Please** provide an **image URL**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        image_url = args[0]
        
        try:
            response = ctx["api"].session.get(image_url, timeout=10)
            if response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to download image.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            image_bytes = response.content
            content_type = response.headers.get('Content-Type', '')
            
            if 'gif' in content_type:
                image_format = 'gif'
            else:
                image_format = 'png'
            
            image_b64 = base64.b64encode(image_bytes).decode()
            
            guild_id = ctx["message"].get("guild_id")
            if not guild_id:
                msg = ctx["api"].send_message(ctx["channel_id"], "> This **command only works** in servers.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            data = {
                "avatar": f"data:image/{image_format};base64,{image_b64}"
            }
            
            result = ctx["api"].request("PATCH", f"/guilds/{guild_id}/members/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Successfully** updated **server** profile picture.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"\nFailed to update server PFP: {result.status_code if result else 'No response'}```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"\nError: {str(e)}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="stealpfp", aliases=["copypfp", "takepfp"])
    def stealpfp(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Please provide** a **user ID**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        
        try:
            user_response = ctx["api"].request("GET", f"/users/{user_id}")
            if not user_response or user_response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Could not** find user.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            user_data = user_response.json()
            avatar_hash = user_data.get("avatar")
            
            if not avatar_hash:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **User** has no profile picture.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            avatar_format = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{avatar_format}?size=1024"
            
            response = ctx["api"].session.get(avatar_url, timeout=10)
            if response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to download avatar.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            image_bytes = response.content
            image_b64 = base64.b64encode(image_bytes).decode()
            
            data = {
                "avatar": f"data:image/{avatar_format};base64,{image_b64}"
            }
            
            result = ctx["api"].request("PATCH", "/users/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Profile picture **stolen**.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Profile picture **failed**.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Profile picture **error**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="setbanner", aliases=["banner"])
    def setbanner(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Please provide** an **image URL**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        image_url = args[0]
        
        try:
            response = ctx["api"].session.get(image_url, timeout=10)
            if response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to download image.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            image_bytes = response.content
            content_type = response.headers.get('Content-Type', '')
            
            if 'gif' in content_type:
                image_format = 'gif'
            else:
                image_format = 'png'
            
            image_b64 = base64.b64encode(image_bytes).decode()
            
            data = {
                "banner": f"data:image/{image_format};base64,{image_b64}"
            }
            
            result = ctx["api"].request("PATCH", "/users/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Banner **updated**.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Banner **failed**.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Banner **error**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="stealbanner", aliases=["copybanner", "takebanner"])
    def stealbanner(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Please provide** a **user ID**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        
        try:
            profile_response = ctx["api"].request("GET", f"/users/{user_id}/profile")
            if not profile_response or profile_response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Could not fetch** user profile.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            profile_data = profile_response.json()
            # Check user_profile.banner first (preferred), then user.banner
            user_profile = profile_data.get("user_profile", {})
            user = profile_data.get("user", {})
            banner_hash = user_profile.get("banner") or user.get("banner")
            
            if not banner_hash:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **User** has no banner.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            banner_format = "gif" if banner_hash.startswith("a_") else "png"
            banner_url = f"https://cdn.discordapp.com/banners/{user_id}/{banner_hash}.{banner_format}?size=1024"
            
            response = ctx["api"].session.get(banner_url, timeout=10)
            if response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to download banner.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            image_bytes = response.content
            image_b64 = base64.b64encode(image_bytes).decode()
            
            data = {
                "banner": f"data:image/{banner_format};base64,{image_b64}"
            }
            
            result = ctx["api"].request("PATCH", "/users/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Banner **stolen successfully**.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Failed** to update banner.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Error** with banner steal.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="pronouns")
    def pronouns(ctx, args):
        if not args:
            target_id = ctx["author_id"]
        else:
            target_id = args[0]
        
        try:
            profile_response = ctx["api"].request("GET", f"/users/{target_id}/profile")
            if not profile_response or profile_response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Pronouns |\nCould not fetch user profile```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            profile_data = profile_response.json()
            pronouns = profile_data.get("user_profile", {}).get("pronouns", "")
            
            user_response = ctx["api"].request("GET", f"/users/{target_id}")
            if user_response and user_response.status_code == 200:
                user_data = user_response.json()
                username = user_data.get("username", "Unknown")
            else:
                username = "Unknown"
            
            if pronouns:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Pronouns |\nUser: {username}\nPronouns: {pronouns}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Pronouns |\nUser: {username}\nNo pronouns set```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Pronouns |\nError: {str(e)}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="setpronouns", aliases=["setpronoun"])
    def setpronouns(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Pronouns |\nUsage: +setpronouns <pronouns>\nExamples: he/him, she/her, they/them```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        pronouns = " ".join(args)
        
        try:
            data = {
                "pronouns": pronouns
            }
            
            result = ctx["api"].request("PATCH", "/users/@me/profile", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Pronouns |\n✓ Pronouns set to: {pronouns}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Pronouns |\n✗ Failed (HTTP {result.status_code if result else 'No response'})```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Pronouns |\nError: {str(e)[:80]}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="bio")
    def bio(ctx, args):
        if not args:
            target_id = ctx["author_id"]
        else:
            target_id = args[0]
        
        try:
            profile_response = ctx["api"].request("GET", f"/users/{target_id}/profile")
            if not profile_response or profile_response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Bio |\nCould not fetch user profile```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            profile_data = profile_response.json()
            bio_text = profile_data.get("user_profile", {}).get("bio", "")
            
            user_response = ctx["api"].request("GET", f"/users/{target_id}")
            if user_response and user_response.status_code == 200:
                user_data = user_response.json()
                username = user_data.get("username", "Unknown")
            else:
                username = "Unknown"
            
            if bio_text:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Bio |\nUser: {username}\nBio:\n{bio_text}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Bio |\nUser: {username}\nNo bio set```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Bio |\nError: {str(e)}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="setbio", aliases=["setaboutme"])
    def setbio(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Bio |\nUsage: +setbio <bio text>```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        bio_text = " ".join(args)
        
        try:
            data = {
                "bio": bio_text
            }
            
            result = ctx["api"].request("PATCH", "/users/@me/profile", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Bio |\n✓ Bio updated```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Bio |\n✗ Failed (HTTP {result.status_code if result else 'No response'})```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Bio |\nError: {str(e)[:80]}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="displayname", aliases=["globalname"])
    def displayname(ctx, args):
        if not args:
            target_id = ctx["author_id"]
        else:
            target_id = args[0]
        
        try:
            user_response = ctx["api"].request("GET", f"/users/{target_id}")
            if not user_response or user_response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Display Name |\nCould not find user```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            user_data = user_response.json()
            username = user_data.get("username", "Unknown")
            global_name = user_data.get("global_name", "")
            
            if global_name:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Display Name |\nUser: {username}\nDisplay Name: {global_name}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Display Name |\nUser: {username}\nNo display name set```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Display Name |\nError: {str(e)}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="setdisplayname", aliases=["setglobalname"])
    def setdisplayname(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Display Name |\nPlease provide a display name```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        display_name = " ".join(args)
        
        try:
            data = {
                "global_name": display_name
            }
            
            result = ctx["api"].request("PATCH", "/users/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Display name **updated**.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Display name **failed**.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Display name **error**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="stealname", aliases=["copyname"])
    def stealname(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Please provide** a **user ID**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        
        try:
            user_response = ctx["api"].request("GET", f"/users/{user_id}")
            if not user_response or user_response.status_code != 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Could not** find user.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            user_data = user_response.json()
            global_name = user_data.get("global_name", "")
            
            if not global_name:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **User** has no display name.")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            data = {
                "global_name": global_name
            }
            
            result = ctx["api"].request("PATCH", "/users/@me", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Display name **stolen**.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Display name **failed**.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Display name **error**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
        
    @bot.command(name="stop", aliases=["exit", "quit"])
    def stop_bot(ctx, args):
        msg = ctx["api"].send_message(ctx["channel_id"], "`Stopping bot...```")
        bot.stop()
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="setstatus", aliases=["customstatus"])
    def setstatus(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "` Set Status |\nPlease provide a status\nFormat: +setstatus [emoji,] status text\nExample: +setstatus 🎮 Gaming now\nExample: +setstatus <:pepe:123456789>, Custom status```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        import re
        
        full_text = " ".join(args)
        emoji_name = None
        emoji_id = None
        message = full_text.strip()
        
        if ',' in message:
            parts = message.split(',', 1)
            emoji_part = parts[0].strip()
            text_part = parts[1].strip() if len(parts) > 1 else ""
            
            if not text_part:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Status |\nPlease provide status text after comma```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            custom_emoji_pattern = r"<:([a-zA-Z0-9_]+):([0-9]+)>"
            custom_emoji_match = re.match(custom_emoji_pattern, emoji_part)
            
            if custom_emoji_match:
                emoji_name = custom_emoji_match.group(1)
                emoji_id = custom_emoji_match.group(2)
            
            elif len(emoji_part) == 1 or (len(emoji_part) > 1 and any(ord(c) > 127 for c in emoji_part)):
                emoji_name = emoji_part
            
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Status |\nInvalid emoji format\nUse standard emoji or <:name:id>```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            message = text_part
        
        if not message:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Status |\nPlease provide status text```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        data = {
            "custom_status": {
                "text": message,
                "emoji_name": emoji_name,
                "emoji_id": emoji_id
            }
        }
        
        try:
            result = ctx["api"].request("PATCH", "/users/@me/settings", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Status **updated**.")
            elif result and result.status_code == 429:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Status **rate limited**.")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Status **failed**.")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Status **error**.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="stealstatus", aliases=["copystatus"])
    def stealstatus(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Steal Status |\nPlease provide a user ID```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        
        try:
            user_response = ctx["api"].request("GET", f"/users/{user_id}")
            if user_response and user_response.status_code == 200:
                user_data = user_response.json()
                username = user_data.get("username", "Unknown")
            else:
                username = "Unknown"
            
            # Note: Custom status is not publicly available through Discord API
            # It can only be set on your own account via /users/@me/settings
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Steal Status |\nUser: {username}\nCustom status is private and cannot be retrieved```")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Steal Status |\nError: {str(e)[:80]}```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="help", aliases=["h"])
    def show_help(ctx, args):
        import formatter as fmt
        p = bot.prefix  # live prefix — auto-reflects config changes

        def help_page(title, *lines):
            return {"title": title, "lines": list(lines)}

        def format_native_lines(lines):
            formatted = []
            for line in lines:
                if isinstance(line, tuple) and len(line) == 2:
                    left, right = line
                    formatted.append(f"{fmt.CYAN}{left:<20}{fmt.DARK}:: {fmt.RESET}{fmt.WHITE}{right}{fmt.RESET}")
                elif isinstance(line, dict) and line.get("type") == "section":
                    formatted.append(f"{fmt.PURPLE}{fmt.BOLD}{line['text']}{fmt.RESET}")
                elif line == "":
                    formatted.append("")
                else:
                    formatted.append(f"{fmt.WHITE}{str(line)}{fmt.RESET}")
            return "\n".join(formatted)

        def render_help_page(page_name, content, current_page, total_pages):
            title = content.get("title", "Help")
            body = format_native_lines(content.get("lines", []))
            footer = content.get("footer") or f"{p}help {page_name} [1-{total_pages}]"
            return fmt.layout(title, body, footer)

        help_pages = {
            # ── Utility ──────────────────────────────────────────────────────
            "utility": {
                "title": f"{p}help Utility",
                "lines": [
                    ("ms", "Test bot latency"),
                    ("purge [amount]", "Delete your messages"),
                    ("guilds", "Count guilds"),
                    ("mutualinfo [user_id]", "Show mutual servers"),
                    ("autoreact [emoji]", "Auto-react to your messages"),
                    ("hypesquad <house>", "Set HypeSquad house"),
                    ("hypesquad_leave", "Leave HypeSquad"),
                    ("status <state>", "Set account status"),
                    ("client <type>", "Switch client type"),
                    ("setprefix <symbol>", "Change command prefix"),
                    ("customize", "UI/terminal customization"),
                    ("terminal", "Terminal settings"),
                    ("ui", "Interface settings"),
                    ("stop", "Stop bot"),
                    ("web", "Start read-only web panel"),
                    ("restart", "Restart bot"),
                ],
            },

            "ms": help_page(
                f"{p}ms",
                "Tests bot latency by measuring round-trip message time.",
                "",
                {"type": "section", "text": "Aliases"},
                "ping",
            ),

                        "purge": help_page(
                                f"{p}purge [amount]",
                                "Deletes your recent messages in the current channel.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("amount", "Number of messages to scan (default: 100)"),
                        ),

            "guilds": help_page(
                f"{p}guilds",
                "Displays the total number of servers the account is in.",
            ),

                        "mutualinfo": help_page(
                                f"{p}mutualinfo <user_id>",
                                "Shows all mutual servers shared with another user.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to check"),
                        ),

                        "autoreact": help_page(
                                f"{p}autoreact [emoji]",
                                "Toggles auto-react on your own messages.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("emoji", "Emoji to react with (omit to disable)"),
                        ),

                        "hypesquad": help_page(
                            f"{p}hypesquad <bravery|brilliance|balance>",
                            "Sets your Discord HypeSquad house.",
                            "",
                            {"type": "section", "text": "Aliases"},
                            "changehypesquad, hs",
                            "",
                            {"type": "section", "text": "Arguments"},
                            ("house", "One of bravery, brilliance, or balance"),
                        ),

                    "hypesquad_leave": help_page(
                    f"{p}hypesquad_leave",
                    "Leaves your current Discord HypeSquad house.",
                    "",
                    {"type": "section", "text": "Aliases"},
                    "leavehypesquad, hsl",
                    ),

                        "status": help_page(
                            f"{p}status <online|idle|dnd|invisible>",
                            "Changes your account presence status.",
                            "",
                            {"type": "section", "text": "Aliases"},
                            "setstatus, changestatus",
                            "",
                            {"type": "section", "text": "Arguments"},
                            ("state", "One of online, idle, dnd, or invisible"),
                        ),

                        "client": help_page(
                            f"{p}client <web|desktop|mobile>",
                            "Switches the client platform Discord sees for this session.",
                            "",
                            {"type": "section", "text": "Aliases"},
                            "clienttype, ct",
                            "",
                            {"type": "section", "text": "Arguments"},
                            ("type", "One of web, desktop, or mobile"),
                        ),

                        "setprefix": help_page(
                                f"{p}setprefix <symbol>",
                                "Changes the bot command prefix.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("symbol", "New prefix character or string"),
                        ),

            "customize": help_page(f"{p}customize", "Opens the UI/terminal customization menu."),

            "terminal": help_page(f"{p}terminal", "Opens terminal emulation settings."),

            "ui": help_page(f"{p}ui", "Opens the interface settings menu."),

            "stop": help_page(f"{p}stop", "Stops the bot process entirely."),

            "web": help_page(f"{p}web", "Starts a read-only web panel for monitoring the bot."),

            "restart": help_page(f"{p}restart", "Restarts the bot process."),

            # ── Messaging ────────────────────────────────────────────────────
            "messaging": {
                "title": f"{p}help Messaging",
                "lines": [
                    ("spam <count> <text>", "Spam messages"),
                    ("massdm <option> <msg>", "Mass DM (1=DM history, 2=friends, 3=both)"),
                    ("closedms", "Close all DM channels"),
                    ("superreact <user_id> <emoji>", "Auto super-react to a user"),
                    ("superreactlist", "List active super-reaction targets"),
                    ("superreactstart", "Start super-reaction worker"),
                    ("superreactstop [user_id]", "Stop worker or remove a target"),
                ],
            },

                        "spam": help_page(
                                f"{p}spam <count> <text>",
                                "Sends a message repeatedly in the current channel.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("count", "Number of times to send the message"),
                                ("text", "Message content to spam"),
                        ),

                        "massdm": help_page(
                                f"{p}massdm <option> <msg>",
                                "Sends a DM to a large group of users.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("option", "Who to DM"),
                                "1 = Users from DM history",
                                "2 = Friends list",
                                "3 = Both DM history and friends",
                                ("msg", "Message content to send"),
                        ),

                            "superreact": help_page(
                                f"{p}superreact <user_id> <emoji>",
                                "Adds a user target for automatic super-reactions.",
                                "",
                                {"type": "section", "text": "Aliases"},
                                "sr",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Target user ID or mention"),
                                ("emoji", "Emoji to use for super-reactions"),
                            ),

                        "superreactlist": help_page(
                        f"{p}superreactlist",
                        "Displays all configured super-reaction targets.",
                        "",
                        {"type": "section", "text": "Aliases"},
                        "srlist",
                        ),

                        "superreactstart": help_page(
                        f"{p}superreactstart",
                        "Starts the background super-reaction worker.",
                        "",
                        {"type": "section", "text": "Aliases"},
                        "srstart",
                        ),

                            "superreactstop": help_page(
                                f"{p}superreactstop [user_id]",
                                "Stops the super-reaction worker or removes a single target.",
                                "",
                                {"type": "section", "text": "Aliases"},
                                "srstop",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Optional target user ID or mention to remove"),
                            ),

            "closedms": help_page(f"{p}closedms", "Closes all open DM channels from your inbox."),

            # ── Profile ──────────────────────────────────────────────────────
            "profile": {
                "title": f"{p}help Profile",
                "lines": [
                    ("avatar [user_id]", "Get avatar/banner URLs"),
                    ("setpfp <url>", "Set profile picture"),
                    ("stealpfp <user_id>", "Steal user PFP"),
                    ("setbanner <url>", "Set banner"),
                    ("stealbanner <user_id>", "Steal user banner"),
                    ("setpronouns <text>", "Set pronouns"),
                    ("setbio <text>", "Set bio"),
                    ("setdisplayname <text>", "Set display name"),
                    ("stealname <user_id>", "Steal display name"),
                    ("setstatus [emoji,] text", "Set custom status"),
                    ("stealstatus <user_id>", "Steal user status"),
                    ("pronouns [user_id]", "View pronouns"),
                    ("bio [user_id]", "View bio"),
                    ("displayname [user_id]", "View display name"),
                    ("badges user <user_id>", "Scrape user badges"),
                ],
            },

                        "avatar": help_page(
                            f"{p}avatar [user_id]",
                            "Gets the avatar URL for yourself or another user, and includes the banner URL if available.",
                            "",
                            {"type": "section", "text": "Aliases"},
                            "av, pfp, pfpurl, getavatar",
                            "",
                            {"type": "section", "text": "Arguments"},
                            ("user_id", "Discord user ID to look up (optional, defaults to you)"),
                        ),

                        "setpfp": help_page(
                                f"{p}setpfp <url>",
                                "Sets your account profile picture from a URL.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("url", "Direct URL to a PNG or JPG image"),
                        ),

                        "stealpfp": help_page(
                                f"{p}stealpfp <user_id>",
                                "Copies another user profile picture and sets it as your own.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to copy the PFP from"),
                        ),

                        "setbanner": help_page(
                                f"{p}setbanner <url>",
                                "Sets your account profile banner from a URL.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("url", "Direct URL to a PNG or JPG image"),
                        ),

                        "stealbanner": help_page(
                                f"{p}stealbanner <user_id>",
                                "Copies another user banner and sets it as your own.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to copy banner from"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "copybanner, takebanner",
                        ),

                        "setpronouns": help_page(
                                f"{p}setpronouns <text>",
                                "Sets your account pronouns field.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("text", "Pronouns text (e.g. he/him, she/her, they/them)"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "setpronoun",
                        ),

                        "setbio": help_page(
                                f"{p}setbio <text>",
                                "Sets your account bio / about me section.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("text", "Bio text to display on your profile"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "setaboutme",
                        ),

                        "setdisplayname": help_page(
                                f"{p}setdisplayname <text>",
                                "Sets your global display name shown instead of username.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("text", "Display name to set"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "setglobalname",
                        ),

                        "stealname": help_page(
                                f"{p}stealname <user_id>",
                                "Copies another user display name and sets it as your own.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to copy display name from"),
                        ),

                        "setstatus": help_page(
                                f"{p}setstatus [emoji,] text",
                                "Sets your Discord custom status.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("emoji", "Optional emoji before the status (include trailing comma)"),
                                ("text", "Status message text"),
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}setstatus hello world",
                                f"{p}setstatus 👋, hey there",
                        ),

                        "stealstatus": help_page(
                                f"{p}stealstatus <user_id>",
                                "Copies another user custom status and sets it as your own.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to copy status from"),
                        ),

                        "pronouns": help_page(
                                f"{p}pronouns [user_id]",
                                "Displays pronouns for yourself or another user.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to look up (optional, defaults to you)"),
                        ),

                        "bio": help_page(
                                f"{p}bio [user_id]",
                                "Displays the bio/about me for yourself or another user.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to look up (optional, defaults to you)"),
                        ),

                        "displayname": help_page(
                                f"{p}displayname [user_id]",
                                "Displays the global display name for yourself or another user.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to look up (optional, defaults to you)"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "globalname",
                        ),

                        "badges": help_page(
                                f"{p}badges user <user_id>",
                                f"{p}badges server <server_id> [limit]",
                                "Scrapes Discord badges from a user or server members.",
                                "",
                                {"type": "section", "text": "Arguments (user)"},
                                ("user_id", "Discord user ID to fetch badges for"),
                                "",
                                {"type": "section", "text": "Arguments (server)"},
                                ("server_id", "Server ID to scrape member badges from"),
                                ("limit", "Max members to scan (optional)"),
                        ),

                        "badges user": help_page(
                                f"{p}badges user <user_id>",
                                "Fetches and displays all Discord badges on a user profile.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to look up"),
                        ),

                        "badges server": help_page(
                                f"[ {p}badges server <server_id> [limit] ]",
                                "Scrapes badges from members of a server.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("server_id", "ID of the server to scan"),
                                ("limit", "Max number of members to check (optional)"),
                        ),

            # ── Server ───────────────────────────────────────────────────────
            "server": {
                "title": f"{p}help Server",
                "lines": [
                    ("servercopy <server_id>", "Copy server structure"),
                    ("serverload <target_id>", "Load copied server"),
                    ("setserverpfp <url>", "Set server profile picture"),
                    ("badges server <server_id> [limit]", "Scrape server badges"),
                    ("myguilds", "List all your guilds"),
                    ("joininvite <code>", "Join server by invite code"),
                    ("leaveguild <guild_id>", "Leave a specific guild"),
                    ("massleave", "Mass leave from guilds"),
                    ("guildmembers <guild_id>", "List guild members"),
                ],
            },

                        "servercopy": help_page(
                                f"{p}servercopy <server_id>",
                                "Copies the channel and role structure of a server into memory.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("server_id", "ID of the server to copy"),
                        ),

                        "serverload": help_page(
                                f"{p}serverload <target_id>",
                                "Applies a previously copied server structure to a target server.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("target_id", "ID of the server to overwrite with copied structure"),
                        ),

                        "setserverpfp": help_page(
                                f"{p}setserverpfp <url>",
                                "Sets the current server profile picture from a URL.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("url", "Direct URL to a PNG or JPG image"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "serverspfp, guildpfp",
                        ),

            "myguilds": help_page(
                f"{p}myguilds",
                "Lists all guilds your account is a member of with details.",
                "",
                {"type": "section", "text": "Aliases"},
                "guilds, guildlist, servers",
            ),

                        "joininvite": help_page(
                                f"{p}joininvite <invite_code>",
                                "Joins a Discord server using an invite code.",
                                "",
                                {"type": "section", "text": "Aliases"},
                                "ji, joinserver",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("invite_code", "Discord invite code or URL"),
                        ),

                        "leaveguild": help_page(
                                f"{p}leaveguild <guild_id>",
                                "Leaves a specific guild.",
                                "",
                                {"type": "section", "text": "Aliases"},
                                "lg, leaveserver",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("guild_id", "Guild ID to leave"),
                        ),

            "massleave": help_page(
                f"{p}massleave",
                "Leaves multiple guilds at once.",
                "",
                {"type": "section", "text": "Aliases"},
                "ml, leaveall, leavemulti",
            ),

                        "guildmembers": help_page(
                                f"{p}guildmembers <guild_id>",
                                "Lists all members of a specific guild.",
                                "",
                                {"type": "section", "text": "Aliases"},
                                "members, gmembers, listmembers",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("guild_id", "Guild ID to list members from"),
                        ),

            # ── Token ────────────────────────────────────────────────────────
            "token": {
                "title": f"{p}help Token",
                "lines": [
                    ("checktoken <token>", "Validate a Discord token"),
                    ("bulkcheck", "Bulk token validation"),
                    ("exportguilds", "Export guild data from tokens"),
                ],
            },

                        "checktoken": help_page(
                                f"{p}checktoken <token>",
                                "Validates a Discord token and returns account information.",
                                "",
                                {"type": "section", "text": "Aliases"},
                                "ct, tokencheck, validatetoken",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("token", "Discord token to validate"),
                        ),

            "bulkcheck": help_page(
                f"{p}bulkcheck",
                "Validates multiple tokens in bulk for validity and account details.",
                "",
                {"type": "section", "text": "Aliases"},
                "bc, bulkvalidate, bvalidate",
            ),

            "exportguilds": help_page(
                f"{p}exportguilds",
                "Exports all guild data to a file (JSON format).",
                "",
                {"type": "section", "text": "Aliases"},
                "eg, dumpguilds, saveguilds",
            ),

            # ── Voice ────────────────────────────────────────────────────────
            "voice": {
                "title": f"{p}help Voice",
                "lines": [
                    ("vc [channel_id]", "Join voice/call"),
                    ("vce", "Leave voice/call"),
                    ("vccam [on/off]", "Toggle camera"),
                    ("vcstream [on/off]", "Toggle stream / Go Live"),
                ],
            },

                        "vc": help_page(
                                f"{p}vc [channel_id]",
                                "Joins a voice channel or call.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("channel_id", "ID of the voice channel to join (optional)"),
                                "Omit to join the channel you are currently in",
                        ),

            "vce": help_page(f"{p}vce", "Disconnects from the current voice channel or call."),

                        "vccam": help_page(
                                f"{p}vccam [on/off]",
                                "Toggles or sets the camera state in voice.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("on/off", "Explicitly turn camera on or off"),
                                "Omit to toggle current state",
                        ),

                        "vcstream": help_page(
                                f"{p}vcstream [on/off]",
                                "Toggles or sets the Go Live stream state in voice.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("on/off", "Explicitly start or stop streaming"),
                                "Omit to toggle current state",
                        ),

            # ── Social ───────────────────────────────────────────────────────
            "social": {
                "title": f"{p}help Social",
                "lines": [
                    ("block <user_id>", "Block user"),
                    ("rpc <type> <args>", "Set rich presence"),
                    ("join <invite>", "Join a server via invite"),
                ],
            },

                        "join": help_page(
                                f"{p}join <invite_code_or_url>",
                                "Joins a server using a Discord invite code or URL.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("invite", "Invite code (e.g. abc123) or full URL"),
                                "",
                                {"type": "section", "text": "Aliases"},
                                "joininvite, acceptinvite",
                        ),

                        "rpc": help_page(
                                f"{p}rpc <type> <args>",
                                "Sets a custom Rich Presence activity on your account.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("type", "Activity type (e.g. playing, watching, listening, competing)"),
                                ("args", "Activity name / detail text"),
                        ),

            # ── Boost ────────────────────────────────────────────────────────
            "boost": {
                "title": f"{p}help Boost",
                "lines": [
                    ("boost <server_id>", "Boost a server"),
                    ("boost transfer <to_id>", "Transfer all available boosts"),
                    ("boost auto <server1,server2,...>", "Auto-boost from list"),
                    ("boost rotate <server1,server2,...> [hours]", "Auto-rotation"),
                    ("boost stop", "Stop rotation"),
                    ("boost status", "Check boost status"),
                    ("boost list", "List boosted servers"),
                ],
            },

                        "boost transfer": help_page(
                                f"{p}boost transfer <to_id>",
                                "Transfers all available boost slots to a server.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("to_id", "Server ID to transfer all available boosts to"),
                                "",
                                {"type": "section", "text": "Shows"},
                                "Per-slot ANSI result (green tick / red cross)",
                                "Total success count out of attempted transfers",
                        ),

                        "boost auto": help_page(
                                f"{p}boost auto <server1,server2,...>",
                                "Distributes available boost slots across a list of servers.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("server1,server2,...", "Comma-separated server IDs (no spaces)"),
                        ),

                        "boost rotate": help_page(
                                f"{p}boost rotate <server1,server2,...> [hours]",
                                "Cycles boosts through a list of servers on a timer.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("server1,server2,...", "Comma-separated server IDs (no spaces)"),
                                ("hours", "Rotation interval in hours (default: 24)"),
                        ),

            "boost stop": help_page(f"{p}boost stop", "Stops the active boost rotation."),

                        "boost status": help_page(
                                f"{p}boost status",
                                "Shows a detailed overview of all boost slots.",
                                "",
                                {"type": "section", "text": "Shows"},
                                ("Total Slots", "Total boost slots on the account"),
                                ("Available", "Slots not currently in use"),
                                ("Used", "Slots actively boosting a server"),
                                ("On Cooldown", "Slots in Discord cooldown period"),
                                ("Boost N", "Time remaining until each slot expires"),
                        ),

            "boost list": help_page(f"{p}boost list", "Lists servers currently boosted by this account (up to 10)."),

            # ── Backup ───────────────────────────────────────────────────────
            "backup": {
                "title": f"{p}help Backup",
                "lines": [
                    ("backup user", "Backup user data, friends, guilds"),
                    ("backup messages <channel_id> [limit]", "Backup channel messages"),
                    ("backup full", "Create complete backup (zipped)"),
                    ("backup list", "List all backups"),
                    ("backup restore <filename>", "Restore from backup"),
                ],
            },

            "backup user": help_page(
                f"{p}backup user",
                "Saves a snapshot of your account data, friends list, and guild membership.",
            ),

                        "backup messages": help_page(
                                f"{p}backup messages <channel_id> [limit]",
                                "Downloads and saves messages from a channel.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("channel_id", "ID of the channel to backup"),
                                ("limit", "Max messages to save (optional, default: 100)"),
                        ),

            "backup full": help_page(
                f"{p}backup full",
                "Creates a complete zipped backup of all bot data and account info.",
            ),

            "backup list": help_page(
                f"{p}backup list",
                "Lists all available local backup files.",
            ),

                        "backup restore": help_page(
                                f"{p}backup restore <filename>",
                                "Restores data from a previously saved backup file.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("filename", f"Name of the backup file (from {p}backup list)"),
                        ),

            # ── Moderation ───────────────────────────────────────────────────
            "moderation": {
                "title": f"{p}help Moderation",
                "lines": [
                    ("mod kick <user_ids>", "Kick multiple users"),
                    ("mod ban <user_ids> [delete_days]", "Ban users"),
                    ("mod filter add <words>", "Add word filter"),
                    ("mod filter check <text>", "Check text against filters"),
                    ("mod cleanup channels", "Delete all channels"),
                    ("mod cleanup roles", "Delete all roles"),
                    ("mod members [limit]", "List server members"),
                    ("mod channels", "List all channels"),
                    ("mod roles", "List all roles"),
                ],
            },

                        "mod kick": help_page(
                                f"{p}mod kick <user_ids>",
                                "Kicks one or more users from the current server.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_ids", "Space-separated list of Discord user IDs"),
                        ),

                        "mod ban": help_page(
                                f"{p}mod ban <user_ids> [delete_days]",
                                "Bans one or more users from the current server.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_ids", "Space-separated list of Discord user IDs"),
                                ("delete_days", "Days of message history to delete (optional, 0-7)"),
                        ),

                        "mod filter": help_page(
                                f"{p}mod filter add <words>",
                                f"{p}mod filter check <text>",
                                "Manages the word filter list.",
                                "",
                                {"type": "section", "text": "Subcommands"},
                                ("add <words>", "Add words to the filter list"),
                                ("check <text>", "Check a string for filtered words"),
                        ),

                        "mod filter add": help_page(
                                f"{p}mod filter add <words>",
                                "Adds words to the word filter list.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("words", "Space-separated words to add"),
                        ),

                        "mod filter check": help_page(
                                f"{p}mod filter check <text>",
                                "Tests a string against the current word filter list.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("text", "Any text to check for filtered words"),
                        ),

                        "mod cleanup": help_page(
                                f"{p}mod cleanup channels",
                                f"{p}mod cleanup roles",
                                "Bulk-deletes all channels or all roles in the current server.",
                                "",
                                {"type": "section", "text": "Subcommands"},
                                ("channels", "Delete every channel in the server"),
                                ("roles", "Delete every role (excluding @everyone)"),
                        ),

            "mod cleanup channels": help_page(
                f"{p}mod cleanup channels",
                "Deletes every channel in the current server.",
            ),

            "mod cleanup roles": help_page(
                f"{p}mod cleanup roles",
                "Deletes every role in the current server (except @everyone).",
            ),

                        "mod members": help_page(
                                f"{p}mod members [limit]",
                                "Lists members in the current server.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("limit", "Max number of members to display (optional)"),
                        ),

            "mod channels": help_page(
                f"{p}mod channels",
                "Lists all channels in the current server with their IDs.",
            ),

            "mod roles": help_page(
                f"{p}mod roles",
                "Lists all roles in the current server with their IDs.",
            ),

            # ── Hosting ──────────────────────────────────────────────────────
            "hosting": {
                "title": f"{p}help Hosting",
                "lines": [
                    ("hoston", "Enable hosting for others (owner only)"),
                    ("hostoff", "Disable hosting for others (owner only)"),
                    ("host <token>", "Host a token"),
                    ("stophost", "Stop hosting your token"),
                    ("listhosted", "List your hosted tokens"),
                    ("listallhosted", "List all hosted tokens (owner only)"),
                    ("hoststopall", "Stop all hosted tokens (owner only)"),
                ],
            },

            "hoston": help_page(
                f"{p}hoston",
                "Enables the hosting feature so other users can host tokens.",
            ),

            "hostoff": help_page(
                f"{p}hostoff",
                "Disables the hosting feature, preventing others from hosting tokens.",
            ),

                        "host": help_page(
                                f"{p}host <token>",
                                "Starts hosting a Discord token through this bot instance.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("token", "Discord user token to host"),
                        ),

            "stophost": help_page(
                f"{p}stophost",
                "Stops hosting your currently hosted token.",
            ),

            "listhosted": help_page(
                f"{p}listhosted",
                "Lists all tokens you are currently hosting.",
            ),

            "listallhosted": help_page(
                f"{p}listallhosted",
                "Lists all tokens currently hosted by any user.",
            ),

            "hoststopall": help_page(
                f"{p}hoststopall",
                "Stops all hosted tokens from all users immediately.",
            ),

            # ── Owner ────────────────────────────────────────────────────────
            "owner": {
                "title": f"{p}help Owner - Developer Commands",
                "lines": [
                    {"type": "section", "text": "Core Developer Commands"},
                    (f"{p}drun", "Execute commands on multiple instances"),
                    (f"{p}dlog", "Manage developer logging"),
                    (f"{p}ddebug", "Toggle debug mode"),
                    (f"{p}dmetrics", "Show developer metrics"),
                    "",
                    {"type": "section", "text": "Guild Management (Multi-Instance)"},
                    (f"{p}djoininvite", "Join servers with instances"),
                    (f"{p}dleaveguild", "Leave specific guilds"),
                    (f"{p}dmyguilds", "List guilds for instances"),
                    (f"{p}dmassleave", "Leave multiple guilds"),
                    (f"{p}dguildmembers", "Show guild members"),
                    "",
                    {"type": "section", "text": "Token Management (Multi-Instance)"},
                    (f"{p}dchecktoken", "Validate token"),
                    (f"{p}dbulkcheck", "Check multiple tokens"),
                    (f"{p}dexportguilds", "Export guild list"),
                    "",
                    {"type": "section", "text": "Message Tracking"},
                    (f"{p}drecentmessages", "View tracked messages (flexible filtering)"),
                ],
            },

                        "drun": help_page(
                                f"{p}drun",
                                "Execute commands on multiple bot instances.",
                                "",
                                f"Format: {p}drun <uid/all/others> <channel_id> <cmd/say> [args...]",
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}drun 1 123456789 say Hello - Send message from UID 1",
                                f"{p}drun 1,2,3 123456789 say Hello - Send from multiple UIDs",
                                f"{p}drun all 123456789 cmd ping - Run ping on all instances",
                                f"{p}drun others 123456789 say Hello - Send from all except developer",
                                f"{p}drun 1,2,3 123456789 say -distribute hello hi hey - Different message per instance",
                        ),

                        "dlog": help_page(
                                f"{p}dlog",
                                "Manage developer logging settings.",
                                "",
                                {"type": "section", "text": "Subcommands"},
                                ("enable <type>", "Enable a logging type"),
                                ("disable <type>", "Disable a logging type"),
                                ("debug", "Toggle debug mode"),
                                ("list", "Show active logging"),
                                ("reset [type/all]", "Reset to defaults"),
                                ("metrics", "Show metrics"),
                        ),

            "ddebug": help_page(
                f"{p}ddebug",
                "Toggle debug mode on/off.",
                "",
                "Shows detailed debug information for development.",
            ),

            "dmetrics": help_page(
                f"{p}dmetrics",
                "Display current developer metrics and session stats.",
            ),

                        "djoininvite": help_page(
                                f"{p}djoininvite <uid/all/others> <invite_code>",
                                "Join a server with one or more bot instances.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Target instances (uid, all, or others)"),
                                ("invite_code", "Discord invite code (with or without discord.gg/)"),
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}djoininvite 1 abc123",
                                f"{p}djoininvite all discord.gg/abc123",
                                f"{p}djoininvite others abc123",
                        ),

                        "dleaveguild": help_page(
                                f"{p}dleaveguild <uid/all/others> <guild_id>",
                                "Leave a guild with one or more bot instances.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Target instances"),
                                ("guild_id", "Discord server ID to leave"),
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}dleaveguild 1 123456789",
                                f"{p}dleaveguild all 123456789",
                        ),

                        "dmyguilds": help_page(
                                f"{p}dmyguilds [uid/all/others]",
                                "List all guilds for bot instance(s).",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Target instances (default: all)"),
                                "",
                                "Shows summary of total guilds and owned servers for each instance.",
                        ),

                        "dmassleave": help_page(
                                f"{p}dmassleave <uid/all/others> [all|guild_id1 guild_id2...]",
                                "Leave multiple guilds at once.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Target instances"),
                                ("all", "Leave all guilds (except owned ones)"),
                                ("guild_id...", "Specific guild IDs to leave"),
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}dmassleave 1 all",
                                f"{p}dmassleave all 123456789 987654321",
                        ),

                        "dguildmembers": help_page(
                                f"{p}dguildmembers <uid/all/others> <guild_id> [limit]",
                                "Show members of a guild.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Target instances"),
                                ("guild_id", "Guild ID to list members from"),
                                ("limit", "Number of members to fetch (default: 20, max: 100)"),
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}dguildmembers 1 123456789",
                                f"{p}dguildmembers all 123456789 50",
                        ),

                        "dchecktoken": help_page(
                                f"{p}dchecktoken <uid/all/others> <token>",
                                "Validate and inspect a Discord token.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Instance to use for validation"),
                                ("token", "Discord token to check"),
                                "",
                                "Shows username, user ID, and account details if valid.",
                        ),

                        "dbulkcheck": help_page(
                                f"{p}dbulkcheck <uid> <token1> <token2> ...",
                                "Check multiple tokens at once.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid", "Instance to use for validation"),
                                ("token1, token2...", "Tokens to validate (max 20)"),
                                "",
                                "Shows validity status for each token with username if valid.",
                        ),

                        "dexportguilds": help_page(
                                f"{p}dexportguilds <uid/all/others> [filename]",
                                "Export guild list to JSON file.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("uid/all/others", "Target instances"),
                                ("filename", "Output filename (default: exported_guilds.json)"),
                                "",
                                "Creates JSON file with guild data (id, name, owner, member count).",
                        ),

                        "drecentmessages": help_page(
                                f"{p}drecentmessages [user] [amount] [channel]",
                                "Retrieve tracked messages from database with flexible filtering.",
                                "",
                                {"type": "section", "text": "Usage"},
                                f"{p}drecentmessages — Show most recent tracked messages in current channel",
                                f"{p}drecentmessages @user/ID — Show tracked messages from user",
                                f"{p}drecentmessages <amount> — Show X most recent tracked messages in channel",
                                f"{p}drecentmessages @user/ID <amount> — Show X recent messages from user",
                                f"{p}drecentmessages #channel — Show messages in specified channel",
                                f"{p}drecentmessages <amount> #channel — Show X messages in channel",
                                f"{p}drecentmessages @user/ID #channel — Show user messages in channel",
                                f"{p}drecentmessages @user/ID <amount> #channel — Show X user messages in channel",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user", "Target user (mention or ID) - optional"),
                                ("amount", "Number of messages (default: 10, max: 50) - optional"),
                                ("channel", "Target channel (mention or ID) - optional, defaults to current channel"),
                                "",
                                {"type": "section", "text": "Examples"},
                                f"{p}drecentmessages",
                                f"{p}drecentmessages @username 25",
                                f"{p}drecentmessages 123456789 #channel-name",
                                f"{p}drecentmessages @user 30 #general",
                        ),

            # ── AFK ──────────────────────────────────────────────────────────
            "afk": {
                "title": f"{p}help AFK",
                "lines": [
                    ("afk [reason]", "Set AFK status"),
                    ("afkstatus [user_id]", "Check AFK status"),
                    ("afkwebhook <url>", "Set notification webhook"),
                ],
            },

                        "afkstatus": help_page(
                                f"{p}afkstatus [user_id]",
                                "Checks the AFK status of yourself or another user.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to check (optional, defaults to you)"),
                        ),

                        "afkwebhook": help_page(
                                f"{p}afkwebhook <url>",
                                "Sets a webhook URL to receive notifications when someone mentions you while AFK.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("url", "Discord webhook URL to send notifications to"),
                        ),

            # ── Nitro ────────────────────────────────────────────────────────
            "nitro": {
                "title": f"{p}help Nitro",
                "lines": [
                    ("nitro on/off", "Toggle nitro sniper"),
                    ("giveaway [on|off]", "Manage giveaway sniper"),
                    ("nitro clear", "Clear used codes"),
                    ("nitro stats", "Show stats"),
                    ("nitro", "Show current status"),
                ],
            },

            "nitro on": help_page(f"{p}nitro on", "Enables the Nitro code sniper."),

            "nitro off": help_page(f"{p}nitro off", "Disables the Nitro code sniper."),

            "nitro clear": help_page(f"{p}nitro clear", "Clears the list of already-seen Nitro codes from memory."),

                    "giveaway": help_page(
                                f"{p}giveaway [on|off]",
                        "Shows giveaway sniper status or toggles it on and off.",
                        "",
                        {"type": "section", "text": "Aliases"},
                        "gw, gsnipe",
                        "",
                        {"type": "section", "text": "Arguments"},
                        ("on/off", "Optional toggle action; omit to show current stats"),
                    ),

                        "nitro stats": help_page(
                                f"{p}nitro stats",
                                "Shows Nitro sniper statistics.",
                                "",
                                {"type": "section", "text": "Shows"},
                                ("Codes Seen", "Total codes the sniper detected"),
                                ("Codes Claimed", "Codes successfully redeemed"),
                                ("Codes Failed", "Codes that were invalid or already used"),
                        ),

            # ── AGCT ─────────────────────────────────────────────────────────
            "agct": {
                "title": f"{p}help AGCT",
                "lines": [
                    ("agct on/off", "Toggle anti-GC trap"),
                    ("agct block on/off", "Toggle blocking creators"),
                    ("agct msg <text>", "Set leave message"),
                    ("agct name <name>", "Set GC name"),
                    ("agct icon <url>", "Set GC icon"),
                    ("agct webhook <url>", "Set alert webhook"),
                    ("agct wl add <user_id>", "Add to whitelist"),
                    ("agct wl remove <user_id>", "Remove from whitelist"),
                    ("agct wl list", "Show whitelist"),
                ],
            },

            "agct on": help_page(f"{p}agct on", "Enables the Anti-GC Trap system."),

            "agct off": help_page(f"{p}agct off", "Disables the Anti-GC Trap system."),

                        "agct block": help_page(
                                f"{p}agct block on/off",
                                "Toggles whether GC trap creators are automatically blocked.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("on", "Enable auto-blocking of trap creators"),
                                ("off", "Disable auto-blocking"),
                        ),

            "agct block on": help_page(f"{p}agct block on", "Enables auto-blocking of group chat trap creators."),

            "agct block off": help_page(f"{p}agct block off", "Disables auto-blocking of group chat trap creators."),

                        "agct msg": help_page(
                                f"{p}agct msg <text>",
                                "Sets the message sent in a GC trap before the bot leaves.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("text", "Message to send before leaving the group chat"),
                        ),

                        "agct name": help_page(
                                f"{p}agct name <name>",
                                "Sets the GC name string used to identify group chat traps.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("name", "GC name pattern to watch for"),
                        ),

                        "agct icon": help_page(
                                f"{p}agct icon <url>",
                                "Sets the icon URL used to identify group chat traps.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("url", "Image URL of the GC icon to watch for"),
                        ),

                        "agct webhook": help_page(
                                f"{p}agct webhook <url>",
                                "Sets a Discord webhook URL for AGCT alert notifications.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("url", "Discord webhook URL to send alerts to"),
                        ),

                        "agct wl": help_page(
                                f"{p}agct wl add <user_id>",
                                f"{p}agct wl remove <user_id>",
                                f"{p}agct wl list",
                                "Manages the AGCT whitelist of trusted users.",
                                "",
                                {"type": "section", "text": "Subcommands"},
                                ("add <user_id>", "Add a user to the whitelist"),
                                ("remove <user_id>", "Remove a user from the whitelist"),
                                ("list", "Show all whitelisted users"),
                        ),

                        "agct wl add": help_page(
                                f"{p}agct wl add <user_id>",
                                "Adds a user to the AGCT whitelist.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to whitelist"),
                        ),

                        "agct wl remove": help_page(
                                f"{p}agct wl remove <user_id>",
                                "Removes a user from the AGCT whitelist.",
                                "",
                                {"type": "section", "text": "Arguments"},
                                ("user_id", "Discord user ID to remove"),
                        ),

            "agct wl list": help_page(
                f"{p}agct wl list",
                "Displays all users currently on the AGCT whitelist.",
            ),

            # ── Raw ──────────────────────────────────────────────────────────
            "raw": {
                "title": f"{p}help Raw",
                "lines": [
                    ("cmdwall", "Display all commands in raw format"),
                ],
            },

            "cmdwall": help_page(
                f"{p}cmdwall",
                "Displays all registered bot commands in raw decorator format.",
                "",
                {"type": "section", "text": "Aliases"},
                "commandsraw, allcmds",
            ),

            # ── Quest ────────────────────────────────────────────────────────
            "quest": {
                "title": f"{p}help Quest",
                "lines": [
                    ("quest", "Show quest status and list"),
                    ("queststart", "Start auto-completing quests"),
                    ("queststop", "Stop auto-completing quests"),
                    ("questrefresh", "Refresh quest data from Discord"),
                ],
            },

            "queststart": help_page(
                f"{p}queststart",
                "Starts automatically completing available Nitro quests.",
            ),

            "queststop": help_page(
                f"{p}queststop",
                "Stops the quest auto-completion process.",
            ),

            "questrefresh": help_page(
                f"{p}questrefresh",
                "Fetches the latest quest data from Discord API.",
            ),

            "all": {
                "title": "All Commands",
                "lines": [
                    ("ms", "Test latency"),
                    ("spam <count> <text>", "Spam"),
                    ("purge [amount]", "Delete messages"),
                    ("massdm <option> <msg>", "Mass DM"),
                    ("block <user_id>", "Block user"),
                    ("guilds", "Count guilds"),
                    ("autoreact [emoji]", "Auto-react"),
                    ("hypesquad <house>", "Set HypeSquad house"),
                    ("hypesquad_leave", "Leave HypeSquad"),
                    ("status <state>", "Set account status"),
                    ("client <type>", "Switch client type"),
                    ("mutualinfo [user_id]", "Mutual servers"),
                    ("closedms", "Close DMs"),
                    ("avatar [user_id]", "Get avatar/banner URLs"),
                    ("superreact <user_id> <emoji>", "Add super-react target"),
                    ("superreactlist", "List super-react targets"),
                    ("superreactstart", "Start super-react worker"),
                    ("superreactstop [user_id]", "Stop worker or remove target"),
                    ("setprefix <symbol>", "Change prefix"),
                    ("setpfp <url>", "Set PFP"),
                    ("stealpfp <user_id>", "Steal PFP"),
                    ("setbanner <url>", "Set banner"),
                    ("stealbanner <user_id>", "Steal banner"),
                    ("setpronouns <text>", "Set pronouns"),
                    ("host <token>", "Host token"),
                    ("listhosted", "Your hosted tokens"),
                    ("afk [reason]", "Set AFK status"),
                    ("afkstatus [id]", "Check AFK"),
                    ("nitro on/off", "Nitro sniper"),
                    ("giveaway [on|off]", "Giveaway sniper"),
                    ("nitro clear", "Clear codes"),
                    ("badges user <user_id>", "User badges"),
                    ("stophost", "Stop hosting"),
                    ("listallhosted", "All hosted (owner)"),
                    ("setbio <text>", "Set bio"),
                    ("setdisplayname <text>", "Set display name"),
                    ("stealname <user_id>", "Steal name"),
                    ("setstatus [emoji,] text", "Set status"),
                    ("stealstatus <user_id>", "Steal status"),
                    ("pronouns [user_id]", "View pronouns"),
                    ("bio [user_id]", "View bio"),
                    ("displayname [user_id]", "View display"),
                    ("servercopy <server_id>", "Copy server"),
                    ("serverload <target_id>", "Load server"),
                    ("setserverpfp <url>", "Set server PFP"),
                    ("badges server <server_id> [limit]", "Server badges"),
                    ("vc [channel_id]", "Join voice/call"),
                    ("vce", "Leave voice/call"),
                    ("vccam [on/off]", "Toggle camera"),
                    ("vcstream [on/off]", "Stream / Go Live"),
                    ("customize", "UI customization"),
                    ("terminal", "Terminal settings"),
                    ("ui", "Interface settings"),
                    ("agct on/off", "Anti-GC trap"),
                    ("agct block on/off", "Block creators"),
                    ("agct msg <text>", "Leave message"),
                    ("agct name <name>", "GC name"),
                    ("agct icon <url>", "GC icon"),
                    ("agct webhook <url>", "Webhook"),
                    ("agct wl add/remove <id>", "Whitelist"),
                    ("backup user", "User backup"),
                    ("backup messages <ch>", "Message backup"),
                    ("backup full", "Full backup"),
                    ("backup list", "List backups"),
                    ("backup restore <file>", "Restore"),
                    ("mod kick <ids>", "Kick users"),
                    ("mod ban <ids>", "Ban users"),
                    ("mod filter", "Word filter"),
                    ("mod cleanup", "Clean channels/roles"),
                    ("mod members", "List members"),
                    ("mod channels", "List channels"),
                    ("mod roles", "List roles"),
                    ("web", "Start web panel"),
                    ("stop", "Stop bot"),
                    ("restart", "Restart bot"),
                    ("help [page]", "This help"),
                    (f"{p}drun", "Dev: Execute on instances"),
                    (f"{p}dlog", "Dev: Logging"),
                    (f"{p}ddebug", "Dev: Debug mode"),
                    (f"{p}dmetrics", "Dev: Metrics"),
                    (f"{p}djoininvite", "Dev: Join servers"),
                    (f"{p}dleaveguild", "Dev: Leave guilds"),
                    (f"{p}dmyguilds", "Dev: List guilds"),
                    (f"{p}dmassleave", "Dev: Mass leave"),
                    (f"{p}dguildmembers", "Dev: Guild members"),
                    (f"{p}dchecktoken", "Dev: Check token"),
                    (f"{p}dbulkcheck", "Dev: Bulk tokens"),
                    (f"{p}dexportguilds", "Dev: Export guilds"),
                    (f"{p}drecentmessages", "Dev: Messages"),
                ],
            },
        }

        if not args:
            categories = [
                ("Utility", f"{p}General Tools & Commands"),
                ("Messaging", f"{p}DM & Group Chat Protocols "),
                ("Profile", f"{p}User identity & Presence"),
                ("Server", f"{p}Guild settings & Configs"),
                ("Voice", f"{p}VC Commands"),
                ("Social", f"{p}Socials & Interactions"),
                ("Boost", f"{p} Boosts Commands"),
                ("Backup", f"{p}Data & config recovery"),
                ("Moderation", f"{p}Server & Anti-Nuke"),
                ("Hosting", f"{p}Auth & Account Access"),
                ("Token", f"{p}Session & Instance Management"),
                ("Owner", f"{p}Admin & Developer tools"),
                ("AFK", f"{p} Status & Auto-response"),
                ("Nitro", f"{p}Sniper and Gifts"),
                ("AGCT", f"{p} Anti-GC Trapping"),
                ("Quest", f"{p}Quest & task automation"),
            
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.command_page(
                    f"{p}help <category> or {p}help <command>",
                    categories,
                    f"{p}Developed By Misconsideration",
                ),
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        # Try full args as a compound key first (e.g. "boost transfer"), then fall back to args[0]
        full_page = " ".join(args).lower()
        
        # Check if last argument is a page number
        page_num = 1
        if args and args[-1].isdigit() and len(args) > 1:
            page_num = int(args[-1])
            # Rebuild the page key without the number
            full_page = " ".join(args[:-1]).lower()
        
        page = full_page if full_page in help_pages else args[0].lower() if args else page
        
        if page in help_pages:
            content = help_pages[page]
            lines = content.get("lines", [])
            lines_per_page = 25
            pages = []
            for index in range(0, len(lines), lines_per_page):
                page_slice = lines[index:index + lines_per_page]
                pages.append({
                    "title": content.get("title", "Help"),
                    "lines": page_slice,
                })

            if page_num < 1 or page_num > len(pages):
                page_num = 1

            content_to_send = pages[page_num - 1]
            rendered = render_help_page(page, content_to_send, page_num, len(pages))
            msg = ctx["api"].send_message(ctx["channel_id"], rendered)
            
            if 'msg' in locals() and msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
        else:
            page_options = "Available pages: utility, messaging, profile, server, voice, social, boost, backup, moderation, hosting, token, owner, afk, nitro, agct, raw, quest, all"
            error_body = f"{fmt.RED}Invalid page{fmt.RESET}\n{fmt.WHITE}{page_options}{fmt.RESET}"
            error_msg = fmt.layout("Help", error_body, f"{p}help all")
            
            msg = ctx["api"].send_message(ctx["channel_id"], error_msg)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="cmdwall", aliases=["commandsraw", "allcmds"])
    def cmdwall(ctx, args):
        all_commands = """```python
@bot.command(name="ms", aliases=["ping"])
@bot.command(name="spam")
@bot.command(name="purge")
@bot.command(name="massdm")
@bot.command(name="block")
@bot.command(name="guilds")
@bot.command(name="autoreact")
@bot.command(name="mutualinfo")
@bot.command(name="closedms")
@bot.command(name="setpfp")
@bot.command(name="stealpfp")
@bot.command(name="setserverpfp", aliases=["serverspfp", "guildpfp"])
@bot.command(name="setbanner", aliases=["banner"])
@bot.command(name="stealbanner", aliases=["copybanner", "takebanner"])
@bot.command(name="setpronouns", aliases=["setpronoun"])
@bot.command(name="pronouns")
@bot.command(name="setbio", aliases=["setaboutme"])
@bot.command(name="bio")
@bot.command(name="setdisplayname", aliases=["setglobalname"])
@bot.command(name="displayname", aliases=["globalname"])
@bot.command(name="stealname", aliases=["copyname"])
@bot.command(name="setstatus", aliases=["customstatus"])
@bot.command(name="stealstatus", aliases=["copystatus"])
@bot.command(name="servercopy")
@bot.command(name="serverload")
@bot.command(name="vc", aliases=["voice", "joinvc"])
@bot.command(name="vce", aliases=["leavevc", "disconnect"])
@bot.command(name="vccam", aliases=["cam", "camera"])
@bot.command(name="vcstream", aliases=["stream", "golive"])
@bot.command(name="rpc", aliases=["rich_presence"])
@bot.command(name="nitro")
@bot.command(name="afk")
@bot.command(name="afkwebhook")
@bot.command(name="afkstatus")
@bot.command(name="agct", aliases=["antigctrap"])
@bot.command(name="backup", aliases=["save"])
@bot.command(name="mod", aliases=["moderation"])
@bot.command(name="web", aliases=["panel"])
@bot.command(name="host")
@bot.command(name="stophost")
@bot.command(name="listhosted")
@bot.command(name="customize", aliases=["theme", "ui"])
@bot.command(name="terminal", aliases=["term", "shell"])
@bot.command(name="ui", aliases=["interface", "settings"])
@bot.command(name="help", aliases=["h"])
@bot.command(name="cmdwall", aliases=["commandsraw", "allcmds"])
@bot.command(name="stop", aliases=["exit", "quit"])
@bot.command(name="restart")
```"""
        
        if len(all_commands) > 2000:
            parts = []
            current = ""
            lines = all_commands.split('\n')
            
            for line in lines:
                if len(current + line + '\n') > 1990:
                    parts.append(current + "```")
                    current = "```python\n" + line + '\n'
                else:
                    current += line + '\n'
            
            if current:
                parts.append(current)
            
            for i, part in enumerate(parts):
                msg = ctx["api"].send_message(ctx["channel_id"], part)
                if msg and i < len(parts) - 1:
                    time.sleep(0.5)
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"), 3)
                elif msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], all_commands)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="restart")
    def restart_cmd(ctx, args):
        msg = ctx["api"].send_message(ctx["channel_id"], "> **Restarting** bot in 3 seconds...```")
        
        def restart_sequence():
            time.sleep(1)
            ctx["api"].edit_message(ctx["channel_id"], msg.get("id"), "> **Restarting** bot in 2 seconds...")
            time.sleep(1)
            ctx["api"].edit_message(ctx["channel_id"], msg.get("id"), "> **Restarting** bot in 1 second...")
            time.sleep(1)
            
            ctx["api"].send_message(ctx["channel_id"], "> **System** restarting...")
            
            import subprocess
            import sys
            
            time.sleep(0.5)
            
            python = sys.executable
            subprocess.Popen([python, "main.py"])
            
            time.sleep(1)
            bot.stop()
        
        threading.Thread(target=restart_sequence, daemon=True).start()
        
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"), 5)

    @bot.command(name="vc", aliases=["voice", "joinvc"])
    def vc(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Join VC** | Usage: +vc <channel_id>")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        channel_id = args[0]
        
        try:
            success = voice_manager.join_vc(channel_id)
            
            if success:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Connected to Voice** | Channel: **{channel_id}**")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to connect to voice channel")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Voice error**: {str(e)[:80]}")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="vce", aliases=["leavevc", "disconnect"])
    def vce(ctx, args):
        try:
            if args:
                success = voice_manager.leave_vc(args[0])
            else:
                success = voice_manager.leave_vc()
            
            if success:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Disconnected** from voice")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Not in** a voice channel")
            
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Voice error**: {str(e)[:80]}")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="vccam", aliases=["cam", "camera"])
    def vccam(ctx, args):
        enabled = True
        if args and args[0].lower() in ("off", "false", "0"):
            enabled = False
        channel_id = args[1] if len(args) > 1 else None
        try:
            ok, detail = voice_manager.set_video(channel_id, enabled)
            status = "enabled" if enabled else "disabled"
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Camera** {status}")
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Camera error**: {str(e)[:80]}")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="vcstream", aliases=["stream", "golive"])
    def vcstream(ctx, args):
        enabled = True
        if args and args[0].lower() in ("off", "stop", "false", "0"):
            enabled = False
        channel_id = args[1] if len(args) > 1 else None
        try:
            ok, detail = voice_manager.set_stream(channel_id, enabled)
            status = "started" if enabled else "stopped"
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Go Live** {status}")
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Stream error**: {str(e)[:80]}")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="quest", aliases=["questlist", "ql", "qstat"])
    def quest_cmd(ctx, args):
        ok, detail = quest_system.fetch_quests()
        s = quest_system.get_summary()
        lines = ["Quest Manager"]
        lines.append(f"Auto-complete :: {'Running' if s['running'] else 'Stopped'}")
        lines.append(f"Total :: {s['total']}")
        lines.append(f"Enrollable :: {len(s['enrollable'])}")
        lines.append(f"In Progress :: {len(s['completeable'])}")
        lines.append(f"Claimable  :: {len(s['claimable'])}")
        lines.append(f"Completed  :: {len(s['completed'])}")
        lines.append(f"Expired    :: {len(s['expired'])}")
        if s["last_fetch"]:
            lines.append(f"Last Fetch :: {time.strftime('%H:%M:%S', time.localtime(s['last_fetch']))}")
        for q in s["completeable"]:
            _, done, total = quest_system._get_progress(q)
            pct = int(done / total * 100) if total else 0
            worthy = " *" if quest_system._is_worthy(q) else ""
            lines.append(f"> {quest_system._quest_name(q)}{worthy} [{quest_system._task_type(q)}] {done}/{total} ({pct}%)")
        for q in s["enrollable"]:
            lines.append(f"> {quest_system._quest_name(q)} [enrollable]")
        for q in s["claimable"]:
            lines.append(f"> {quest_system._quest_name(q)} [claim now]")
        for q in s["completed"]:
            lines.append(f"> {quest_system._quest_name(q)} [done]")
        text = "```| " + " |\n".join(lines) + "```"
        msg = ctx["api"].send_message(ctx["channel_id"], text)
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="queststart", aliases=["qstart", "qs"])
    def queststart_cmd(ctx, args):
        quest_system.fetch_quests()
        ok, detail = quest_system.start()
        s = quest_system.get_summary()
        if ok:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Quest **enabled**. {detail}.")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], f"Quest error: {detail}.")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="queststop", aliases=["qstop", "qx"])
    def queststop_cmd(ctx, args):
        ok, detail = quest_system.stop()
        msg = ctx["api"].send_message(ctx["channel_id"], f"> **Quest **disabled**. {detail}.")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="questrefresh", aliases=["qr", "qrefresh"])
    def questrefresh_cmd(ctx, args):
        ok, detail = quest_system.fetch_quests()
        s = quest_system.get_summary()
        status = "Refreshed" if ok else "Failed"
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Quest |\n{status}: {detail}\nTotal: {s['total']} | Enrollable: {len(s['enrollable'])} | Claimable: {len(s['claimable'])}```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="questenroll", aliases=["qenroll", "qe"])
    def questenroll_cmd(ctx, args):
        quest_system.fetch_quests()
        s = quest_system.get_summary()
        enrollable = s["enrollable"]
        if not enrollable:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Quest |\nNo enrollable quests```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        enrolled = 0
        failed = 0
        for q in enrollable:
            status = quest_system.enroll(q)
            if status:
                q["user_status"] = status
                enrolled += 1
            else:
                failed += 1
            time.sleep(0.8)
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Quest Enroll |\nEnrolled: {enrolled} | Failed: {failed}```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="guildbadge", aliases=["gbadge", "grotate", "gb"])
    def guildbadge_cmd(ctx, args):
        gr = guild_rotator
        sub = args[0].lower() if args else ""

        if sub == "start":
            ok, detail = gr.start()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\n{detail}```")

        elif sub == "stop":
            ok, detail = gr.stop()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\n{detail}```")

        elif sub == "name" and len(args) >= 2:
            gr.config["tag_name"] = args[1]
            gr._save()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nTag name set to {args[1]}```")

        elif sub == "delay" and len(args) >= 2:
            try:
                secs = max(30, int(args[1]))
                gr.config["delay"] = secs
                gr._save()
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nDelay set to {secs}s```")
            except ValueError:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nInvalid number```")

        elif sub == "addguild" and len(args) >= 2:
            gid = args[1]
            if gid not in gr.config["guilds"]:
                gr.config["guilds"].append(gid)
                gr._save()
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nAdded guild {gid}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nGuild already in list```")

        elif sub == "removeguild" and len(args) >= 2:
            gid = args[1]
            if gid in gr.config["guilds"]:
                gr.config["guilds"].remove(gid)
                gr._save()
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nRemoved guild {gid}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nGuild not found```")

        elif sub == "addcolor" and len(args) >= 3:
            p, s = args[1], args[2]
            if gr._hex_re.match(p) and gr._hex_re.match(s):
                gr.config["colors"].append([p, s])
                gr._save()
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nAdded color {p} / {s}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nInvalid hex. Use #RRGGBB format```")

        elif sub == "removecolor" and len(args) >= 2:
            try:
                idx = int(args[1]) - 1
                colors = gr.config["colors"]
                if 0 <= idx < len(colors):
                    removed = colors.pop(idx)
                    gr._save()
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nRemoved {removed[0]} / {removed[1]}```")
                else:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nIndex out of range (1-{len(colors)})```")
            except ValueError:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge |\nInvalid index```")

        elif sub == "listbadges":
            badge_str = "  ".join(f"{bid}:{name}" for bid, name in _GUILDBADGE_BADGES.items())
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Guild Badge Types |\n{badge_str}```")

        else:
            # Status panel
            status = "Running" if gr.running else "Stopped"
            guilds = ", ".join(gr.config.get("guilds", [])) or "none"
            colors = gr.config.get("colors", [])
            lines = [
                "Guild Badge Rotator",
                f"Status :: {status}",
                f"Tag    :: {gr.config.get('tag_name', 'aria')}",
                f"Delay  :: {gr.config.get('delay', 180)}s",
                f"Guilds :: {guilds}",
                f"Colors :: {len(colors)} pairs",
                "",
                f"> {bot.prefix}guildbadge start/stop",
                f"> {bot.prefix}guildbadge name <tag>",
                f"> {bot.prefix}guildbadge delay <secs>",
                f"> {bot.prefix}guildbadge addguild/removeguild <id>",
                f"> {bot.prefix}guildbadge addcolor <#hex1> <#hex2>",
                f"> {bot.prefix}guildbadge removecolor <index>",
                f"> {bot.prefix}guildbadge listbadges",
            ]
            msg = ctx["api"].send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")

        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="host")
    def host_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Host |\n{bot.prefix}host <token>```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        # Non-owners need hosting to be enabled by owner
        if not is_control_user(ctx["author_id"]) and not host_manager.hosting_enabled:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Host |\nHosting is currently disabled```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        # Prefix is optional — last arg used as prefix only if it's a short symbol (1-3 chars, no dot)
        if len(args) > 1 and len(args[-1]) <= 3 and "." not in args[-1]:
            host_prefix = args[-1]
            token_input = " ".join(args[:-1])
        else:
            host_prefix = bot.prefix
            token_input = " ".join(args)

        # Resolve the hosted token's Discord user info
        hosted_user_id = ""
        hosted_username = ""
        try:
            clean_token = token_input.strip('"\' ')
            import requests
            r = requests.get(
                "https://discord.com/api/v9/users/@me",
                headers={"Authorization": clean_token},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                hosted_user_id = data.get("id", "")
                hosted_username = data.get("username", "") or data.get("global_name", "")
        except Exception:
            pass

        success, message = host_manager.host_token(
            ctx["author_id"], token_input,
            prefix=host_prefix,
            user_id=hosted_user_id,
            username=hosted_username,
        )

        msg = ctx["api"].send_message(ctx["channel_id"], f"> **Host: {message}**")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="stophost")
    def stophost_cmd(ctx, args):
        success, message = host_manager.stop_hosting(ctx["author_id"])
        msg = ctx["api"].send_message(ctx["channel_id"], f"> **Hosting **stopped**. {message}")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="listhosted")
    def listhosted_cmd(ctx, args):
        import formatter as fmt
        hosted = host_manager.list_hosted(ctx["author_id"])
        if not hosted:
            msg = ctx["api"].send_message(ctx["channel_id"], "```You have no hosted tokens```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        cmds = [("User", "#ID"), ("----", "---")]
        for u in hosted:
            name = u.get("username") or "Unknown"
            user_id = u.get("user_id", "?")
            cmds.append((name, f"#{user_id}"))
        status_msg = fmt.command_page("Your Hosted Tokens", cmds, f"{bot.prefix}host <token>")
        msg = ctx["api"].send_message(ctx["channel_id"], status_msg)
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="listallhosted")
    def listallhosted_cmd(ctx, args):
        import formatter as fmt
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Host")
            return
        hosted = host_manager.list_all_hosted()
        if not hosted:
            msg = ctx["api"].send_message(ctx["channel_id"], "No hosted users.")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        cmds = [("User", "#ID"), ("----", "---")]
        for u in hosted:
            name = u.get("username") or "Unknown"
            user_id = u.get("user_id", "?")
            cmds.append((name, f"#{user_id}"))
        status_msg = fmt.command_page("All Hosted Tokens", cmds, f"{bot.prefix}listallhosted")
        msg = ctx["api"].send_message(ctx["channel_id"], status_msg)
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="hoststopall")
    def hoststopall_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Host")
            return
        count = host_manager.stop_all()
        msg = ctx["api"].send_message(ctx["channel_id"], f"> **Hosting **stopped**. {count} token(s).")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="hoston")
    def hoston_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Host")
            return
        host_manager.hosting_enabled = True
        msg = ctx["api"].send_message(ctx["channel_id"], "> **Hosting **enabled**.")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="hostoff")
    def hostoff_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Host")
            return
        host_manager.hosting_enabled = False
        msg = ctx["api"].send_message(ctx["channel_id"], "> **Hosting **disabled**.")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="backup", aliases=["save"])
    def backup_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], """```asciidoc
| Backup Commands |
backup user :: Backup user data, friends, guilds
backup messages <channel_id> [limit] :: Backup channel messages
backup full :: Create complete backup (zipped)
backup list :: List all backups
backup restore <filename> :: Restore from backup

Examples:
+backup user
+backup messages 1234567890 500
+backup list```""")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0] == "user":
            filename = backup_manager.backup_user_data()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Backup |\n✓ User backup complete\nFile: {filename}```")
        
        elif args[0] == "messages" and len(args) >= 2:
            channel_id = args[1]
            limit = int(args[2]) if len(args) >= 3 else 1000
            filename = backup_manager.backup_messages(channel_id, limit)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Backup |\n✓ Message backup complete\nFile: {filename}\nMessages: {limit}```")
        
        elif args[0] == "full":
            filename = backup_manager.create_full_backup()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Backup |\n✓ Full backup complete\nFile: {filename}```")
        
        elif args[0] == "list":
            backups = backup_manager.list_backups()
            if backups:
                backup_list = "\n".join([f"• {b['name']} ({b['size']//1024}KB)" for b in backups[:10]])
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Backup List |\n{backup_list}\n\nTotal: {len(backups)} backups```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Backup |\nNo backups found```")
        
        elif args[0] == "restore" and len(args) >= 2:
            backup_name = args[1]
            success = backup_manager.restore_backup(backup_name)
            if success:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Backup |\n✓ Restored from {backup_name}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Backup |\n✗ Backup not found: {backup_name}```")
        
        if 'msg' in locals() and msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="mod", aliases=["moderation"])
    def mod_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], """```asciidoc
| Moderation Commands |
mod kick <user_id1,user_id2,...> :: Kick multiple users
mod ban <user_id1,user_id2,...> [delete_days] :: Ban users
mod filter add <word1,word2,...> :: Add word filter
mod filter check <text> :: Check text against filters
mod cleanup channels :: Delete all channels
mod cleanup roles :: Delete all roles
mod members [limit] :: List server members
mod channels :: List all channels
mod roles :: List all roles

Examples:
+mod kick 1111111111,2222222222
+mod ban 1111111111,2222222222 1
+mod filter add bad,word,here```""")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        guild_id = ctx["message"].get("guild_id")
        if not guild_id:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Moderation |\n✗ This command only works in servers```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0] == "kick" and len(args) >= 2:
            user_ids = args[1].split(',')
            count = mod_manager.mass_kick(guild_id, user_ids)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\n✓ Kicked {count}/{len(user_ids)} users```")
        
        elif args[0] == "ban" and len(args) >= 2:
            user_ids = args[1].split(',')
            delete_days = int(args[2]) if len(args) >= 3 else 0
            count = mod_manager.mass_ban(guild_id, user_ids, delete_days)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\n✓ Banned {count}/{len(user_ids)} users\nDelete days: {delete_days}```")
        
        elif args[0] == "filter":
            if len(args) >= 3 and args[1] == "add":
                words = args[2].split(',')
                count = mod_manager.create_word_filter(guild_id, words)
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\n✓ Added {count} words to filter```")
            elif len(args) >= 3 and args[1] == "check":
                text = " ".join(args[2:])
                match = mod_manager.check_message_filter(guild_id, text)
                if match:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\n✗ Filter matched: {match}```")
                else:
                    msg = ctx["api"].send_message(ctx["channel_id"], "```| Moderation |\n✓ No filter matches```")
        
        elif args[0] == "cleanup":
            if len(args) >= 2 and args[1] == "channels":
                channels = mod_manager.get_channels(guild_id)
                channel_ids = [c["id"] for c in channels]
                count = mod_manager.mass_delete_channels(guild_id, channel_ids)
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\n✓ Deleted {count}/{len(channel_ids)} channels```")
            elif len(args) >= 2 and args[1] == "roles":
                roles = mod_manager.get_roles(guild_id)
                role_ids = [r["id"] for r in roles if not r.get("managed", False) and r["name"] != "@everyone"]
                count = mod_manager.mass_delete_roles(guild_id, role_ids)
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\n✓ Deleted {count}/{len(role_ids)} roles```")
        
        elif args[0] == "members":
            limit = int(args[1]) if len(args) >= 2 else 100
            members = mod_manager.get_members(guild_id, limit)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\nMembers: {len(members)}/{limit}\nUse IDs for kick/ban commands```")
        
        elif args[0] == "channels":
            channels = mod_manager.get_channels(guild_id)
            channel_list = "\n".join([f"#{c['name']}: {c['id']}" for c in channels[:15]])
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\nChannels: {len(channels)}\n{channel_list}\n{'...' if len(channels) > 15 else ''}```")
        
        elif args[0] == "roles":
            roles = mod_manager.get_roles(guild_id)
            role_list = "\n".join([f"@{r['name']}: {r['id']}" for r in roles[:15]])
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Moderation |\nRoles: {len(roles)}\n{role_list}\n{'...' if len(roles) > 15 else ''}```")
        
        if 'msg' in locals() and msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="web", aliases=["panel"])
    def web_cmd(ctx, args):
        started = web_panel.start()
        status_line = "Started web interface" if started else "Web interface already running"
        msg = ctx["api"].send_message(ctx["channel_id"], f"""```asciidoc
| Web Panel |
    {status_line}:
http://127.0.0.1:8080

Features:
• View bot status
• View history/boost snapshot
• Refresh status panel

Note: Discord remains the only command interface```""")
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    original_run_command = bot.run_command
    def new_run_command(cmd_name, ctx, args):
        # delete_command_message(ctx["api"], ctx["channel_id"], ctx["message"]["id"])  # Commented out to speed up
        original_run_command(cmd_name, ctx, args)
    
    bot.run_command = new_run_command
    
    def check_for_github_updates(message_data):
        return github_updater.check_message(message_data)
    
    original_process_message = bot._handle_message
    
    def new_process_message(message_data):
        content = message_data.get("content", "")

        if check_for_github_updates(message_data):
            return

        if anti_gc_trap.check_gc_creation(message_data):
            pass

        author_id = message_data.get("author", {}).get("id")
        guild_id = message_data.get("guild_id")
        channel_id = message_data.get("channel_id")
        msg_id = message_data.get("id")
        is_control = is_control_user(author_id)
        is_hosted = is_hosted_user(author_id)

        # ------------------------------------------------------------------
        # Hosted-user command routing
        # If a saved hosted user sends a message with their configured prefix,
        # route it through the bot's command system on their behalf.
        # ------------------------------------------------------------------
        if content and author_id and author_id != bot.user_id:
            for entry in host_manager.saved_users.values():
                if entry.get("user_id") == author_id:
                    hosted_prefix = entry.get("prefix", bot.prefix)
                    if content.startswith(hosted_prefix) and len(content) > len(hosted_prefix):
                        ctx = {
                            "message": message_data,
                            "channel_id": channel_id,
                            "author_id": author_id,
                            "api": bot.api,
                            "bot": bot,
                        }
                        parts = content[len(hosted_prefix):].strip().split()
                        if parts:
                            bot.run_command(parts[0].lower(), ctx, parts[1:])
                    break

        # Ignore normal message handling for anyone who is not hosted.
        # Control users still need access to owner/developer management paths.
        if author_id and author_id != bot.user_id and not is_hosted and not is_control:
            return
        
        # Super react is handled by SuperReactClient WebSocket
        # if author_id in super_react.targets:
        #     super_react.executor.submit(super_react._react_single, guild_id, channel_id, msg_id, super_react.targets[author_id])
        
        # if author_id in super_react.msr_targets:
        #     emojis, idx = super_react.msr_targets[author_id]
        #     emoji = emojis[idx]
        #     super_react.executor.submit(super_react._react_single, guild_id, channel_id, msg_id, emoji)
        #     super_react.msr_targets[author_id] = (emojis, (idx + 1) % len(emojis))
        
        # if author_id in super_react.ssr_targets:
        #     for emoji in super_react.ssr_targets[author_id]:
        #         super_react.executor.submit(super_react._react_single, guild_id, channel_id, msg_id, emoji)
        
        if content:
            author_id = message_data.get("author", {}).get("id", "")
            
            if f"<@{bot.user_id}>" in content or f"<@!{bot.user_id}>" in content:
                if afk_system.is_afk(author_id):
                    afk_data = afk_system.get_afk_info(author_id)
                    afk_since = int(time.time() - afk_data["since"])
                    
                    hours = afk_since // 3600
                    minutes = (afk_since % 3600) // 60
                    
                    time_str = ""
                    if hours > 0:
                        time_str += f"{hours}h "
                    if minutes > 0 or hours == 0:
                        time_str += f"{minutes}m"
                    
                    channel_id = message_data.get("channel_id")
                    if channel_id:
                        bot.api.send_message(channel_id, f"```| AFK Notice |\nUser <@{author_id}> is AFK\nReason: {afk_data['reason']}\nDuration: {time_str}```")

        if is_control and developer_tools.process_message(message_data, bot):
            return

        original_process_message(message_data)
    
    @bot.command(name="history", aliases=["hist"])
    def history_cmd(ctx, args):
        if not args:
            help_text = """```asciidoc
| History Commands |
history user <user_id> :: View user profile history
history server <server_id> :: View server history  
history scrape user <user_id> :: Scrape user profile (only if bot shares server)
history scrape server <server_id> :: Scrape server data
history scrape all :: Scrape all accessible data
history scrape queue <user_id> [user_id2 ...] :: Queue users for scraping
history scrape process :: Process queued users
history changes user <user_id> :: Show user profile changes
history changes server <server_id> :: Show server changes
history stats :: Show history statistics
history health :: Show system health status

Background scraping is disabled. Use +localstats and +export instead.
```"""
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0] == "user" and len(args) >= 2:
            user_id = args[1]
            history = history_manager.get_user_history(user_id)
            
            if not history:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| User History |\nNo history found for user {user_id}```")
            else:
                latest = history[-1]
                history_text = f"""```asciidoc
| User Profile History |
User: {latest.get('username', 'Unknown')}#{latest.get('discriminator', '0000')}
ID: {user_id}
Snapshots: {len(history)}
Latest: {time.strftime('%Y-%m-%d %H:%M', time.localtime(latest['timestamp']))}

Current Profile
Username: {latest.get('username', 'N/A')}
Display Name: {latest.get('global_name', 'N/A')}
Bio: {latest.get('bio', 'N/A') or 'None'}
Pronouns: {latest.get('pronouns', 'N/A') or 'None'}
Server Nick: {latest.get('nick', 'N/A') or 'None'}
Avatar: {'Yes' if latest.get('avatar') else 'No'}
Banner: {'Yes' if latest.get('banner') else 'No'}
Connected Accounts: {len(latest.get('connected_accounts', []))}
Shared Servers Seen: {latest.get('mutual_guild_count', len(latest.get('source_guild_ids', [])))}
Nitro: {'Yes' if latest.get('premium_type') else 'No'}```"""
                msg = ctx["api"].send_message(ctx["channel_id"], history_text)
        
        elif args[0] == "server" and len(args) >= 2:
            server_id = args[1]
            history = history_manager.get_server_history(server_id)
            
            if not history:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Server History |\nNo history found for server {server_id}```")
            else:
                latest = history[-1]
                history_text = f"""```asciidoc
| Server History |
Server: {latest.get('name', 'Unknown')}
ID: {server_id}
Snapshots: {len(history)}
Latest: {time.strftime('%Y-%m-%d %H:%M', time.localtime(latest['timestamp']))}

Current Server Info
Members: {latest.get('approximate_member_count', 'Unknown')}
Boosts: {latest.get('premium_subscription_count', 0)}
Channels: {len(latest.get('channels', []))}
Roles: {len(latest.get('roles', []))}
Owner: {latest.get('owner_id', 'Unknown')}
Region: {latest.get('region', 'Unknown')}```"""
                msg = ctx["api"].send_message(ctx["channel_id"], history_text)
        
        elif args[0] == "scrape" and len(args) >= 2:
            if args[1] == "user" and len(args) >= 3:
                user_id = args[2]
                profile_data = history_manager.scrape_user_profile(user_id)
                
                if profile_data:
                    history_manager.add_profile_snapshot(user_id, profile_data)
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Profile Scraped |\nUser: {profile_data.get('username', 'Unknown')}\nStatus: ✓ Success```")
                else:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Profile Scrape Failed |\nUser ID: {user_id}\nStatus: ✗ Failed```")
            
            elif args[1] == "server" and len(args) >= 3:
                server_id = args[2]
                server_data = history_manager.scrape_server_data(server_id)
                
                if server_data:
                    history_manager.add_server_snapshot(server_id, server_data)
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Server Scraped |\nServer: {server_data.get('name', 'Unknown')}\nStatus: ✓ Success```")
                else:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Server Scrape Failed |\nServer ID: {server_id}\nStatus: ✗ Failed```")
            
            elif args[1] == "all":
                # Scrape all accessible servers and some recent users
                status_msg = ctx["api"].send_message(ctx["channel_id"], "```| Mass Scraping |\nStarting data collection...```")
                
                servers_scraped = 0
                users_scraped = 0
                
                # Get all guilds
                guilds_response = ctx["api"].request("GET", "/users/@me/guilds")
                if guilds_response and guilds_response.status_code == 200:
                    guilds = guilds_response.json()
                    
                    for guild in guilds[:10]:  # Limit to first 10 servers
                        server_data = history_manager.scrape_server_data(guild['id'])
                        if server_data:
                            history_manager.add_server_snapshot(guild['id'], server_data)
                            servers_scraped += 1
                        
                        # Try to scrape some members from this server
                        members = history_manager.scrape_all_guild_members(guild['id'], limit=50)
                        for member in members[:5]:  # Limit to 5 members per server
                            user_id = member['user_id']
                            if user_id not in history_manager.profiles:  # Only scrape if we don't have history
                                profile_data = history_manager.scrape_user_profile(user_id)
                                if profile_data:
                                    history_manager.add_profile_snapshot(user_id, profile_data)
                                    users_scraped += 1
                
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass Scraping Complete |\nServers: {servers_scraped}\nUsers: {users_scraped}\nStatus: ✓ Complete```")
                delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
                return
            
            elif args[1] == "queue":
                # Queue users for scraping
                if len(args) >= 3:
                    user_ids = args[2:]
                    queued_count = 0
                    
                    for user_id in user_ids:
                        if history_manager.add_user_to_scrape(user_id):
                            queued_count += 1
                    
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Users Queued |\nAdded {queued_count} users to scrape queue\nTotal queued: {len(history_manager.get_users_to_scrape())}```")
                else:
                    queued_users = history_manager.get_users_to_scrape()
                    if queued_users:
                        queue_text = f"```| Scrape Queue |\nTotal queued: {len(queued_users)}\n\n"
                        for i, user_id in enumerate(list(queued_users)[:10], 1):
                            queue_text += f"{i}. {user_id}\n"
                        if len(queued_users) > 10:
                            queue_text += f"... and {len(queued_users) - 10} more\n"
                        queue_text += "```"
                        msg = ctx["api"].send_message(ctx["channel_id"], queue_text)
                    else:
                        msg = ctx["api"].send_message(ctx["channel_id"], "```| Scrape Queue |\nNo users queued for scraping```")
            
            elif args[1] == "process":
                # Process the queued users
                status_msg = ctx["api"].send_message(ctx["channel_id"], "```| Processing Queue |\nStarting profile scraping...```")
                history_manager.scrape_queued_users()
                queued_remaining = len(history_manager.get_users_to_scrape())
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Queue Processed |\nRemaining in queue: {queued_remaining}\nStatus: ✓ Complete```")
                delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
                return
        
        elif args[0] == "changes" and len(args) >= 3:
            if args[1] == "user" and len(args) >= 3:
                user_id = args[2]
                changes = history_manager.get_user_profile_changes(user_id)
                
                if not changes:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| User Changes |\nNo changes found for user {user_id}```")
                else:
                    changes_text = f"```| User Profile Changes |\nUser ID: {user_id}\nTotal Changes: {len(changes)}\n\n"
                    
                    for i, change in enumerate(changes[-5:], 1):  # Show last 5 changes
                        changes_text += f"[ Change {i} - {time.strftime('%m/%d %H:%M', time.localtime(change['timestamp']))} ]\n"
                        for field, change_data in change['changes'].items():
                            changes_text += f"> {field}: {change_data['from'] or 'None'} → {change_data['to'] or 'None'}\n"
                        changes_text += "\n"
                    
                    changes_text += "```"
                    msg = ctx["api"].send_message(ctx["channel_id"], changes_text)
            
            elif args[1] == "server" and len(args) >= 3:
                server_id = args[2]
                changes = history_manager.get_server_changes(server_id)
                
                if not changes:
                    msg = ctx["api"].send_message(ctx["channel_id"], f"```| Server Changes |\nNo changes found for server {server_id}```")
                else:
                    changes_text = f"```| Server Changes |\nServer ID: {server_id}\nTotal Changes: {len(changes)}\n\n"
                    
                    for i, change in enumerate(changes[-5:], 1):  # Show last 5 changes
                        changes_text += f"[ Change {i} - {time.strftime('%m/%d %H:%M', time.localtime(change['timestamp']))} ]\n"
                        for field, change_data in change['changes'].items():
                            changes_text += f"> {field}: {change_data['from'] or 'None'} → {change_data['to'] or 'None'}\n"
                        changes_text += "\n"
                    
                    changes_text += "```"
                    msg = ctx["api"].send_message(ctx["channel_id"], changes_text)
        
        elif args[0] == "stats":
            total_profiles = len(history_manager.profiles)
            total_servers = len(history_manager.servers)
            total_snapshots = sum(len(snapshots) for snapshots in history_manager.profiles.values()) + \
                            sum(len(snapshots) for snapshots in history_manager.servers.values())
            
            stats_text = f"""```| History Statistics
Total Profiles Tracked: {total_profiles}
Total Servers Tracked: {total_servers}
Total Snapshots: {total_snapshots}
Storage File: history_data.json
Last Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}```"""
            
            msg = ctx["api"].send_message(ctx["channel_id"], stats_text)
        
        elif args[0] == "auto" and len(args) >= 2:
            msg = ctx["api"].send_message(ctx["channel_id"], "```asciidoc |\nHistory Auto-Scrape\nDisabled. Use +localstats for summaries and +export for real-time account data.```")
        
        elif args[0] == "health":
            health_status = history_manager.perform_health_check()
            health_text = f"""```asciidoc
| History System Health |
Status: {'✓ Healthy' if health_status['healthy'] else '✗ Issues Detected'}
API Response Time: {health_status['metrics']['last_api_call']:.1f}s ago
Consecutive Failures: {health_status['metrics']['consecutive_failures']}
Profiles: {health_status['metrics']['profiles_count']}
Servers: {health_status['metrics']['servers_count']}
Recent Users: {health_status['metrics']['recent_users']}
Queued Users: {health_status['metrics']['queued_users']}"""
            
            if health_status['issues']:
                health_text += f"\n\nIssues\n" + "\n".join(f"> {issue}" for issue in health_status['issues'][:3])
            health_text += "```"
            msg = ctx["api"].send_message(ctx["channel_id"], health_text)
        
        if 'msg' in locals() and msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="localstats", aliases=["lstats", "accountstats"])
    def localstats_cmd(ctx, args):
        if not args:
            latest = account_data_manager.get_latest_summary()
            if not latest:
                latest = account_data_manager.refresh_local_summary(force=True)

            guilds = latest.get("guilds", {})
            account = latest.get("account", {})
            status = "✓ Active" if account_data_manager.stats_active else "✗ Inactive"
            captured_at = latest.get("captured_at", time.time())
            feature_counts = guilds.get("feature_counts", {})
            feature_text = ", ".join(f"{name}:{count}" for name, count in feature_counts.items()) or "None"

            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Local Stats |\nStatus: {status}\nLast Run: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(captured_at))}\nGuild Count: {guilds.get('count', 0)}\nOwned Guilds: {guilds.get('owned_count', 0)}\nAdmin Guilds: {guilds.get('admin_count', 0)}\nHas Nitro: {'Yes' if account.get('premium_type') else 'No'}\nTop Features: {feature_text}```"
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        if args[0] == "run":
            summary = account_data_manager.refresh_local_summary(force=True)
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Local Stats |\nRefreshed at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(summary['captured_at']))}\nGuild Count: {summary['guilds']['count']}\nStatus: ✓ Saved to account_stats.json```"
            )
        elif args[0] == "start":
            interval = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 900
            success, message = account_data_manager.start_stats_job(interval)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Local Stats |\n{message}```")
        elif args[0] == "stop":
            success, message = account_data_manager.stop_stats_job()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Local Stats |\n{message}```")
        elif args[0] == "status":
            status = account_data_manager.get_job_status()
            last_run = status.get("last_run")
            last_run_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_run)) if last_run else "Never"
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Local Stats Status |\nActive: {'Yes' if status['active'] else 'No'}\nInterval: {status['interval_seconds']}s\nLast Run: {last_run_text}```"
            )
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Local Stats |\nUsage: +localstats [run|start <seconds>|stop|status]```")

        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="export")
    def export_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Export Commands |\nexport account :: Export current account profile\nexport guilds :: Export current guild list\nexport friends :: Export current relationships\nexport dms :: Export DM channel summaries\nexport summary :: Export the latest non-sensitive local summary\nexport all :: Export all supported runtime datasets\nexport auto start [target] [seconds] :: Start background auto scrape\nexport auto stop :: Stop background auto scrape\nexport auto status :: Show background auto scrape status\nexport auto run [target] :: Run one immediate background scrape cycle\n\nManual exports write JSON under ./exports. Auto scrape stores rolling snapshots in account_stats.json\n```"
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        if args[0].lower() == "auto":
            if len(args) == 1 or args[1].lower() == "status":
                status = account_data_manager.get_auto_scrape_status()
                last_run = status.get("last_run")
                last_run_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_run)) if last_run else "Never"
                targets_text = ", ".join(status.get("targets", [])) or "all"
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    f"```| Export Auto Scrape |\nActive: {'Yes' if status['active'] else 'No'}\nInterval: {status['interval_seconds']}s\nTargets: {targets_text}\nLast Run: {last_run_text}```"
                )
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return

            action = args[1].lower()
            if action == "start":
                target = "all"
                interval = 900
                if len(args) >= 3:
                    if args[2].isdigit():
                        interval = int(args[2])
                    else:
                        target = args[2].lower()
                if len(args) >= 4 and args[3].isdigit():
                    interval = int(args[3])

                success, message = account_data_manager.start_auto_scrape(interval, [target])
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Export Auto Scrape |\n{message}```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return

            if action == "stop":
                success, message = account_data_manager.stop_auto_scrape()
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Export Auto Scrape |\n{message}```")
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return

            if action == "run":
                target = args[2].lower() if len(args) >= 3 else "all"
                snapshot = account_data_manager.refresh_auto_scrape([target])
                targets_text = ", ".join(snapshot.get("targets", [])) or target
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    f"```| Export Auto Scrape |\nRan immediate scrape\nTargets: {targets_text}\nCaptured At: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snapshot['captured_at']))}```"
                )
                if msg:
                    delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
                return

            msg = ctx["api"].send_message(ctx["channel_id"], "```| Export Auto Scrape |\nUsage: +export auto [status|start [target] [seconds]|stop|run [target]]```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        target = args[0].lower()
        status_msg = ctx["api"].send_message(ctx["channel_id"], f"```| Export |\nFetching real-time {target} data...```")
        success, message, file_path, payload = account_data_manager.export_requested_data(target)

        if not status_msg:
            return

        if success and file_path and payload is not None:
            count_lines = []
            if target in ["guilds", "all"]:
                guild_count = len(payload.get("guilds", [])) if isinstance(payload, dict) else 0
                count_lines.append(f"> Guilds: {guild_count}")
            if target in ["friends", "all"]:
                relationship_count = len(payload.get("relationships", [])) if isinstance(payload, dict) else 0
                count_lines.append(f"> Relationships: {relationship_count}")
            if target in ["dms", "all"]:
                channel_count = len(payload.get("channels", [])) if isinstance(payload, dict) else 0
                count_lines.append(f"> Channels: {channel_count}")
            if target == "summary":
                count_lines.append(f"> Guild Count: {payload.get('guilds', {}).get('count', 0)}")

            detail_block = "\n".join(count_lines)
            if detail_block:
                detail_block = "\n" + detail_block

            ctx["api"].edit_message(
                ctx["channel_id"],
                status_msg.get("id"),
                f"```| Export Complete |\nTarget: {target}\nFile: {file_path}{detail_block}\nStatus: ✓ Success```"
            )
        else:
            ctx["api"].edit_message(
                ctx["channel_id"],
                status_msg.get("id"),
                f"```| Export Failed |\nTarget: {target}\nError: {message}```"
            )

        delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))

    @bot.command(name="vrrpc", aliases=["vrstatus", "vrpresence"])
    def vrrpc_cmd(ctx, args):
        global VR_HEADLESS_TOKEN

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| VR RPC Commands |\nvrrpc on :: Enable VR headless status loop (uses config token/settings)\nvrrpc off :: Disable VR headless status loop and clear session\nvrrpc stop :: Clear normal activity payload\nvrrpc preset <social|battle|explore|chill> :: Quick VR status\nvrrpc custom \"World | Details | State [| image_url] [>> Button Label >> Button URL]\" :: Custom VR status\n```"
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        if args[0].lower() == "stop":
            bot.set_activity(None)
            msg = ctx["api"].send_message(ctx["channel_id"], "```| VR RPC |\nCleared VR activity```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        presets = {
            "social": {
                "world": "Black Cat",
                "details": "Hanging out in VRChat",
                "state": "Talking with friends",
                "button_label": "Join VRChat",
                "button_url": "https://hello.vrchat.com/"
            },
            "battle": {
                "world": "Udon Arena",
                "details": "In a VR battle session",
                "state": "Competitive mode",
                "button_label": "Open VRChat",
                "button_url": "https://hello.vrchat.com/"
            },
            "explore": {
                "world": "World Explorer",
                "details": "Exploring community worlds",
                "state": "Traveling through portals",
                "button_label": "Explore Worlds",
                "button_url": "https://vrchat.com/home/worlds"
            },
            "chill": {
                "world": "Midnight Rooftop",
                "details": "Relaxing in VR",
                "state": "Lo-fi vibe",
                "button_label": "VRChat Home",
                "button_url": "https://vrchat.com/home"
            }
        }

        async def run_async_vr():
            if args[0].lower() == "on":
                oauth_token = str(config.get("vr_oauth_token", "")).strip()
                activity_name = str(config.get("vr_headless_name", "~~")).strip() or "~~"
                platform = str(config.get("vr_headless_platform", "meta_quest")).strip() or "meta_quest"
                interval = int(config.get("vr_headless_interval", 60) or 60)

                if not oauth_token:
                    return "```| VR Headless |\nMissing vr_oauth_token in config.json\nSet vr_oauth_token once, then use +vrrpc on```"

                started, info = start_vr_headless_loop(
                    bot,
                    oauth_token,
                    activity_name=activity_name,
                    platform=platform,
                    interval=interval,
                )

                if not started and VR_HEADLESS_LOOP["running"]:
                    return "```| VR Headless |\nAlready enabled```"

                return (
                    "```| "
                    "VR Headless |\n"
                    "> Status: ✓ Enabled\n"
                    f"> Name: {activity_name}\n"
                    f"> Platform: {platform}\n"
                    f"> Interval: {max(30, interval)}s\n"
                    "```"
                )

            if args[0].lower() == "off":
                _ = stop_vr_headless_loop()
                oauth_token = VR_HEADLESS_LOOP.get("oauth_token", "") or str(config.get("vr_oauth_token", "")).strip()

                if oauth_token and VR_HEADLESS_TOKEN:
                    ok, info = await clear_vr_headless_status(bot, oauth_token, VR_HEADLESS_TOKEN)
                    if not ok:
                        return f"```| VR Headless |\nFailed to fully disable\nError: {info}```"

                VR_HEADLESS_TOKEN = None
                return "```| VR Headless |\nStatus: ✓ Disabled```"

            if args[0].lower() == "preset" and len(args) >= 2:
                preset = presets.get(args[1].lower())
                if not preset:
                    return "```| VR RPC |\nUnknown preset\nAvailable: social, battle, explore, chill```"

                await send_vr_activity(
                    bot,
                    preset["world"],
                    details=preset["details"],
                    state=preset["state"],
                    button_label=preset["button_label"],
                    button_url=preset["button_url"]
                )
                return f"```| VR RPC |\nPreset: {args[1].lower()}\nWorld: {preset['world']}\nStatus: ✓ Active```"

            if args[0].lower() == "custom" and len(args) >= 2:
                raw = " ".join(args[1:]).strip().strip('"')
                button_label = None
                button_url = None

                if " >> " in raw:
                    button_parts = raw.split(" >> ")
                    if len(button_parts) >= 3:
                        raw = button_parts[0].strip()
                        button_label = button_parts[1].strip()
                        button_url = button_parts[2].strip()

                parts = [item.strip() for item in raw.split("|")]
                if len(parts) < 3:
                    return "```| VR RPC |\nInvalid custom format\nUse: vrrpc custom \"World | Details | State [| image_url] [>> Label >> URL]\"```"

                world = parts[0]
                details = parts[1]
                state = parts[2]
                image_url = parts[3] if len(parts) >= 4 and parts[3] else None

                await send_vr_activity(
                    bot,
                    world,
                    details=details,
                    state=state,
                    image_url=image_url,
                    button_label=button_label,
                    button_url=button_url
                )
                return f"```| VR RPC |\nWorld: {world}\nDetails: {details}\nState: {state}\nStatus: ✓ Active```"

            return "```| VR RPC |\nInvalid command\nUse: vrrpc preset <name> or vrrpc custom \"...\"```"

        msg_text = asyncio.run(run_async_vr())
        msg = ctx["api"].send_message(ctx["channel_id"], msg_text)
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="scrapesummary", aliases=["autosummary", "lastscrape"])
    def scrape_summary_cmd(ctx, args):
        snapshot = account_data_manager.get_last_auto_scrape()
        status = account_data_manager.get_auto_scrape_status()

        if not snapshot:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Background Scrape Summary |\nNo automatic scrape snapshot available yet\nUse +export auto run all or wait for the background cycle```"
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        targets_text = ", ".join(snapshot.get("targets", [])) or "all"
        captured_at = snapshot.get("captured_at", time.time())

        summary_block = snapshot.get("summary", {}) if isinstance(snapshot.get("summary"), dict) else {}
        summary_guilds = summary_block.get("guilds", {}) if isinstance(summary_block.get("guilds"), dict) else {}
        summary_account = summary_block.get("account", {}) if isinstance(summary_block.get("account"), dict) else {}

        guild_count = snapshot.get("guild_count")
        if guild_count is None:
            guild_count = len(snapshot.get("guilds", [])) if isinstance(snapshot.get("guilds"), list) else None
        if guild_count is None:
            guild_count = summary_guilds.get("count", 0)

        relationship_count = snapshot.get("relationship_count")
        if relationship_count is None:
            relationship_count = len(snapshot.get("relationships", [])) if isinstance(snapshot.get("relationships"), list) else 0

        channel_count = snapshot.get("channel_count")
        if channel_count is None:
            channel_count = len(snapshot.get("channels", [])) if isinstance(snapshot.get("channels"), list) else 0

        account = snapshot.get("account", {}) if isinstance(snapshot.get("account"), dict) else {}
        account_username = account.get("username") or summary_account.get("username") or "N/A"
        premium_type = account.get("premium_type", summary_account.get("premium_type", 0))

        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Background Scrape Summary |\nAuto Active: {'Yes' if status['active'] else 'No'}\nInterval: {status['interval_seconds']}s\nCaptured: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(captured_at))}\nTargets: {targets_text}\nAccount: {account_username}\nGuilds: {guild_count}\nRelationships: {relationship_count}\nDM Channels: {channel_count}\nNitro: {'Yes' if premium_type else 'No'}```"
        )

        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    @bot.command(name="badges", aliases=["badge"])
    def badges_cmd(ctx, args):
        if not args:
            help_text = """```asciidoc
| Badge Commands |
badges user <user_id> :: Scrape badges for one user
badges server <server_id> [limit] :: Scrape badges from server members
badges export <server_id> [limit] :: Scrape and export badge results
badges decode <public_flags> :: Decode a public_flags integer
```"""
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        if args[0] == "decode" and len(args) >= 2:
            decoded = badge_scraper.decode_public_flags(args[1])
            badge_text = ", ".join(decoded) if decoded else "No known badges"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Badge Decode |\nFlags: {args[1]}\nBadges: {badge_text}```")

        elif args[0] == "user" and len(args) >= 2:
            user_id = args[1]
            record = badge_scraper.scrape_user_badges(user_id)
            if not record:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Badge Scraper |\nInvalid user ID: {user_id}```")
            else:
                badge_text = ", ".join(record.get("badges", [])) if record.get("badges") else "No known badges"
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| User Badges |\nUser: {record.get('username', 'Unknown')}#{record.get('discriminator', '0000')}\nID: {record.get('user_id')}\nFlags: {record.get('public_flags', 0)}\nBadges: {badge_text}```")

        elif args[0] in {"server", "export"} and len(args) >= 2:
            server_id = args[1]
            limit = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 1000
            status_msg = ctx["api"].send_message(ctx["channel_id"], f"```| Badge Scraper |\nScraping badges from server {server_id}\nLimit: {limit}```")

            payload = badge_scraper.scrape_guild_badges(server_id, limit=limit)
            summary = badge_scraper.summarize_results(payload)
            top_badges = list(summary.items())[:6]
            top_lines = "\n".join(f"> {name}: {count}" for name, count in top_badges) if top_badges else "> None"

            result_text = f"```| Server Badge Results |\nServer: {payload.get('server_name') or 'Unknown'}\nServer ID: {server_id}\nScanned Members: {payload.get('scanned_members', 0)}\nMembers With Badges: {payload.get('matched_members', 0)}\n\nTop Badges\n{top_lines}```"

            if args[0] == "export":
                paths = badge_scraper.export_guild_badges(payload)
                result_text = result_text[:-3] + f"\n\nFiles\nJSON: {paths['json']}\nTXT: {paths['txt']}```"

            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), result_text)
            delete_after_delay(ctx["api"], ctx["channel_id"], status_msg.get("id"))
            return

        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Badge Commands |\nInvalid command. Use +badges for help```")

        if 'msg' in locals() and msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # joininvite — join a server by invite code with verification/onboarding
    # -----------------------------------------------------------------------

    @bot.command(name="joininvite", aliases=["ji", "joinserver"])
    def joininvite_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Join Invite |\nUsage: {bot.prefix}joininvite <invite_code>\nExamples:\n  {bot.prefix}ji abc123\n  {bot.prefix}ji discord.gg/abc123```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        raw = args[0].rstrip("/")
        invite_code = raw.split("/")[-1]

        status_msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Join Invite |\nJoining {invite_code}...```",
        )

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)

        # Optional fingerprint for better anti-detection
        try:
            fp_r = api.session.get(
                "https://discord.com/api/v10/experiments",
                headers={"Authorization": api.token, "User-Agent": headers.get("User-Agent", "")},
                timeout=8,
            )
            if fp_r.status_code == 200:
                fp = fp_r.json().get("fingerprint", "")
                if fp:
                    headers["X-Fingerprint"] = fp
        except Exception:
            pass

        # POST invite join
        try:
            join_r = api.session.post(
                f"https://discord.com/api/v9/invites/{invite_code}",
                headers=headers,
                json={"session_id": ""},
                timeout=15,
            )
        except Exception as e:
            result = f"Request error: {str(e)[:80]}"
            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Join Invite |\n{result}```")
                delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))
            return

        if join_r.status_code != 200:
            err_body = {}
            try:
                err_body = join_r.json()
            except Exception:
                pass
            err_msg = err_body.get("message", f"HTTP {join_r.status_code}")
            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Join Invite |\nFailed: {err_msg}```")
                delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))
            return

        join_data = join_r.json()
        guild_name = join_data.get("guild", {}).get("name", "Unknown")
        guild_id = join_data.get("guild", {}).get("id")

        parts = [f"Joined: {guild_name}"]

        if guild_id:
            ver = _ji_handle_verification(api, guild_id, invite_code, headers)
            if ver:
                if ver.get("status"):
                    if ver.get("already_verified"):
                        parts.append("Already verified")
                    else:
                        parts.append(f"Verified ({ver.get('num_fields', 0)} fields)")
                else:
                    parts.append(f"Verify failed: {ver.get('error', '')[:40]}")

            ob = _ji_handle_onboarding(api, guild_id, headers)
            if ob and ob.get("status"):
                parts.append(f"Onboarding ({ob.get('num_responses', 0)} responses)")

        result_text = " | ".join(parts)
        if status_msg:
            api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Join Invite |\n{result_text}```")
            delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))

    # -----------------------------------------------------------------------
    # leaveguild — leave a guild by ID
    # -----------------------------------------------------------------------

    @bot.command(name="leaveguild", aliases=["lg", "leaveserver"])
    def leaveguild_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Leave Guild", hosted_only=True)
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Leave Guild |\nUsage: {bot.prefix}leaveguild <guild_id>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        guild_id = args[0]
        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)

        try:
            r = api.request(
                "DELETE",
                f"/users/@me/guilds/{guild_id}",
                data={"lurking": False}
            )
            if r and r.status_code in (200, 204):
                msg = api.send_message(ctx["channel_id"], f"```| Leave Guild |\nLeft guild {guild_id}```")
            else:
                err = ""
                try:
                    err = r.json().get("message", "")
                except Exception:
                    pass
                msg = api.send_message(ctx["channel_id"], f"```| Leave Guild |\nFailed ({r.status_code}): {err or 'Unknown error'}```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Leave Guild |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # checktoken — validate a Discord token via API
    # -----------------------------------------------------------------------

    @bot.command(name="checktoken", aliases=["ct", "tokencheck", "validatetoken"])
    def checktoken_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Check Token")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Check Token |\nUsage: {bot.prefix}checktoken <token>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        check_token = args[0].strip("\"' ")
        api = ctx["api"]

        try:
            r = api.session.get(
                "https://discord.com/api/v9/users/@me",
                headers={"Authorization": check_token, "Content-Type": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                username = data.get("username", "Unknown")
                user_id = data.get("id", "?")
                nitro = "Yes" if data.get("premium_type") else "No"
                phone = "Yes" if data.get("phone") else "No"
                email = data.get("email", "None") or "None"
                mfa = "Yes" if data.get("mfa_enabled") else "No"
                msg = api.send_message(
                    ctx["channel_id"],
                    f"```| Token Valid |\nUser: {username} ({user_id})\nEmail: {email}\nNitro: {nitro}\nPhone: {phone}\nMFA: {mfa}```",
                )
            elif r.status_code == 401:
                msg = api.send_message(ctx["channel_id"], "```| Check Token |\nInvalid token (401 Unauthorized)```")
            else:
                msg = api.send_message(ctx["channel_id"], f"```| Check Token |\nUnexpected response: HTTP {r.status_code}```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Check Token |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # myguilds — list guilds the account is currently in
    # -----------------------------------------------------------------------

    @bot.command(name="myguilds", aliases=["guilds", "guildlist", "servers"])
    def myguilds_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "My Guilds", hosted_only=True)
            return

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)

        try:
            r = api.request(
                "GET",
                "/users/@me/guilds?with_counts=true"
            )
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| My Guilds |\nFailed: HTTP {r.status_code if r else 'no response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            guilds = r.json()
            total = len(guilds)

            # Optional page argument
            page = 1
            if args and args[0].isdigit():
                page = max(1, int(args[0]))

            page_size = 15
            import math
            total_pages = max(1, math.ceil(total / page_size))
            page = min(page, total_pages)
            start = (page - 1) * page_size
            page_guilds = guilds[start:start + page_size]

            lines = [f"My Guilds ({total} total — page {page}/{total_pages})"]
            for g in page_guilds:
                name = g.get("name", "Unknown")
                gid = g.get("id", "?")
                approx = g.get("approximate_member_count")
                owner = " [owner]" if g.get("owner") else ""
                count_str = f" | {approx} members" if approx else ""
                lines.append(f"> {name}{owner} — {gid}{count_str}")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| My Guilds |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # hostblacklist — block/unblock users from using +host
    # -----------------------------------------------------------------------

    @bot.command(name="hostblacklist", aliases=["hbl", "hostblock"])
    def hostblacklist_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Host Blacklist")
            return

        bl_file = "host_blacklist.json"

        def _load_bl():
            try:
                if os.path.exists(bl_file):
                    with open(bl_file, "r") as f:
                        return json.load(f)
            except Exception:
                pass
            return {}

        def _save_bl(data):
            try:
                with open(bl_file, "w") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                print(f"[hostblacklist] save error: {e}")

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Host Blacklist |\n{bot.prefix}hostblacklist add <user_id> :: Block a user from hosting\n{bot.prefix}hostblacklist remove <user_id> :: Unblock a user\n{bot.prefix}hostblacklist list :: Show all blacklisted users```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        bl = _load_bl()
        action = args[0].lower()

        if action == "add" and len(args) >= 2:
            uid = args[1]
            bl[uid] = {"blocked_at": int(time.time())}
            _save_bl(bl)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Host Blacklist |\nBlacklisted user {uid}```")

        elif action == "remove" and len(args) >= 2:
            uid = args[1]
            if uid in bl:
                del bl[uid]
                _save_bl(bl)
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Host Blacklist |\nRemoved {uid} from blacklist```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Host Blacklist |\n{uid} is not blacklisted```")

        elif action == "list":
            if not bl:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Host Blacklist |\nNo blacklisted users```")
            else:
                lines = [f"> {uid}" for uid in list(bl.keys())[:20]]
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    f"```| Host Blacklist |\nTotal: {len(bl)}\n" + "\n".join(lines) + "```",
                )
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Host Blacklist |\nUsage: add/remove/list```")

        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # userinfo — look up any Discord user by ID
    # -----------------------------------------------------------------------

    @bot.command(name="userinfo", aliases=["whois", "lookup", "profile"])
    def userinfo_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "User Info", hosted_only=True)
            return

        uid = args[0] if args else ctx["author_id"]
        api = ctx["api"]

        try:
            r = api.request("GET", f"/users/{uid}/profile?with_mutual_guilds=true")
            if not r or r.status_code != 200:
                # Fall back to basic user endpoint
                r = api.request("GET", f"/users/{uid}")

            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| User Info |\nUser not found: {uid}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            d = r.json()
            user = d.get("user") or d  # profile endpoint nests under "user"

            username = user.get("username", "Unknown")
            global_name = user.get("global_name") or ""
            discriminator = user.get("discriminator", "0")
            user_id = user.get("id", uid)
            bot_flag = " [BOT]" if user.get("bot") else ""
            system_flag = " [SYSTEM]" if user.get("system") else ""

            # Flags/badges bitmask
            public_flags = user.get("public_flags", 0)
            premium_type = user.get("premium_type", 0)
            nitro_str = {0: "None", 1: "Classic", 2: "Nitro", 3: "Basic"}.get(premium_type, str(premium_type))

            # Account created from snowflake
            created_ts = (int(user_id) >> 22) + 1420070400000
            import datetime
            created_dt = datetime.datetime.utcfromtimestamp(created_ts / 1000)
            created_str = created_dt.strftime("%Y-%m-%d")

            mutual_guilds = d.get("mutual_guilds", [])
            mutual_count = len(mutual_guilds)

            display = f"{global_name} ({username})" if global_name else username
            lines = [
                f"User Info{bot_flag}{system_flag}",
                f"> Name       :: {display}",
                f"> ID         :: {user_id}",
                f"> Created    :: {created_str}",
                f"> Nitro      :: {nitro_str}",
                f"> Mutual     :: {mutual_count} shared server(s)",
            ]
            if public_flags:
                lines.append(f"> Flags      :: {public_flags}")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| User Info |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # guildinfo — get info about a guild by ID
    # -----------------------------------------------------------------------

    @bot.command(name="guildinfo", aliases=["gi", "serverinfo", "sinfo"])
    def guildinfo_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Guild Info", hosted_only=True)
            return

        api = ctx["api"]
        # Try to get current guild from context if no arg
        guild_id = args[0] if args else ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], f"```| Guild Info |\nUsage: {bot.prefix}guildinfo <guild_id>```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}?with_counts=true")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Guild Info |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            d = r.json()
            name = d.get("name", "Unknown")
            gid = d.get("id", guild_id)
            owner_id = d.get("owner_id", "?")
            member_count = d.get("approximate_member_count") or d.get("member_count", "?")
            online_count = d.get("approximate_presence_count", "?")
            boosts = d.get("premium_subscription_count", 0)
            boost_tier = d.get("premium_tier", 0)
            description = d.get("description") or "None"
            channel_count = len(d.get("channels", []))
            role_count = len(d.get("roles", []))
            features = ", ".join(d.get("features", [])[:5]) or "None"
            verification = d.get("verification_level", 0)
            ver_str = {0: "None", 1: "Low", 2: "Medium", 3: "High", 4: "Highest"}.get(verification, str(verification))

            lines = [
                f"Guild Info",
                f"> Name        :: {name}",
                f"> ID          :: {gid}",
                f"> Owner       :: {owner_id}",
                f"> Members     :: {member_count} ({online_count} online)",
                f"> Boosts      :: {boosts} (Tier {boost_tier})",
                f"> Channels    :: {channel_count}",
                f"> Roles       :: {role_count}",
                f"> Verify      :: {ver_str}",
                f"> Features    :: {features}",
            ]
            if description and description != "None":
                lines.append(f"> Desc        :: {description[:60]}")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Guild Info |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # channelmsgs — fetch recent messages from a channel
    # -----------------------------------------------------------------------

    @bot.command(name="channelmsgs", aliases=["cm", "fetchmsgs", "getmsgs"])
    def channelmsgs_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Channel Msgs", hosted_only=True)
            return

        api = ctx["api"]

        # Args: [channel_id] [limit]  — both optional
        channel_id = ctx["channel_id"]
        limit = 10
        for arg in args:
            if arg.isdigit() and len(arg) > 5:
                channel_id = arg
            elif arg.isdigit():
                limit = min(50, max(1, int(arg)))

        try:
            r = api.request("GET", f"/channels/{channel_id}/messages?limit={limit}")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Channel Msgs |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            messages = r.json()
            if not messages:
                msg = api.send_message(ctx["channel_id"], "```| Channel Msgs |\nNo messages found```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            lines = [f"Channel Msgs last {len(messages)} from <{channel_id}>"]
            for m in reversed(messages):
                author = m.get("author", {}).get("username", "?")
                content = m.get("content", "")
                if not content:
                    attach = m.get("attachments", [])
                    embeds = m.get("embeds", [])
                    if attach:
                        content = f"[{len(attach)} attachment(s)]"
                    elif embeds:
                        content = f"[embed: {embeds[0].get('title','no title')[:30]}]"
                    else:
                        content = "[no content]"
                content = content.replace("```", "'''")[:60]
                lines.append(f"> {author}: {content}")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Channel Msgs |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # bulkcheck — validate multiple tokens at once
    # -----------------------------------------------------------------------

    @bot.command(name="bulkcheck", aliases=["bc", "bulkvalidate", "bvalidate"])
    def bulkcheck_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Bulk Check")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Bulk Check |\nUsage: {bot.prefix}bulkcheck <token1> <token2> ...```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        tokens = [a.strip("\"' ") for a in args if a.strip("\"' ")]

        status_msg = api.send_message(ctx["channel_id"], f"```| Bulk Check |\nChecking {len(tokens)} token(s)...```")

        results = []
        valid = 0
        invalid = 0
        for tok in tokens[:20]:  # cap at 20 to avoid abuse
            try:
                r = api.session.get(
                    "https://discord.com/api/v9/users/@me",
                    headers={"Authorization": tok, "Content-Type": "application/json"},
                    timeout=8,
                )
                if r.status_code == 200:
                    d = r.json()
                    uname = d.get("username", "?")
                    nitro = "N+" if d.get("premium_type") else "N-"
                    results.append(f"> [VALID]   {uname} ({nitro}) :: {tok[:20]}...")
                    valid += 1
                elif r.status_code == 401:
                    results.append(f"> [INVALID] {tok[:24]}...")
                    invalid += 1
                else:
                    results.append(f"> [HTTP {r.status_code}] {tok[:24]}...")
                    invalid += 1
            except Exception as e:
                results.append(f"> [ERROR]   {str(e)[:30]}")
                invalid += 1

        summary = f"Valid: {valid} | Invalid: {invalid} | Total: {len(tokens)}"
        output = "```| Bulk Check |\n" + summary + "\n" + "\n".join(results) + "```"
        # Split into chunks if needed
        if len(output) > 1950:
            output = output[:1950] + "\n... (truncated)```"

        if status_msg:
            api.edit_message(ctx["channel_id"], status_msg.get("id"), output)
            delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))

    # -----------------------------------------------------------------------
    # exportguilds — write guild list to a local JSON file
    # -----------------------------------------------------------------------

    @bot.command(name="exportguilds", aliases=["eg", "dumpguilds", "saveguilds"])
    def exportguilds_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Export Guilds")
            return

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)

        try:
            r = api.request(
                "GET",
                "/users/@me/guilds?with_counts=true"
            )
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Export Guilds |\nFailed: HTTP {r.status_code if r else 'no response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            guilds = r.json()
            filename = args[0] if args else "exported_guilds.json"
            if not filename.endswith(".json"):
                filename += ".json"

            export_data = {
                "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
                "total": len(guilds),
                "guilds": [
                    {
                        "id": g.get("id"),
                        "name": g.get("name"),
                        "owner": g.get("owner", False),
                        "member_count": g.get("approximate_member_count"),
                        "features": g.get("features", []),
                    }
                    for g in guilds
                ],
            }

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            msg = api.send_message(
                ctx["channel_id"],
                f"```| Export Guilds |\nExported {len(guilds)} guilds to {filename}```",
            )
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Export Guilds |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # massleave — leave multiple guilds in one shot
    # -----------------------------------------------------------------------

    @bot.command(name="massleave", aliases=["ml", "leaveall", "leavemulti"])
    def massleave_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Mass Leave")
            return

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)

        # Modes: "massleave all" or "massleave <id1> <id2> ..."
        if not args:
            msg = api.send_message(
                ctx["channel_id"],
                f"```| Mass Leave |\nUsage:\n  {bot.prefix}massleave all            — leave every guild\n  {bot.prefix}massleave <id> <id> ...  — leave specific guilds\n  {bot.prefix}massleave all except <id> <id>  — leave all except listed```",
            )
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        status_msg = api.send_message(ctx["channel_id"], "```| Mass Leave |\nFetching guild list...```")

        try:
            r = api.request(
                "GET",
                "/users/@me/guilds"
            )
            if not r or r.status_code != 200:
                if status_msg:
                    api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass Leave |\nFailed to fetch guilds: HTTP {r.status_code if r else 'no response'}```")
                    delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))
                return

            all_guilds = r.json()
            # Filter out owned guilds (can't leave those)
            leavable = [g for g in all_guilds if not g.get("owner", False)]

            if args[0].lower() == "all":
                # Check for "except" clause: massleave all except <id1> <id2>
                if "except" in [a.lower() for a in args]:
                    exc_idx = [a.lower() for a in args].index("except")
                    excluded = set(args[exc_idx + 1:])
                else:
                    excluded = set()
                targets = [g for g in leavable if g.get("id") not in excluded]
            else:
                requested = set(args)
                targets = [g for g in leavable if g.get("id") in requested]

            if not targets:
                if status_msg:
                    api.edit_message(ctx["channel_id"], status_msg.get("id"), "```| Mass Leave |\nNo eligible guilds to leave```")
                    delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))
                return

            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass Leave |\nLeaving {len(targets)} guild(s)...```")

            left = 0
            failed = 0
            import time as _time
            for g in targets:
                gid = g.get("id")
                try:
                    dr = api.request(
                        "DELETE",
                        f"/users/@me/guilds/{gid}",
                        data={"lurking": False}
                    )
                    if dr and dr.status_code in (200, 204):
                        left += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                _time.sleep(0.4)  # rate-limit safe delay

            if status_msg:
                api.edit_message(
                    ctx["channel_id"],
                    status_msg.get("id"),
                    f"```| Mass Leave |\nDone\nLeft: {left} | Failed: {failed} | Owned (skipped): {len(all_guilds) - len(leavable)}```",
                )
                delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))

        except Exception as e:
            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass Leave |\nError: {str(e)[:80]}```")
                delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))

    # -----------------------------------------------------------------------
    # guildmembers — list members in a guild (requires access)
    # -----------------------------------------------------------------------

    @bot.command(name="guildmembers", aliases=["members", "gmembers", "listmembers"])
    def guildmembers_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Guild Members", hosted_only=True)
            return

        api = ctx["api"]
        guild_id = args[0] if args else ctx.get("guild_id")
        limit = 20
        if len(args) >= 2 and args[1].isdigit():
            limit = min(100, max(1, int(args[1])))

        if not guild_id:
            msg = api.send_message(ctx["channel_id"], f"```| Guild Members |\nUsage: {bot.prefix}members <guild_id> [limit]```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}/members?limit={limit}")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Guild Members |\nFailed: HTTP {r.status_code if r else 'No response'}\n(Need GUILD_MEMBERS intent / admin access)```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            members = r.json()
            lines = [f"Guild Members ({len(members)} shown | guild {guild_id})"]
            for m in members:
                user = m.get("user", {})
                uname = user.get("username", "?")
                uid = user.get("id", "?")
                nick = m.get("nick")
                display = f"{nick} ({uname})" if nick else uname
                bot_tag = " [BOT]" if user.get("bot") else ""
                roles = len(m.get("roles", []))
                lines.append(f"> {display}{bot_tag} :: {uid} | {roles} role(s)")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Guild Members |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # drecentmessages — fetch tracked messages with flexible filtering
    # -----------------------------------------------------------------------

    @bot.command(name="drecentmessages", aliases=["drecent", "drm", "drecentdms"])
    def drecentmessages_cmd(ctx, args):
        """Retrieve tracked recent messages with flexible filtering
        
        Usage:
        <prefix>drecentmessages - Show most recent tracked messages in current channel
        <prefix>drecentmessages @user/ID - Show most recent tracked messages from user
        <prefix>drecentmessages <amount> - Show X most recent tracked messages in channel
        <prefix>drecentmessages @user/ID <amount> - Show X most recent tracked messages from user
        <prefix>drecentmessages #channel - Show most recent tracked messages in specified channel
        <prefix>drecentmessages <amount> #channel - Show X most recent tracked messages in specified channel
        <prefix>drecentmessages @user/ID #channel - Show most recent tracked messages from user in specified channel
        <prefix>drecentmessages @user/ID <amount> #channel - Show X most recent tracked messages in specified channel
        """
        # Developer-only check
        if not is_developer_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Recent Messages", developer_only=True)
            return

        api = ctx["api"]
        
        # Parse arguments flexibly
        user_id = None
        amount = 10  # Default
        channel_id = ctx["channel_id"]  # Default to current channel
        
        for arg in args:
            # Check if it's a user mention/ID
            if arg.startswith("<@") or arg.startswith("@"):
                try:
                    user_id = int(arg.strip("<@!>"))
                except ValueError:
                    pass
            # Check if it's a channel mention/ID
            elif arg.startswith("<#") or arg.startswith("#"):
                try:
                    channel_id = int(arg.strip("<#>"))
                except ValueError:
                    pass
            # Check if it's a numeric amount
            elif arg.isdigit():
                amount = min(int(arg), 50)  # Cap at 50
        
        try:
            # Build query filter
            query = {}
            if user_id:
                query["user_id"] = user_id
            
            # Always filter by channel
            query["channel_id"] = channel_id
            
            # Fetch from database
            if not hasattr(bot, 'db') or not bot.db or not bot.db.is_active:
                msg = api.send_message(ctx["channel_id"], "```| Recent Messages |\nDatabase not available```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return
            
            # Query the database (assuming similar structure to the example provided)
            try:
                # Attempt to query the messages collection
                cursor = bot.db.db.user_messages.find(query).sort("created_at", -1).limit(amount)
                messages = list(cursor)
            except Exception as db_err:
                # Fallback if database structure is different
                msg = api.send_message(ctx["channel_id"], f"```| Recent Messages |\nDatabase error: {str(db_err)[:60]}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return
            
            if not messages:
                if user_id:
                    no_msg_text = f"No tracked messages found from user {user_id} in this channel"
                else:
                    no_msg_text = "No tracked messages found in this channel"
                msg = api.send_message(ctx["channel_id"], f"```| Recent Messages |\n{no_msg_text}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return
            
            # Format output
            output = "```"
            output += f"| Recent Messages |\n"
            output += f"{'─' * 40}\n"
            
            if user_id:
                output += f"User: {user_id}\n"
            output += f"Channel: {channel_id}\n"
            output += f"Messages: {len(messages)}\n"
            output += f"{'─' * 40}\n\n"
            
            # Reverse to show oldest first
            messages.reverse()
            
            for idx, msg_data in enumerate(messages, 1):
                username = msg_data.get("username", "Unknown")
                user_id_msg = msg_data.get("user_id", "?")
                content = msg_data.get("content", "")
                created_at = msg_data.get("created_at", "")
                
                # Format timestamp
                if created_at:
                    try:
                        from datetime import datetime
                        if hasattr(created_at, 'strftime'):
                            time_str = created_at.strftime("%I:%M %p")
                        else:
                            time_str = str(created_at)[:16]
                    except:
                        time_str = str(created_at)[:16]
                else:
                    time_str = "Unknown"
                
                # Truncate and clean content
                if len(content) > 120:
                    content = content[:117] + "..."
                content = content.replace("```", "").replace("`", "").replace("|", "")
                
                output += f"#{idx} {username} ({user_id_msg}) — {time_str}\n"
                output += f"    {content}\n\n"
            
            output += f"{'─' * 40}```"
            
            result_msg = api.send_message(ctx["channel_id"], output)
            if result_msg:
                delete_after_delay(api, ctx["channel_id"], result_msg.get("id"), delay=60)
        
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Recent Messages |\nError: {str(e)[:80]}```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # friends — list, add, remove friends
    # -----------------------------------------------------------------------

    @bot.command(name="friends", aliases=["friend", "fl", "friendlist"])
    def friends_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Friends", hosted_only=True)
            return

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)
        action = args[0].lower() if args else "list"

        if action == "list":
            try:
                r = api.session.get(
                    "https://discord.com/api/v9/users/@me/relationships",
                    headers=headers,
                    timeout=10,
                )
                if r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nFailed: HTTP {r.status_code}```")
                    if msg:
                        delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                    return

                rels = r.json()
                # type 1 = friend, type 2 = blocked, type 3 = incoming req, type 4 = outgoing req
                friends = [r for r in rels if r.get("type") == 1]
                incoming = [r for r in rels if r.get("type") == 3]
                outgoing = [r for r in rels if r.get("type") == 4]
                blocked = [r for r in rels if r.get("type") == 2]

                lines = [f"Friends Total: {len(friends)} friends | {len(incoming)} incoming | {len(outgoing)} outgoing | {len(blocked)} blocked"]
                page = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 1
                per = 15
                import math as _math
                total_pages = max(1, _math.ceil(len(friends) / per))
                page = min(page, total_pages)
                shown = friends[(page - 1) * per: page * per]
                for f in shown:
                    user = f.get("user", {})
                    uname = user.get("username", "?")
                    uid = user.get("id", "?")
                    lines.append(f"> {uname} :: {uid}")
                if total_pages > 1:
                    lines.append(f"> Page {page}/{total_pages} — use {bot.prefix}friends list <page>")

                msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
            except Exception as e:
                msg = api.send_message(ctx["channel_id"], f"```| Friends |\nError: {str(e)[:80]}```")

            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

        elif action == "add" and len(args) >= 2:
            # add by user ID
            target_id = args[1]
            try:
                r = api.session.put(
                    f"https://discord.com/api/v9/users/@me/relationships/{target_id}",
                    headers=headers,
                    json={},
                    timeout=8,
                )
                if r.status_code in (200, 204):
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nFriend request sent to {target_id}```")
                else:
                    err = ""
                    try:
                        err = r.json().get("message", "")
                    except Exception:
                        pass
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nFailed ({r.status_code}): {err or 'Unknown'}```")
            except Exception as e:
                msg = api.send_message(ctx["channel_id"], f"```| Friends |\nError: {str(e)[:80]}```")

            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

        elif action == "remove" and len(args) >= 2:
            target_id = args[1]
            try:
                r = api.session.delete(
                    f"https://discord.com/api/v9/users/@me/relationships/{target_id}",
                    headers=headers,
                    timeout=8,
                )
                if r.status_code in (200, 204):
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nRemoved {target_id}```")
                else:
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nFailed: HTTP {r.status_code}```")
            except Exception as e:
                msg = api.send_message(ctx["channel_id"], f"```| Friends |\nError: {str(e)[:80]}```")

            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

        elif action == "block" and len(args) >= 2:
            target_id = args[1]
            try:
                r = api.session.put(
                    f"https://discord.com/api/v9/users/@me/relationships/{target_id}",
                    headers=headers,
                    json={"type": 2},
                    timeout=8,
                )
                if r.status_code in (200, 204):
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nBlocked {target_id}```")
                else:
                    msg = api.send_message(ctx["channel_id"], f"```| Friends |\nFailed: HTTP {r.status_code}```")
            except Exception as e:
                msg = api.send_message(ctx["channel_id"], f"```| Friends |\nError: {str(e)[:80]}```")

            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

        else:
            msg = api.send_message(
                ctx["channel_id"],
                f"```| Friends |\n{bot.prefix}friends list [page]     — show friend list\n{bot.prefix}friends add <id>         — send friend request\n{bot.prefix}friends remove <id>      — remove friend\n{bot.prefix}friends block <id>       — block user```",
            )
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # dmuser — send a DM to any user by ID
    # -----------------------------------------------------------------------

    @bot.command(name="dmuser", aliases=["dm", "senddm", "dmu"])
    def dmuser_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "DM User", hosted_only=True)
            return

        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| DM User |\nUsage: {bot.prefix}dmuser <user_id> <message...>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        target_id = args[0]
        content = " ".join(args[1:])

        try:
            # Open DM channel
            dm_r = api.request("POST", "/users/@me/channels", data={"recipient_id": target_id})
            if not dm_r or dm_r.status_code != 200:
                code = dm_r.status_code if dm_r else "No response"
                msg = api.send_message(ctx["channel_id"], f"```| DM User |\nFailed to open DM: HTTP {code}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            dm_channel_id = dm_r.json().get("id")
            sent = api.send_message(dm_channel_id, content)
            if sent:
                msg = api.send_message(ctx["channel_id"], f"```| DM User |\nSent to {target_id}```")
            else:
                msg = api.send_message(ctx["channel_id"], f"```| DM User |\nFailed to send message```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| DM User |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # deletehistory — bulk delete your own messages in a channel
    # -----------------------------------------------------------------------

    @bot.command(name="deletehistory", aliases=["dh", "clearmymsgs", "deletemy"])
    def deletehistory_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Delete History")
            return

        api = ctx["api"]
        limit = 50
        channel_id = ctx["channel_id"]

        for arg in args:
            if arg.isdigit() and len(arg) > 5:
                channel_id = arg
            elif arg.isdigit():
                limit = min(200, max(1, int(arg)))

        status_msg = api.send_message(ctx["channel_id"], f"```| Delete History |\nScanning for your messages (limit {limit})...```")

        try:
            import time as _time
            deleted = 0
            last_id = None
            remaining = limit

            while remaining > 0:
                batch = min(100, remaining)
                url = f"/channels/{channel_id}/messages?limit={batch}"
                if last_id:
                    url += f"&before={last_id}"

                r = api.request("GET", url)
                if not r or r.status_code != 200:
                    break

                messages = r.json()
                if not messages:
                    break

                last_id = messages[-1].get("id")
                my_msgs = [m for m in messages if m.get("author", {}).get("id") == str(bot.user_id)]

                for m in my_msgs:
                    try:
                        del_r = api.request("DELETE", f"/channels/{channel_id}/messages/{m['id']}")
                        if del_r and del_r.status_code == 204:
                            deleted += 1
                        _time.sleep(0.35)
                    except Exception:
                        pass

                remaining -= len(messages)
                if len(messages) < batch:
                    break

            if status_msg:
                api.edit_message(
                    ctx["channel_id"],
                    status_msg.get("id"),
                    f"```| Delete History |\nDeleted {deleted} of your messages```",
                )
                delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))

        except Exception as e:
            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Delete History |\nError: {str(e)[:80]}```")
                delete_after_delay(api, ctx["channel_id"], status_msg.get("id"))

    # -----------------------------------------------------------------------
    # snipe — show last deleted message in a channel
    # -----------------------------------------------------------------------

    @bot.command(name="snipe", aliases=["sn"])
    def snipe_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Snipe", hosted_only=True)
            return

        channel_id = args[0] if args and len(args[0]) > 5 and args[0].isdigit() else ctx["channel_id"]
        snap = bot._snipe_cache.get(channel_id)
        if not snap:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Snipe |\nNothing sniped in this channel yet```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        m = snap["message"]
        author = m.get("author", {}).get("username", "?")
        uid = m.get("author", {}).get("id", "?")
        content = (m.get("content") or "[no content]").replace("```", "'''")[:300]
        attachments = m.get("attachments", [])
        attach_str = f" + {len(attachments)} attachment(s)" if attachments else ""
        import datetime as _dt
        deleted_str = _dt.datetime.utcfromtimestamp(snap["deleted_at"]).strftime("%H:%M:%S UTC")

        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Snipe deleted at {deleted_str} |\n{author} ({uid}){attach_str}:\n{content}```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # esnipe — show last edited message (before/after)
    # -----------------------------------------------------------------------

    @bot.command(name="esnipe", aliases=["es", "editsnipe"])
    def esnipe_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Edit Snipe", hosted_only=True)
            return

        channel_id = args[0] if args and len(args[0]) > 5 and args[0].isdigit() else ctx["channel_id"]
        snap = bot._esnipe_cache.get(channel_id)
        if not snap:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Edit Snipe |\nNo edits sniped in this channel yet```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        before_m = snap["before"]
        after_m = snap["after"]
        author = before_m.get("author", {}).get("username", "?")
        uid = before_m.get("author", {}).get("id", "?")
        before_c = (before_m.get("content") or "[empty]").replace("```", "'''")[:200]
        after_c = (after_m.get("content") or "[empty]").replace("```", "'''")[:200]
        import datetime as _dt
        edited_str = _dt.datetime.utcfromtimestamp(snap["edited_at"]).strftime("%H:%M:%S UTC")

        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Edit Snipe {author} ({uid}) at {edited_str} |\nBefore\n{before_c}\nAfter \n{after_c}```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # inviteinfo — inspect an invite without joining
    # -----------------------------------------------------------------------

    @bot.command(name="inviteinfo", aliases=["ii", "invite", "checkinvite"])
    def inviteinfo_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Invite Info", hosted_only=True)
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Invite Info |\nUsage: {bot.prefix}inviteinfo <code_or_url>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        code = args[0].rstrip("/").split("/")[-1]

        try:
            r = api.request("GET", f"/invites/{code}?with_counts=true&with_expiration=true")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], "```| Invite Info |\nInvalid or expired invite```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            d = r.json()
            guild = d.get("guild") or {}
            channel = d.get("channel") or {}
            inviter = d.get("inviter") or {}

            guild_name = guild.get("name", "Unknown")
            guild_id = guild.get("id", "?")
            channel_name = channel.get("name", "?")
            channel_id_inv = channel.get("id", "?")
            members = d.get("approximate_member_count", "?")
            online = d.get("approximate_presence_count", "?")
            inviter_name = inviter.get("username", "N/A")
            expires = d.get("expires_at") or "Never"

            lines = [
                f"Invite Info discord.gg/{code}",
                f"> Guild    :: {guild_name} ({guild_id})",
                f"> Channel  :: #{channel_name} ({channel_id_inv})",
                f"> Members  :: {members} ({online} online)",
                f"> Inviter  :: {inviter_name}",
                f"> Expires  :: {str(expires)[:30]}",
            ]
            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Invite Info |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # createinvite — create a temp invite in current or target channel
    # -----------------------------------------------------------------------

    @bot.command(name="createinvite", aliases=["ci", "mkinvite", "newinvite"])
    def createinvite_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Create Invite", hosted_only=True)
            return

        api = ctx["api"]
        target_channel = ctx["channel_id"]
        max_uses = 0
        max_age = 86400  # 24h default

        for arg in args:
            if arg.isdigit() and len(arg) > 5:
                target_channel = arg
            elif arg.isdigit() and int(arg) <= 100:
                max_uses = int(arg)
            elif arg.isdigit():
                max_age = int(arg)

        try:
            r = api.request(
                "POST",
                f"/channels/{target_channel}/invites",
                data={"max_age": max_age, "max_uses": max_uses, "temporary": False, "unique": True},
            )
            if not r or r.status_code not in (200, 201):
                msg = api.send_message(ctx["channel_id"], f"```| Create Invite |\nFailed: HTTP {r.status_code if r else 'No response'}```")
            else:
                inv_code = r.json().get("code", "?")
                age_str = f"{max_age // 3600}h" if max_age >= 3600 else f"{max_age}s"
                uses_str = str(max_uses) if max_uses else "unlimited"
                msg = api.send_message(
                    ctx["channel_id"],
                    f"```| Create Invite |\ndiscord.gg/{inv_code}\nExpires: {age_str} | Uses: {uses_str}```",
                )
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Create Invite |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # channelinfo — info about a channel
    # -----------------------------------------------------------------------

    @bot.command(name="channelinfo", aliases=["cinfo", "chinfo"])
    def channelinfo_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Channel Info", hosted_only=True)
            return

        api = ctx["api"]
        channel_id = args[0] if args and args[0].isdigit() else ctx["channel_id"]

        try:
            r = api.request("GET", f"/channels/{channel_id}")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Channel Info |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            d = r.json()
            type_map = {
                0: "Text", 1: "DM", 2: "Voice", 3: "Group DM", 4: "Category",
                5: "Announcement", 10: "Thread", 11: "Thread", 12: "Thread",
                13: "Stage", 15: "Forum", 16: "Media",
            }
            ctype = type_map.get(d.get("type", 0), f"Type {d.get('type', '?')}")
            name = d.get("name") or "(DM)"
            cid = d.get("id", channel_id)
            guild_id = d.get("guild_id", "N/A")
            topic = (d.get("topic") or "None")[:60]
            position = d.get("position", "?")
            nsfw = "Yes" if d.get("nsfw") else "No"
            slowmode = d.get("rate_limit_per_user", 0)
            bitrate = d.get("bitrate")

            lines = [
                "Channel Info",
                f"> Name      :: #{name}",
                f"> ID        :: {cid}",
                f"> Type      :: {ctype}",
                f"> Guild     :: {guild_id}",
                f"> Position  :: {position}",
                f"> NSFW      :: {nsfw}",
            ]
            if slowmode:
                lines.append(f"> Slowmode  :: {slowmode}s")
            if bitrate:
                lines.append(f"> Bitrate   :: {bitrate // 1000}kbps")
            if topic and topic != "None":
                lines.append(f"> Topic     :: {topic}")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Channel Info |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # typing — trigger typing indicator in a channel for N seconds
    # -----------------------------------------------------------------------

    @bot.command(name="typing", aliases=["type", "typingindicator"])
    def typing_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Typing", hosted_only=True)
            return

        api = ctx["api"]
        channel_id = ctx["channel_id"]
        duration = 5
        for arg in args:
            if arg.isdigit() and len(arg) > 5:
                channel_id = arg
            elif arg.isdigit():
                duration = min(60, max(1, int(arg)))

        def _type_loop(cid, secs, _api):
            import time as _t
            end = _t.time() + secs
            while _t.time() < end:
                try:
                    _api.request("POST", f"/channels/{cid}/typing")
                except Exception:
                    pass
                _t.sleep(8)

        import threading as _th
        _th.Thread(target=_type_loop, args=(channel_id, duration, api), daemon=True).start()

        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Typing |\nTyping in {channel_id} for {duration}s```",
        )
        if msg:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # acceptall — accept all pending incoming friend requests
    # -----------------------------------------------------------------------

    @bot.command(name="acceptall", aliases=["acceptfriends", "aa", "acceptrequests"])
    def acceptall_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Accept All", hosted_only=True)
            return

        api = ctx["api"]
        headers = api.header_spoofer.get_protected_headers(api.token)

        try:
            r = api.session.get(
                "https://discord.com/api/v9/users/@me/relationships",
                headers=headers,
                timeout=10,
            )
            if r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Accept All |\nFailed: HTTP {r.status_code}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            rels = r.json()
            incoming = [rel for rel in rels if rel.get("type") == 3]

            if not incoming:
                msg = api.send_message(ctx["channel_id"], "```| Accept All |\nNo pending friend requests```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            accepted = 0
            failed = 0
            import time as _t
            for rel in incoming:
                uid = rel.get("id")
                try:
                    ar = api.session.put(
                        f"https://discord.com/api/v9/users/@me/relationships/{uid}",
                        headers=headers,
                        json={},
                        timeout=8,
                    )
                    if ar.status_code in (200, 204):
                        accepted += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                _t.sleep(0.3)

            msg = api.send_message(
                ctx["channel_id"],
                f"```| Accept All |\nAccepted: {accepted} | Failed: {failed} | Total: {len(incoming)}```",
            )
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Accept All |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # react — add a reaction to a message
    # -----------------------------------------------------------------------

    @bot.command(name="react", aliases=["r", "addreact", "reaction"])
    def react_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "React", hosted_only=True)
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| React |\nUsage: {bot.prefix}react <emoji>\n       {bot.prefix}react <msg_id> <emoji>\n       {bot.prefix}react <ch_id> <msg_id> <emoji>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]

        if len(args) == 1:
            emoji = args[0]
            r = api.request("GET", f"/channels/{ctx['channel_id']}/messages?limit=10")
            target_id = None
            if r and r.status_code == 200:
                for m in r.json():
                    if m.get("author", {}).get("id") != str(bot.user_id):
                        target_id = m.get("id")
                        break
            if not target_id:
                msg = api.send_message(ctx["channel_id"], "```| React |\nNo target message found```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return
            channel_id = ctx["channel_id"]
            message_id = target_id
        elif len(args) == 2:
            message_id, emoji = args[0], args[1]
            channel_id = ctx["channel_id"]
        else:
            channel_id, message_id, emoji = args[0], args[1], args[2]

        import urllib.parse
        encoded = urllib.parse.quote(emoji)
        r = api.request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me")
        if r and r.status_code == 204:
            msg = api.send_message(ctx["channel_id"], f"```| React |\nReacted {emoji}```")
        else:
            code = r.status_code if r else "No response"
            err = ""
            try:
                err = r.json().get("message", "") if r else ""
            except Exception:
                pass
            msg = api.send_message(ctx["channel_id"], f"```| React |\nFailed ({code}): {err or 'Unknown'}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # pin / unpin — pin or unpin a message
    # -----------------------------------------------------------------------

    @bot.command(name="pin", aliases=["pinmsg", "pinmessage"])
    def pin_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Pin", hosted_only=True)
            return

        api = ctx["api"]
        if not args:
            r = api.request("GET", f"/channels/{ctx['channel_id']}/messages?limit=10")
            target_id = None
            if r and r.status_code == 200:
                for m in r.json():
                    if m.get("author", {}).get("id") != str(bot.user_id):
                        target_id = m.get("id")
                        break
            if not target_id:
                msg = api.send_message(ctx["channel_id"], "```| Pin |\nNo target message found```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return
            message_id = target_id
        else:
            message_id = args[0]

        r = api.request("PUT", f"/channels/{ctx['channel_id']}/pins/{message_id}")
        if r and r.status_code == 204:
            msg = api.send_message(ctx["channel_id"], f"```| Pin |\nPinned {message_id}```")
        else:
            msg = api.send_message(ctx["channel_id"], f"```| Pin |\nFailed: HTTP {r.status_code if r else 'No response'}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    @bot.command(name="unpin", aliases=["unpinmsg", "unpinmessage"])
    def unpin_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Unpin", hosted_only=True)
            return

        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Unpin |\nUsage: {bot.prefix}unpin <message_id>```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        r = api.request("DELETE", f"/channels/{ctx['channel_id']}/pins/{args[0]}")
        if r and r.status_code == 204:
            msg = api.send_message(ctx["channel_id"], f"```| Unpin |\nUnpinned {args[0]}```")
        else:
            msg = api.send_message(ctx["channel_id"], f"```| Unpin |\nFailed: HTTP {r.status_code if r else 'No response'}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # setnick — change own nickname in the current guild
    # -----------------------------------------------------------------------

    @bot.command(name="setnick", aliases=["nick", "nickname", "changenick"])
    def setnick_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set Nick", hosted_only=True)
            return

        api = ctx["api"]
        guild_id = ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "```| Set Nick |\nMust be used in a server```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        new_nick = " ".join(args) if args else None
        r = api.request("PATCH", f"/guilds/{guild_id}/members/@me", data={"nick": new_nick})
        if r and r.status_code in (200, 204):
            display = f'"{new_nick}"' if new_nick else "reset"
            msg = api.send_message(ctx["channel_id"], f"```| Set Nick |\nNickname {display}```")
        else:
            msg = api.send_message(ctx["channel_id"], f"```| Set Nick |\nFailed: HTTP {r.status_code if r else 'No response'}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # avatar — get avatar (and banner) URL for any user
    # -----------------------------------------------------------------------

    @bot.command(name="avatar", aliases=["av", "pfp", "pfpurl", "getavatar"])
    def avatar_cmd(ctx, args):
        api = ctx["api"]
        uid = args[0] if args else str(ctx["author_id"])

        try:
            r = api.request("GET", f"/users/{uid}")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"> **User** not found: {uid}.")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            d = r.json()
            username = d.get("username", "Unknown")
            avatar_hash = d.get("avatar")
            banner_hash = d.get("banner")

            if avatar_hash:
                ext = "gif" if avatar_hash.startswith("a_") else "png"
                avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.{ext}?size=4096"
            else:
                default_idx = (int(uid) >> 22) % 6
                avatar_url = f"https://cdn.discordapp.com/embed/avatars/{default_idx}.png"

            lines = [f"Avatar {username}", f"> Avatar :: {avatar_url}"]
            if banner_hash:
                ext = "gif" if banner_hash.startswith("a_") else "png"
                lines.append(f"> Banner :: https://cdn.discordapp.com/banners/{uid}/{banner_hash}.{ext}?size=4096")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **Error:** {str(e)[:80]}.")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # roleinfo — details on a role in the current guild
    # -----------------------------------------------------------------------

    @bot.command(name="roleinfo", aliases=["role", "ri", "rinfo"])
    def roleinfo_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Role Info", hosted_only=True)
            return

        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Role Info |\nUsage: {bot.prefix}roleinfo <role_id>```")
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        role_id = args[0]
        guild_id = ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "```| Role Info |\nMust be used in a server```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}/roles")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Role Info |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            role = next((ro for ro in r.json() if ro.get("id") == role_id), None)
            if not role:
                msg = api.send_message(ctx["channel_id"], f"```| Role Info |\nRole {role_id} not found```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            color = f"#{role.get('color', 0):06X}"
            lines = [
                "Role Info",
                f"> Name        :: {role.get('name', '?')}",
                f"> ID          :: {role_id}",
                f"> Color       :: {color}",
                f"> Position    :: {role.get('position', '?')}",
                f"> Mentionable :: {'Yes' if role.get('mentionable') else 'No'}",
                f"> Hoisted     :: {'Yes' if role.get('hoist') else 'No'}",
                f"> Managed     :: {'Yes' if role.get('managed') else 'No'}",
                f"> Permissions :: {role.get('permissions', '0')}",
            ]
            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Role Info |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # stealemoji — copy an emoji and add it to another guild
    # -----------------------------------------------------------------------

    @bot.command(name="stealemoji", aliases=["se", "copyemoji", "takeemoji"])
    def stealemoji_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Steal Emoji", hosted_only=True)
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Steal Emoji |\nUsage: {bot.prefix}stealemoji <:name:id> [target_guild_id]```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        raw = args[0]
        target_guild = args[1] if len(args) >= 2 else ctx.get("guild_id")

        if not target_guild:
            msg = api.send_message(ctx["channel_id"], "```| Steal Emoji |\nProvide target guild ID or run in a server```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        import re as _re
        match = _re.match(r"<(a?):([^:]+):(\d+)>", raw)
        if match:
            animated = match.group(1) == "a"
            emoji_name = match.group(2)
            emoji_id = match.group(3)
        elif raw.isdigit():
            emoji_id = raw
            emoji_name = f"emoji_{emoji_id}"
            animated = False
        else:
            msg = api.send_message(ctx["channel_id"], "```| Steal Emoji |\nPaste as <:name:id>, <a:name:id>, or raw ID```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        try:
            ext = "gif" if animated else "png"
            img_r = api.session.get(f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=256", timeout=10)
            if img_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Emoji |\nFailed to download: HTTP {img_r.status_code}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            import base64
            mime = "image/gif" if animated else "image/png"
            b64 = base64.b64encode(img_r.content).decode("utf-8")
            upload_r = api.request(
                "POST",
                f"/guilds/{target_guild}/emojis",
                data={"name": emoji_name, "image": f"data:{mime};base64,{b64}", "roles": []}
            )
            if upload_r and upload_r.status_code in (200, 201):
                new_id = upload_r.json().get("id", "?")
                msg = api.send_message(ctx["channel_id"], f"```| Steal Emoji |\nAdded :{emoji_name}: (ID {new_id}) to {target_guild}```")
            else:
                err = ""
                try:
                    err = upload_r.json().get("message", "")
                except Exception:
                    pass
                msg = api.send_message(ctx["channel_id"], f"```| Steal Emoji |\nUpload failed ({upload_r.status_code}): {err or 'Unknown'}```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Steal Emoji |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # listinvites — list all active invites for a guild
    # -----------------------------------------------------------------------

    @bot.command(name="listinvites", aliases=["invites", "ginvites", "guildinvites"])
    def listinvites_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "List Invites")
            return

        api = ctx["api"]
        guild_id = args[0] if args and args[0].isdigit() else ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], f"```| List Invites |\nUsage: {bot.prefix}listinvites [guild_id]```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}/invites")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| List Invites |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            invites = r.json()
            if not invites:
                msg = api.send_message(ctx["channel_id"], "```| List Invites |\nNo active invites```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
                return

            lines = [f"List Invites {len(invites)} active"]
            for inv in invites[:20]:
                code = inv.get("code", "?")
                uses = inv.get("uses", 0)
                max_uses = inv.get("max_uses", 0)
                uses_str = f"{uses}/{max_uses}" if max_uses else f"{uses}/\u221e"
                channel_name = inv.get("channel", {}).get("name", "?")
                inviter = inv.get("inviter", {}).get("username", "?")
                lines.append(f"> discord.gg/{code} :: #{channel_name} | {uses_str} uses | {inviter}")

            msg = api.send_message(ctx["channel_id"], "```| " + " |\n".join(lines) + "```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| List Invites |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # webhook — post a message through a webhook URL
    # -----------------------------------------------------------------------

    @bot.command(name="webhook", aliases=["wh", "webhooksend", "hookpost"])
    def webhook_cmd(ctx, args):
        if not is_owner_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Webhook")
            return

        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Webhook |\nUsage: {bot.prefix}webhook <url> <message>\n       {bot.prefix}webhook <url> --name <username> <message>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        url = args[0]
        if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
            msg = api.send_message(ctx["channel_id"], "```| Webhook |\nInvalid webhook URL```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))
            return

        remaining = list(args[1:])
        username = None
        avatar_url = None

        if "--name" in remaining:
            idx = remaining.index("--name")
            if idx + 1 < len(remaining):
                username = remaining[idx + 1]
                del remaining[idx:idx + 2]

        if "--avatar" in remaining:
            idx = remaining.index("--avatar")
            if idx + 1 < len(remaining):
                avatar_url = remaining[idx + 1]
                del remaining[idx:idx + 2]

        payload = {"content": " ".join(remaining)}
        if username:
            payload["username"] = username
        if avatar_url:
            payload["avatar_url"] = avatar_url

        try:
            r = api.session.post(url + "?wait=true", json=payload, timeout=10)
            if r.status_code in (200, 204):
                msg = api.send_message(ctx["channel_id"], "```| Webhook |\nMessage sent```")
            else:
                err = ""
                try:
                    err = r.json().get("message", "")
                except Exception:
                    pass
                msg = api.send_message(ctx["channel_id"], f"```| Webhook |\nFailed ({r.status_code}): {err or 'Unknown'}```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Webhook |\nError: {str(e)[:80]}```")

        if msg:
            delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    # -----------------------------------------------------------------------
    # reply — reply to a message by ID
    # -----------------------------------------------------------------------

    @bot.command(name="reply", aliases=["rep", "replyto"])
    def reply_cmd(ctx, args):
        if not is_hosted_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Reply", hosted_only=True)
            return

        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Reply |\nUsage: {bot.prefix}reply <message_id> <content...>```",
            )
            if msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            return

        api = ctx["api"]
        message_id = args[0]
        content = " ".join(args[1:])

        try:
            r = api.request(
                "POST",
                f"/channels/{ctx['channel_id']}/messages",
                data={
                    "content": content,
                    "message_reference": {
                        "message_id": message_id,
                        "channel_id": ctx["channel_id"],
                        "fail_if_not_exists": False,
                    },
                },
            )
            if r and r.status_code in (200, 201):
                sent = r.json()
                delete_after_delay(api, ctx["channel_id"], sent.get("id"))
            else:
                code = r.status_code if r else "No response"
                msg = api.send_message(ctx["channel_id"], f"```| Reply |\nFailed: HTTP {code}```")
                if msg:
                    delete_after_delay(api, ctx["channel_id"], msg.get("id"))
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Reply |\nError: {str(e)[:80]}```")
            if msg:
                delete_after_delay(api, ctx["channel_id"], msg.get("id"))

    bot._handle_message = new_process_message
    
    # Cleanup function for bot shutdown
    original_stop = bot.stop
    def new_stop():
        global VR_HEADLESS_TOKEN
        print("[AccountData] Stopping local stats job...")

        if VR_HEADLESS_LOOP["running"]:
            stop_vr_headless_loop()
            oauth_token = VR_HEADLESS_LOOP.get("oauth_token", "")
            if oauth_token and VR_HEADLESS_TOKEN:
                try:
                    ok, info = asyncio.run(clear_vr_headless_status(bot, oauth_token, VR_HEADLESS_TOKEN))
                    if ok:
                        print("[VR Headless] Session cleared on shutdown")
                    else:
                        print(f"[VR Headless] Failed to clear session on shutdown: {info}")
                except Exception as e:
                    print(f"[VR Headless] Shutdown clear error: {e}")

        VR_HEADLESS_TOKEN = None
        account_data_manager.stop_stats_job()
        account_data_manager.stop_auto_scrape()
        history_manager.stop_background_scraping()
        history_manager.save_history()
        boost_manager.save_state()
        original_stop()
    bot.stop = new_stop
    
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.stop()
        print("\nBot stopped")

if __name__ == "__main__":

    main()



