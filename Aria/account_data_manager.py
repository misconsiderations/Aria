import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from api_client import DiscordAPIClient


class AccountDataManager:
    def __init__(self, api_client: DiscordAPIClient):
        self.api = api_client
        self.stats_file = "account_stats.json"
        self.export_dir = "exports"
        self.stats_interval = 900
        self.stats_active = False
        self.stats_thread: Optional[threading.Thread] = None
        self.auto_scrape_interval = 900
        self.auto_scrape_targets = ["account", "guilds", "friends", "dms", "summary"]
        self.auto_scrape_active = False
        self.auto_scrape_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.data = self._load_stats()

    def _load_stats(self) -> Dict[str, Any]:
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, "r", encoding="utf-8") as file_handle:
                    data = json.load(file_handle)
                    if isinstance(data, dict):
                        return data
            except Exception as error:
                print(f"[AccountData] Failed to load stats file: {error}")

        return {
            "last_summary": None,
            "history": [],
            "last_export": None,
            "last_auto_scrape": None,
            "auto_scrape_history": [],
        }

    def _save_stats(self):
        with self._lock:
            temp_file = f"{self.stats_file}.{threading.get_ident()}.tmp"
            with open(temp_file, "w", encoding="utf-8") as file_handle:
                json.dump(self.data, file_handle, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.stats_file)

    def _permissions_to_int(self, permissions: Any) -> int:
        if isinstance(permissions, int):
            return permissions
        if isinstance(permissions, str) and permissions.isdigit():
            return int(permissions)
        return 0

    def _summarize_features(self, guilds: List[Dict[str, Any]]) -> Dict[str, int]:
        feature_counts: Dict[str, int] = {}
        for guild in guilds:
            features = guild.get("features", [])
            if not isinstance(features, list):
                continue
            for feature in features:
                if not isinstance(feature, str):
                    continue
                feature_counts[feature] = feature_counts.get(feature, 0) + 1

        ordered = sorted(feature_counts.items(), key=lambda item: (-item[1], item[0]))
        return {key: value for key, value in ordered[:10]}

    def build_local_summary(self, force: bool = True) -> Dict[str, Any]:
        user = self.api.get_user_info(force=force) or {}
        guilds = self.api.get_guilds(force=force)

        owner_count = 0
        admin_count = 0
        icon_count = 0
        banner_count = 0

        for guild in guilds:
            if guild.get("owner"):
                owner_count += 1
            permissions = self._permissions_to_int(guild.get("permissions"))
            if permissions & 0x8:
                admin_count += 1
            if guild.get("icon"):
                icon_count += 1
            if guild.get("banner"):
                banner_count += 1

        return {
            "captured_at": time.time(),
            "account": {
                "premium_type": user.get("premium_type", 0),
                "verified": bool(user.get("verified", False)),
                "locale": user.get("locale"),
                "has_avatar": bool(user.get("avatar")),
                "has_banner": bool(user.get("banner")),
            },
            "guilds": {
                "count": len(guilds),
                "owned_count": owner_count,
                "admin_count": admin_count,
                "icon_count": icon_count,
                "banner_count": banner_count,
                "feature_counts": self._summarize_features(guilds),
            },
        }

    def refresh_local_summary(self, force: bool = True) -> Dict[str, Any]:
        summary = self.build_local_summary(force=force)
        history = self.data.setdefault("history", [])
        history.append(summary)
        if len(history) > 96:
            self.data["history"] = history[-96:]
        self.data["last_summary"] = summary
        self._save_stats()
        return summary

    def get_latest_summary(self) -> Optional[Dict[str, Any]]:
        return self.data.get("last_summary")

    def start_stats_job(self, interval_seconds: int = 900) -> Tuple[bool, str]:
        if self.stats_thread and self.stats_active:
            return False, "Local stats job already running"

        self.stats_interval = max(60, int(interval_seconds))
        self.stats_active = True
        self.stats_thread = threading.Thread(target=self._stats_worker, daemon=True)
        self.stats_thread.start()
        return True, f"Local stats job started ({self.stats_interval}s interval)"

    def stop_stats_job(self) -> Tuple[bool, str]:
        if not self.stats_active:
            return False, "Local stats job is not running"

        self.stats_active = False
        if self.stats_thread:
            self.stats_thread.join(timeout=5)
        return True, "Local stats job stopped"

    def get_job_status(self) -> Dict[str, Any]:
        latest = self.get_latest_summary()
        return {
            "active": self.stats_active,
            "interval_seconds": self.stats_interval,
            "last_run": latest.get("captured_at") if isinstance(latest, dict) else None,
        }

    def _normalize_targets(self, targets: Optional[List[str]]) -> List[str]:
        valid_targets = ["account", "guilds", "friends", "dms", "summary"]
        if not targets:
            return list(valid_targets)

        normalized = []
        for target in targets:
            if not isinstance(target, str):
                continue
            target_name = target.lower()
            if target_name == "all":
                return list(valid_targets)
            if target_name in valid_targets and target_name not in normalized:
                normalized.append(target_name)

        return normalized or list(valid_targets)

    def build_auto_scrape_snapshot(self, targets: Optional[List[str]] = None) -> Dict[str, Any]:
        normalized_targets = self._normalize_targets(targets)
        snapshot = {
            "captured_at": time.time(),
            "targets": normalized_targets,
        }

        if "summary" in normalized_targets:
            snapshot["summary"] = self.build_local_summary(force=True)
        if "account" in normalized_targets:
            snapshot["account"] = self._build_account_export().get("account", {})
        if "guilds" in normalized_targets:
            guild_export = self._build_guild_export()
            snapshot["guild_count"] = guild_export.get("guild_count", 0)
            snapshot["guilds"] = guild_export.get("guilds", [])
        if "friends" in normalized_targets:
            friend_export = self._build_friend_export()
            snapshot["relationship_count"] = friend_export.get("relationship_count", 0)
            snapshot["relationships"] = friend_export.get("relationships", [])
        if "dms" in normalized_targets:
            dm_export = self._build_dm_export()
            snapshot["channel_count"] = dm_export.get("channel_count", 0)
            snapshot["channels"] = dm_export.get("channels", [])

        return snapshot

    def refresh_auto_scrape(self, targets: Optional[List[str]] = None) -> Dict[str, Any]:
        normalized_targets = self._normalize_targets(targets or self.auto_scrape_targets)
        snapshot = self.build_auto_scrape_snapshot(normalized_targets)
        history = self.data.setdefault("auto_scrape_history", [])
        history.append(snapshot)
        if len(history) > 48:
            self.data["auto_scrape_history"] = history[-48:]
        self.data["last_auto_scrape"] = snapshot
        self._save_stats()
        return snapshot

    def start_auto_scrape(self, interval_seconds: int = 900, targets: Optional[List[str]] = None) -> Tuple[bool, str]:
        if self.auto_scrape_thread and self.auto_scrape_active:
            return False, "Background auto scrape already running"

        self.auto_scrape_interval = max(60, int(interval_seconds))
        self.auto_scrape_targets = self._normalize_targets(targets)
        self.auto_scrape_active = True
        self.auto_scrape_thread = threading.Thread(target=self._auto_scrape_worker, daemon=True)
        self.auto_scrape_thread.start()
        target_text = ", ".join(self.auto_scrape_targets)
        return True, f"Background auto scrape started ({self.auto_scrape_interval}s, targets: {target_text})"

    def stop_auto_scrape(self) -> Tuple[bool, str]:
        if not self.auto_scrape_active:
            return False, "Background auto scrape is not running"

        self.auto_scrape_active = False
        if self.auto_scrape_thread:
            self.auto_scrape_thread.join(timeout=5)
        return True, "Background auto scrape stopped"

    def get_auto_scrape_status(self) -> Dict[str, Any]:
        latest = self.data.get("last_auto_scrape")
        return {
            "active": self.auto_scrape_active,
            "interval_seconds": self.auto_scrape_interval,
            "targets": list(self.auto_scrape_targets),
            "last_run": latest.get("captured_at") if isinstance(latest, dict) else None,
        }

    def get_last_auto_scrape(self) -> Optional[Dict[str, Any]]:
        latest = self.data.get("last_auto_scrape")
        return latest if isinstance(latest, dict) else None

    def _stats_worker(self):
        while self.stats_active:
            try:
                self.refresh_local_summary(force=True)
            except Exception as error:
                print(f"[AccountData] Local stats refresh failed: {error}")

            for _ in range(self.stats_interval):
                if not self.stats_active:
                    break
                time.sleep(1)

    def _auto_scrape_worker(self):
        while self.auto_scrape_active:
            try:
                self.refresh_auto_scrape(self.auto_scrape_targets)
            except Exception as error:
                print(f"[AccountData] Background auto scrape failed: {error}")

            for _ in range(self.auto_scrape_interval):
                if not self.auto_scrape_active:
                    break
                time.sleep(1)

    def _safe_json(self, endpoint: str) -> Any:
        response = self.api.request("GET", endpoint)
        if response and response.status_code == 200:
            try:
                return response.json()
            except Exception as error:
                print(f"[AccountData] Failed to parse {endpoint}: {error}")
        return None

    def _build_account_export(self) -> Dict[str, Any]:
        user = self.api.get_user_info(force=True) or {}
        profile = None
        user_id = user.get("id")
        if user_id:
            profile = self._safe_json(f"/users/{user_id}/profile")

        user_profile = profile.get("user_profile", {}) if isinstance(profile, dict) else {}

        return {
            "captured_at": time.time(),
            "account": {
                "id": user.get("id"),
                "username": user.get("username"),
                "global_name": user.get("global_name"),
                "discriminator": user.get("discriminator"),
                "avatar": user.get("avatar"),
                "banner": user.get("banner"),
                "accent_color": user.get("accent_color"),
                "verified": user.get("verified"),
                "locale": user.get("locale"),
                "premium_type": user.get("premium_type"),
                "flags": user.get("flags"),
                "public_flags": user.get("public_flags"),
                "bio": user_profile.get("bio"),
                "pronouns": user_profile.get("pronouns"),
            },
        }

    def _build_guild_export(self) -> Dict[str, Any]:
        guilds = self.api.get_guilds(force=True)
        return {
            "captured_at": time.time(),
            "guild_count": len(guilds),
            "guilds": [
                {
                    "id": guild.get("id"),
                    "name": guild.get("name"),
                    "owner": guild.get("owner", False),
                    "permissions": guild.get("permissions"),
                    "features": guild.get("features", []),
                    "icon": guild.get("icon"),
                    "banner": guild.get("banner"),
                }
                for guild in guilds
            ],
        }

    def _build_friend_export(self) -> Dict[str, Any]:
        relationships = self._safe_json("/users/@me/relationships")
        if not isinstance(relationships, list):
            relationships = []

        # Filter for friends only (type 1), exclude blocked/pending
        friend_relationships = [r for r in relationships if isinstance(r, dict) and r.get("type") == 1]
        
        return {
            "captured_at": time.time(),
            "relationship_count": len(friend_relationships),
            "friend_user_ids": [str(r.get("user", {}).get("id", "")) for r in friend_relationships if r.get("user", {}).get("id")],
            "relationships": [
                {
                    "id": relationship.get("id"),
                    "type": relationship.get("type"),
                    "nickname": relationship.get("nickname"),
                    "user": {
                        "id": relationship.get("user", {}).get("id"),
                        "username": relationship.get("user", {}).get("username"),
                        "global_name": relationship.get("user", {}).get("global_name"),
                        "avatar": relationship.get("user", {}).get("avatar"),
                        "discriminator": relationship.get("user", {}).get("discriminator"),
                        "bot": relationship.get("user", {}).get("bot", False),
                    },
                }
                for relationship in friend_relationships
            ],
        }

    def _build_dm_export(self) -> Dict[str, Any]:
        channels = self._safe_json("/users/@me/channels")
        if not isinstance(channels, list):
            channels = []

        return {
            "captured_at": time.time(),
            "channel_count": len(channels),
            "channels": [
                {
                    "id": channel.get("id"),
                    "type": channel.get("type"),
                    "last_message_id": channel.get("last_message_id"),
                    "recipient_count": len(channel.get("recipients", [])) if isinstance(channel.get("recipients"), list) else 0,
                    "recipients": [
                        {
                            "id": recipient.get("id"),
                            "username": recipient.get("username"),
                            "global_name": recipient.get("global_name"),
                            "avatar": recipient.get("avatar"),
                        }
                        for recipient in channel.get("recipients", [])
                        if isinstance(recipient, dict)
                    ],
                }
                for channel in channels
                if isinstance(channel, dict)
            ],
        }

    def export_requested_data(self, export_name: str) -> Tuple[bool, str, Optional[str], Optional[Dict[str, Any]]]:
        export_name = export_name.lower()
        builders = {
            "account": self._build_account_export,
            "guilds": self._build_guild_export,
            "friends": self._build_friend_export,
            "dms": self._build_dm_export,
            "summary": lambda: self.refresh_local_summary(force=True),
            "all": lambda: {
                "captured_at": time.time(),
                "account": self._build_account_export().get("account", {}),
                "guilds": self._build_guild_export().get("guilds", []),
                "relationships": self._build_friend_export().get("relationships", []),
                "channels": self._build_dm_export().get("channels", []),
            },
        }

        if export_name not in builders:
            return False, "Unsupported export target", None, None

        try:
            payload = builders[export_name]()
            os.makedirs(self.export_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time()))
            file_path = os.path.join(self.export_dir, f"{export_name}_{timestamp}.json")
            with open(file_path, "w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, indent=2, ensure_ascii=False)

            self.data["last_export"] = {
                "name": export_name,
                "file": file_path,
                "timestamp": time.time(),
            }
            self._save_stats()
            return True, f"Exported {export_name}", file_path, payload
        except Exception as error:
            return False, f"Export failed: {error}", None, None