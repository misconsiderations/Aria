import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


class BadgeScraper:
    BADGE_FLAGS = {
        1 << 0: "Discord Staff",
        1 << 1: "Partnered Server Owner",
        1 << 2: "HypeSquad Events",
        1 << 3: "Bug Hunter Level 1",
        1 << 6: "HypeSquad Bravery",
        1 << 7: "HypeSquad Brilliance",
        1 << 8: "HypeSquad Balance",
        1 << 9: "Early Supporter",
        1 << 10: "Team User",
        1 << 14: "Bug Hunter Level 2",
        1 << 16: "Verified Bot",
        1 << 17: "Early Verified Bot Developer",
        1 << 18: "Certified Moderator",
        1 << 19: "Bot HTTP Interactions",
        1 << 22: "Active Developer",
    }

    PREMIUM_TYPES = {
        1: "Nitro Classic",
        2: "Nitro",
        3: "Nitro Basic",
    }

    def __init__(self, api_client, history_manager=None, output_dir: str = "backups"):
        self.api = api_client
        self.history_manager = history_manager
        self.output_dir = output_dir

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def decode_public_flags(self, public_flags: Any) -> List[str]:
        flags = self._safe_int(public_flags)
        return [name for bit, name in self.BADGE_FLAGS.items() if flags & bit]

    def decode_premium_type(self, premium_type: Any) -> List[str]:
        premium_value = self._safe_int(premium_type)
        badge = self.PREMIUM_TYPES.get(premium_value)
        return [badge] if badge else []

    def _normalize_raw_badges(self, raw_badges: Any) -> List[str]:
        if not isinstance(raw_badges, list):
            return []

        normalized = []
        for badge in raw_badges:
            if isinstance(badge, str) and badge:
                normalized.append(badge)
            elif isinstance(badge, int):
                normalized.append(f"badge_{badge}")
        return normalized

    def build_badge_record(self, user_data: Dict[str, Any], extra_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        extra_profile = extra_profile or {}
        decoded_badges = self.decode_public_flags(user_data.get("public_flags"))
        decoded_badges.extend(self.decode_premium_type(extra_profile.get("premium_type", user_data.get("premium_type"))))

        for raw_badge in self._normalize_raw_badges(extra_profile.get("badges", [])):
            if raw_badge not in decoded_badges:
                decoded_badges.append(raw_badge)

        decoded_badges = sorted(set(decoded_badges))
        return {
            "timestamp": time.time(),
            "user_id": str(user_data.get("id", "")),
            "username": user_data.get("username") or extra_profile.get("username") or "Unknown",
            "global_name": user_data.get("global_name") or extra_profile.get("global_name"),
            "discriminator": user_data.get("discriminator") or extra_profile.get("discriminator", "0000"),
            "public_flags": self._safe_int(user_data.get("public_flags", extra_profile.get("public_flags"))),
            "premium_type": self._safe_int(extra_profile.get("premium_type", user_data.get("premium_type"))),
            "badges": decoded_badges,
        }

    def scrape_user_badges(self, user_id: str, force_refresh: bool = True) -> Optional[Dict[str, Any]]:
        if not user_id or not user_id.isdigit():
            return None

        profile_data = None
        if self.history_manager and force_refresh:
            profile_data = self.history_manager.scrape_user_profile(user_id)

        if not profile_data and self.history_manager:
            history = self.history_manager.get_user_history(user_id)
            if history:
                profile_data = history[-1]

        response = self.api.request("GET", f"/users/{user_id}")
        user_data = response.json() if response and response.status_code == 200 else {"id": user_id}

        record = self.build_badge_record(user_data, profile_data)
        return record if record["badges"] else record

    def _fetch_guild_name(self, server_id: str) -> Optional[str]:
        response = self.api.request("GET", f"/guilds/{server_id}")
        if response and response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                return data.get("name")
        return None

    def scrape_guild_badges(self, server_id: str, limit: int = 1000) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        scanned_members = 0
        after = None
        limit = max(1, min(limit, 10000))

        while scanned_members < limit:
            params = {"limit": min(1000, limit - scanned_members)}
            if after:
                params["after"] = after

            response = self.api.request("GET", f"/guilds/{server_id}/members", params=params)
            if not response or response.status_code != 200:
                break

            members = response.json()
            if not isinstance(members, list) or not members:
                break

            for member in members:
                user_data = member.get("user", {}) if isinstance(member, dict) else {}
                if not user_data:
                    continue

                scanned_members += 1
                record = self.build_badge_record(user_data)
                if record["badges"]:
                    record["server_id"] = server_id
                    record["nick"] = member.get("nick")
                    results.append(record)

                if scanned_members >= limit:
                    break

            after = members[-1].get("user", {}).get("id") if members else None
            if not after or len(members) < params["limit"]:
                break

        return {
            "server_id": server_id,
            "server_name": self._fetch_guild_name(server_id),
            "generated_at": time.time(),
            "scanned_members": scanned_members,
            "matched_members": len(results),
            "results": results,
        }

    def summarize_results(self, payload: Dict[str, Any]) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for record in payload.get("results", []):
            for badge in record.get("badges", []):
                summary[badge] = summary.get(badge, 0) + 1
        return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))

    def export_guild_badges(self, payload: Dict[str, Any]) -> Dict[str, str]:
        os.makedirs(self.output_dir, exist_ok=True)
        server_id = payload.get("server_id", "unknown")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base_name = f"badge_scrape_{server_id}_{timestamp}"
        json_path = os.path.join(self.output_dir, f"{base_name}.json")
        txt_path = os.path.join(self.output_dir, f"{base_name}.txt")

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

        lines = []
        for record in payload.get("results", []):
            badge_list = ", ".join(record.get("badges", []))
            lines.append(
                f"[SCRAPED] User: \"{record.get('username', 'Unknown')}\" | ID: {record.get('user_id')} | Badges: {badge_list}"
            )

        with open(txt_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        return {"json": json_path, "txt": txt_path}