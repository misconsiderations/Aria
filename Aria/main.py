bot = None
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
try:
    import aiohttp  # type: ignore[import-untyped]
except ImportError:
    aiohttp = None
import base64
import asyncio
import importlib
from bot import DiscordBot
from config import Config
from voice import SimpleVoice
from backup import BackupManager
from moderation import ModerationManager
from error_handler import error_guard
from data_engine import data_core
from notification import alert_system
from analytics import insight_tracker
from host import host_manager
from afk_system import afk_system
from anti_gc_trap import AntiGCTrap
from GitHub import GitHubUpdater
from superreact import SuperReactClient, super_react_client
from typing import Optional
from history_manager import HistoryManager
from account_data_manager import AccountDataManager
from badge_scraper import BadgeScraper
from format_bootstrap import install_global_formatter
from quest import QuestSystem
from developer import DeveloperTools
from command_integration import integrate_command_engine
try:
    from message_db import MessageDatabase
except ImportError:
    from Aria.message_db import MessageDatabase

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

def send_spotify_with_spoofing(bot, song_name, artist, album, duration_minutes=3.5, current_position_minutes: float = 0.0, image_url=None):
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

def send_spotify_listening_activity(bot, song_name, artist, album=None, elapsed_minutes=0.0, total_minutes=None, image_url=None):
    """Modern Spotify-style listening activity without legacy spoof metadata."""
    start_ms = int(time.time() * 1000) - int(float(max(0.0, elapsed_minutes)) * 60 * 1000)
    activity = {
        "type": 2,
        "name": "Spotify",
        "application_id": "3201606009684",
        "details": song_name,
        "state": artist,
    }
    if total_minutes is not None:
        total_ms = int(float(max(0.1, total_minutes)) * 60 * 1000)
        activity["timestamps"] = {"start": start_ms, "end": start_ms + total_ms}

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "spotify",
        "large_text": f"{album} on Spotify" if album else "Spotify",
    }
    bot.set_activity(activity)

def send_youtube_activity(bot, title, channel, elapsed_minutes=0.0, total_minutes=None, image_url=None, button_label=None, button_url=None):
    start_ms = int(time.time() * 1000) - int(float(max(0.0, elapsed_minutes)) * 60 * 1000)
    activity = {
        "type": 3,
        "name": "YouTube",
        "application_id": "880218394199220334",
        "details": title,
        "state": channel,
    }
    if total_minutes is not None:
        total_ms = int(float(max(0.1, total_minutes)) * 60 * 1000)
        activity["timestamps"] = {"start": start_ms, "end": start_ms + total_ms}

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "youtube",
        "large_text": "YouTube",
    }

    if button_label and button_url:
        activity["buttons"] = [button_label]
        activity["metadata"] = {"button_urls": [button_url]}

    bot.set_activity(activity)

def send_soundcloud_activity(bot, track, artist, elapsed_minutes=0.0, total_minutes=None, image_url=None, button_label=None, button_url=None):
    start_ms = int(time.time() * 1000) - int(float(max(0.0, elapsed_minutes)) * 60 * 1000)
    activity = {
        "type": 2,
        "name": "SoundCloud",
        "application_id": "451016423729692673",
        "details": track,
        "state": artist,
    }
    if total_minutes is not None:
        total_ms = int(float(max(0.1, total_minutes)) * 60 * 1000)
        activity["timestamps"] = {"start": start_ms, "end": start_ms + total_ms}

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "soundcloud",
        "large_text": "SoundCloud",
    }

    if button_label and button_url:
        activity["buttons"] = [button_label]
        activity["metadata"] = {"button_urls": [button_url]}

    bot.set_activity(activity)


REAL_RPC_APPS = {
    "youtube_music": {
        "name": "YouTube Music",
        "type": 2,
        "application_id": "880218394199220334",
        "asset": "youtube",
        "default_button": "Listen",
        "default_url": "https://music.youtube.com",
    },
    "applemusic": {
        "name": "Apple Music",
        "type": 2,
        "application_id": "886578863147192381",
        "asset": "music",
        "default_button": "Listen",
        "default_url": "https://music.apple.com",
    },
    "deezer": {
        "name": "Deezer",
        "type": 2,
        "application_id": "356268235697553409",
        "asset": "music",
        "default_button": "Listen",
        "default_url": "https://www.deezer.com",
    },
    "tidal": {
        "name": "TIDAL",
        "type": 2,
        "application_id": "967730792256327751",
        "asset": "music",
        "default_button": "Listen",
        "default_url": "https://tidal.com",
    },
    "twitch": {
        "name": "Twitch",
        "type": 1,
        "application_id": "432980957394370572",
        "asset": "twitch",
        "default_button": "Watch",
        "default_url": "https://www.twitch.tv",
    },
    "kick": {
        "name": "Kick",
        "type": 1,
        "application_id": "1108574023776385135",
        "asset": "stream",
        "default_button": "Watch",
        "default_url": "https://kick.com",
    },
    "netflix": {
        "name": "Netflix",
        "type": 3,
        "application_id": "523416993301913601",
        "asset": "movie",
        "default_button": "Watch",
        "default_url": "https://www.netflix.com",
    },
    "disneyplus": {
        "name": "Disney+",
        "type": 3,
        "application_id": "911240629547008050",
        "asset": "movie",
        "default_button": "Watch",
        "default_url": "https://www.disneyplus.com",
    },
    "primevideo": {
        "name": "Prime Video",
        "type": 3,
        "application_id": "1052207893980653608",
        "asset": "movie",
        "default_button": "Watch",
        "default_url": "https://www.primevideo.com",
    },
    "plex": {
        "name": "Plex",
        "type": 3,
        "application_id": "435674941344555008",
        "asset": "movie",
        "default_button": "Open",
        "default_url": "https://app.plex.tv",
    },
    "jellyfin": {
        "name": "Jellyfin",
        "type": 3,
        "application_id": "1011297904504971264",
        "asset": "movie",
        "default_button": "Open",
        "default_url": "https://jellyfin.org",
    },
    "vscode": {
        "name": "Visual Studio Code",
        "type": 0,
        "application_id": "383226320970055681",
        "asset": "code",
        "default_button": "Open",
        "default_url": "https://code.visualstudio.com",
    },
    "browser": {
        "name": "Browser",
        "type": 0,
        "application_id": "485951488964247552",
        "asset": "browser",
        "default_button": "Open",
        "default_url": "https://www.google.com",
    },
}

REAL_RPC_ALIASES = {
    "ytmusic": "youtube_music",
    "youtubemusic": "youtube_music",
    "apple_music": "applemusic",
    "disney+": "disneyplus",
    "disney_plus": "disneyplus",
    "prime": "primevideo",
    "prime_video": "primevideo",
    "amazonprime": "primevideo",
    "amazon_prime": "primevideo",
    "chrome": "browser",
    "web": "browser",
}


def send_real_app_activity(
    bot,
    app_key,
    title,
    context,
    elapsed_minutes=0.0,
    total_minutes=None,
    image_url=None,
    button_label=None,
    button_url=None,
):
    cfg = REAL_RPC_APPS.get(app_key)
    if not cfg:
        raise ValueError(f"Unknown app type: {app_key}")

    start_ms = int(time.time() * 1000) - int(float(max(0.0, elapsed_minutes)) * 60 * 1000)
    activity = {
        "type": cfg["type"],
        "name": cfg["name"],
        "details": title,
        "state": context,
    }

    app_id = cfg.get("application_id")
    if app_id:
        activity["application_id"] = app_id

    if total_minutes is not None:
        total_ms = int(float(max(0.1, total_minutes)) * 60 * 1000)
        activity["timestamps"] = {"start": start_ms, "end": start_ms + total_ms}

    if int(cfg.get("type", 0)) == 1:
        activity["url"] = button_url or cfg.get("default_url") or "https://www.twitch.tv"

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else cfg.get("asset", "game"),
        "large_text": cfg["name"],
    }

    final_button = button_label or cfg.get("default_button")
    final_url = button_url or cfg.get("default_url")
    if final_button and final_url:
        activity["buttons"] = [final_button]
        activity["metadata"] = {"button_urls": [final_url]}

    bot.set_activity(activity)

