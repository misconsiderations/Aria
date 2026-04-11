import os
import threading
import urllib.parse
import time


GIVEAWAY_KEYWORDS = ["giveaway", "win", "prize", "hosted by", "ends in", "🎉, react to win, React to win, Nitro, Giveaway, giveaway"]


class GiveawaySniper:
    def __init__(self, api_client):
        self.api = api_client
        self.enabled = False
        self._entered = set()          # message IDs already entered
        self._lock = threading.Lock()
        self.stats = {"entered": 0, "won": 0, "failed": 0}

    # ------------------------------------------------------------------
    # Public entry point — called from bot.py MESSAGE_CREATE
    # ------------------------------------------------------------------

    def check_message(self, message_data: dict):
        if not self.enabled:
            return

        author = message_data.get("author") or {}
        author_id = str(author.get("id", ""))
        is_bot = author.get("bot", False)

        # Never act on own messages
        if author_id == str(getattr(self.api, "user_id", "") or ""):
            return

        # Win detection — any message that mentions us
        threading.Thread(
            target=self._check_win, args=(message_data,), daemon=True
        ).start()

        # Giveaway entry — bot messages only
        if is_bot:
            threading.Thread(
                target=self._try_enter, args=(message_data,), daemon=True
            ).start()

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _full_text(self, message_data: dict) -> str:
        content = (message_data.get("content") or "").lower()
        embed_parts = []
        for embed in message_data.get("embeds") or []:
            embed_parts.append(str(embed.get("title") or ""))
            embed_parts.append(str(embed.get("description") or ""))
            for field in embed.get("fields") or []:
                embed_parts.append(str(field.get("name") or ""))
                embed_parts.append(str(field.get("value") or ""))
            embed_parts.append(str((embed.get("footer") or {}).get("text") or ""))
            embed_parts.append(str((embed.get("author") or {}).get("name") or ""))
        return content + " " + " ".join(embed_parts).lower()

    def _is_giveaway(self, message_data: dict) -> bool:
        return any(kw in self._full_text(message_data) for kw in GIVEAWAY_KEYWORDS)

    def _already_reacted(self, message_data: dict) -> bool:
        for r in message_data.get("reactions") or []:
            if r.get("me"):
                name = (r.get("emoji") or {}).get("name", "")
                if name == "🎉":
                    return True
        return False

    # ------------------------------------------------------------------
    # Entry logic — button first, reactions fallback
    # ------------------------------------------------------------------

    def _first_button(self, message_data: dict):
        for row in message_data.get("components") or []:
            for comp in row.get("components") or []:
                if comp.get("type") == 2 and comp.get("custom_id"):  # Button
                    return comp
        return None

    def _reaction_identifiers(self, message_data: dict):
        result = []
        for r in message_data.get("reactions") or []:
            if r.get("me"):
                continue
            if (r.get("count") or 0) <= 0:
                continue
            enc = self._encode_emoji(r.get("emoji"))
            if enc:
                result.append(enc)
        return result

    @staticmethod
    def _encode_emoji(emoji) -> str:
        if not emoji:
            return ""
        if isinstance(emoji, str):
            return urllib.parse.quote(emoji)
        eid = emoji.get("id")
        name = emoji.get("name") or ""
        if eid:
            prefix = "a:" if emoji.get("animated") else ""
            return f"{prefix}{name}:{eid}"
        return urllib.parse.quote(name) if name else ""

    def _try_enter(self, message_data: dict):
        if not self._is_giveaway(message_data):
            return

        msg_id = str(message_data.get("id", ""))

        with self._lock:
            if msg_id in self._entered:
                return

        if self._already_reacted(message_data):
            return

        button = self._first_button(message_data)
        reactions = self._reaction_identifiers(message_data)

        if not button and not reactions:
            return

        with self._lock:
            if msg_id in self._entered:
                return
            self._entered.add(msg_id)

        success = False
        if button:
            success = self._click_button(message_data, button)
        if not success and reactions:
            success = self._add_reactions(message_data, reactions)

        if success:
            self.stats["entered"] += 1
            guild = message_data.get("guild_id", "DM")
            channel = message_data.get("channel_id", "?")
            ts = time.strftime("%H:%M:%S")
            print(
                f"\033[1;34m[GIVEAWAY]\033[0m [{ts}] Entered | guild={guild} "
                f"| channel={channel} | msg={msg_id} | total={self.stats['entered']}"
            )
        else:
            self.stats["failed"] += 1

    def _click_button(self, message_data: dict, button: dict) -> bool:
        headers = self.api.header_spoofer.get_protected_headers(self.api.token)
        payload = {
            "type": 3,
            "nonce": str(int.from_bytes(os.urandom(8), "big") % (10**19 - 10**18) + 10**18),
            "guild_id": message_data.get("guild_id"),
            "channel_id": message_data.get("channel_id"),
            "message_flags": message_data.get("flags", 0),
            "message_id": message_data.get("id"),
            "application_id": str((message_data.get("author") or {}).get("id", "")),
            "session_id": "0",
            "data": {
                "component_type": button.get("type", 2),
                "custom_id": button.get("custom_id"),
            },
        }
        try:
            resp = self.api.session.post(
                "https://discord.com/api/v10/interactions",
                headers=headers,
                json=payload,
                timeout=10,
            )
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def _add_reactions(self, message_data: dict, identifiers: list) -> bool:
        headers = self.api.header_spoofer.get_protected_headers(self.api.token)
        channel_id = message_data.get("channel_id")
        msg_id = message_data.get("id")
        success = False
        for enc in identifiers:
            try:
                resp = self.api.session.put(
                    f"https://discord.com/api/v9/channels/{channel_id}/messages/{msg_id}/reactions/{enc}/@me",
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code in (200, 204):
                    success = True
            except Exception:
                pass
        return success

    # ------------------------------------------------------------------
    # Win detection
    # ------------------------------------------------------------------

    def _check_win(self, message_data: dict):
        user_id = str(getattr(self.api, "user_id", "") or "")
        if not user_id:
            return

        content = (message_data.get("content") or "").lower()
        mentions = message_data.get("mentions") or []

        mentioned = (
            f"<@{user_id}>" in content
            or f"<@!{user_id}>" in content
            or any(str((m or {}).get("id", "")) == user_id for m in mentions)
        )

        if mentioned and any(kw in content for kw in ["congratulations", "won", "winner", "🎉"]):
            self.stats["won"] += 1
            ts = time.strftime("%H:%M:%S")
            print(
                f"\033[1;32m[GIVEAWAY WIN]\033[0m [{ts}] WON! | guild={message_data.get('guild_id')} "
                f"| channel={message_data.get('channel_id')} | total_wins={self.stats['won']}"
            )

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def toggle(self, state=None):
        self.enabled = state if state is not None else not self.enabled
        return self.enabled

    def get_stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "entered": self.stats["entered"],
            "won": self.stats["won"],
            "failed": self.stats["failed"],
        }
