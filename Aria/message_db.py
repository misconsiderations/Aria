import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class MessageDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.is_active = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        except Exception:
            pass

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_messages (
                        id TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        guild_id TEXT,
                        user_id TEXT NOT NULL,
                        username TEXT,
                        content TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_um_channel_created ON user_messages(channel_id, created_at DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_um_user_channel_created ON user_messages(user_id, channel_id, created_at DESC)"
                )
                conn.commit()
            self.is_active = True
        except Exception:
            self.is_active = False

    def track_message(self, message_data: Dict[str, Any]) -> None:
        if not self.is_active:
            return

        msg_id = str(message_data.get("id", "")).strip()
        if not msg_id:
            return

        author = message_data.get("author", {}) or {}
        content = str(message_data.get("content", "") or "")
        channel_id = str(message_data.get("channel_id", "") or "")
        guild_id = str(message_data.get("guild_id", "") or "")
        user_id = str(author.get("id", "") or "")
        username = str(author.get("username", "Unknown") or "Unknown")
        created_at = str(message_data.get("timestamp", "") or datetime.utcnow().isoformat())

        if not channel_id or not user_id:
            return

        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO user_messages
                    (id, channel_id, guild_id, user_id, username, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (msg_id, channel_id, guild_id, user_id, username, content, created_at),
                )
                conn.commit()

    def get_recent_messages(self, channel_id: str, user_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.is_active:
            return []

        limit = max(1, min(int(limit), 50))
        params: List[Any] = [str(channel_id)]

        if user_id:
            sql = (
                "SELECT id, channel_id, guild_id, user_id, username, content, created_at "
                "FROM user_messages WHERE channel_id = ? AND user_id = ? "
                "ORDER BY created_at DESC LIMIT ?"
            )
            params.append(str(user_id))
            params.append(limit)
        else:
            sql = (
                "SELECT id, channel_id, guild_id, user_id, username, content, created_at "
                "FROM user_messages WHERE channel_id = ? "
                "ORDER BY created_at DESC LIMIT ?"
            )
            params.append(limit)

        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]