def send_crunchyroll_activity(bot, name, episode_title, elapsed_minutes, total_minutes, image_url=None):
    """Create a Crunchyroll-like watching activity with progress timer."""
    elapsed = float(max(0.0, elapsed_minutes))
    total = float(max(0.1, total_minutes))
    start_ms = int(time.time() * 1000) - int(elapsed * 60 * 1000)
    end_ms = start_ms + int(total * 60 * 1000)

    activity = {
        "type": 3,
        "name": "Crunchyroll",
        "details": episode_title,
        "state": name,
        "application_id": "367827983903490050",
        "timestamps": {"start": start_ms, "end": end_ms},
    }

    asset_key = upload_n_get_asset_key(bot, image_url) if image_url else None
    activity["assets"] = {
        "large_image": asset_key if asset_key else "game",
        "large_text": f"{name} on Crunchyroll",
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
        "url": "https://twitch.tv/misconsiderations",
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

LAST_SERVER_COPY = None

RPC_KEEPALIVE_LOCK = threading.Lock()
RPC_KEEPALIVE = {
    "running": False,
    "thread": None,
    "mode": "",
    "interval": 120,
    "refresh_fn": None,
    "last_refresh": 0,
    "last_error": "",
}


def configure_rpc_keepalive(bot, mode, refresh_fn=None, interval=120):
    """Keep RPC alive by periodically refreshing the current activity payload."""
    with RPC_KEEPALIVE_LOCK:
        RPC_KEEPALIVE["mode"] = str(mode)
        RPC_KEEPALIVE["interval"] = max(30, int(interval))
        RPC_KEEPALIVE["refresh_fn"] = refresh_fn
        if RPC_KEEPALIVE["running"]:
            return True, "RPC keepalive updated"
        RPC_KEEPALIVE["running"] = True
        RPC_KEEPALIVE["last_refresh"] = int(time.time())
        RPC_KEEPALIVE["last_error"] = ""

    def _worker():
        while RPC_KEEPALIVE["running"] and bot.running:
            try:
                fn = RPC_KEEPALIVE.get("refresh_fn")
                if callable(fn):
                    fn()
                elif bot.activity:
                    bot.set_activity(bot.activity)
                RPC_KEEPALIVE["last_refresh"] = int(time.time())
                RPC_KEEPALIVE["last_error"] = ""
            except Exception as e:
                RPC_KEEPALIVE["last_error"] = str(e)

            wait_for = int(RPC_KEEPALIVE.get("interval", 120))
            for _ in range(wait_for):
                if not RPC_KEEPALIVE["running"] or not bot.running:
                    break
                time.sleep(1)

    thread = threading.Thread(target=_worker, daemon=True, name="rpc-keepalive")
    RPC_KEEPALIVE["thread"] = thread
    thread.start()
    return True, "RPC keepalive started"


def stop_rpc_keepalive(bot=None, clear_activity=False):
    with RPC_KEEPALIVE_LOCK:
        was_running = RPC_KEEPALIVE["running"]
        RPC_KEEPALIVE["running"] = False
        RPC_KEEPALIVE["mode"] = ""
        RPC_KEEPALIVE["refresh_fn"] = None
    if clear_activity and bot is not None:
        try:
            bot.set_activity(None)
        except Exception:
            pass
    return (True, "RPC keepalive stopped") if was_running else (False, "RPC keepalive is not running")


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
            json.dump({"token": "token here", "prefix": "$"}, f, indent=4)
            print("Created config.json - edit it with your token")
        return
    
    bot = DiscordBot(token, config.get("prefix") or "$", config)
    bot.db = MessageDatabase(os.path.join(os.path.dirname(__file__), "messages.db"))

    command_response_state = threading.local()
    original_api_send_message = bot.api.send_message

    def managed_send_message(channel_id, content, reply_to=None, tts=False):
        msg = original_api_send_message(channel_id, content, reply_to=reply_to, tts=tts)
        active_channel = getattr(command_response_state, "channel_id", None)
        active_delay = getattr(command_response_state, "delay", 20)
        if msg and getattr(command_response_state, "enabled", False) and channel_id == active_channel:
            delete_after_delay(bot.api, channel_id, msg.get("id"), active_delay)
        return msg

    bot.api.send_message = managed_send_message

    # Integrate enhanced command engine (500+ commands, ANSI-safe help)
    try:
        integrate_command_engine(bot, bot.api, bot.prefix)
    except Exception as e:
        # Integration failure should not break main startup
        print(f"[command_integration] failed: {e}")
    voice_manager = SimpleVoice(bot.api, token, bot)
    backup_manager = BackupManager(bot.api)
    mod_manager = ModerationManager(bot.api)
    web_panel = None
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

    # In hosted mode, the instance owner is the person who requested hosting,
    # passed via the HOSTED_OWNER_ID env var. Fall back to the hardcoded owner
    # only if that env var isn't set (i.e. this is the main bot process).
    if HOSTED_MODE and os.environ.get("HOSTED_OWNER_ID"):
        owner_user_id = str(os.environ["HOSTED_OWNER_ID"])
    else:
        owner_user_id = str(bot.ownerId)
    developer_tools.dev_id = owner_user_id
    developer_user_id = owner_user_id

    # --- Auth system: persisted set of user IDs allowed to run commands ---
    _AUTH_FILE = os.path.join(os.path.dirname(__file__), "authed_users.json")
    _ADMIN_FILE = os.path.join(os.path.dirname(__file__), "admin_users.json")
    _DASH_AUTH_FILE = os.path.join(os.path.dirname(__file__), "dashboard_authed_users.json")
    _DASH_BLOCK_FILE = os.path.join(os.path.dirname(__file__), "dashboard_blocked_users.json")

    def _load_authed():
        try:
            with open(_AUTH_FILE) as f:
                return set(str(x) for x in json.load(f))
        except Exception:
            return set()

    def _load_id_set(path):
        try:
            with open(path) as f:
                return set(str(x) for x in json.load(f))
        except Exception:
            return set()

    def _save_authed(s):
        try:
            with open(_AUTH_FILE, "w") as f:
                json.dump(list(s), f)
        except Exception:
            pass

    def _save_id_set(path, values):
        try:
            with open(path, "w") as f:
                json.dump(sorted(list(values)), f)
        except Exception:
            pass

    _authed_users = _load_authed()
    _admin_users = _load_id_set(_ADMIN_FILE)
    _dashboard_authed_users = _load_id_set(_DASH_AUTH_FILE)
    _dashboard_blocked_users = _load_id_set(_DASH_BLOCK_FILE)

    if _authed_users and not _dashboard_authed_users:
        _dashboard_authed_users = set(_authed_users)
        _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)

    def is_owner_user(user_id):
        return str(user_id) == owner_user_id

    def is_developer_user(user_id):
        return str(user_id) == developer_user_id

    def is_admin_user(user_id):
        return str(user_id) in _admin_users

    def is_owner_like_user(user_id):
        uid = str(user_id)
        return uid == _MASTER_OWNER_ID or uid == owner_user_id or uid in _admin_users

    def is_authed_user(user_id):
        return str(user_id) in _authed_users

    # The master owner ID always has full control over every instance,
    # including all hosted bots — regardless of whose token is running.
    _MASTER_OWNER_ID = str(bot.ownerId)

    def is_control_user(user_id):
        uid = str(user_id)
        # Master owner controls everything always
        if uid == _MASTER_OWNER_ID:
            return True
        # On hosted instances: only the master owner has cross-control.
        # The hosted user's own account already passes via the bot.user_id check
        # in message processing, so they don't need extra permissions here.
        # Nobody else (no authed users, no other hosted users) can run commands.
        if HOSTED_MODE:
            return False
        # Main instance: owner/admin/developer/authed users
        return uid == owner_user_id or uid == developer_user_id or uid in _admin_users or uid in _authed_users

    def deny_restricted_command(ctx, title):
        import formatter as _fmt
        msg = ctx["api"].send_message(ctx["channel_id"], _fmt.error(f"{title} :: Owner/Admin only"))
        return False

    account_data_manager.start_stats_job(900)
    account_data_manager.start_auto_scrape(900, ["all"])

    boost_manager.load_state()
    bot.boost_manager = boost_manager  # Attach to bot for event handling
    
    # Fetch current server boost counts
    boost_manager.fetch_server_boosts()
    
    try:
        from boost_commands import setup_boost_commands
        setup_boost_commands(bot, bot.api, delete_after_delay)
    except Exception as e:
        print(f"[boost_commands] failed: {e}")
    
    # Setup extended commands and new systems
    try:
        from extended_commands import setup_extended_commands
        setup_extended_commands(bot, delete_after_delay)
    except Exception as e:
        print(f"[extended_commands] failed: {e}")

    try:
        from extended_system_commands import setup_extended_system_commands
        setup_extended_system_commands(bot, delete_after_delay)
    except Exception as e:
        print(f"[extended_system_commands] failed: {e}")

    try:
        from bulk_commands import setup_bulk_commands
        setup_bulk_commands(bot, delete_after_delay)
    except Exception as e:
        print(f"[bulk_commands] failed: {e}")

    # Initialize friend scraper
    from friend_scraper import EnhancedFriendScraper
    friend_scraper = EnhancedFriendScraper(bot.api)
    bot.friend_scraper = friend_scraper
    
    if not HOSTED_MODE:
        try:
            host_manager.restore_hosted_users()
        except Exception:
            pass
    

    @bot.command(name="nitro")
    def nitro_cmd(ctx, args):
        import formatter as fmt
        msg = None
        if not args:
            stats = ctx["bot"].nitro_sniper.get_stats()
            status = "ON" if stats["enabled"] else "OFF"
            cmds = [
                (f"{bot.prefix}nitro on", "Enable sniper"),
                (f"{bot.prefix}nitro off", "Disable sniper"),
                (f"{bot.prefix}nitro clear", "Clear cached codes"),
                (f"{bot.prefix}nitro stats", "Show full stats"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "\n".join(
                    [
                        fmt.nitro_status(status, stats["claimed"], stats["cached"], stats.get("last_claimed")),
                        fmt.command_list(cmds),
                    ]
                ),
            )
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
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.nitro_status(status, stats["claimed"], stats["cached"], stats.get("last_claimed")),
            )

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
            import formatter as fmt
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.giveaway_status(status, s["entered"], s["won"], s["failed"], s.get("last_win")),
            )

    @bot.command(name="agct", aliases=["antigctrap"])
    def agct_cmd(ctx, args):
        import formatter as fmt
        agct = ctx["bot"].anti_gc_trap
        msg = None

        if not args:
            status = "ON" if agct.enabled else "OFF"
            block = "ON" if agct.block_creators else "OFF"
            cmds = [
                (f"{bot.prefix}agct on", "Enable AGCT"),
                (f"{bot.prefix}agct off", "Disable AGCT"),
                (f"{bot.prefix}agct block on", "Enable creator blocking"),
                (f"{bot.prefix}agct block off", "Disable creator blocking"),
                (f"{bot.prefix}agct wl list", "Show whitelist"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "\n".join(
                    [
                        fmt.status_box(
                            "Anti-GC Trap",
                            {
                                "Status": status,
                                "Block Creators": block,
                                "Whitelisted": len(agct.whitelist),
                            },
                        ),
                        fmt.command_list(cmds),
                    ]
                ),
            )
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
        api.edit_message(
            ctx["channel_id"], msg.get("id"),
            f"```ansi\n\u001b[1;35mAria\u001b[0m :: \u001b[1;34mLinux\u001b[0m :: \u001b[1;32mConsole\u001b[0m\nREST :: {rest_ms:.0f}ms\nWS   :: {ws_str}```",
        )

    @bot.command(name="afk")
    def afk_cmd(ctx, args):
        reason = " ".join(args) if args else "AFK"
        success = afk_system.set_afk(ctx["author_id"], reason)
        
        if success:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| AFK |\nSet AFK: {reason}```")
            afk_system.save_state()
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| AFK |\nFailed to set AFK```")
        
    @bot.command(name="afkwebhook")
    def afk_webhook_cmd(ctx, args):
        if not args:
            current = afk_system.webhook_url or "None"
            display = current if len(current) < 50 else current[:47] + "..."
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| AFK Webhook |\nUsage: +afkwebhook <webhook_url>\nCurrent: {display}```")
            return
        
        webhook_url = args[0]
        
        success = afk_system.set_webhook(webhook_url)
        afk_system.save_state()
        
        if success:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| AFK Webhook |\nWebhook set successfully```")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| AFK Webhook |\nFailed to set webhook```")
        
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
        
    @bot.command(name="spam", aliases=["s"])
    def spam(ctx, args):
        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Spam |\nUsage: {bot.prefix}spam <count> <message>```",
            )
            return

        try:
            count = min(int(args[0]), 100)
        except ValueError:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Spam |\nCount must be a number```")
            return

        text = " ".join(args[1:])
        api = ctx["api"]

        for _ in range(count):
            api.send_message(ctx["channel_id"], text)
            time.sleep(random.uniform(1.5, 3.0))  # Random delay between 1.5-3 seconds
    
    @bot.command(name="purge", aliases=[ "clear", "clean"])
    def purge(ctx, args):
        import formatter as _fmt
        # Usage: +purge [amount] [user_id]
        amount = 100
        target_user = None
        for arg in (args or []):
            if arg.strip('<@!>').isdigit() and len(arg.strip('<@!>')) > 4:
                target_user = arg.strip('<@!>')
            elif arg.isdigit():
                amount = min(500, max(1, int(arg)))

        status = ctx["api"].send_message(
            ctx["channel_id"],
            f"> **Purge** :: Scanning {amount} messages{' for ' + target_user if target_user else ''}...",
        )
        status_id = status.get("id") if status else None
        scan_limit = min(1000, max(amount, 1))
        messages = []
        before = None
        try:
            while len(messages) < scan_limit:
                batch_size = min(100, scan_limit - len(messages))
                batch = ctx["api"].get_messages(ctx["channel_id"], batch_size, before=before)
                if not batch:
                    break
                messages.extend(batch)
                before = batch[-1].get("id")
                if len(batch) < batch_size or not before:
                    break
        except Exception as e:
            if status_id:
                ctx["api"].edit_message(
                    ctx["channel_id"], status_id,
                    f"> **✗ Purge** :: Failed to fetch messages: {str(e)[:60]}",
                )
            return

        deleted = 0
        failed = 0
        scanned = 0
        mine_id = str(bot.user_id)
        for m in messages:
            if status_id and m.get("id") == status_id:
                continue

            author_id = m.get("author", {}).get("id", "")
            is_mine = author_id == mine_id
            scanned += 1

            if target_user:
                if author_id != target_user:
                    continue
            else:
                if not is_mine:
                    continue

            try:
                r = ctx["api"].request("DELETE", f"/channels/{ctx['channel_id']}/messages/{m['id']}")
                if r and r.status_code in (200, 202, 204):
                    deleted += 1
                else:
                    # Already deleted / not found shouldn't hard-fail purge loops.
                    if r and r.status_code == 404:
                        continue
                    # Only count as failed if it was our own message
                    if is_mine:
                        failed += 1
                time.sleep(0.2)
            except Exception:
                if is_mine:
                    failed += 1

        if status:
            suffix = f" | Failed {failed}" if failed else ""
            result = f"Deleted **{deleted}** — Scanned {scanned}{suffix}"
            ctx["api"].edit_message(
                ctx["channel_id"], status.get("id"),
                f"> **✓ Purge** :: {result}",
            )
    
    @bot.command(name="massdm")
    def mass_dm(ctx, args):
        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Mass DM |\nUsage: {bot.prefix}massdm <1|2|3> <message>\n1 = DM history  2 = Friends  3 = Both```",
            )
            return

        try:
            option = int(args[0])
            message = " ".join(args[1:])
            
            option_names = {1: "DM History", 2: "Friends", 3: "Both"}
            if option not in [1, 2, 3]:
                msg = ctx["api"].send_message(ctx["channel_id"], "```| Mass DM |\nInvalid option. Use 1, 2, or 3```")
                return
            
            status_msg = ctx["api"].send_message(ctx["channel_id"], f"```| Mass DM |\nMode: {option_names[option]}\nFetching targets...```")
            
            dms_response = ctx["api"].request("GET", "/users/@me/channels")
            if not dms_response or dms_response.status_code != 200:
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "```| Mass DM |\nFailed to fetch DMs```")
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
                ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "```| Mass DM |\nNo targets found```")
                return
            
            sent = 0
            total = len(targets)
            failed = 0
            current_target = ""
            
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass DM |\nMode: {option_names[option]}\nTargets: {total}\nStatus: Starting\nSent: 0/{total}\nFailed: 0```")
            
            for i, (channel_id, user_id, username) in enumerate(targets):
                current_target = username
                result = ctx["api"].send_message(channel_id, message)
                if result:
                    sent += 1
                else:
                    failed += 1
                
                if (i + 1) % 3 == 0 or i == total - 1:
                    ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass DM |\nMode: {option_names[option]}\nTargets: {total}\nStatus: Sending\nSent: {sent}/{total}\nFailed: {failed}\nCurrent: {username}```")
                
                time.sleep(random.uniform(2.5, 4.0))
            
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass DM |\nMode: {option_names[option]}\nSent: {sent}/{total}\nFailed: {failed}\nTime: {time.strftime('%H:%M:%S')}```")
            
        except Exception as e:
            print(f"Mass DM error: {e}")
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Mass DM |\nUsage: {bot.prefix}massdm <1|2|3> <message>\n1 = DM history  2 = Friends  3 = Both```",
            )
    @bot.command(name="join", aliases=["acceptinvite"])
    def join_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Join |\nUsage: join <invite_code_or_url>```"
            )
            return

        invite = args[0]
        # Strip full URLs down to just the code
        if "/" in invite:
            invite = invite.rstrip("/").split("/")[-1]

        status = ctx["api"].send_message(
            ctx["channel_id"],
            f"> **Joining** {invite}..."
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
                f"> **Join** | {result}"
            )

    @bot.command(name="block", aliases=["blockuser", "bu"])
    def block_user(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Block** | Usage: {bot.prefix}block <user_id> [user_id2] ...")
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
    def _clear_hypesquad_badge(api):
        # Primary endpoint used by Discord for joining/leaving HypeSquad.
        resp = api.request("DELETE", "/hypesquad/online")
        # Fallback endpoint for compatibility with older implementations.
        if not resp or resp.status_code == 404:
            resp = api.request("DELETE", "/users/@me/hypesquad/online")
        if not resp:
            return False, "No response"
        if resp.status_code in (200, 204):
            return True, "Badge removed"
        if resp.status_code in (400, 404):
            return True, "Badge already removed"
        return False, f"HTTP {resp.status_code}"

    @bot.command(name="hypesquad", aliases=["changehypesquad", "hs"])
    def hypesquad_cmd(ctx, args):
        houses = {"bravery": 1, "brilliance": 2, "balance": 3}
        house = (args[0].lower() if args else "")
        if house in {"off", "leave", "remove", "none"}:
            ok, note = _clear_hypesquad_badge(ctx["api"])
            if ok:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ Hypesquad** :: {note}")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ Hypesquad** :: {note}")
            return

        if house not in houses:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"> **Hypesquad** :: Usage: {bot.prefix}hypesquad bravery/brilliance/balance/off",
            )
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
    @bot.command(name="hypesquad_leave", aliases=["leavehypesquad", "hsl", "hypesquadleave"])
    def hypesquad_leave_cmd(ctx, args):
        ok, note = _clear_hypesquad_badge(ctx["api"])
        if ok:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ Hypesquad** :: {note}")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ Hypesquad** :: {note}")
    @bot.command(name="status", aliases=["setstatus", "changestatus"])
    def status_cmd(ctx, args):
        import formatter as fmt
        valid = {"online", "idle", "dnd", "invisible"}
        status = (args[0].lower() if args else "")
        if status not in valid:
            cmds = [
                (f"{bot.prefix}status online",    "Set status to online"),
                (f"{bot.prefix}status idle",      "Set status to idle"),
                (f"{bot.prefix}status dnd",       "Set status to do not disturb"),
                (f"{bot.prefix}status invisible", "Set status to invisible"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.header("Status") + "\n" + fmt.command_list(cmds),
            )
            return
        ok = ctx["bot"].set_status(status)
        result = f"Set to **{status}**" if ok else f"Saved **{status}** — applies on reconnect"
        msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ Status** :: {result}")
    @bot.command(name="client", aliases=["clienttype", "ct"])
    def client_cmd(ctx, args):
        import formatter as fmt
        valid = {"web", "desktop", "mobile", "vr"}
        ctype = (args[0].lower() if args else "")
        labels = {
            "web":     "Web (Chrome/Linux)",
            "desktop": "Desktop (Discord Client/Windows)",
            "mobile":  "Android (Discord Android)",
            "vr":      "VR (Meta Quest 3)",
        }
        if ctype not in valid:
            current = getattr(ctx["bot"], "_client_type", "mobile")
            cmds = [
                (f"{bot.prefix}client web", "Web browser client"),
                (f"{bot.prefix}client desktop", "Desktop app client"),
                (f"{bot.prefix}client mobile", "Android mobile client"),
                (f"{bot.prefix}client vr", "Meta Quest VR client"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.header("Client Type") + "\n" + fmt.command_list(cmds) + "\n" +
                fmt._block(f"{fmt.CYAN}Current{fmt.DARK} :: {fmt.RESET}{fmt.WHITE}{labels.get(current, current)}{fmt.RESET}"),
            )
            return
        ok = ctx["bot"].set_client_type(ctype)
        if ok:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ Client** :: Switched to **{labels[ctype]}** — reconnecting...")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ Client** :: Failed to switch client type")
    @bot.command(name="superreact", aliases=["sr"])
    def superreact_cmd(ctx, args):
        if len(args) >= 2:
            target_arg, emoji = args[0], args[1]
            target_id = target_arg.strip('<@!>')
            if target_id.isdigit():
                super_react_client.add_target(target_id, emoji)  # type: ignore[union-attr]
                if not super_react_client.is_running():  # type: ignore[union-attr]
                    super_react_client.start()  # type: ignore[union-attr]
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| SuperReact |\n✓ Enabled for user\nTarget: <@{target_id}>\nEmoji: {emoji}\nUse +srstop to stop.```")
        elif not args:
            import formatter as fmt
            if super_react_client and super_react_client.is_running():  # type: ignore[union-attr]
                status = "Running"
                targets = super_react_client.get_targets()  # type: ignore[union-attr]
                t_count = len(targets)
            else:
                status = "Stopped"
                t_count = 0
            p = bot.prefix
            cmds = [
                (f"{p}sr <@user> <emoji>", "Add target (auto-start)"),
                (f"{p}srlist", "List targets"),
                (f"{p}srstop", "Stop all"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "\n".join([
                    fmt.status_box("SuperReact", {"Status": status, "Targets": t_count}),
                    fmt.command_list(cmds),
                ]),
            )
    @bot.command(name="superreactlist", aliases=["srlist"])
    def superreact_list_cmd(ctx, args):
        import formatter as fmt
        targets = super_react_client.get_targets()  # type: ignore[union-attr]
        msr_targets = super_react_client.get_msr_targets()  # type: ignore[union-attr]
        ssr_targets = super_react_client.get_ssr_targets()  # type: ignore[union-attr]
        
        if not targets and not msr_targets and not ssr_targets:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("SuperReact", {"Status": "No active targets"}),
            )
        else:
            response = ""
            if targets:
                response += "Single SuperReactions:\n"
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

            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.info_block("SuperReact Status", response.strip()),
            )
        
        if 'msg' in locals() and msg:
            pass

    # @bot.command(name="superreactrandom", aliases=["srrandom"])
    # def superreact_random_cmd(ctx, args):
    #     if not args:
    #         msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact Random |\nUsage: +srrandom <message_id>```")
    #    #    #         return
    #     
    #     target_msg_id = args[0].strip()
    #     if not target_msg_id.isdigit():
    #         msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact Random |\nError: Invalid message ID```")
    #    #    #         return
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
    #    #    #     if msg2:
    #         delete_after_delay(ctx["api"], ctx["channel_id"], msg2.get("id"))
    
    @bot.command(name="superreactstart", aliases=["srstart"])
    def superreact_start_cmd(ctx, args):
        # Merged into +superreact / +sr — kept as no-op redirect so old aliases still work
        msg = ctx["api"].send_message(ctx["channel_id"], f"```| SuperReact |\nJust use {bot.prefix}sr <@user> <emoji> — it auto-starts now.```")
        pass
    @bot.command(name="superreactstop", aliases=["srstop"])
    def superreact_stop_cmd(ctx, args):
        if super_react_client and super_react_client.is_running():
            super_react_client.stop()
            msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\n✗ Stopped```")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| SuperReact |\nNot running```")
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
    @bot.command(name="setprefix", aliases=["prefix"])
    def setprefix_cmd(ctx, args):
        if not args:
            user_prefix = bot.get_user_prefix(ctx["author_id"])
            import formatter as fmt
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("Prefix", {
                    "Current": user_prefix,
                    "Usage": f"{user_prefix}setprefix <symbol>",
                })
            )
            return

        new_prefix = args[0]
        if any(ch.isspace() for ch in new_prefix) or len(new_prefix) > 5:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Prefix |\nPrefix must be 1-5 non-space characters```")
            return
        user_prefix = bot.get_user_prefix(ctx["author_id"])
        old_prefix = user_prefix
        
        # Set user's prefix (persisted to file)
        bot.set_user_prefix(ctx["author_id"], new_prefix)
        
        import formatter as fmt
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            fmt.status_box("Prefix", {"Old": old_prefix, "New": new_prefix}),
        )
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
            return
        
        if args[0].lower() == "toggle":
            new_state = bot.customizer.toggle_terminal_mode()
            status = "✓ Enabled" if new_state else "✗ Disabled"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```yaml\nTerminal Emulation:\n  Status: {status}\n  Mode: {bot.customizer.get_setting('terminal_mode')}```")
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
            return
        
        if args[0].lower() == "time":
            import datetime
            now = datetime.datetime.now()
            
            if bot.customizer.get_setting('time_format') == '12h':
                time_display = now.strftime("%I:%M:%S %p")
            else:
                time_display = now.strftime("%H:%M:%S")
            
            date_fmt = bot.customizer.get_setting('date_format') or 'dd/mm/yyyy'
            date_display = now.strftime(date_fmt.replace('dd', '%d').replace('mm', '%m').replace('yyyy', '%Y'))
            
            msg = ctx["api"].send_message(ctx["channel_id"], f"```ansi\n\u001b[35m{date_display} \u001b[33m{time_display}\u001b[0m\nTerminal Mode: {bot.customizer.get_setting('terminal_mode')}```")
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
            return
        
        if args[0].lower() == "reset" and len(args) > 1:
            setting = args[1]
            if bot.customizer.reset_customization(setting):
                msg = ctx["api"].send_message(ctx["channel_id"], f"```yaml\nReset Complete:\n  Setting: {setting}\n  Status: ✓ Restored to default```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```yaml\nReset Failed:\n  Setting: {setting}\n  Status: ✗ Setting not found```")
            
            return
        
        if args[0].lower() == "save":
            try:
                import json
                with open("ui_config.json", "w") as f:
                    json.dump(bot.customizer.config, f, indent=2)
                msg = ctx["api"].send_message(ctx["channel_id"], "```yaml\nConfiguration Saved:\n  File: ui_config.json\n  Status: ✓ Success```")
            except:
                msg = ctx["api"].send_message(ctx["channel_id"], "```yaml\nSave Failed:\n  Status: ✗ Error writing file```")
            
            return
    
    @bot.command(name="autoreact")
    def set_autoreact(ctx, args):
        if args:
            bot.auto_react_emoji = args[0]
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Auto-React |\nSet to: {args[0]}```")
        else:
            bot.auto_react_emoji = None
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Auto-React disabled**.")
    @bot.command(name="mutualinfo")
    def mutualinfo(ctx, args):
        if not args:
            target_id = ctx["author_id"]
        else:
            target_id = args[0]
        
        user_info = ctx["api"].request("GET", f"/users/{target_id}")
        if not user_info or user_info.status_code != 200:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Mutual Info |\nCould not find user with ID {target_id}```")
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
    @bot.command(name="closedms")
    def closedms(ctx, args):
        status_msg = ctx["api"].send_message(ctx["channel_id"], "```| Close DMs |\nFetching DM channels...```")
        
        dms_response = ctx["api"].request("GET", "/users/@me/channels")
        if not dms_response or dms_response.status_code != 200:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "```| Close DMs |\nFailed to fetch DMs```")
            return
        
        dm_data = dms_response.json()
        dm_channels = []
        
        for dm in dm_data:
            if dm.get("type") == 1:
                dm_channels.append(dm)
        
        if not dm_channels:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "```| Close DMs |\nNo DM channels to close```")
            return
        
        closed_count = 0
        total = len(dm_channels)
        
        ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Close DMs |\nClosing {total} DM channels...\nClosed: 0/{total}```")
        
        for i, dm in enumerate(dm_channels):
            try:
                result = ctx["api"].request("DELETE", f"/channels/{dm['id']}")
                if result and result.status_code in [200, 204]:
                    closed_count += 1
                
                if (i + 1) % 5 == 0 or i == total - 1:
                    ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Close DMs |\nClosing {total} DM channels...\nClosed: {closed_count}/{total}```")
                
                time.sleep(0.5)
            except:
                pass
        
        ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Close DMs |\nClosed: {closed_count}/{total}```")
    
    @bot.command(name="setpfp", aliases=["setavatar", "spfp", "changepfp"])
    def setpfp(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set PFP")
            return
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetPFP** :: Usage: `{bot.prefix}setpfp <image_url>`")
            return

        image_url = args[0]
        api = ctx["api"]
        try:
            r = api.session.get(image_url, timeout=15)
            if r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetPFP** :: Failed to download image (HTTP {r.status_code})")
                return

            ct = r.headers.get("Content-Type", "").lower()
            url_lower = image_url.lower().split("?")[0]
            if "gif" in ct or url_lower.endswith(".gif"):
                fmt = "gif"
            elif "jpeg" in ct or "jpg" in ct or url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
                fmt = "jpeg"
            elif "webp" in ct or url_lower.endswith(".webp"):
                fmt = "webp"
            else:
                fmt = "png"

            b64 = base64.b64encode(r.content).decode()
            patch = api.request("PATCH", "/users/@me", data={"avatar": f"data:image/{fmt};base64,{b64}"})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"], "> **✓ SetPFP** :: Profile picture updated")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    body = patch.json().get("message", "") if patch else ""
                except Exception:
                    body = ""
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetPFP** :: Failed HTTP {code}{' — ' + body if body else ''}")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ SetPFP** :: Error: {str(e)[:80]}")
    @bot.command(name="servercopy")
    def servercopy(ctx, args):
        global LAST_SERVER_COPY
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> Please **provide** a **server ID** to copy.")
            return
        
        server_id = args[0]
        
        status_msg = ctx["api"].send_message(ctx["channel_id"], f"> **Fetching** server data for {server_id}...")
        
        guild_response = ctx["api"].request("GET", f"/guilds/{server_id}")
        if not guild_response or guild_response.status_code != 200:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), "> **Could** not find **server** or no **access**.")
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
    
    @bot.command(name="serverload")
    def serverload(ctx, args):
        global LAST_SERVER_COPY
        
        if not LAST_SERVER_COPY:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **No server** data to load. Use **servercopy** first.")
            return
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> Please **provide** a target server ID.")
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
            
        except Exception as e:
            ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Server Load |\nError: {str(e)}```")
    
    @bot.command(name="rpc", aliases=["rich_presence"])
    def rich_presence(ctx, args):
        if not args:
            import formatter as fmt
            p = bot.prefix
            cmds = [
                (f"{p}rpc spotify", '"Song | Artist | Album | Elapsed [| Total] [| img]"'),
                (f"{p}rpc youtube", '"Title | Channel | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc soundcloud", '"Track | Artist | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc youtube_music", '"Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc applemusic", '"Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc deezer", '"Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc tidal", '"Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc twitch", '"Stream Title | Channel | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc kick", '"Stream Title | Channel | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc netflix", '"Title | Show/Movie | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc disneyplus", '"Title | Show/Movie | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc primevideo", '"Title | Show/Movie | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc plex", '"Title | Library/User | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc jellyfin", '"Title | Library/User | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc vscode", '"Workspace/Task | File/Project | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc browser", '"Tab/Task | Site | Elapsed [| Total] [| img] [>> Btn >> URL]"'),
                (f"{p}rpc listening", '"Details | State | Name [| img] [>> Btn >> URL]"'),
                (f"{p}rpc streaming", '"Details | State | Name [| img] [>> Btn >> URL]"'),
                (f"{p}rpc playing", '"Details | State | Name [| img]"'),
                (f"{p}rpc timer", '"Details | State | Name | Start | End [| img]"'),
                (f"{p}rpc crunchyroll", 'name=<show> episode_title=<ep> elapsed_minutes=<n> total_minutes=<n> [image_url=<url>]'),
                (f"{p}rpc stop", "Clear all activities"),
            ]
            help_text = fmt.header("RPC Commands") + "\n" + fmt.command_list(cmds)
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            return
        
        parts = args[0].lower()
        parts = REAL_RPC_ALIASES.get(parts, parts)
        remaining = " ".join(args[1:]) if len(args) > 1 else ""
        
        if parts == "stop":
            stop_rpc_keepalive(bot=bot, clear_activity=True)
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Cleared** all **activities**.")
            return
        
        if not remaining:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Missing** arguments.")
            return
        
        image_url = None
        button_label = None
        button_url = None
        details = None
        state = None
        name = None
        duration = ""
        current_pos = ""
        start_time = ""
        end_time = ""
        msg_text = "```| RPC |\nInvalid input```"
        
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
        
        if parts == "crunchyroll":
            import shlex
            kv = {}
            try:
                tokens = shlex.split(main_text)
            except Exception:
                tokens = main_text.split()
            for token in tokens:
                if "=" not in token:
                    continue
                k, v = token.split("=", 1)
                kv[k.strip().lower()] = v.strip()

            try:
                show_name = kv.get("name")
                episode_title = kv.get("episode_title")
                elapsed = kv.get("elapsed_minutes")
                total = kv.get("total_minutes")
                image_url = kv.get("image_url")
                if not (show_name and episode_title and elapsed and total):
                    msg_text = (
                        "```| Crunchyroll RPC |\n"
                        "Format: name=<show> episode_title=<ep> elapsed_minutes=<n> total_minutes=<n> [image_url=<url>]\n"
                        f"Example: {bot.prefix}rpc crunchyroll name=\"Solo Leveling\" episode_title=\"Episode 12\" elapsed_minutes=6 total_minutes=24 image_url=https://img.url"
                        "```"
                    )
                else:
                    elapsed_val = float(elapsed)
                    total_val = float(total)
                    send_crunchyroll_activity(bot, show_name, episode_title, elapsed_val, total_val, image_url)
                    _cr_start = time.time() - (elapsed_val * 60.0)
                    _cr_total = max(0.1, float(total_val))

                    def _refresh_crunchyroll(
                        _show=show_name,
                        _episode=episode_title,
                        _start=_cr_start,
                        _total=_cr_total,
                        _img=image_url,
                    ):
                        cyc_elapsed = ((time.time() - _start) / 60.0) % _total
                        send_crunchyroll_activity(bot, _show, _episode, cyc_elapsed, _total, _img)

                    configure_rpc_keepalive(bot, "crunchyroll", _refresh_crunchyroll)
                    msg_text = (
                        "```| Crunchyroll RPC |\n"
                        f"Show: {show_name}\n"
                        f"Episode: {episode_title}\n"
                        f"Progress: {elapsed_val} / {total_val} min"
                        "```"
                    )
                    if image_url:
                        msg_text = msg_text.replace("```", "\nImage: Yes```")
            except Exception as e:
                msg_text = f"```| Crunchyroll RPC |\nError: {str(e)}```"

        elif ' | ' in main_text:
            pipe_parts = [part.strip() for part in main_text.split('|')]
            
            if parts == "spotify":
                if len(pipe_parts) >= 4:
                    song = pipe_parts[0]
                    artist = pipe_parts[1]
                    album = pipe_parts[2]
                    duration = pipe_parts[3]
                    
                    if len(pipe_parts) >= 5:
                        current_pos = pipe_parts[4]
                    if len(pipe_parts) >= 6:
                        image_url = pipe_parts[5]
                    
                    details = song
                    state = artist
                    name = album

            elif parts == "youtube":
                if len(pipe_parts) >= 3:
                    details = pipe_parts[0]  # title
                    state = pipe_parts[1]    # channel
                    duration = pipe_parts[2] # elapsed
                    if len(pipe_parts) >= 4:
                        current_pos = pipe_parts[3]  # total
                    if len(pipe_parts) >= 5:
                        image_url = pipe_parts[4]

            elif parts == "soundcloud":
                if len(pipe_parts) >= 3:
                    details = pipe_parts[0]  # track
                    state = pipe_parts[1]    # artist
                    duration = pipe_parts[2] # elapsed
                    if len(pipe_parts) >= 4:
                        current_pos = pipe_parts[3]  # total
                    if len(pipe_parts) >= 5:
                        image_url = pipe_parts[4]

            elif parts in REAL_RPC_APPS:
                if len(pipe_parts) >= 3:
                    details = pipe_parts[0]
                    state = pipe_parts[1]
                    duration = pipe_parts[2]
                    if len(pipe_parts) >= 4:
                        current_pos = pipe_parts[3]
                    if len(pipe_parts) >= 5:
                        image_url = pipe_parts[4]
            
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
                    elapsed_val = float(duration) if duration else 0.0
                    total_val = float(current_pos) if current_pos else None
                    send_spotify_listening_activity(bot, details, state, name, elapsed_val, total_val, image_url)
                    _sp_start = time.time() - (elapsed_val * 60.0)
                    _sp_total = float(total_val) if total_val is not None else None

                    def _refresh_spotify(
                        _song=details,
                        _artist=state,
                        _album=name,
                        _start=_sp_start,
                        _total=_sp_total,
                        _img=image_url,
                    ):
                        if _total is not None and _total > 0:
                            cyc_elapsed = ((time.time() - _start) / 60.0) % _total
                        else:
                            cyc_elapsed = max(0.0, (time.time() - _start) / 60.0)
                        send_spotify_listening_activity(bot, _song, _artist, _album, cyc_elapsed, _total, _img)

                    configure_rpc_keepalive(bot, "spotify", _refresh_spotify)
                    msg_text = f"```| Spotify RPC |\nSong: {details}\nArtist: {state}\nAlbum: {name}\nElapsed: {elapsed_val}min```"
                    if total_val is not None:
                        msg_text = msg_text.replace("```", f"\nTotal: {total_val}min```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = (
                        "```| Spotify RPC |\n"
                        "Format: Song | Artist | Album | Elapsed [| Total] [| image_url]\n"
                        f"Example: {bot.prefix}rpc spotify \"Song Name | Artist Name | Album Name | 1.5 | 3.5 | https://image.url\""
                        "```"
                    )
            except Exception as e:
                msg_text = f"```| Spotify RPC |\nError: {str(e)}```"

        elif parts == "youtube":
            try:
                if details and state:
                    elapsed_val = float(duration) if duration else 0.0
                    total_val = float(current_pos) if current_pos else None
                    send_youtube_activity(bot, details, state, elapsed_val, total_val, image_url, button_label, button_url)
                    _yt_start = time.time() - (elapsed_val * 60.0)
                    _yt_total = float(total_val) if total_val is not None else None

                    def _refresh_youtube(
                        _title=details,
                        _channel=state,
                        _start=_yt_start,
                        _total=_yt_total,
                        _img=image_url,
                        _btn=button_label,
                        _url=button_url,
                    ):
                        if _total is not None and _total > 0:
                            cyc_elapsed = ((time.time() - _start) / 60.0) % _total
                        else:
                            cyc_elapsed = max(0.0, (time.time() - _start) / 60.0)
                        send_youtube_activity(bot, _title, _channel, cyc_elapsed, _total, _img, _btn, _url)

                    configure_rpc_keepalive(bot, "youtube", _refresh_youtube)
                    msg_text = f"```| YouTube RPC |\nTitle: {details}\nChannel: {state}\nElapsed: {elapsed_val}min```"
                    if total_val is not None:
                        msg_text = msg_text.replace("```", f"\nTotal: {total_val}min```")
                    if button_label:
                        msg_text = msg_text.replace("```", f"\nButton: {button_label}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = (
                        "```| YouTube RPC |\n"
                        "Format: Title | Channel | Elapsed [| Total] [| image_url] [>> Button >> URL]\n"
                        f"Example: {bot.prefix}rpc youtube \"Devlog #12 | Aria Channel | 2.5 | 10 | https://image.url >> Watch >> https://youtube.com\""
                        "```"
                    )
            except Exception as e:
                msg_text = f"```| YouTube RPC |\nError: {str(e)}```"

        elif parts == "soundcloud":
            try:
                if details and state:
                    elapsed_val = float(duration) if duration else 0.0
                    total_val = float(current_pos) if current_pos else None
                    send_soundcloud_activity(bot, details, state, elapsed_val, total_val, image_url, button_label, button_url)
                    _sc_start = time.time() - (elapsed_val * 60.0)
                    _sc_total = float(total_val) if total_val is not None else None

                    def _refresh_soundcloud(
                        _track=details,
                        _artist=state,
                        _start=_sc_start,
                        _total=_sc_total,
                        _img=image_url,
                        _btn=button_label,
                        _url=button_url,
                    ):
                        if _total is not None and _total > 0:
                            cyc_elapsed = ((time.time() - _start) / 60.0) % _total
                        else:
                            cyc_elapsed = max(0.0, (time.time() - _start) / 60.0)
                        send_soundcloud_activity(bot, _track, _artist, cyc_elapsed, _total, _img, _btn, _url)

                    configure_rpc_keepalive(bot, "soundcloud", _refresh_soundcloud)
                    msg_text = f"```| SoundCloud RPC |\nTrack: {details}\nArtist: {state}\nElapsed: {elapsed_val}min```"
                    if total_val is not None:
                        msg_text = msg_text.replace("```", f"\nTotal: {total_val}min```")
                    if button_label:
                        msg_text = msg_text.replace("```", f"\nButton: {button_label}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = (
                        "```| SoundCloud RPC |\n"
                        "Format: Track | Artist | Elapsed [| Total] [| image_url] [>> Button >> URL]\n"
                        f"Example: {bot.prefix}rpc soundcloud \"Track Name | Artist Name | 1.2 | 4.1 | https://image.url >> Listen >> https://soundcloud.com\""
                        "```"
                    )
            except Exception as e:
                msg_text = f"```| SoundCloud RPC |\nError: {str(e)}```"

        elif parts in REAL_RPC_APPS:
            try:
                cfg = REAL_RPC_APPS[parts]
                app_label = cfg["name"]
                if details and state:
                    elapsed_val = float(duration) if duration else 0.0
                    total_val = float(current_pos) if current_pos else None
                    send_real_app_activity(bot, parts, details, state, elapsed_val, total_val, image_url, button_label, button_url)
                    _app_start = time.time() - (elapsed_val * 60.0)
                    _app_total = float(total_val) if total_val is not None else None

                    def _refresh_real_app(
                        _mode=parts,
                        _title=details,
                        _state=state,
                        _start=_app_start,
                        _total=_app_total,
                        _img=image_url,
                        _btn=button_label,
                        _url=button_url,
                    ):
                        if _total is not None and _total > 0:
                            cyc_elapsed = ((time.time() - _start) / 60.0) % _total
                        else:
                            cyc_elapsed = max(0.0, (time.time() - _start) / 60.0)
                        send_real_app_activity(bot, _mode, _title, _state, cyc_elapsed, _total, _img, _btn, _url)

                    configure_rpc_keepalive(bot, parts, _refresh_real_app)
                    msg_text = f"```| {app_label} RPC |\nTitle: {details}\nContext: {state}\nElapsed: {elapsed_val}min```"
                    if total_val is not None:
                        msg_text = msg_text.replace("```", f"\nTotal: {total_val}min```")
                    if button_label:
                        msg_text = msg_text.replace("```", f"\nButton: {button_label}```")
                    if image_url:
                        msg_text = msg_text.replace("```", f"\nImage: Yes```")
                else:
                    msg_text = (
                        f"```| {app_label} RPC |\n"
                        "Format: Title | Context | Elapsed [| Total] [| image_url] [>> Button >> URL]\n"
                        f"Example: {bot.prefix}rpc {parts} \"Title Here | Context Here | 3.5 | 22 | https://image.url >> Open >> https://example.com\""
                        "```"
                    )
            except Exception as e:
                msg_text = f"```| RPC |\nError ({parts}): {str(e)}```"

        elif parts == "listening":
            try:
                if name:
                    send_listening_activity(bot, name, button_label, button_url, image_url, state, details)

                    def _refresh_listening(
                        _name=name,
                        _btn=button_label,
                        _url=button_url,
                        _img=image_url,
                        _state=state,
                        _details=details,
                    ):
                        send_listening_activity(bot, _name, _btn, _url, _img, _state, _details)

                    configure_rpc_keepalive(bot, "listening", _refresh_listening)
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

                    def _refresh_streaming(
                        _name=name,
                        _btn=button_label,
                        _url=button_url,
                        _img=image_url,
                        _state=state,
                        _details=details,
                    ):
                        send_streaming_activity(bot, _name, _btn, _url, _img, _state, _details)

                    configure_rpc_keepalive(bot, "streaming", _refresh_streaming)
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

                    def _refresh_playing(
                        _name=name,
                        _btn=button_label,
                        _url=button_url,
                        _img=image_url,
                        _state=state,
                        _details=details,
                    ):
                        send_playing_activity(bot, _name, _btn, _url, _img, _state, _details)

                    configure_rpc_keepalive(bot, "playing", _refresh_playing)
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
                if name and start_time and end_time:
                    start_val = float(start_time) if start_time else time.time()
                    end_val = float(end_time) if end_time else time.time() + 3600
                    send_timer_activity(bot, name, start_val, end_val, details, state, image_url)
                    timer_duration = max(60.0, end_val - start_val)

                    def _refresh_timer(
                        _name=name,
                        _dur=timer_duration,
                        _details=details,
                        _state=state,
                        _img=image_url,
                    ):
                        now = time.time()
                        send_timer_activity(bot, _name, now, now + _dur, _details, _state, _img)

                    configure_rpc_keepalive(bot, "timer", _refresh_timer)
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

        elif parts == "crunchyroll":
            pass

        else:
            valid_types = [
                "spotify", "youtube", "soundcloud",
                "youtube_music", "applemusic", "deezer", "tidal",
                "twitch", "kick",
                "netflix", "disneyplus", "primevideo", "plex", "jellyfin", "vscode", "browser",
                "listening", "streaming", "playing", "timer", "crunchyroll",
            ]
            msg_text = "```| RPC |\nInvalid type. Use: " + ", ".join(valid_types) + "```"

        msg = ctx["api"].send_message(ctx["channel_id"], msg_text)
    @bot.command(name="setserverpfp", aliases=["serverspfp", "guildpfp", "setguildpfp", "sserverpfp"])
    def setserverpfp(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set Server PFP")
            return
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetServerPFP** :: Usage: `{bot.prefix}setserverpfp <image_url>`")
            return

        guild_id = ctx.get("guild_id") or ctx["message"].get("guild_id")
        if not guild_id:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ SetServerPFP** :: Must be used in a server")
            return

        image_url = args[0]
        api = ctx["api"]
        try:
            r = api.session.get(image_url, timeout=15)
            if r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetServerPFP** :: Failed to download (HTTP {r.status_code})")
                return

            ct = r.headers.get("Content-Type", "").lower()
            url_lower = image_url.lower().split("?")[0]
            if "gif" in ct or url_lower.endswith(".gif"):
                fmt = "gif"
            elif "jpeg" in ct or "jpg" in ct or url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
                fmt = "jpeg"
            elif "webp" in ct or url_lower.endswith(".webp"):
                fmt = "webp"
            else:
                fmt = "png"

            b64 = base64.b64encode(r.content).decode()
            patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me", data={"avatar": f"data:image/{fmt};base64,{b64}"})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"], "> **✓ SetServerPFP** :: Server profile picture updated")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    body = patch.json().get("message", "") if patch else ""
                except Exception:
                    body = ""
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetServerPFP** :: Failed HTTP {code}{' — ' + body if body else ''} (Nitro required)")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ SetServerPFP** :: Error: {str(e)[:80]}")
    @bot.command(name="setserverbanner", aliases=["ssb", "setguildbanner", "sserverbanner"])
    def setserverbanner(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set Server Banner")
            return
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Set Server Banner |\nUsage: {bot.prefix}setserverbanner <image_url>\n(Nitro required for server banners)```")
            return

        guild_id = ctx.get("guild_id") or ctx["message"].get("guild_id")
        if not guild_id:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Set Server Banner |\nMust be used in a server```")
            return

        image_url = args[0]
        api = ctx["api"]
        try:
            r = api.session.get(image_url, timeout=15)
            if r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Set Server Banner |\nFailed to download image (HTTP {r.status_code})```")
                return

            ct = r.headers.get("Content-Type", "").lower()
            url_lower = image_url.lower().split("?")[0]
            if "gif" in ct or url_lower.endswith(".gif"):
                fmt = "gif"
            elif "jpeg" in ct or "jpg" in ct or url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
                fmt = "jpeg"
            elif "webp" in ct or url_lower.endswith(".webp"):
                fmt = "webp"
            else:
                fmt = "png"

            b64 = base64.b64encode(r.content).decode()
            patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me", data={"banner": f"data:image/{fmt};base64,{b64}"})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"], "```| Set Server Banner |\nServer banner updated```")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    body = patch.json().get("message", "") if patch else ""
                except Exception:
                    body = ""
                msg = api.send_message(ctx["channel_id"], f"```| Set Server Banner |\nFailed: HTTP {code}{' — ' + body if body else ''}\n(Nitro required for server banners)```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Set Server Banner |\nError: {str(e)[:80]}```")
    @bot.command(name="stealpfp", aliases=["copypfp", "takepfp"])
    def stealpfp(ctx, args):
        # Usage: +stealpfp <user_id|@mention> [server]
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"> **StealPFP** :: Usage: `{bot.prefix}stealpfp <user_id> [server]`")
            return

        raw = args[0].strip("<@!>")
        user_id = raw if raw.isdigit() else args[0]
        server_mode = len(args) >= 2 and args[1].lower() in ("server", "guild", "s", "g")
        guild_id = ctx["message"].get("guild_id")

        api = ctx["api"]

        try:
            if server_mode:
                # --- steal their server avatar ---
                if not guild_id:
                    msg = api.send_message(ctx["channel_id"], "> **✗ StealPFP** :: Must be in a server for server mode")
                    return
                member_r = api.request("GET", f"/guilds/{guild_id}/members/{user_id}")
                if not member_r or member_r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: Could not fetch member {user_id} in this server")
                    return
                member_data = member_r.json()
                avatar_hash = member_data.get("avatar")
                if not avatar_hash:
                    # Fall back to their global avatar
                    user_data = member_data.get("user", {})
                    avatar_hash = user_data.get("avatar")
                    target_name = user_data.get("username", user_id)
                    if not avatar_hash:
                        msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: {target_name} has no server or global avatar")
                        return
                    ext = "gif" if avatar_hash.startswith("a_") else "png"
                    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=1024"
                    fallback_note = " (no server avatar, used global)"
                else:
                    user_data = member_data.get("user", {})
                    target_name = user_data.get("username", user_id)
                    ext = "gif" if avatar_hash.startswith("a_") else "png"
                    avatar_url = f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/avatars/{avatar_hash}.{ext}?size=1024"
                    fallback_note = ""

                img_r = api.session.get(avatar_url, timeout=10)
                if img_r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: Failed to download image (HTTP {img_r.status_code})")
                    return

                b64 = base64.b64encode(img_r.content).decode()
                patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me",
                                    data={"avatar": f"data:image/{ext};base64,{b64}"})
                if patch and patch.status_code in (200, 204):
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✓ StealPFP** :: Stole **{target_name}**'s server avatar{fallback_note}")
                else:
                    code = patch.status_code if patch else "no response"
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✗ StealPFP** :: Failed to set server avatar (HTTP {code})")

            else:
                # --- steal their global avatar ---
                user_r = api.request("GET", f"/users/{user_id}")
                if not user_r or user_r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: User not found: {user_id}")
                    return

                user_data = user_r.json()
                avatar_hash = user_data.get("avatar")
                target_name = user_data.get("username", user_id)
                if not avatar_hash:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: **{target_name}** has no avatar")
                    return

                ext = "gif" if avatar_hash.startswith("a_") else "png"
                avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=1024"

                img_r = api.session.get(avatar_url, timeout=10)
                if img_r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: Failed to download image (HTTP {img_r.status_code})")
                    return

                b64 = base64.b64encode(img_r.content).decode()
                patch = api.request("PATCH", "/users/@me",
                                    data={"avatar": f"data:image/{ext};base64,{b64}"})
                if patch and patch.status_code == 200:
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✓ StealPFP** :: Stole **{target_name}**'s avatar")
                else:
                    code = patch.status_code if patch else "no response"
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✗ StealPFP** :: Failed to set avatar (HTTP {code})")

        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ StealPFP** :: Error: {str(e)[:80]}")

    @bot.command(name="setbanner", aliases=["banner", "sbanner", "changebanner"])
    def setbanner(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set Banner")
            return
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetBanner** :: Usage: `{bot.prefix}setbanner <image_url>`")
            return

        image_url = args[0]
        api = ctx["api"]
        try:
            r = api.session.get(image_url, timeout=15)
            if r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetBanner** :: Failed to download (HTTP {r.status_code})")
                return

            ct = r.headers.get("Content-Type", "").lower()
            url_lower = image_url.lower().split("?")[0]
            if "gif" in ct or url_lower.endswith(".gif"):
                fmt = "gif"
            elif "jpeg" in ct or "jpg" in ct or url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
                fmt = "jpeg"
            elif "webp" in ct or url_lower.endswith(".webp"):
                fmt = "webp"
            else:
                fmt = "png"

            b64 = base64.b64encode(r.content).decode()
            patch = api.request("PATCH", "/users/@me", data={"banner": f"data:image/{fmt};base64,{b64}"})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"], "> **✓ SetBanner** :: Banner updated")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    body = patch.json().get("message", "") if patch else ""
                except Exception:
                    body = ""
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetBanner** :: Failed HTTP {code}{' — ' + body if body else ''} (Nitro required)")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ SetBanner** :: Error: {str(e)[:80]}")
    @bot.command(name="stealbanner", aliases=["copybanner", "takebanner"])
    def stealbanner(ctx, args):
        # Usage: +stealbanner <user_id|@mention>
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"> **StealBanner** :: Usage: `{bot.prefix}stealbanner <user_id>`")
            return

        raw = args[0].strip("<@!>")
        user_id = raw if raw.isdigit() else args[0]
        api = ctx["api"]

        try:
            banner_hash = None
            target_name = user_id

            # Try profile endpoint first (has user_profile.banner and user.banner)
            pr = api.request("GET", f"/users/{user_id}/profile?with_mutual_guilds=false")
            if pr and pr.status_code in (200, 201):
                pd = pr.json()
                user_obj = pd.get("user") or {}
                target_name = user_obj.get("username", user_id)
                banner_hash = (
                    user_obj.get("banner")
                    or (pd.get("user_profile") or {}).get("banner")
                )

            # Fallback: basic user endpoint (returns user.banner for Nitro users)
            if not banner_hash:
                ur = api.request("GET", f"/users/{user_id}")
                if ur and ur.status_code == 200:
                    ud = ur.json()
                    target_name = ud.get("username", user_id)
                    banner_hash = ud.get("banner")

            if not banner_hash:
                msg = api.send_message(ctx["channel_id"],
                    f"> **✗ StealBanner** :: **{target_name}** has no banner")
                return

            ext = "gif" if banner_hash.startswith("a_") else "png"
            banner_url = f"https://cdn.discordapp.com/banners/{user_id}/{banner_hash}.{ext}?size=1024"

            img_r = api.session.get(banner_url, timeout=10)
            if img_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"],
                    f"> **✗ StealBanner** :: Failed to download (HTTP {img_r.status_code})")
                return

            b64 = base64.b64encode(img_r.content).decode()
            patch = api.request("PATCH", "/users/@me",
                                data={"banner": f"data:image/{ext};base64,{b64}"})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"],
                    f"> **✓ StealBanner** :: Stole **{target_name}**'s banner")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    err = patch.json().get("message", "") if patch else ""
                except Exception:
                    err = ""
                msg = api.send_message(ctx["channel_id"],
                    f"> **✗ StealBanner** :: Failed (HTTP {code}){': ' + err if err else ''}")

        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ StealBanner** :: Error: {str(e)[:80]}")

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
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Pronouns |\nError: {str(e)}```")
    @bot.command(name="setpronouns", aliases=["setpronoun"])
    def setpronouns(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetPronouns** :: Usage: `{bot.prefix}setpronouns <pronouns>`")
            return
        
        pronouns = " ".join(args)
        
        try:
            data = {
                "pronouns": pronouns
            }
            
            result = ctx["api"].request("PATCH", "/users/@me/profile", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ SetPronouns** :: Set to **{pronouns}**")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ SetPronouns** :: Failed (HTTP {result.status_code if result else 'No response'})")
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ SetPronouns** :: Error: {str(e)[:80]}")
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
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Bio |\nError: {str(e)}```")
    @bot.command(name="setbio", aliases=["setaboutme"])
    def setbio(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetBio** :: Usage: `{bot.prefix}setbio <bio text>`")
            return
        
        bio_text = " ".join(args)
        
        try:
            data = {
                "bio": bio_text
            }
            
            result = ctx["api"].request("PATCH", "/users/@me/profile", data=data)
            
            if result and result.status_code == 200:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **✓ SetBio** :: Bio updated")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ SetBio** :: Failed (HTTP {result.status_code if result else 'No response'})")
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ SetBio** :: Error: {str(e)[:80]}")
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
                return
            
            user_data = user_response.json()
            username = user_data.get("username", "Unknown")
            global_name = user_data.get("global_name", "")
            
            if global_name:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Display Name |\nUser: {username}\nDisplay Name: {global_name}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Display Name |\nUser: {username}\nNo display name set```")
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Display Name |\nError: {str(e)}```")
    @bot.command(name="setdisplayname", aliases=["setglobalname", "setname", "changename", "setdn"])
    def setdisplayname(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set Display Name")
            return
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetName** :: Usage: `{bot.prefix}setname <display name>`")
            return

        display_name = " ".join(args)
        api = ctx["api"]
        try:
            patch = api.request("PATCH", "/users/@me", data={"global_name": display_name})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"], f"> **✓ SetName** :: Display name set to **{display_name}**")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    body = patch.json().get("message", "") if patch else ""
                except Exception:
                    body = ""
                msg = api.send_message(ctx["channel_id"], f"> **✗ SetName** :: Failed HTTP {code}{' — ' + body if body else ''}")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ SetName** :: Error: {str(e)[:80]}")
    @bot.command(name="stealname", aliases=["copyname"])
    def stealname(ctx, args):
        # Usage: +stealname <user_id|@mention> [server]
        # 'server' flag steals their server nickname and applies as your server nickname in this guild
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"> **StealName** :: Usage: `{bot.prefix}stealname <user_id> [server]`")
            return

        raw = args[0].strip("<@!>")
        user_id = raw if raw.isdigit() else args[0]
        server_mode = len(args) >= 2 and args[1].lower() in ("server", "guild", "s", "g")
        guild_id = ctx["message"].get("guild_id")
        api = ctx["api"]

        try:
            if server_mode:
                if not guild_id:
                    msg = api.send_message(ctx["channel_id"], "> **✗ StealName** :: Must be in a server for server mode")
                    return
                member_r = api.request("GET", f"/guilds/{guild_id}/members/{user_id}")
                if not member_r or member_r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealName** :: Could not find member {user_id} in this server")
                    return
                member_data = member_r.json()
                nick = member_data.get("nick")
                target_name = (member_data.get("user") or {}).get("username", user_id)
                if not nick:
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✗ StealName** :: **{target_name}** has no server nickname")
                    return
                patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me",
                                    data={"nick": nick})
                if patch and patch.status_code in (200, 204):
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✓ StealName** :: Set nickname to **{nick}** (from {target_name})")
                else:
                    code = patch.status_code if patch else "no response"
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✗ StealName** :: Failed to set nickname (HTTP {code})")
            else:
                user_r = api.request("GET", f"/users/{user_id}")
                if not user_r or user_r.status_code != 200:
                    msg = api.send_message(ctx["channel_id"], f"> **✗ StealName** :: User not found: {user_id}")
                    return
                user_data = user_r.json()
                global_name = user_data.get("global_name") or ""
                target_name = user_data.get("username", user_id)
                if not global_name:
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✗ StealName** :: **{target_name}** has no display name set")
                    return
                patch = api.request("PATCH", "/users/@me", data={"global_name": global_name})
                if patch and patch.status_code == 200:
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✓ StealName** :: Set display name to **{global_name}** (from {target_name})")
                else:
                    code = patch.status_code if patch else "no response"
                    msg = api.send_message(ctx["channel_id"],
                        f"> **✗ StealName** :: Failed to set display name (HTTP {code})")

        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ StealName** :: Error: {str(e)[:80]}")

    @bot.command(name="stop", aliases=["exit", "quit"])
    def stop_bot(ctx, args):
        msg = ctx["api"].send_message(ctx["channel_id"], "`Stopping bot...```")
        bot.stop()
    @bot.command(name="setstatus", aliases=["customstatus"])
    def setstatus(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **SetStatus** :: Usage: `{bot.prefix}setstatus [emoji,] <text>` — e.g. `{bot.prefix}setstatus 🎮, Gaming now`")
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
                msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ SetStatus** :: Provide status text after the comma")
                return
            
            custom_emoji_pattern = r"<:([a-zA-Z0-9_]+):([0-9]+)>"
            custom_emoji_match = re.match(custom_emoji_pattern, emoji_part)
            
            if custom_emoji_match:
                emoji_name = custom_emoji_match.group(1)
                emoji_id = custom_emoji_match.group(2)
            
            elif len(emoji_part) == 1 or (len(emoji_part) > 1 and any(ord(c) > 127 for c in emoji_part)):
                emoji_name = emoji_part
            
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ SetStatus** :: Invalid emoji — use standard emoji or `<:name:id>`")
                return
            
            message = text_part
        
        if not message:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ SetStatus** :: Please provide status text")
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
                msg = ctx["api"].send_message(ctx["channel_id"], "> **✓ SetStatus** :: Status updated")
            elif result and result.status_code == 429:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ SetStatus** :: Rate limited")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ SetStatus** :: Failed to set status")
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ SetStatus** :: Error: {str(e)[:80]}")
    @bot.command(name="stealstatus", aliases=["copystatus"])
    def stealstatus(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **✗ StealStatus** :: Please provide a user ID")
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
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ StealStatus** :: **{username}**'s custom status is private — cannot be retrieved")
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ StealStatus** :: Error: {str(e)[:80]}")
    # -----------------------------------------------------------------------
    # stealserverpfp — steal a member's SERVER avatar and apply as YOURS in this server
    # -----------------------------------------------------------------------

    @bot.command(name="stealserverpfp", aliases=["sspfp", "ssavatar", "stealservavatar"])
    def stealserverpfp_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"> **StealServerPFP** :: Usage: `{bot.prefix}stealserverpfp <user_id>`")
            return

        raw = args[0].strip("<@!>")
        user_id = raw if raw.isdigit() else args[0]
        guild_id = ctx["message"].get("guild_id")
        api = ctx["api"]

        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "> **✗ StealServerPFP** :: Must be used inside a server")
            return

        try:
            member_r = api.request("GET", f"/guilds/{guild_id}/members/{user_id}")
            if not member_r or member_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"> **✗ StealServerPFP** :: Could not find member {user_id} in this server")
                return

            member_data = member_r.json()
            avatar_hash = member_data.get("avatar")
            user_obj = member_data.get("user") or {}
            target_name = user_obj.get("username", user_id)

            if not avatar_hash:
                msg = api.send_message(ctx["channel_id"],
                    f"> **✗ StealServerPFP** :: **{target_name}** has no server avatar — try `{bot.prefix}stealpfp`")
                return

            ext = "gif" if avatar_hash.startswith("a_") else "png"
            img_url = f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/avatars/{avatar_hash}.{ext}?size=1024"

            img_r = api.session.get(img_url, timeout=10)
            if img_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"> **✗ StealServerPFP** :: Failed to download (HTTP {img_r.status_code})")
                return

            b64 = base64.b64encode(img_r.content).decode()
            patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me",
                                data={"avatar": f"data:image/{ext};base64,{b64}"})
            if patch and patch.status_code in (200, 204):
                msg = api.send_message(ctx["channel_id"],
                    f"> **✓ StealServerPFP** :: Applied **{target_name}**'s avatar as your server avatar")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    err = (patch.json() or {}).get("message", "") if patch else ""
                except Exception:
                    err = ""
                msg = api.send_message(ctx["channel_id"],
                    f"> **✗ StealServerPFP** :: Failed (HTTP {code}){': ' + err if err else ''} (Nitro required)")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ StealServerPFP** :: Error: {str(e)[:80]}")

    # -----------------------------------------------------------------------
    # stealserverbanner — steal a member's SERVER banner and apply as YOURS
    # -----------------------------------------------------------------------

    @bot.command(name="stealserverbanner", aliases=["ssbanner", "stealservbanner"])
    def stealserverbanner_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Steal Server Banner |\nUsage: {bot.prefix}stealserverbanner <user_id|@mention>\nSteals their server-specific banner and sets it as YOUR server banner in this server```")
            return

        raw = args[0].strip("<@!>")
        user_id = raw if raw.isdigit() else args[0]
        guild_id = ctx["message"].get("guild_id")
        api = ctx["api"]

        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "```| Steal Server Banner |\nMust be used inside a server```")
            return

        try:
            member_r = api.request("GET", f"/guilds/{guild_id}/members/{user_id}")
            if not member_r or member_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Server Banner |\nCould not find member {user_id} in this server```")
                return

            member_data = member_r.json()
            banner_hash = member_data.get("banner")
            user_obj = member_data.get("user") or {}
            target_name = user_obj.get("username", user_id)

            if not banner_hash:
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Banner |\n{target_name} has no server-specific banner in this server\nTip: use {bot.prefix}stealbanner to steal their global banner```")
                return

            ext = "gif" if banner_hash.startswith("a_") else "png"
            img_url = f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/banners/{banner_hash}.{ext}?size=1024"

            img_r = api.session.get(img_url, timeout=10)
            if img_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Server Banner |\nFailed to download (HTTP {img_r.status_code})```")
                return

            b64 = base64.b64encode(img_r.content).decode()
            patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me",
                                data={"banner": f"data:image/{ext};base64,{b64}"})
            if patch and patch.status_code in (200, 204):
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Banner |\nApplied {target_name}'s server banner as YOUR server banner in this server```")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    err = (patch.json() or {}).get("message", "") if patch else ""
                except Exception:
                    err = ""
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Banner |\nFailed (HTTP {code}){': ' + err if err else ''}\nNote: server banners require Nitro```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Steal Server Banner |\nError: {str(e)[:80]}```")

    # -----------------------------------------------------------------------
    # stealservernick — steal a member's SERVER nickname and apply as yours
    # -----------------------------------------------------------------------

    @bot.command(name="stealservernick", aliases=["ssnick", "stealservnick", "stealsnick"])
    def stealservernick_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Steal Server Nick |\nUsage: {bot.prefix}stealservernick <user_id|@mention>\nSteals their server nickname and sets it as YOUR nickname in this server```")
            return

        raw = args[0].strip("<@!>")
        user_id = raw if raw.isdigit() else args[0]
        guild_id = ctx["message"].get("guild_id")
        api = ctx["api"]

        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "```| Steal Server Nick |\nMust be used inside a server```")
            return

        try:
            member_r = api.request("GET", f"/guilds/{guild_id}/members/{user_id}")
            if not member_r or member_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Server Nick |\nCould not find member {user_id} in this server```")
                return

            member_data = member_r.json()
            nick = member_data.get("nick")
            user_obj = member_data.get("user") or {}
            target_name = user_obj.get("username", user_id)

            if not nick:
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Nick |\n{target_name} has no server nickname set```")
                return

            patch = api.request("PATCH", f"/guilds/{guild_id}/members/@me",
                                data={"nick": nick})
            if patch and patch.status_code in (200, 204):
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Nick |\nSet YOUR nickname to: {nick}\n(stolen from {target_name})```")
            else:
                code = patch.status_code if patch else "no response"
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Nick |\nFailed to set nickname (HTTP {code})```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Steal Server Nick |\nError: {str(e)[:80]}```")

    # -----------------------------------------------------------------------
    # stealservericon — steal the SERVER'S icon and set as your global avatar
    # -----------------------------------------------------------------------

    @bot.command(name="stealservericon", aliases=["ssicon", "stealicon", "stealguildicon"])
    def stealservericon_cmd(ctx, args):
        # No args needed — steals current server's icon; can also pass a guild_id
        guild_id = args[0] if args and args[0].isdigit() else ctx["message"].get("guild_id")
        api = ctx["api"]

        if not guild_id:
            msg = api.send_message(ctx["channel_id"],
                f"```| Steal Server Icon |\nUsage: {bot.prefix}stealservericon [guild_id]\nSteals the server's icon and sets it as YOUR global avatar\n(no guild_id needed when used inside the server)```")
            return

        try:
            guild_r = api.request("GET", f"/guilds/{guild_id}")
            if not guild_r or guild_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Server Icon |\nCould not fetch guild {guild_id}```")
                return

            guild_data = guild_r.json()
            icon_hash = guild_data.get("icon")
            guild_name = guild_data.get("name", guild_id)

            if not icon_hash:
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Icon |\n{guild_name} has no server icon```")
                return

            ext = "gif" if icon_hash.startswith("a_") else "png"
            img_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.{ext}?size=1024"

            img_r = api.session.get(img_url, timeout=10)
            if img_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Server Icon |\nFailed to download (HTTP {img_r.status_code})```")
                return

            b64 = base64.b64encode(img_r.content).decode()
            patch = api.request("PATCH", "/users/@me",
                                data={"avatar": f"data:image/{ext};base64,{b64}"})
            if patch and patch.status_code == 200:
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Icon |\nSet {guild_name}'s icon as YOUR global avatar```")
            else:
                code = patch.status_code if patch else "no response"
                try:
                    err = (patch.json() or {}).get("message", "") if patch else ""
                except Exception:
                    err = ""
                msg = api.send_message(ctx["channel_id"],
                    f"```| Steal Server Icon |\nFailed to set avatar (HTTP {code}){': ' + err if err else ''}```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Steal Server Icon |\nError: {str(e)[:80]}```")

    @bot.command(name="help", aliases=["h", "commands"])
    def show_help(ctx, args):
        import formatter as fmt
        p = bot.prefix  # live prefix — auto-reflects config changes

        def help_page(title, *lines):
            return {"title": title, "lines": list(lines)}

        def render_help_page(page_name, content, current_page, total_pages):
            title = content.get("title", "Help")
            lines = content.get("lines", [])
            out = []
            for line in lines:
                if isinstance(line, tuple) and len(line) == 2:
                    out.append(f"{fmt.PINK}{line[0]:<24}{fmt.DARK}:: {fmt.RESET}{fmt.GREEN}{line[1]}{fmt.RESET}")
                elif isinstance(line, dict) and line.get("type") == "section":
                    section_text = str(line.get("text", "")).strip().lower()
                    if section_text in {"tip", "tips", "note", "notes", "usage"}:
                        continue
                    out.append(f"  [{line['text']}]")
                elif line == "":
                    out.append("")
                else:
                    line_text = str(line)
                    if line_text.strip().lower().startswith(("tip:", "note:", "usage:")):
                        continue
                    out.append(line_text)
            body = "\n".join(out)

            if total_pages > 1:
                footer_line = (
                    f"{fmt.GREEN}{p}help {page_name} [1-{total_pages}]{fmt.RESET}"
                    f"{fmt.DARK} | page {current_page}/{total_pages}{fmt.RESET}"
                )
            else:
                footer_line = f"{fmt.GREEN}{p}help {page_name}{fmt.RESET}"
            
            return "\n".join(
                [
                    fmt.header(f"Help {page_name.title()}"),
                    fmt._block(
                        f"{fmt.PINK}{title}{fmt.RESET}\n"
                        f"\n{body}\n"
                        f"\n{footer_line}"
                    ),
                ]
            )

        help_pages = {
            # ── General ──────────────────────────────────────────────────────
            "general": {
                "title": f"{p}help General",
                "lines": [
                    ("help [category|command]", "Open the main help system"),
                    ("helpwall", "Show the full command wall"),
                    ("quickhelp", "Show common starter commands"),
                    ("categories", "List command-engine categories"),
                    ("commands", "Show command overview"),
                    ("ping", "Test bot latency"),
                    ("profile [user_id]", "Show a user profile"),
                    ("guilds", "List your guilds"),
                    ("autoreact [emoji]", "Auto-react to your own messages"),
                    ("bold <text>", "Make text bold"),
                    ("italic <text>", "Make text italic"),
                    ("quote <text>", "Quote text"),
                    ("mock <text>", "Mock text"),
                    ("flip <text>", "Flip text upside down"),
                    ("version", "Show Aria version"),
                    ("restart", "Restart the bot"),
                ],
            },

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
                            f"{p}client <web|desktop|mobile|vr>",
                            "Switches the client platform Discord sees for this session.",
                            "",
                            {"type": "section", "text": "Aliases"},
                            "clienttype, ct",
                            "",
                            {"type": "section", "text": "Arguments"},
                            ("type", "One of web, desktop, mobile, or vr"),
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
                    ("join <invite>", "Join a server via invite"),
                ],
            },

            # ── RPC ──────────────────────────────────────────────────────────
            "rpc": {
                "title": f"{p}help RPC",
                "lines": [
                    ("rpc spotify <args>", "Song | Artist | Album | Elapsed [| Total] [| img]"),
                    ("rpc youtube <args>", "Title | Channel | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc soundcloud <args>", "Track | Artist | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc youtube_music <args>", "Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc applemusic <args>", "Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc deezer <args>", "Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc tidal <args>", "Track | Artist/Playlist | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc twitch <args>", "Stream Title | Channel | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc kick <args>", "Stream Title | Channel | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc netflix <args>", "Title | Show/Movie | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc disneyplus <args>", "Title | Show/Movie | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc primevideo <args>", "Title | Show/Movie | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc plex <args>", "Title | Library/User | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc jellyfin <args>", "Title | Library/User | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc vscode <args>", "Workspace/Task | File/Project | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc browser <args>", "Tab/Task | Site | Elapsed [| Total] [| img] [>> Btn >> URL]"),
                    ("rpc listening <args>", "Details | State | Name [| img] [>> Btn >> URL]"),
                    ("rpc streaming <args>", "Details | State | Name [| img] [>> Btn >> URL]"),
                    ("rpc playing <args>", "Details | State | Name [| img]"),
                    ("rpc timer <args>", "Details | State | Name | Start | End [| img]"),
                    ("rpc crunchyroll <args>", "name=<show> episode_title=<ep> elapsed_minutes=<n> total_minutes=<n> [image_url=<url>]"),
                    ("rpc stop", "Clear all activities"),
                    "",
                    {"type": "section", "text": "Aliases"},
                    "ytmusic/youtubemusic => youtube_music",
                    "apple_music => applemusic",
                    "disney+, disney_plus => disneyplus",
                    "prime, prime_video, amazonprime, amazon_prime => primevideo",
                    "chrome, web => browser",
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

                        "rpc mode": help_page(
                            f"{p}rpc <type> <args>",
                            "Sets a custom Rich Presence activity on your account.",
                            "",
                            {"type": "section", "text": "Tip"},
                            f"Use {p}help rpc to see all RPC subcommands and formats.",
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
                    ("auth <user_id>", "Grant account access (owner)"),
                    ("unauth <user_id>", "Revoke account access (owner)"),
                    ("authlist", "List authed users"),
                    ("listhosted", "List your hosted tokens"),
                    ("listallhosted", "List all hosted tokens (owner)"),
                    ("stopallhosted", "Stop all hosted tokens now (owner)"),
                    ("restartallhosted", "Restart all hosted tokens now (owner)"),
                    ("clearhost [uid]", "Remove a hosted entry"),
                    ("clearallhosted", "Clear all hosted entries (owner)"),
                ],
            },

            "auth": help_page(
                f"{p}auth <user_id>",
                "Grants account access to a user (owner only).",
                "",
                {"type": "section", "text": "Arguments"},
                ("user_id", "Discord user ID to authorize"),
            ),

            "unauth": help_page(
                f"{p}unauth <user_id>",
                "Revokes account access from a user (owner only).",
                "",
                {"type": "section", "text": "Arguments"},
                ("user_id", "Discord user ID to deauthorize"),
            ),

            "authlist": help_page(
                f"{p}authlist",
                "Lists all currently authorized users.",
            ),

            "listhosted": help_page(
                f"{p}listhosted",
                "Lists your currently hosted tokens.",
            ),

            "listallhosted": help_page(
                f"{p}listallhosted",
                "Lists all hosted tokens (owner only).",
            ),

            "clearhost": help_page(
                f"{p}clearhost [user_id]",
                "Removes a hosted token entry.",
            ),

            "clearallhosted": help_page(
                f"{p}clearallhosted",
                "Clears all hosted token entries (owner only).",
            ),

            "stopallhosted": help_page(
                f"{p}stopallhosted",
                "Stops all running hosted token processes immediately (owner only).",
                "",
                {"type": "section", "text": "Aliases"},
                "stopall, killallhosted",
            ),

            "restartallhosted": help_page(
                f"{p}restartallhosted",
                "Restarts all persisted hosted token processes (owner only).",
                "",
                {"type": "section", "text": "Aliases"},
                "restartall, rebootallhosted",
            ),

            # ── Owner ────────────────────────────────────────────────────────
            "owner": {
                "title": f"{p}help Owner",
                "lines": [
                    ("auth <user_id>", "Grant account access"),
                    ("unauth <user_id>", "Revoke account access"),
                    ("authlist", "List authed users"),
                    ("listallhosted", "List all hosted tokens"),
                    ("stopallhosted", "Stop all hosted tokens now"),
                    ("restartallhosted", "Restart all hosted tokens now"),
                    ("clearallhosted", "Clear all hosted entries"),
                    (f"{p}drun", "Execute commands on instances"),
                    (f"{p}dlog", "Manage developer logging"),
                    (f"{p}ddebug", "Toggle developer debug mode"),
                    (f"{p}dmetrics", "Show developer metrics"),
                    (f"{p}djoininvite", "Join servers with instances"),
                    (f"{p}dleaveguild", "Leave guilds with instances"),
                    (f"{p}dmyguilds", "List guilds for instances"),
                    (f"{p}dmassleave", "Mass leave guilds with instances"),
                    (f"{p}dguildmembers", "List guild members on instances"),
                    (f"{p}dchecktoken", "Validate a token"),
                    (f"{p}dbulkcheck", "Validate multiple tokens"),
                    (f"{p}dexportguilds", "Export guild lists"),
                    (f"{p}dboost", "Run boost commands on instances"),
                    (f"{p}dboosttransfer", "Transfer boosts on instances"),
                    (f"{p}dbooststatus", "Show boost status on instances"),
                    (f"{p}dboostlist", "List boosted servers on instances"),
                    (f"{p}daccountcmd", "Run any command on instances"),
                    (f"{p}drpc", "Run RPC on instances"),
                    (f"{p}drecentmessages", "Show tracked recent messages"),
                ],
            },

                        "drun": help_page(
                                f"{p}drun",
                                "Execute commands on multiple bot instances.",
                                "",
                            f"Format: {p}drun <uid/all/others> [channel_id] <cmd/say> [args...]",
                                "",
                                {"type": "section", "text": "Examples"},
                            f"{p}drun 1 say Hello - Send in current channel",
                            f"{p}drun all cmd ping - Run ping in current channel",
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

                        "dboost": help_page(
                            f"{p}dboost <uid/all/others> <boost_args...>",
                            "Run boost subcommands on selected instances.",
                            "",
                            {"type": "section", "text": "Examples"},
                            f"{p}dboost all status",
                            f"{p}dboost 1 transfer 123456789",
                            f"{p}dboost others list",
                        ),

                        "dboosttransfer": help_page(
                            f"{p}dboosttransfer <uid/all/others> <to_guild_id>",
                            "Transfer available boosts to a guild from selected instances.",
                            "",
                            {"type": "section", "text": "Examples"},
                            f"{p}dboosttransfer all 123456789",
                            f"{p}dboosttransfer 1,2,3 123456789",
                        ),

                        "dbooststatus": help_page(
                            f"{p}dbooststatus [uid/all/others]",
                            "Show boost status from selected instances.",
                            "",
                            {"type": "section", "text": "Examples"},
                            f"{p}dbooststatus",
                            f"{p}dbooststatus all",
                            f"{p}dbooststatus others",
                        ),

                        "dboostlist": help_page(
                            f"{p}dboostlist [uid/all/others]",
                            "List boosted servers from selected instances.",
                            "",
                            {"type": "section", "text": "Examples"},
                            f"{p}dboostlist",
                            f"{p}dboostlist all",
                            f"{p}dboostlist 1,2",
                        ),

                        "daccountcmd": help_page(
                            f"{p}daccountcmd <uid/all/others> <command> [args...]",
                            "Run any existing command across selected instances.",
                            "",
                            {"type": "section", "text": "Examples"},
                            f"{p}daccountcmd all joininvite abc123",
                            f"{p}daccountcmd others checktoken token_here",
                            f"{p}daccountcmd 1,2 boost status",
                        ),

                        "drpc": help_page(
                            f"{p}drpc <uid/all/others> <rpc_mode> [rpc_args...]",
                            "Run rich presence modes on selected instances.",
                            "",
                            {"type": "section", "text": "Examples"},
                            f"{p}drpc all stop",
                            f"{p}drpc 1 spotify Song | Artist | Album | 1.0 | 3.5",
                            f"{p}drpc others youtube Title | Channel | 2.0 | 10",
                            f"{p}drpc all crunchyroll name=Solo episode_title=Ep1 elapsed_minutes=3 total_minutes=24",
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
                    ("questclaim", "Claim all claimable quest rewards"),
                    ("questautoclaimer <sub>", "All-in-one quest auto claimer"),
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

            "questclaim": help_page(
                f"{p}questclaim",
                "Claims all currently claimable quest rewards.",
                "",
                {"type": "section", "text": "Aliases"},
                "qclaim, qc",
            ),

            "questautoclaimer": help_page(
                f"{p}questautoclaimer <start|stop|status|refresh|enroll|claim>",
                "Unified quest automation command.",
                "",
                {"type": "section", "text": "Aliases"},
                "quest-auto-claimer, qac, autoclaimer",
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
                    ("auth <user_id>", "Grant access"),
                    ("unauth <user_id>", "Revoke access"),
                    ("authlist", "List authed users"),
                    ("listhosted", "Your hosted tokens"),
                    ("listallhosted", "All hosted (owner)"),
                    ("stopallhosted", "Stop all hosted now (owner)"),
                    ("restartallhosted", "Restart all hosted now (owner)"),
                    ("clearhost [uid]", "Remove hosted entry"),
                    ("clearallhosted", "Clear all hosted (owner)"),
                    ("afk [reason]", "Set AFK status"),
                    ("afkstatus [id]", "Check AFK"),
                    ("nitro on/off", "Nitro sniper"),
                    ("giveaway [on|off]", "Giveaway sniper"),
                    ("nitro clear", "Clear codes"),
                    ("badges user <user_id>", "User badges"),
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
                    (f"{p}drun", "Owner: Execute on instances"),
                    (f"{p}dlog", "Owner: Logging"),
                    (f"{p}ddebug", "Owner: Debug mode"),
                    (f"{p}dmetrics", "Owner: Metrics"),
                    (f"{p}djoininvite", "Owner: Join servers"),
                    (f"{p}dleaveguild", "Owner: Leave guilds"),
                    (f"{p}dmyguilds", "Owner: List guilds"),
                    (f"{p}dmassleave", "Owner: Mass leave"),
                    (f"{p}dguildmembers", "Owner: Guild members"),
                    (f"{p}dchecktoken", "Owner: Check token"),
                    (f"{p}dbulkcheck", "Owner: Bulk tokens"),
                    (f"{p}dexportguilds", "Owner: Export guilds"),
                    (f"{p}dboost", "Owner: Boost commands"),
                    (f"{p}dboosttransfer", "Owner: Boost transfer"),
                    (f"{p}dbooststatus", "Owner: Boost status"),
                    (f"{p}dboostlist", "Owner: Boosted list"),
                    (f"{p}daccountcmd", "Owner: Any account command"),
                    (f"{p}drpc", "Owner: RPC commands"),
                    (f"{p}drecentmessages", "Owner: Messages"),
                ],
            },
        }

        if not args:
            categories = [
                ("General", "Starter"),
                ("Utility", "Tools"),
                ("Messaging", "DM/GC"),
                ("Profile", "Identity"),
                ("Server", "Guild"),
                ("Voice", "VC"),
                ("Social", "Interaction"),
                ("RPC", "Presence"),
                ("Boost", "Boosts"),
                ("Backup", "Recovery"),
                ("Moderation", "Mod"),
                ("Hosting", "Hosted"),
                ("Token", "Session"),
                ("AFK", "AFK"),
                ("Nitro", "Sniper"),
                ("AGCT", "Anti-GC"),
                ("Quest", "Quests"),
            
            ]
            if is_owner_user(ctx["author_id"]):
                categories.insert(0, ("Owner", "Admin"))
            cat_cmds = [(f"{p}help {cat}", desc) for cat, desc in categories]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "\n".join([
                    fmt.header("Help"),
                    fmt.command_list(cat_cmds),
                    fmt._block(f"{fmt.DARK}Developed by {fmt.WHITE}Misconsiderations{fmt.RESET}"),
                ]),
            )
            return
        
        # Parse "help <category> page <n>" (preferred) and legacy "help <category> <n>"
        page_num = 1
        full_page = " ".join(args).lower()
        if len(args) >= 3 and args[-2].lower() == "page" and args[-1].isdigit():
            page_num = int(args[-1])
            full_page = " ".join(args[:-2]).lower()
        elif args and args[-1].isdigit() and len(args) > 1:
            page_num = int(args[-1])
            full_page = " ".join(args[:-1]).lower()
        
        page = full_page if full_page in help_pages else (args[0].lower() if args else "")
        
        if page == "owner" and not is_owner_user(ctx["author_id"]):
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "\n".join(
                    [
                        fmt.header("Help"),
                        fmt._block(
                            f"{fmt.YELLOW}Unknown help page{fmt.RESET}\n"
                            f"{fmt.PINK}Try{fmt.DARK} :: {fmt.RESET}{fmt.GREEN}{p}help general{fmt.RESET}"
                        ),
                    ]
                ),
            )
            return

        if page in help_pages:
            content = help_pages[page]
            lines = content.get("lines", [])
            lines_per_page = 8  # Split into more pages
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
                pass
        else:
            # Fallback: if the user asked for a real command name that lacks a static help page,
            # show command details dynamically so new commands remain discoverable.
            lookup = (full_page or (args[0] if args else "")).strip().lower()
            cmd = ctx["bot"].commands.get(lookup) if lookup else None
            if cmd:
                aliases = ", ".join(cmd.aliases) if getattr(cmd, "aliases", None) else "none"
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    "\n".join(
                        [
                            fmt.header(cmd.name),
                            fmt._block(
                                f"{fmt.CYAN}Command{fmt.DARK} :: {fmt.RESET}{fmt.WHITE}{p}{cmd.name}{fmt.RESET}\n"
                                f"{fmt.CYAN}Aliases{fmt.DARK} :: {fmt.RESET}{fmt.WHITE}{aliases}{fmt.RESET}"
                            ),
                        ]
                    ),
                )
            else:
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    "\n".join(
                        [
                            fmt.header("Help"),
                            fmt._block(
                                f"{fmt.YELLOW}Unknown help page{fmt.RESET}\n"
                                f"{fmt.PINK}Try{fmt.DARK} :: {fmt.RESET}{fmt.GREEN}{p}help general{fmt.RESET}"
                            ),
                        ]
                    ),
                )
    @bot.command(name="cmdwall", aliases=["commandsraw", "allcmds"])
    def cmdwall(ctx, args):
        import formatter as _fmt
        # Collect unique commands (primary names only), sorted
        seen = set()
        unique = []
        for key in sorted(ctx["bot"].commands.keys()):
            cmd = ctx["bot"].commands[key]
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            unique.append(cmd)

        p = ctx["bot"].prefix
        chunk, messages = [], []
        for cmd in unique:
            alias_str = f" [{', '.join(cmd.aliases)}]" if cmd.aliases else ""
            chunk.append(f"{_fmt.CYAN}{p}{cmd.name}{_fmt.RESET}{_fmt.DARK}{alias_str}{_fmt.RESET}")
            if len(chunk) >= 30:
                messages.append(_fmt._block("\n".join(chunk)))
                chunk = []
        if chunk:
            messages.append(_fmt._block("\n".join(chunk)))

        for i, part in enumerate(messages):
            msg = ctx["api"].send_message(ctx["channel_id"], part)
            if msg and i < len(messages) - 1:
                time.sleep(0.3)
            elif msg:
                pass

    @bot.command(name="restart")
    def restart_cmd(ctx, args):
        msg = ctx["api"].send_message(ctx["channel_id"], "> **Restarting** bot in 3 seconds...")
        
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

            # Terminate all hosted child processes so the new instance
            # can cleanly restore them all via restore_hosted_users().
            if not HOSTED_MODE:
                try:
                    host_manager.cleanup()
                except Exception:
                    pass

            python = sys.executable
            subprocess.Popen([python, "main.py"])

            time.sleep(1)
            bot.stop()
        
        threading.Thread(target=restart_sequence, daemon=True).start()
        
    @bot.command(name="vc", aliases=["voice", "joinvc"])
    def vc(ctx, args):
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "> **Join VC** | Usage: +vc <channel_id>")
            return
        
        channel_id = args[0]
        
        try:
            success = voice_manager.join_vc(channel_id)
            
            if success:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Connected to Voice** | Channel: **{channel_id}**")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Failed** to connect to voice channel")
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Voice error**: {str(e)[:80]}")
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
            
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Voice error**: {str(e)[:80]}")
    @bot.command(name="vccam", aliases=["cam", "camera"])
    def vccam(ctx, args):
        enabled = True
        if args and args[0].lower() in ("off", "false", "0"):
            enabled = False
        channel_id = args[1] if len(args) > 1 else None
        try:
            ok, detail = voice_manager.set_video(channel_id, enabled)
            if ok:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ Camera** :: {detail}")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ Camera** :: {detail}")
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ Camera error**: {str(e)[:80]}")
    @bot.command(name="vcstream", aliases=["stream", "golive"])
    def vcstream(ctx, args):
        enabled = True
        if args and args[0].lower() in ("off", "stop", "false", "0"):
            enabled = False
        channel_id = args[1] if len(args) > 1 else None
        try:
            ok, detail = voice_manager.set_stream(channel_id, enabled)
            if ok:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✓ Go Live** :: {detail}")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ Go Live** :: {detail}")
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **✗ Stream error**: {str(e)[:80]}")
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
    @bot.command(name="questclaim", aliases=["qclaim", "qc"])
    def questclaim_cmd(ctx, args):
        quest_system.fetch_quests()
        s = quest_system.get_summary()
        claimable = s["claimable"]
        if not claimable:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Quest |\nNo claimable quests```")
            return

        claimed = 0
        failed = 0
        for q in claimable:
            if quest_system.claim(q):
                claimed += 1
            else:
                failed += 1
            time.sleep(0.6)

        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Quest Claim |\nClaimed: {claimed} | Failed: {failed}```",
        )
    @bot.command(name="queststart", aliases=["qstart", "qs"])
    def queststart_cmd(ctx, args):
        ok_fetch, fetch_detail = quest_system.fetch_quests()
        if not ok_fetch:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Quest** refresh failed: {fetch_detail}.")
            return
        ok, detail = quest_system.start()
        if ok:
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Quest enabled**. {detail}.")
        else:
            msg = ctx["api"].send_message(ctx["channel_id"], f"Quest error: {detail}.")
    @bot.command(name="queststop", aliases=["qstop", "qx"])
    def queststop_cmd(ctx, args):
        ok, detail = quest_system.stop()
        msg = ctx["api"].send_message(ctx["channel_id"], f"> **Quest disabled**. {detail}.")
    @bot.command(name="questrefresh", aliases=["qr", "qrefresh"])
    def questrefresh_cmd(ctx, args):
        ok, detail = quest_system.fetch_quests()
        s = quest_system.get_summary()
        status = "Refreshed" if ok else "Failed"
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Quest |\n{status}: {detail}\nTotal: {s['total']} | Enrollable: {len(s['enrollable'])} | Claimable: {len(s['claimable'])}```",
        )
    @bot.command(name="questenroll", aliases=["qenroll", "qe"])
    def questenroll_cmd(ctx, args):
        quest_system.fetch_quests()
        s = quest_system.get_summary()
        enrollable = s["enrollable"]
        if not enrollable:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Quest |\nNo enrollable quests```")
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
    @bot.command(name="questautoclaimer", aliases=["quest-auto-claimer", "qac", "autoclaimer"])
    def questautoclaimer_cmd(ctx, args):
        sub = (args[0].lower() if args else "status")

        if sub == "status":
            quest_cmd(ctx, [])
            return

        if sub == "start":
            queststart_cmd(ctx, [])
            return

        if sub == "stop":
            queststop_cmd(ctx, [])
            return

        if sub == "refresh":
            questrefresh_cmd(ctx, [])
            return

        if sub == "enroll":
            questenroll_cmd(ctx, [])
            return

        if sub == "claim":
            questclaim_cmd(ctx, [])
            return

        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Quest Auto Claimer |\nUsage: {bot.prefix}questautoclaimer <start|stop|status|refresh|enroll|claim>```",
        )
    @bot.command(name="deco", aliases=["decoration", "profiledeco", "cleardeco", "removedeco"])
    def deco_cmd(ctx, args):
        import formatter as fmt
        sub = args[0].lower() if args else ""
        if sub != "remove":
            cmds = [
                (f"{bot.prefix}deco remove", "Remove avatar decoration & profile effect"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.header("Decoration") + "\n" + fmt.command_list(cmds),
            )
            return
        # Clear avatar decoration (type 3) and profile effect (type 4)
        resp = ctx["api"].request(
            "PATCH",
            "/users/@me/profile",
            data={"avatar_decoration_id": None, "profile_effect_id": None},
        )
        if resp and resp.status_code in (200, 204):
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("Decoration", {"Status": "Decoration & profile effect cleared"}),
            )
        else:
            code = resp.status_code if resp else "N/A"
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("Decoration", {"Status": f"Failed (HTTP {code})"}),
            )
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

    @bot.command(name="admin", aliases=["admins", "paneladmin"])
    def admin_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Admin")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Admin |\nUsage:\n{bot.prefix}admin add <user_id>\n{bot.prefix}admin remove <user_id>\n{bot.prefix}admin list```",
            )
            return

        action = args[0].lower()
        if action == "add" and len(args) >= 2 and args[1].isdigit():
            uid = str(args[1])
            _admin_users.add(uid)
            _save_id_set(_ADMIN_FILE, _admin_users)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Admin |\nAdded admin: {uid}```")
            return

        if action == "remove" and len(args) >= 2 and args[1].isdigit():
            uid = str(args[1])
            _admin_users.discard(uid)
            _save_id_set(_ADMIN_FILE, _admin_users)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Admin |\nRemoved admin: {uid}```")
            return

        if action == "list":
            entries = sorted(_admin_users)
            body = "\n".join(f"> {uid}" for uid in entries[:50]) if entries else "No admins configured"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Admin |\nTotal: {len(entries)}\n{body}```")
            return

        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Admin |\nUsage: add/remove/list```")

    @bot.command(name="auth", aliases=["authuser"])
    def auth_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Auth")
            return
        if not args or not args[0].isdigit():
            p = bot.prefix
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Auth |\nUsage: {p}auth <user_id>   — allow user to run commands\n       {p}unauth <user_id> — revoke access\n       {p}authlist       — list authed users```")
            return
        uid = str(args[0])
        _authed_users.add(uid)
        _dashboard_authed_users.add(uid)
        _dashboard_blocked_users.discard(uid)
        _save_authed(_authed_users)
        _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)
        _save_id_set(_DASH_BLOCK_FILE, _dashboard_blocked_users)
        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Auth |\n✓ User {uid} authorised```")
    @bot.command(name="unauth", aliases=["deauth"])
    def unauth_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Unauth")
            return
        if not args or not args[0].isdigit():
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Unauth |\nUsage: {bot.prefix}unauth <user_id>```")
            return
        uid = str(args[0])
        _authed_users.discard(uid)
        _dashboard_authed_users.discard(uid)
        _save_authed(_authed_users)
        _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)
        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Auth |\n✓ User {uid} revoked```")

    @bot.command(name="whitelist", aliases=["wl", "sitewl"])
    def whitelist_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Whitelist")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Whitelist |\nUsage:\n{bot.prefix}whitelist add <user_id>\n{bot.prefix}whitelist remove <user_id>\n{bot.prefix}whitelist list```",
            )
            return

        action = args[0].lower()
        if action == "add" and len(args) >= 2 and args[1].isdigit():
            uid = str(args[1])
            _dashboard_authed_users.add(uid)
            _authed_users.add(uid)
            _dashboard_blocked_users.discard(uid)
            _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)
            _save_id_set(_DASH_BLOCK_FILE, _dashboard_blocked_users)
            _save_authed(_authed_users)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Whitelist |\nAdded {uid}```")
            return

        if action == "remove" and len(args) >= 2 and args[1].isdigit():
            uid = str(args[1])
            _dashboard_authed_users.discard(uid)
            _authed_users.discard(uid)
            _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)
            _save_authed(_authed_users)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Whitelist |\nRemoved {uid}```")
            return

        if action == "list":
            lines = sorted(_dashboard_authed_users)
            body = "\n".join(f"> {uid}" for uid in lines[:50]) if lines else "No whitelisted users"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Whitelist |\nTotal: {len(lines)}\n{body}```")
            return

        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Whitelist |\nUsage: add/remove/list```")

    @bot.command(name="blacklist", aliases=["bl", "sitebl"])
    def blacklist_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Blacklist")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Blacklist |\nUsage:\n{bot.prefix}blacklist add <user_id>\n{bot.prefix}blacklist remove <user_id>\n{bot.prefix}blacklist list```",
            )
            return

        action = args[0].lower()
        if action == "add" and len(args) >= 2 and args[1].isdigit():
            uid = str(args[1])
            _dashboard_blocked_users.add(uid)
            _dashboard_authed_users.discard(uid)
            _authed_users.discard(uid)
            _save_id_set(_DASH_BLOCK_FILE, _dashboard_blocked_users)
            _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)
            _save_authed(_authed_users)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Blacklist |\nBlocked {uid}```")
            return

        if action == "remove" and len(args) >= 2 and args[1].isdigit():
            uid = str(args[1])
            _dashboard_blocked_users.discard(uid)
            _save_id_set(_DASH_BLOCK_FILE, _dashboard_blocked_users)
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Blacklist |\nUnblocked {uid}```")
            return

        if action == "list":
            lines = sorted(_dashboard_blocked_users)
            body = "\n".join(f"> {uid}" for uid in lines[:50]) if lines else "No blacklisted users"
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Blacklist |\nTotal: {len(lines)}\n{body}```")
            return

        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Blacklist |\nUsage: add/remove/list```")

    @bot.command(name="host", aliases=["hosttoken", "hostuser", "hostme", "addhost"])
    def host_cmd(ctx, args):
        if HOSTED_MODE:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Host |\nUnavailable on hosted instances```")
            return

        requester_id = str(ctx["author_id"])

        if not host_manager.hosting_enabled and not is_control_user(requester_id):
            deny_restricted_command(ctx, "Host")
            return

        try:
            with open("host_blacklist.json", "r") as f:
                host_bl = json.load(f)
        except Exception:
            host_bl = {}

        if requester_id in host_bl and not is_owner_user(requester_id):
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Host |\nYou are blocked from hosting. Contact @misconsiderations```",
            )
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Host |\nUsage: {bot.prefix}host <token> [prefix]\nExample: {bot.prefix}host mfa.xxxxxx ;```",
            )
            return

        token_input = args[0].strip("\"' ")
        prefix = args[1] if len(args) >= 2 else ";"
        api = ctx["api"]

        try:
            verify = api.session.get(
                "https://discord.com/api/v9/users/@me",
                headers={"Authorization": token_input, "Content-Type": "application/json"},
                timeout=12,
            )
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Host |\nToken check failed: {str(e)[:80]}```")
            return

        if verify.status_code != 200:
            msg = api.send_message(ctx["channel_id"], "```| Host |\nInvalid token```")
            return

        account = verify.json() or {}
        hosted_user_id = str(account.get("id", ""))
        hosted_username = str(account.get("username", "Unknown"))

        ok, detail = host_manager.host_token(
            owner_id=requester_id,
            token_input=token_input,
            prefix=prefix,
            user_id=hosted_user_id,
            username=hosted_username,
        )
        if not ok:
            msg = api.send_message(ctx["channel_id"], f"```| Host |\n{detail}```")
            return

        # Hosted users are automatically granted dashboard access unless explicitly blocked.
        if hosted_user_id:
            _dashboard_authed_users.add(hosted_user_id)
            _dashboard_blocked_users.discard(hosted_user_id)
            _save_id_set(_DASH_AUTH_FILE, _dashboard_authed_users)
            _save_id_set(_DASH_BLOCK_FILE, _dashboard_blocked_users)

        hosted_uid = "unknown"
        try:
            entries = host_manager.list_hosted_entries(requester_id)
            if entries:
                hosted_uid = str(entries[-1][1].get("uid") or entries[-1][0])
        except Exception:
            pass

        msg = api.send_message(
            ctx["channel_id"],
            f"```| Host |\nHosted: {hosted_username} ({hosted_user_id})\nUID: {hosted_uid}\nPrefix: {prefix}```",
        )

    @bot.command(name="authlist", aliases=["authed"])
    def authlist_cmd(ctx, args):
        import formatter as fmt
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Auth List")
            return
        if not _authed_users:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("Auth", {"Authorised Users": 0}),
            )
        else:
            lines = "\n".join(f"• {uid}" for uid in sorted(_authed_users))
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.info_block("Authed Users", lines + f"\n\nDashboard Whitelist: {len(_dashboard_authed_users)} | Dashboard Blacklist: {len(_dashboard_blocked_users)}"),
            )
    @bot.command(name="listallhosted", aliases=["lah"])
    def listallhosted_cmd(ctx, args):
        import formatter as fmt
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "List All Hosted")
            return
        hosted = host_manager.list_hosted_entries()
        if not hosted:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("All Hosted", {"Entries": 0}),
            )
            return
        lines = ["All Hosted Tokens"]
        for i, (token_id, u) in enumerate(hosted, 1):
            name = u.get("username") or "Unknown"
            user_id = u.get("user_id") or "?"
            uid = u.get("uid") or token_id
            lines.append(
                f"{i}. user={name} | user_id={user_id} | uid={uid} | id={token_id}"
            )
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            fmt.info_block("All Hosted", "\n".join(lines)),
        )
    @bot.command(name="listhosted", aliases=["lh"])
    def listhosted_cmd(ctx, args):
        import formatter as fmt
        hosted = host_manager.list_hosted_entries(ctx["author_id"])
        if not hosted:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("Hosted", {"Entries": 0}),
            )
            return
        lines = ["Your Hosted Tokens"]
        for i, (token_id, u) in enumerate(hosted, 1):
            name = u.get("username") or "Unknown"
            user_id = u.get("user_id") or "?"
            uid = u.get("uid") or token_id
            lines.append(
                f"{i}. user={name} | user_id={user_id} | uid={uid} | id={token_id}"
            )
        lines.append(f"\nUse {bot.prefix}clearhost [uid] to remove")
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            fmt.info_block("Hosted", "\n".join(lines)),
        )
    @bot.command(name="hostedlogs", aliases=["hlogs", "hostlog"])
    def hostedlogs_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Hosted Logs")
            return
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Hosted Logs |\nUsage: {bot.prefix}hostedlogs <uid> [lines=50]```")
            return
        uid = args[0]
        lines_count = 50
        if len(args) >= 2 and args[1].isdigit():
            lines_count = min(int(args[1]), 200)
        import os
        log_path = os.path.join("hosted_logs", f"hosted_{uid}.log")
        if not os.path.exists(log_path):
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Hosted Logs |\nNo log found for uid: {uid}```")
            return
        try:
            with open(log_path, "r", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines_count:]
            content = "".join(tail).replace("```", "'''")[:1800]
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Hosted Logs [{uid}] (last {len(tail)} lines) |\n{content}```")
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"],
                f"```| Hosted Logs |\nError reading log: {str(e)[:80]}```")
    @bot.command(name="hostedstatus", aliases=["hstatus", "hoststat"])
    def hostedstatus_cmd(ctx, args):
        import formatter as fmt
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Hosted Status")
            return
        all_entries = host_manager.list_hosted_entries()
        if not all_entries:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.status_box("Hosted Status", {"Entries": 0}),
            )
            return
        lines = ["Hosted Status"]
        for i, (token_id, u) in enumerate(all_entries, 1):
            uid = u.get("uid") or token_id
            name = u.get("username") or "Unknown"
            owner = u.get("owner") or "?"
            proc = host_manager.processes.get(token_id)
            if proc is None:
                status = "no process"
            elif proc.poll() is None:
                status = "running"
            else:
                status = f"exited({proc.poll()})"
            has_keepalive = token_id in host_manager._stop_events
            ka = "keepalive" if has_keepalive else "no-keepalive"
            lines.append(f"{i}. {name} | uid={uid} | owner={owner} | {status} | {ka}")
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            fmt.info_block("Hosted Status", "\n".join(lines)),
        )
    @bot.command(name="clearallhosted", aliases=["cah"])
    def clearallhosted_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Clear All Hosted")
            return
        removed = host_manager.remove_hosts(all_hosts=True)
        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Clear All Hosted |\nRemoved {removed} entries```")
    @bot.command(name="stopallhosted", aliases=["stopall", "killallhosted", "sah"])
    def stopallhosted_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Stop All Hosted")
            return
        stopped = host_manager.stop_all()
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Stop All Hosted |\nStopped {stopped} running instance{'s' if stopped != 1 else ''}```",
        )
    @bot.command(name="restartallhosted", aliases=["restartall", "rebootallhosted", "rah"])
    def restartallhosted_cmd(ctx, args):
        if not is_owner_like_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Restart All Hosted")
            return
        restarted = host_manager.restart_all()
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            f"```| Restart All Hosted |\nRestarted {restarted} hosted instance{'s' if restarted != 1 else ''}```",
        )
    @bot.command(name="clearhost", aliases=["ch"])
    def clearhost_cmd(ctx, args):
        # optional uid/index — if omitted clears all of caller's entries
        selectors = args if args else []
        removed = host_manager.remove_hosts(requester_id=ctx["author_id"], selectors=selectors)
        msg = ctx["api"].send_message(ctx["channel_id"], f"```| Clear Host |\nRemoved {removed} entr{'y' if removed == 1 else 'ies'}```")
    @bot.command(name="backup", aliases=["save"])
    def backup_cmd(ctx, args):
        msg = None
        if not args:
            import formatter as fmt
            p = bot.prefix
            cmds = [
                (f"{p}backup user", "Backup user data, friends, guilds"),
                (f"{p}backup messages <ch_id> [limit]", "Backup channel messages"),
                (f"{p}backup full", "Create complete backup (zipped)"),
                (f"{p}backup list", "List all backups"),
                (f"{p}backup restore <filename>", "Restore from backup"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.header("Backup Commands") + "\n" + fmt.command_list(cmds),
            )
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
            pass
    
    @bot.command(name="mod", aliases=["moderation"])
    def mod_cmd(ctx, args):
        msg = None
        if not args:
            import formatter as fmt
            p = bot.prefix
            cmds = [
                (f"{p}mod kick <id1,id2,...>", "Kick multiple users"),
                (f"{p}mod ban <id1,id2,...> [days]", "Ban users"),
                (f"{p}mod filter add <w1,w2,...>", "Add word filter"),
                (f"{p}mod filter check <text>", "Check text against filters"),
                (f"{p}mod cleanup channels", "Delete all channels"),
                (f"{p}mod cleanup roles", "Delete all roles"),
                (f"{p}mod members [limit]", "List server members"),
                (f"{p}mod channels", "List all channels"),
                (f"{p}mod roles", "List all roles"),
            ]
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.header("Moderation Commands") + "\n" + fmt.command_list(cmds),
            )
            return
        
        guild_id = ctx["message"].get("guild_id")
        if not guild_id:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Moderation |\n✗ This command only works in servers```")
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
            pass

    @bot.command(name="web", aliases=["panel"])
    def web_cmd(ctx, args):
        import formatter as fmt
        nonlocal web_panel

        force_reload = bool(args and args[0].lower() in {"reload", "refresh"})

        if web_panel is None or force_reload:
            # If panel is already running, Flask thread cannot be safely replaced in-process.
            if force_reload and web_panel is not None:
                panel_thread = getattr(web_panel, "_thread", None)
                if panel_thread and panel_thread.is_alive():
                    msg = ctx["api"].send_message(
                        ctx["channel_id"],
                        fmt.header("Web Panel")
                        + "\n"
                        + fmt._block(
                            f"{fmt.CYAN}Status{fmt.DARK}  :: {fmt.RESET}{fmt.WHITE}Already running; restart bot to apply page code updates{fmt.RESET}\n"
                            f"{fmt.CYAN}URL{fmt.DARK}     :: {fmt.RESET}{fmt.WHITE}http://127.0.0.1:8080{fmt.RESET}"
                        ),
                    )
                    return

            try:
                import webpanel as webpanel_module

                if force_reload:
                    importlib.invalidate_caches()
                    webpanel_module = importlib.reload(webpanel_module)

                web_panel = webpanel_module.WebPanel(bot.api, bot, host="127.0.0.1", port=8080)
            except Exception as e:
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    fmt.header("Web Panel")
                    + "\n"
                    + fmt._block(
                        f"{fmt.CYAN}Status{fmt.DARK}  :: {fmt.RESET}{fmt.WHITE}Failed to load web panel{fmt.RESET}\n"
                        f"{fmt.CYAN}Error{fmt.DARK}   :: {fmt.RESET}{fmt.WHITE}{e}{fmt.RESET}"
                    ),
                )
                return

        started = web_panel.start()
        if force_reload:
            status_line = "Reloaded web panel code and started interface" if started else "Reloaded web panel code (already running)"
        else:
            status_line = "Started web interface" if started else "Web interface already running"
        msg = ctx["api"].send_message(
            ctx["channel_id"],
            fmt.header("Web Panel") + "\n" + fmt._block(
                f"{fmt.CYAN}Status{fmt.DARK}  :: {fmt.RESET}{fmt.WHITE}{status_line}{fmt.RESET}\n"
                f"{fmt.CYAN}URL{fmt.DARK}     :: {fmt.RESET}{fmt.WHITE}http://127.0.0.1:8080{fmt.RESET}\n"
                f"{fmt.DARK}\u2022 View bot status{fmt.RESET}\n"
                f"{fmt.DARK}\u2022 View history/boost snapshot{fmt.RESET}\n"
                f"{fmt.DARK}\u2022 Refresh status panel{fmt.RESET}"
            ),
        )
    original_run_command = bot.run_command
    def new_run_command(command_name: str, ctx, args):
        channel_id = ctx.get("channel_id")
        message = ctx.get("message") or {}
        message_id = message.get("id")
        author_id = str(ctx.get("author_id") or "")

        command_response_state.enabled = True
        command_response_state.channel_id = channel_id
        command_response_state.delay = 20
        try:
            original_run_command(command_name, ctx, args)
        finally:
            command_response_state.enabled = False
            command_response_state.channel_id = None
            command_response_state.delay = 20

        if channel_id and message_id and (author_id == str(bot.user_id) or is_control_user(author_id)):
            try:
                ctx["api"].delete_message(channel_id, message_id)
            except Exception:
                pass
    
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
        is_hosted = is_control_user(author_id)

        # AFK notice check runs for ALL messages before the owner-only filter
        # so users who ping us while we're AFK get a reply
        if (
            content
            and author_id
            and author_id != str(bot.user_id)
            and channel_id
            and (f"<@{bot.user_id}>" in content or f"<@!{bot.user_id}>" in content)
            and afk_system.is_afk(bot.user_id)
        ):
            afk_data = afk_system.get_afk_info(bot.user_id)
            afk_since = int(time.time() - afk_data.get("since", time.time()))
            hours = afk_since // 3600
            minutes = (afk_since % 3600) // 60
            time_str = (f"{hours}h " if hours > 0 else "") + f"{minutes}m"
            bot.api.send_message(
                channel_id,
                f"```| AFK Notice |\nI'm currently AFK\nReason: {afk_data.get('reason', 'AFK')}\nDuration: {time_str}```",
            )

        # Auto-remove AFK when the owner sends any message
        if (
            author_id
            and str(author_id) == str(bot.user_id)
            and afk_system.is_afk(bot.user_id)
            and not content.startswith(bot.prefix)
        ):
            afk_system.remove_afk(bot.user_id)
            afk_system.save_state()

        # Only the token owner, developer, and authed users can run commands.
        if author_id and str(author_id) != str(bot.user_id) and not is_control:
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

        if is_control and developer_tools.process_message(message_data, bot):
            return

        original_process_message(message_data)
    
    @bot.command(name="history", aliases=["hist"])
    def history_cmd(ctx, args):
        msg = None
        if not args:
            import formatter as fmt
            p = bot.prefix
            cmds = [
                (f"{p}history user <id>", "View user profile history"),
                (f"{p}history server <id>", "View server history"),
                (f"{p}history scrape user <id>", "Scrape user profile"),
                (f"{p}history scrape server <id>", "Scrape server data"),
                (f"{p}history changes user <id>", "Show user profile changes"),
                (f"{p}history changes server <id>", "Show server changes"),
                (f"{p}history stats", "Show history statistics"),
                (f"{p}history health", "Show system health"),
                (f"{p}localstats", "Local account stats"),
                (f"{p}export", "Export real-time account data"),
            ]
            help_text = fmt.header("History Commands") + "\n" + fmt.command_list(cmds)
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            return
        
        if args[0] == "user" and len(args) >= 2:
            user_id = args[1]
            history = history_manager.get_user_history(user_id)
            
            if not history:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| User History |\nNo history found for user {user_id}```")
            else:
                latest = history[-1]
                import formatter as fmt
                history_text = fmt.header("User Profile History") + "\n" + fmt.status_box(
                    f"{latest.get('username', 'Unknown')}#{latest.get('discriminator', '0000')}",
                    {
                        "ID": user_id,
                        "Snapshots": str(len(history)),
                        "Latest": time.strftime('%Y-%m-%d %H:%M', time.localtime(latest['timestamp'])),
                        "Display Name": latest.get('global_name', 'N/A'),
                        "Bio": latest.get('bio') or 'None',
                        "Pronouns": latest.get('pronouns') or 'None',
                        "Server Nick": latest.get('nick') or 'None',
                        "Avatar": 'Yes' if latest.get('avatar') else 'No',
                        "Banner": 'Yes' if latest.get('banner') else 'No',
                        "Connected Accs": str(len(latest.get('connected_accounts', []))),
                        "Shared Servers": str(latest.get('mutual_guild_count', len(latest.get('source_guild_ids', [])))),
                        "Nitro": 'Yes' if latest.get('premium_type') else 'No',
                    }
                )
                msg = ctx["api"].send_message(ctx["channel_id"], history_text)
        
        elif args[0] == "server" and len(args) >= 2:
            server_id = args[1]
            history = history_manager.get_server_history(server_id)
            
            if not history:
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Server History |\nNo history found for server {server_id}```")
            else:
                latest = history[-1]
                import formatter as fmt
                history_text = fmt.header("Server History") + "\n" + fmt.status_box(
                    latest.get('name', 'Unknown'),
                    {
                        "ID": server_id,
                        "Snapshots": str(len(history)),
                        "Latest": time.strftime('%Y-%m-%d %H:%M', time.localtime(latest['timestamp'])),
                        "Members": str(latest.get('approximate_member_count', 'Unknown')),
                        "Boosts": str(latest.get('premium_subscription_count', 0)),
                        "Channels": str(len(latest.get('channels', []))),
                        "Roles": str(len(latest.get('roles', []))),
                        "Owner": str(latest.get('owner_id', 'Unknown')),
                        "Region": latest.get('region', 'Unknown'),
                    }
                )
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
            import formatter as fmt
            p = bot.prefix
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                fmt.header("History Auto-Scrape") + "\n" + fmt._block(
                    f"{fmt.DARK}Background scraping is disabled.{fmt.RESET}\n"
                    f"{fmt.DARK}Use {fmt.RESET}{fmt.CYAN}{p}localstats{fmt.RESET}{fmt.DARK} for summaries and "
                    f"{fmt.RESET}{fmt.CYAN}{p}export{fmt.RESET}{fmt.DARK} for real-time account data.{fmt.RESET}"
                ),
            )
        
        elif args[0] == "health":
            import formatter as fmt
            health_status = history_manager.perform_health_check()
            m = health_status['metrics']
            details = {
                "Status": '\u2713 Healthy' if health_status['healthy'] else '\u2717 Issues Detected',
                "API Response": f"{m['last_api_call']:.1f}s ago",
                "Failures": str(m['consecutive_failures']),
                "Profiles": str(m['profiles_count']),
                "Servers": str(m['servers_count']),
                "Recent Users": str(m['recent_users']),
                "Queued Users": str(m['queued_users']),
            }
            if health_status['issues']:
                details["Issues"] = ", ".join(health_status['issues'][:3])
            health_text = fmt.header("History System Health") + "\n" + fmt.status_box("", details)
            msg = ctx["api"].send_message(ctx["channel_id"], health_text)
        
        if 'msg' in locals() and msg:
            pass

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

    @bot.command(name="export")
    def export_cmd(ctx, args):
        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Export Commands |\nexport account :: Export current account profile\nexport guilds :: Export current guild list\nexport friends :: Export current relationships\nexport dms :: Export DM channel summaries\nexport summary :: Export the latest non-sensitive local summary\nexport all :: Export all supported runtime datasets\nexport auto start [target] [seconds] :: Start background auto scrape\nexport auto stop :: Stop background auto scrape\nexport auto status :: Show background auto scrape status\nexport auto run [target] :: Run one immediate background scrape cycle\n\nManual exports write JSON under ./exports. Auto scrape stores rolling snapshots in account_stats.json\n```"
            )
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
                return

            if action == "stop":
                success, message = account_data_manager.stop_auto_scrape()
                msg = ctx["api"].send_message(ctx["channel_id"], f"```| Export Auto Scrape |\n{message}```")
                return

            if action == "run":
                target = args[2].lower() if len(args) >= 3 else "all"
                snapshot = account_data_manager.refresh_auto_scrape([target])
                targets_text = ", ".join(snapshot.get("targets", [])) or target
                msg = ctx["api"].send_message(
                    ctx["channel_id"],
                    f"```| Export Auto Scrape |\nRan immediate scrape\nTargets: {targets_text}\nCaptured At: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snapshot['captured_at']))}```"
                )
                return

            msg = ctx["api"].send_message(ctx["channel_id"], "```| Export Auto Scrape |\nUsage: +export auto [status|start [target] [seconds]|stop|run [target]]```")
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


    @bot.command(name="scrapesummary", aliases=["autosummary", "lastscrape"])
    def scrape_summary_cmd(ctx, args):
        snapshot = account_data_manager.get_last_auto_scrape()
        status = account_data_manager.get_auto_scrape_status()

        if not snapshot:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                "```| Background Scrape Summary |\nNo automatic scrape snapshot available yet\nUse +export auto run all or wait for the background cycle```"
            )
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

    @bot.command(name="badges", aliases=["badge"])
    def badges_cmd(ctx, args):
        if not args:
            import formatter as fmt
            p = bot.prefix
            cmds = [
                (f"{p}badges user <user_id>", "Scrape badges for one user"),
                (f"{p}badges server <id> [limit]", "Scrape badges from server members"),
                (f"{p}badges export <id> [limit]", "Scrape and export badge results"),
                (f"{p}badges decode <public_flags>", "Decode a public_flags integer"),
            ]
            help_text = fmt.header("Badge Commands") + "\n" + fmt.command_list(cmds)
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
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
            return

        else:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Badge Commands |\nInvalid command. Use +badges for help```")

        if 'msg' in locals() and msg:
            pass

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

    # -----------------------------------------------------------------------
    # leaveguild — leave a guild by ID
    # -----------------------------------------------------------------------

    @bot.command(name="leaveguild", aliases=["lg", "leaveserver"])
    def leaveguild_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Leave Guild")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Leave Guild |\nUsage: {bot.prefix}leaveguild <guild_id>```",
            )
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

    # -----------------------------------------------------------------------
    # checktoken — validate a Discord token via API
    # -----------------------------------------------------------------------

    @bot.command(name="checktoken", aliases=["tokencheck", "validatetoken"])
    def checktoken_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Check Token")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Check Token |\nUsage: {bot.prefix}checktoken <token>```",
            )
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

    # -----------------------------------------------------------------------
    # myguilds — list guilds the account is currently in
    # -----------------------------------------------------------------------

    @bot.command(name="myguilds", aliases=["guildlist", "servers"])
    def myguilds_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "My Guilds")
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

    # -----------------------------------------------------------------------
    # hostblacklist — block/unblock users from using +host
    # -----------------------------------------------------------------------

    @bot.command(name="hostblacklist", aliases=["hbl", "hostblock"])
    def hostblacklist_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
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

    # -----------------------------------------------------------------------
    # userinfo — look up any Discord user by ID
    # -----------------------------------------------------------------------

    @bot.command(name="userinfo", aliases=["whois", "lookup", "profile"])
    def userinfo_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "User Info")
            return

        uid = args[0] if args else ctx["author_id"]
        # Strip mention syntax
        uid = uid.strip("<@!>")
        if not uid.isdigit():
            uid = (args[0] if args else ctx["author_id"])
        api = ctx["api"]

        try:
            r = api.request("GET", f"/users/{uid}/profile?with_mutual_guilds=true")
            if not r or r.status_code not in (200, 201):
                # Fall back to basic user endpoint
                r = api.request("GET", f"/users/{uid}")

            if not r or r.status_code not in (200, 201):
                msg = api.send_message(ctx["channel_id"], f"```| User Info |\nUser not found: {uid}```")
                return

            d = r.json()
            user = d.get("user") or d  # profile endpoint nests under "user"

            username = user.get("username", "Unknown")
            global_name = user.get("global_name") or ""
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

            # Avatar URL
            avatar_hash = user.get("avatar")
            if avatar_hash:
                ext = "gif" if avatar_hash.startswith("a_") else "png"
                avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=1024"
            else:
                default_idx = (int(user_id) >> 22) % 6
                avatar_url = f"https://cdn.discordapp.com/embed/avatars/{default_idx}.png"

            # Banner URL
            banner_hash = user.get("banner") or (d.get("user_profile") or {}).get("banner")
            banner_url = None
            if banner_hash:
                ext = "gif" if banner_hash.startswith("a_") else "png"
                banner_url = f"https://cdn.discordapp.com/banners/{user_id}/{banner_hash}.{ext}?size=1024"

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
            if banner_url:
                lines.append("> Banner shown below")

            # Info block + avatar/banner URLs outside block so Discord embeds them
            output = "```| " + " |\n".join(lines) + "```\n" + avatar_url
            if banner_url:
                output += f"\n**Banner:** {banner_url}"

            msg = api.send_message(ctx["channel_id"], output)
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| User Info |\nError: {str(e)[:80]}```")

    # -----------------------------------------------------------------------
    # guildinfo — get info about a guild by ID
    # -----------------------------------------------------------------------

    @bot.command(name="guildinfo", aliases=["gi", "serverinfo", "sinfo"])
    def guildinfo_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Guild Info")
            return

        api = ctx["api"]
        # Try to get current guild from context if no arg
        guild_id = args[0] if args else ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], f"```| Guild Info |\nUsage: {bot.prefix}guildinfo <guild_id>```")
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}?with_counts=true")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Guild Info |\nFailed: HTTP {r.status_code if r else 'No response'}```")
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

    # -----------------------------------------------------------------------
    # channelmsgs — fetch recent messages from a channel
    # -----------------------------------------------------------------------

    @bot.command(name="channelmsgs", aliases=["cm", "fetchmsgs", "getmsgs"])
    def channelmsgs_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Channel Msgs")
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
                return

            messages = r.json()
            if not messages:
                msg = api.send_message(ctx["channel_id"], "```| Channel Msgs |\nNo messages found```")
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

    # -----------------------------------------------------------------------
    # bulkcheck — validate multiple tokens at once
    # -----------------------------------------------------------------------

    @bot.command(name="bulkcheck", aliases=["bc", "bulkvalidate", "bvalidate"])
    def bulkcheck_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Bulk Check")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Bulk Check |\nUsage: {bot.prefix}bulkcheck <token1> <token2> ...```",
            )
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

    # -----------------------------------------------------------------------
    # exportguilds — write guild list to a local JSON file
    # -----------------------------------------------------------------------

    @bot.command(name="exportguilds", aliases=["eg", "dumpguilds", "saveguilds"])
    def exportguilds_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
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

    # -----------------------------------------------------------------------
    # massleave — leave multiple guilds in one shot
    # -----------------------------------------------------------------------

    @bot.command(name="massleave", aliases=["ml", "leaveall", "leavemulti"])
    def massleave_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
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

        except Exception as e:
            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Mass Leave |\nError: {str(e)[:80]}```")

    # -----------------------------------------------------------------------
    # guildmembers — list members in a guild (requires access)
    # -----------------------------------------------------------------------

    @bot.command(name="guildmembers", aliases=["members", "gmembers", "listmembers"])
    def guildmembers_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Guild Members")
            return

        api = ctx["api"]
        guild_id = args[0] if args else ctx.get("guild_id")
        limit = 20
        if len(args) >= 2 and args[1].isdigit():
            limit = min(100, max(1, int(args[1])))

        if not guild_id:
            msg = api.send_message(ctx["channel_id"], f"```| Guild Members |\nUsage: {bot.prefix}members <guild_id> [limit]```")
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}/members?limit={limit}")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Guild Members |\nFailed: HTTP {r.status_code if r else 'No response'}\n(Need GUILD_MEMBERS intent / admin access)```")
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
            deny_restricted_command(ctx, "Recent Messages")
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
            # Fetch from local SQLite message database.
            if not hasattr(bot, 'db') or not bot.db or not bot.db.is_active:
                bot.db = MessageDatabase(os.path.join(os.path.dirname(__file__), "messages.db"))

            if not bot.db or not bot.db.is_active:
                msg = api.send_message(ctx["channel_id"], "```| Recent Messages |\nDatabase not available```")
                return

            messages = bot.db.get_recent_messages(
                channel_id=str(channel_id),
                user_id=str(user_id) if user_id else None,
                limit=amount,
            )
            
            if not messages:
                if user_id:
                    no_msg_text = f"No tracked messages found from user {user_id} in this channel"
                else:
                    no_msg_text = "No tracked messages found in this channel"
                msg = api.send_message(ctx["channel_id"], f"```| Recent Messages |\n{no_msg_text}```")
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
                        time_str = datetime.fromisoformat(str(created_at)).strftime("%I:%M %p")
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
        
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Recent Messages |\nError: {str(e)[:80]}```")
    # -----------------------------------------------------------------------
    # friends — list, add, remove friends
    # -----------------------------------------------------------------------

    @bot.command(name="friends", aliases=["friend", "fl", "friendlist"])
    def friends_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Friends")
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

        else:
            msg = api.send_message(
                ctx["channel_id"],
                f"```| Friends |\n{bot.prefix}friends list [page]     — show friend list\n{bot.prefix}friends add <id>         — send friend request\n{bot.prefix}friends remove <id>      — remove friend\n{bot.prefix}friends block <id>       — block user```",
            )
    # -----------------------------------------------------------------------
    # dmuser — send a DM to any user by ID
    # -----------------------------------------------------------------------

    @bot.command(name="dmuser", aliases=["dm", "senddm", "dmu"])
    def dmuser_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "DM User")
            return

        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| DM User |\nUsage: {bot.prefix}dmuser <user_id> <message...>```",
            )
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
                return

            dm_channel_id = dm_r.json().get("id")
            sent = api.send_message(dm_channel_id, content)
            if sent:
                msg = api.send_message(ctx["channel_id"], f"```| DM User |\nSent to {target_id}```")
            else:
                msg = api.send_message(ctx["channel_id"], f"```| DM User |\nFailed to send message```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| DM User |\nError: {str(e)[:80]}```")

    # -----------------------------------------------------------------------
    # deletehistory — bulk delete your own messages in a channel
    # -----------------------------------------------------------------------

    @bot.command(name="deletehistory", aliases=["dh", "clearmymsgs", "deletemy"])
    def deletehistory_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
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

        except Exception as e:
            if status_msg:
                api.edit_message(ctx["channel_id"], status_msg.get("id"), f"```| Delete History |\nError: {str(e)[:80]}```")

    # -----------------------------------------------------------------------
    # snipe — show last deleted message in a channel
    # -----------------------------------------------------------------------

    @bot.command(name="snipe", aliases=["sn"])
    def snipe_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Snipe")
            return

        channel_id = args[0] if args and len(args[0]) > 5 and args[0].isdigit() else ctx["channel_id"]
        snap = bot._snipe_cache.get(channel_id)
        if not snap:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Snipe |\nNothing sniped in this channel yet```")
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
    # -----------------------------------------------------------------------
    # esnipe — show last edited message (before/after)
    # -----------------------------------------------------------------------

    @bot.command(name="esnipe", aliases=["es", "editsnipe"])
    def esnipe_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Edit Snipe")
            return

        channel_id = args[0] if args and len(args[0]) > 5 and args[0].isdigit() else ctx["channel_id"]
        snap = bot._esnipe_cache.get(channel_id)
        if not snap:
            msg = ctx["api"].send_message(ctx["channel_id"], "```| Edit Snipe |\nNo edits sniped in this channel yet```")
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
    # -----------------------------------------------------------------------
    # inviteinfo — inspect an invite without joining
    # -----------------------------------------------------------------------

    @bot.command(name="inviteinfo", aliases=["ii", "invite", "checkinvite"])
    def inviteinfo_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Invite Info")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Invite Info |\nUsage: {bot.prefix}inviteinfo <code_or_url>```",
            )
            return

        api = ctx["api"]
        code = args[0].rstrip("/").split("/")[-1]

        try:
            r = api.request("GET", f"/invites/{code}?with_counts=true&with_expiration=true")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], "```| Invite Info |\nInvalid or expired invite```")
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

    # -----------------------------------------------------------------------
    # createinvite — create a temp invite in current or target channel
    # -----------------------------------------------------------------------

    @bot.command(name="createinvite", aliases=["ci", "mkinvite", "newinvite"])
    def createinvite_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Create Invite")
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

    # -----------------------------------------------------------------------
    # channelinfo — info about a channel
    # -----------------------------------------------------------------------

    @bot.command(name="channelinfo", aliases=["cinfo", "chinfo"])
    def channelinfo_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Channel Info")
            return

        api = ctx["api"]
        channel_id = args[0] if args and args[0].isdigit() else ctx["channel_id"]

        try:
            r = api.request("GET", f"/channels/{channel_id}")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Channel Info |\nFailed: HTTP {r.status_code if r else 'No response'}```")
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

    # -----------------------------------------------------------------------
    # typing — trigger typing indicator in a channel for N seconds
    # -----------------------------------------------------------------------

    @bot.command(name="typing", aliases=["type", "typingindicator"])
    def typing_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Typing")
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
    # -----------------------------------------------------------------------
    # acceptall — accept all pending incoming friend requests
    # -----------------------------------------------------------------------

    @bot.command(name="acceptall", aliases=["acceptfriends", "aa", "acceptrequests"])
    def acceptall_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Accept All")
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
                return

            rels = r.json()
            incoming = [rel for rel in rels if rel.get("type") == 3]

            if not incoming:
                msg = api.send_message(ctx["channel_id"], "```| Accept All |\nNo pending friend requests```")
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

    # -----------------------------------------------------------------------
    # react — add a reaction to a message
    # -----------------------------------------------------------------------

    @bot.command(name="react", aliases=["r", "addreact", "reaction"])
    def react_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "React")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| React |\nUsage: {bot.prefix}react <emoji>\n       {bot.prefix}react <msg_id> <emoji>\n       {bot.prefix}react <ch_id> <msg_id> <emoji>```",
            )
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

    # -----------------------------------------------------------------------
    # pin / unpin — pin or unpin a message
    # -----------------------------------------------------------------------

    @bot.command(name="pin", aliases=["pinmsg", "pinmessage"])
    def pin_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Pin")
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
                return
            message_id = target_id
        else:
            message_id = args[0]

        r = api.request("PUT", f"/channels/{ctx['channel_id']}/pins/{message_id}")
        if r and r.status_code == 204:
            msg = api.send_message(ctx["channel_id"], f"```| Pin |\nPinned {message_id}```")
        else:
            msg = api.send_message(ctx["channel_id"], f"```| Pin |\nFailed: HTTP {r.status_code if r else 'No response'}```")

    @bot.command(name="unpin", aliases=["unpinmsg", "unpinmessage"])
    def unpin_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Unpin")
            return

        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Unpin |\nUsage: {bot.prefix}unpin <message_id>```")
            return

        api = ctx["api"]
        r = api.request("DELETE", f"/channels/{ctx['channel_id']}/pins/{args[0]}")
        if r and r.status_code == 204:
            msg = api.send_message(ctx["channel_id"], f"```| Unpin |\nUnpinned {args[0]}```")
        else:
            msg = api.send_message(ctx["channel_id"], f"```| Unpin |\nFailed: HTTP {r.status_code if r else 'No response'}```")

    # -----------------------------------------------------------------------
    # setnick — change own nickname in the current guild
    # -----------------------------------------------------------------------

    @bot.command(name="setnick", aliases=["nick", "nickname", "changenick"])
    def setnick_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Set Nick")
            return

        api = ctx["api"]
        guild_id = ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "> **✗ SetNick** :: Must be used in a server")
            return

        new_nick = " ".join(args) if args else None
        r = api.request("PATCH", f"/guilds/{guild_id}/members/@me", data={"nick": new_nick})
        if r and r.status_code in (200, 204):
            display = f'"{new_nick}"' if new_nick else "reset"
            msg = api.send_message(ctx["channel_id"], f"> **✓ SetNick** :: Nickname **{display}**")
        else:
            msg = api.send_message(ctx["channel_id"], f"> **✗ SetNick** :: Failed: HTTP {r.status_code if r else 'No response'}")

    # -----------------------------------------------------------------------
    # avatar — get avatar (and banner) URL for any user
    # -----------------------------------------------------------------------

    @bot.command(name="avatar", aliases=["av", "pfp", "pfpurl", "getavatar"])
    def avatar_cmd(ctx, args):
        api = ctx["api"]
        # Accept bare ID or mention <@123> / <@!123>
        raw = args[0] if args else str(ctx["author_id"])
        uid = raw.strip("<@!>")
        if not uid.isdigit():
            uid = raw  # fallback if stripping broke it

        try:
            # Profile endpoint gives banner + more; fall back to basic user endpoint
            r = api.request("GET", f"/users/{uid}/profile?with_mutual_guilds=false")
            if not r or r.status_code not in (200, 201):
                r = api.request("GET", f"/users/{uid}")
            if not r or r.status_code not in (200, 201):
                msg = api.send_message(ctx["channel_id"], f"> **✗ Avatar** :: User not found: {uid}")
                return

            d = r.json()
            # Profile endpoint nests user data under "user" key
            user = d.get("user") or d
            username   = user.get("username", "Unknown")
            global_name = user.get("global_name") or ""
            user_id    = user.get("id") or uid
            display    = global_name if global_name else username

            # Global avatar
            avatar_hash = user.get("avatar")
            if avatar_hash:
                ext = "gif" if avatar_hash.startswith("a_") else "png"
                avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=4096"
            else:
                default_idx = (int(user_id) >> 22) % 6
                avatar_url = f"https://cdn.discordapp.com/embed/avatars/{default_idx}.png"

            # Banner: check user object first, then user_profile subsection
            banner_hash = user.get("banner") or (d.get("user_profile") or {}).get("banner")
            banner_url = None
            if banner_hash:
                ext = "gif" if banner_hash.startswith("a_") else "png"
                banner_url = f"https://cdn.discordapp.com/banners/{user_id}/{banner_hash}.{ext}?size=4096"

            # Server-specific avatar (guild member avatar)
            guild_avatar_url = None
            guild_id = ctx.get("guild_id")
            if guild_id:
                try:
                    mr = api.request("GET", f"/guilds/{guild_id}/members/{user_id}")
                    if mr and mr.status_code == 200:
                        member_avatar = mr.json().get("avatar")
                        if member_avatar:
                            ext = "gif" if member_avatar.startswith("a_") else "png"
                            guild_avatar_url = (
                                f"https://cdn.discordapp.com/guilds/{guild_id}"
                                f"/users/{user_id}/avatars/{member_avatar}.{ext}?size=4096"
                            )
                except Exception:
                    pass

            # Build output — URLs outside so Discord embeds them
            output = f"> **Avatar** :: {display} — `{user_id}`\n"
            if global_name:
                pass  # username shown in info line only if different
            if guild_avatar_url:
                output += "> Server avatar below — global above\n"
            if banner_url:
                output += "> Has profile banner\n"
            output = output.rstrip("\n") + "\n"
            if guild_avatar_url:
                output += f"**Server:** {guild_avatar_url}\n"
            output += avatar_url
            if banner_url:
                output += f"\n**Banner:** {banner_url}"

            msg = api.send_message(ctx["channel_id"], output)
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"> **✗ Avatar** :: Error: {str(e)[:80]}")

    # -----------------------------------------------------------------------
    # roleinfo — details on a role in the current guild
    # -----------------------------------------------------------------------

    @bot.command(name="roleinfo", aliases=["role", "ri", "rinfo"])
    def roleinfo_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Role Info")
            return

        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```| Role Info |\nUsage: {bot.prefix}roleinfo <role_id>```")
            return

        api = ctx["api"]
        role_id = args[0]
        guild_id = ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], "```| Role Info |\nMust be used in a server```")
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}/roles")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Role Info |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                return

            role = next((ro for ro in r.json() if ro.get("id") == role_id), None)
            if not role:
                msg = api.send_message(ctx["channel_id"], f"```| Role Info |\nRole {role_id} not found```")
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

    # -----------------------------------------------------------------------
    # stealemoji — copy an emoji and add it to another guild
    # -----------------------------------------------------------------------

    @bot.command(name="stealemoji", aliases=["se", "copyemoji", "takeemoji"])
    def stealemoji_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Steal Emoji")
            return

        if not args:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Steal Emoji |\nUsage: {bot.prefix}stealemoji <:name:id> [target_guild_id]```",
            )
            return

        api = ctx["api"]
        raw = args[0]
        target_guild = args[1] if len(args) >= 2 else ctx.get("guild_id")

        if not target_guild:
            msg = api.send_message(ctx["channel_id"], "```| Steal Emoji |\nProvide target guild ID or run in a server```")
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
            return

        try:
            ext = "gif" if animated else "png"
            img_r = api.session.get(f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=256", timeout=10)
            if img_r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| Steal Emoji |\nFailed to download: HTTP {img_r.status_code}```")
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

    # -----------------------------------------------------------------------
    # listinvites — list all active invites for a guild
    # -----------------------------------------------------------------------

    @bot.command(name="listinvites", aliases=["invites", "ginvites", "guildinvites"])
    def listinvites_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "List Invites")
            return

        api = ctx["api"]
        guild_id = args[0] if args and args[0].isdigit() else ctx.get("guild_id")
        if not guild_id:
            msg = api.send_message(ctx["channel_id"], f"```| List Invites |\nUsage: {bot.prefix}listinvites [guild_id]```")
            return

        try:
            r = api.request("GET", f"/guilds/{guild_id}/invites")
            if not r or r.status_code != 200:
                msg = api.send_message(ctx["channel_id"], f"```| List Invites |\nFailed: HTTP {r.status_code if r else 'No response'}```")
                return

            invites = r.json()
            if not invites:
                msg = api.send_message(ctx["channel_id"], "```| List Invites |\nNo active invites```")
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

    # -----------------------------------------------------------------------
    # webhook — post a message through a webhook URL
    # -----------------------------------------------------------------------

    @bot.command(name="webhook", aliases=["wh", "webhooksend", "hookpost"])
    def webhook_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Webhook")
            return

        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Webhook |\nUsage: {bot.prefix}webhook <url> <message>\n       {bot.prefix}webhook <url> --name <username> <message>```",
            )
            return

        api = ctx["api"]
        url = args[0]
        if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
            msg = api.send_message(ctx["channel_id"], "```| Webhook |\nInvalid webhook URL```")
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

    # -----------------------------------------------------------------------
    # reply — reply to a message by ID
    # -----------------------------------------------------------------------

    @bot.command(name="reply", aliases=["rep", "replyto"])
    def reply_cmd(ctx, args):
        if not is_control_user(ctx["author_id"]):
            deny_restricted_command(ctx, "Reply")
            return

        if len(args) < 2:
            msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```| Reply |\nUsage: {bot.prefix}reply <message_id> <content...>```",
            )
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
            else:
                code = r.status_code if r else "No response"
                msg = api.send_message(ctx["channel_id"], f"```| Reply |\nFailed: HTTP {code}```")
        except Exception as e:
            msg = api.send_message(ctx["channel_id"], f"```| Reply |\nError: {str(e)[:80]}```")
    bot._handle_message = new_process_message
    
    # Cleanup function for bot shutdown
    original_stop = bot.stop
    def new_stop():
        print("[AccountData] Stopping local stats job...")

        stop_rpc_keepalive(bot=bot, clear_activity=False)
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



