import json
import os
import time


class AFKSystem:
    def __init__(self, state_file="afk_state.json"):
        self.state_file = state_file
        self.afk_users = {}
        self.webhook_url = None

    def load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as handle:
                    data = json.load(handle)
                self.afk_users = data.get("afk_users", {}) or {}
                self.webhook_url = data.get("webhook_url")
        except Exception:
            self.afk_users = {}
            self.webhook_url = None

    def save_state(self):
        try:
            with open(self.state_file, "w") as handle:
                json.dump(
                    {
                        "afk_users": self.afk_users,
                        "webhook_url": self.webhook_url,
                    },
                    handle,
                    indent=2,
                )
        except Exception:
            pass

    def set_afk(self, user_id, reason="AFK"):
        user_id = str(user_id)
        self.afk_users[user_id] = {
            "reason": reason or "AFK",
            "since": int(time.time()),
        }
        return True

    def remove_afk(self, user_id):
        user_id = str(user_id)
        if user_id in self.afk_users:
            del self.afk_users[user_id]
            return True
        return False

    def is_afk(self, user_id):
        return str(user_id) in self.afk_users

    def get_afk_info(self, user_id):
        return self.afk_users.get(str(user_id), {})

    def set_webhook(self, webhook_url):
        self.webhook_url = webhook_url.strip() if webhook_url else None
        return True


afk_system = AFKSystem()
