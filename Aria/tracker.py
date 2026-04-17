"""tracker.py — User identity + deleted-message persistence layer.

Works with or without MongoDB:
  • MongoDB enabled  → data stored in dedicated collections (users / deleted_messages)
  • MongoDB disabled → JSON flat-files in the bot directory (fallback)

Hooks called by bot.py on every MESSAGE_CREATE and MESSAGE_DELETE event.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def user_schema(user_data: dict) -> dict:
    now = _now()
    return {
        "_id": str(user_data["_id"]),
        "name": user_data.get("name"),
        "current_username": user_data.get("current_username"),
        "current_displayname": user_data.get("current_displayname"),
        "current_avatar_url": user_data.get("current_avatar_url"),
        "current_banner_url": user_data.get("current_banner_url"),
        "first_seen": user_data.get("first_seen", now),
        "last_seen": user_data.get("last_seen", now),
        "username_history": user_data.get("username_history", []),
        "displayname_history": user_data.get("displayname_history", []),
        "avatar_history": user_data.get("avatar_history", []),
        "banner_history": user_data.get("banner_history", []),
    }


def deleted_message_schema(message_data: dict) -> dict:
    now = _now()
    return {
        "_id": str(message_data["message_id"]),
        "user_id": str(message_data["user_id"]),
        "channel_id": str(message_data["channel_id"]),
        "guild_id": str(message_data["guild_id"]) if message_data.get("guild_id") else None,
        "content": message_data.get("content", ""),
        "attachments": message_data.get("attachments", []),
        "deleted_at": message_data.get("deleted_at", now),
        "channel_name": message_data.get("channel_name", "Unknown"),
        "guild_name": message_data.get("guild_name"),
        "author_name": message_data.get("author_name", "Unknown"),
    }


def history_entry(value: str) -> dict:
    return {"value": value, "changed_at": _now()}


# ---------------------------------------------------------------------------
# JSON flat-file fallback store
# ---------------------------------------------------------------------------

_DIR = os.path.dirname(os.path.abspath(__file__))
_USERS_FILE = os.path.join(_DIR, "tracker_users.json")
_DELETED_FILE = os.path.join(_DIR, "tracker_deleted.json")
_MAX_DELETED_FLAT = 500  # cap for flat-file storage


def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TrackerStore
# ---------------------------------------------------------------------------

class TrackerStore:
    """Unified tracker that writes to MongoDB when available, JSON otherwise."""

    def __init__(self):
        self._lock = threading.Lock()
        self._mongo_users = None       # pymongo Collection
        self._mongo_deleted = None     # pymongo Collection
        self._flat_users: Dict[str, dict] = {}
        self._flat_deleted: Dict[str, dict] = {}
        self._mongo_ok = False
        self._dirty_users = False
        self._dirty_deleted = False
        self._flush_thread: Optional[threading.Thread] = None
        self._running = True
        self._init()

    # ── Init ──────────────────────────────────────────────────────────────

    def _init(self):
        # Try MongoDB first
        try:
            from mongo_store import _read_config_file, _as_bool
            import pymongo
            cfg = _read_config_file()
            enabled = _as_bool(os.getenv("ARIA_MONGO_ENABLED", cfg.get("mongo_enabled", False)))
            if enabled:
                uri = os.getenv("ARIA_MONGO_URI", cfg.get("mongo_uri", "mongodb://127.0.0.1:27017"))
                db_name = os.getenv("ARIA_MONGO_DATABASE", cfg.get("mongo_database", "aria"))
                timeout = int(cfg.get("mongo_timeout_ms", 1500))
                client = pymongo.MongoClient(
                    uri,
                    serverSelectionTimeoutMS=timeout,
                    connectTimeoutMS=timeout,
                )
                client.admin.command("ping")
                db = client[db_name]
                self._mongo_users = db["tracked_users"]
                self._mongo_deleted = db["deleted_messages"]
                # Indexes
                self._mongo_users.create_index("last_seen")
                self._mongo_deleted.create_index("deleted_at")
                self._mongo_deleted.create_index("user_id")
                self._mongo_deleted.create_index("channel_id")
                self._mongo_ok = True
                print("[TRACKER] MongoDB backend active")
                return
        except Exception:
            pass

        # Fallback: JSON flat-files
        self._flat_users = _load_json(_USERS_FILE)
        self._flat_deleted = _load_json(_DELETED_FILE)
        self._start_flush_thread()
        print("[TRACKER] JSON flat-file backend active")

    def _start_flush_thread(self):
        def _loop():
            while self._running:
                time.sleep(30)
                self._flush_flat()
        self._flush_thread = threading.Thread(target=_loop, daemon=True, name="tracker-flush")
        self._flush_thread.start()

    def _flush_flat(self):
        with self._lock:
            if self._dirty_users:
                _save_json(_USERS_FILE, self._flat_users)
                self._dirty_users = False
            if self._dirty_deleted:
                _save_json(_DELETED_FILE, self._flat_deleted)
                self._dirty_deleted = False

    # ── User tracking ─────────────────────────────────────────────────────

    def upsert_user(self, user_id: str, username: str, displayname: str,
                    avatar_url: Optional[str], banner_url: Optional[str]) -> None:
        """Upsert a user record, appending history entries on changes."""
        uid = str(user_id)
        now = _now()

        if self._mongo_ok:
            try:
                existing = self._mongo_users.find_one({"_id": uid})
                if not existing:
                    doc = user_schema({
                        "_id": uid,
                        "name": username,
                        "current_username": username,
                        "current_displayname": displayname,
                        "current_avatar_url": avatar_url,
                        "current_banner_url": banner_url,
                        "first_seen": now,
                        "last_seen": now,
                    })
                    self._mongo_users.insert_one(doc)
                    return

                push = {}
                set_fields = {"last_seen": now}

                if existing.get("current_username") != username:
                    set_fields["current_username"] = username
                    push.setdefault("username_history", []).append(history_entry(username))

                if existing.get("current_displayname") != displayname:
                    set_fields["current_displayname"] = displayname
                    push.setdefault("displayname_history", []).append(history_entry(displayname))

                if avatar_url and existing.get("current_avatar_url") != avatar_url:
                    set_fields["current_avatar_url"] = avatar_url
                    push.setdefault("avatar_history", []).append(history_entry(avatar_url))

                if banner_url and existing.get("current_banner_url") != banner_url:
                    set_fields["current_banner_url"] = banner_url
                    push.setdefault("banner_history", []).append(history_entry(banner_url))

                update: dict = {"$set": set_fields}
                if push:
                    update["$push"] = {k: {"$each": v} for k, v in push.items()}
                self._mongo_users.update_one({"_id": uid}, update)
            except Exception as e:
                print(f"[TRACKER] mongo upsert_user error: {e}")
            return

        # Flat-file path
        with self._lock:
            existing = self._flat_users.get(uid)
            if not existing:
                self._flat_users[uid] = user_schema({
                    "_id": uid,
                    "name": username,
                    "current_username": username,
                    "current_displayname": displayname,
                    "current_avatar_url": avatar_url,
                    "current_banner_url": banner_url,
                    "first_seen": now.isoformat(),
                    "last_seen": now.isoformat(),
                })
                self._dirty_users = True
                return

            changed = False
            if existing.get("current_username") != username:
                existing["username_history"].append({"value": username, "changed_at": now.isoformat()})
                existing["current_username"] = username
                changed = True
            if existing.get("current_displayname") != displayname:
                existing["displayname_history"].append({"value": displayname, "changed_at": now.isoformat()})
                existing["current_displayname"] = displayname
                changed = True
            if avatar_url and existing.get("current_avatar_url") != avatar_url:
                existing["avatar_history"].append({"value": avatar_url, "changed_at": now.isoformat()})
                existing["current_avatar_url"] = avatar_url
                changed = True
            if banner_url and existing.get("current_banner_url") != banner_url:
                existing["banner_history"].append({"value": banner_url, "changed_at": now.isoformat()})
                existing["current_banner_url"] = banner_url
                changed = True
            existing["last_seen"] = now.isoformat()
            if changed:
                self._dirty_users = True

    def get_user(self, user_id: str) -> Optional[dict]:
        uid = str(user_id)
        if self._mongo_ok:
            try:
                return self._mongo_users.find_one({"_id": uid})
            except Exception:
                return None
        with self._lock:
            return self._flat_users.get(uid)

    def get_all_users(self, limit: int = 50) -> List[dict]:
        if self._mongo_ok:
            try:
                return list(self._mongo_users.find().sort("last_seen", -1).limit(limit))
            except Exception:
                return []
        with self._lock:
            users = list(self._flat_users.values())
            users.sort(key=lambda u: u.get("last_seen", ""), reverse=True)
            return users[:limit]

    # ── Deleted message tracking ──────────────────────────────────────────

    def store_deleted(self, message_id: str, user_id: str, channel_id: str,
                      content: str, attachments: List[dict],
                      guild_id: Optional[str] = None,
                      channel_name: str = "Unknown",
                      guild_name: Optional[str] = None,
                      author_name: str = "Unknown") -> None:
        doc = deleted_message_schema({
            "message_id": message_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "guild_id": guild_id,
            "content": content,
            "attachments": attachments,
            "deleted_at": _now(),
            "channel_name": channel_name,
            "guild_name": guild_name,
            "author_name": author_name,
        })

        if self._mongo_ok:
            try:
                self._mongo_deleted.replace_one({"_id": message_id}, doc, upsert=True)
            except Exception as e:
                print(f"[TRACKER] mongo store_deleted error: {e}")
            return

        with self._lock:
            self._flat_deleted[message_id] = {**doc, "deleted_at": doc["deleted_at"].isoformat()}
            # Cap at 500 entries — drop oldest
            if len(self._flat_deleted) > _MAX_DELETED_FLAT:
                oldest_key = next(iter(self._flat_deleted))
                del self._flat_deleted[oldest_key]
            self._dirty_deleted = True

    def get_deleted_in_channel(self, channel_id: str, limit: int = 10) -> List[dict]:
        cid = str(channel_id)
        if self._mongo_ok:
            try:
                return list(
                    self._mongo_deleted.find({"channel_id": cid})
                    .sort("deleted_at", -1)
                    .limit(limit)
                )
            except Exception:
                return []
        with self._lock:
            msgs = [m for m in self._flat_deleted.values() if m.get("channel_id") == cid]
            msgs.sort(key=lambda m: m.get("deleted_at", ""), reverse=True)
            return msgs[:limit]

    def get_deleted_by_user(self, user_id: str, limit: int = 20) -> List[dict]:
        uid = str(user_id)
        if self._mongo_ok:
            try:
                return list(
                    self._mongo_deleted.find({"user_id": uid})
                    .sort("deleted_at", -1)
                    .limit(limit)
                )
            except Exception:
                return []
        with self._lock:
            msgs = [m for m in self._flat_deleted.values() if m.get("user_id") == uid]
            msgs.sort(key=lambda m: m.get("deleted_at", ""), reverse=True)
            return msgs[:limit]

    def stop(self):
        self._running = False
        self._flush_flat()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_TRACKER: Optional[TrackerStore] = None
_TRACKER_LOCK = threading.Lock()


def get_tracker() -> TrackerStore:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = TrackerStore()
        return _TRACKER


# ---------------------------------------------------------------------------
# Helper: extract fields from a raw Discord MESSAGE_CREATE payload
# ---------------------------------------------------------------------------

def extract_user_from_message(msg: dict) -> Optional[dict]:
    author = msg.get("author")
    if not author or author.get("bot"):
        return None
    uid = author.get("id")
    if not uid:
        return None
    username = author.get("username", "")
    displayname = author.get("global_name") or author.get("display_name") or username
    avatar_hash = author.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.{'gif' if avatar_hash and avatar_hash.startswith('a_') else 'png'}?size=1024"
        if avatar_hash else None
    )
    banner_hash = author.get("banner")
    banner_url = (
        f"https://cdn.discordapp.com/banners/{uid}/{banner_hash}.{'gif' if banner_hash and banner_hash.startswith('a_') else 'png'}?size=1024"
        if banner_hash else None
    )
    return {
        "user_id": uid,
        "username": username,
        "displayname": displayname,
        "avatar_url": avatar_url,
        "banner_url": banner_url,
    }
