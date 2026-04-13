import json
import os

class Config:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.default_config = {
            "token": "token here",
            "prefix": ";",
            "auto_restart": True,
            "logging": True,
            "rate_limit_delay": 0.1,
            "cache_enabled": True,
            "max_message_cache": 1000,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "impersonate_browser": "chrome120",
            "vr_oauth_token": "default_oauth_key_for_all_users",
            "vr_headless_auto_start": False,
            "vr_headless_name": "~~",
            "vr_headless_platform": "meta_quest",
            "vr_headless_interval": 60,
            "rpcname": "In VR",
            "details": "Meta Quest",
            "state": "Playing",
            "large_image": "",
            "application_id": "0",
            "vr_rpc_auto_start": False,
            "vr_rpc_icon_only": True,
            "discord_client_id": "1491307436148129822",
            "discord_client_secret": "u969UvYVRgaYG8kGleosNl3JkQxUHHnd",
            "dashboard_url": "https://stackss.lol",
            "oauth_redirect_uri": "https://stackss.lol/callback",
            "discord_bot_token": "MTQ5MTMwNzQzNjE0ODEyOTgyMg.GcU03l.0K3Rw6Eoy4_NkqrD_zSaYKLxj8Sy5HgPgOJ9O4",
            "discord_slash_guild_id": "",
            "auto_start_slash_bot": True,
                "slash_hide_replies": True,
            "captcha_enabled": False,
            "captcha_api_key": "6354c8b64c602d94cadf5912f437cd28",
            "captcha_service": "2captcha"  # 2captcha, anticaptcha, capmonster
        }
        self.config = self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    config = self.default_config.copy()
                    config.update(loaded)
                    
                    if not config["token"] or config["token"] == "token here":
                        if os.path.exists("hosted_token.txt"):
                            with open("hosted_token.txt", "r") as tf:
                                config["token"] = tf.read().strip()
                    
                    return config
            except:
                return self.default_config
        return self.default_config
    
    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)
    
    def get(self, key, default=None):
        return self.config.get(key, default)
    
    def set(self, key, value):
        self.config[key] = value
        self.save_config()