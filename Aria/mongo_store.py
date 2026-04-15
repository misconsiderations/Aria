from __future__ import annotations

import copy
import json
import os
import threading
import time
from typing import Any, Dict, Optional

try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _read_config_file() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class MongoStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._collection = None
        self._last_error = ""
        self._settings = self._load_settings()

    def _load_settings(self) -> Dict[str, Any]:
        config = _read_config_file()
        enabled = _as_bool(os.getenv("ARIA_MONGO_ENABLED", config.get("mongo_enabled", False)))
        return {
            "enabled": enabled,
            "uri": os.getenv("ARIA_MONGO_URI", config.get("mongo_uri", "mongodb://127.0.0.1:27017")),
            "database": os.getenv("ARIA_MONGO_DATABASE", config.get("mongo_database", "aria")),
            "collection": os.getenv("ARIA_MONGO_COLLECTION", config.get("mongo_collection", "app_state")),
            "timeout_ms": int(os.getenv("ARIA_MONGO_TIMEOUT_MS", config.get("mongo_timeout_ms", 1500)) or 1500),
        }

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled")) and MongoClient is not None

    @property
    def available(self) -> bool:
        return self.enabled

    @property
    def last_error(self) -> str:
        return self._last_error

    def describe(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "uri": self._settings.get("uri"),
            "database": self._settings.get("database"),
            "collection": self._settings.get("collection"),
            "driver_installed": MongoClient is not None,
            "last_error": self._last_error,
        }

    def _get_collection(self):
        if not self.enabled:
            raise RuntimeError("MongoDB backend is disabled or pymongo is not installed")
        with self._lock:
            if self._collection is not None:
                return self._collection
            try:
                self._client = MongoClient(
                    self._settings["uri"],
                    serverSelectionTimeoutMS=self._settings["timeout_ms"],
                    connectTimeoutMS=self._settings["timeout_ms"],
                    socketTimeoutMS=max(self._settings["timeout_ms"], 3000),
                    retryWrites=True,
                )
                self._client.admin.command("ping")
                self._collection = self._client[self._settings["database"]][self._settings["collection"]]
                self._collection.create_index("updated_at")
            except Exception as error:
                self._last_error = str(error)
                self._client = None
                self._collection = None
                raise
            return self._collection

    def load_document(self, key: str, default: Any = None) -> Any:
        if not self.enabled:
            return copy.deepcopy(default)
        try:
            document = self._get_collection().find_one({"_id": key}, {"payload": 1})
            if not document:
                return copy.deepcopy(default)
            return copy.deepcopy(document.get("payload", default))
        except Exception as error:
            self._last_error = str(error)
            return copy.deepcopy(default)

    def save_document(self, key: str, payload: Any) -> bool:
        if not self.enabled:
            return False
        try:
            self._get_collection().update_one(
                {"_id": key},
                {
                    "$set": {
                        "payload": copy.deepcopy(payload),
                        "updated_at": time.time(),
                    }
                },
                upsert=True,
            )
            return True
        except Exception as error:
            self._last_error = str(error)
            return False


_STORE: Optional[MongoStore] = None
_STORE_LOCK = threading.Lock()


def get_mongo_store() -> MongoStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = MongoStore()
        return _STORE