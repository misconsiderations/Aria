import json
import time
import requests
from collections import defaultdict
from datetime import datetime
import threading

class AFKSystem:
    def __init__(self):
        self.afk_users = {}
        self.ping_history = defaultdict(set)
        self.webhook_url = None
        self.last_notify = {}
        self.dm_buffer = defaultdict(list)
        self.last_flush = time.time()
        
    def set_afk(self, user_id, reason=""):
        self.afk_users[user_id] = {
            "since": time.time(),
            "reason": reason,
            "notified": set()
        }
        return True
    
    def remove_afk(self, user_id):
        if user_id in self.afk_users:
            del self.afk_users[user_id]
            if user_id in self.ping_history:
                del self.ping_history[user_id]
            return True
        return False
    
    def is_afk(self, user_id):
        return user_id in self.afk_users
    
    def get_afk_info(self, user_id):
        return self.afk_users.get(user_id)
    
    def set_webhook(self, webhook_url):
        self.webhook_url = webhook_url
        return True
    
    def check_mention(self, message_data, bot_instance):
        current_time = time.time()
        
        if current_time - self.last_flush > 10:
            for sender_id in list(self.dm_buffer.keys()):
                if self.dm_buffer[sender_id]:
                    self._flush_dm_buffer(sender_id, bot_instance)
        
        author_id = message_data.get("author", {}).get("id", "")
        content = message_data.get("content", "")
        channel_id = message_data.get("channel_id", "")
        channel_type = message_data.get("type", 0)
        guild_id = message_data.get("guild_id")
        
        if not author_id:
            return False
        
        bot_id = bot_instance.user_id
        
        is_dm = channel_type == 1
        is_mention = f"<@{bot_id}>" in content or f"<@!{bot_id}>" in content
        is_dm_to_bot = is_dm and author_id != bot_id
        
        if is_dm_to_bot:
            self._buffer_dm(author_id, content, channel_id, bot_instance)
            if len(self.dm_buffer[author_id]) >= 2:
                self._flush_dm_buffer(author_id, bot_instance)
            return True
        
        if is_mention and bot_id in self.afk_users:
            return self._handle_mention(author_id, content, channel_id, guild_id, bot_instance)
        
        return False
    
    def _buffer_dm(self, sender_id, content, channel_id, bot_instance):
        timestamp = time.time()
        
        message_info = {
            "content": content,
            "timestamp": timestamp
        }
        
        self.dm_buffer[sender_id].append(message_info)
        
        if len(self.dm_buffer[sender_id]) >= 3:
            self._flush_dm_buffer(sender_id, bot_instance)
    
    def _flush_dm_buffer(self, sender_id, bot_instance):
        if sender_id not in self.dm_buffer or not self.dm_buffer[sender_id]:
            return
        
        messages = self.dm_buffer[sender_id]
        
        try:
            user_response = bot_instance.api.request("GET", f"/users/{sender_id}")
            if user_response and user_response.status_code == 200:
                user_data = user_response.json()
                username = user_data.get("username", "Unknown")
            else:
                username = "Unknown"
        except:
            username = "Unknown"
        
        embed_description = f"**User:** {username} (`{sender_id}`)\n**Total Messages:** {len(messages)}\n\n"
        
        for i, msg in enumerate(messages[:10], 1):
            timestamp = datetime.fromtimestamp(msg["timestamp"]).strftime("%H:%M:%S")
            content_preview = msg["content"]
            if len(content_preview) > 100:
                content_preview = content_preview[:97] + "..."
            embed_description += f"{i}. [{timestamp}] {content_preview}\n"
        
        if len(messages) > 10:
            embed_description += f"\n... and {len(messages) - 10} more messages"
        
        embed = {
            "title": "📨 DM Batch Received",
            "description": embed_description,
            "color": 0x5865f2,
            "timestamp": datetime.now().isoformat()
        }
        
        self._send_webhook(embed)
        
        self.dm_buffer[sender_id] = []
        self.last_flush = time.time()
    
    def _handle_mention(self, sender_id, content, channel_id, guild_id, bot_instance):
        afk_data = self.afk_users.get(bot_instance.user_id)
        if not afk_data:
            return False
        
        current_time = time.time()
        last_time = self.last_notify.get(sender_id, 0)
        
        if current_time - last_time < 300:
            return True
        
        afk_since = int(current_time - afk_data["since"])
        hours = afk_since // 3600
        minutes = (afk_since % 3600) // 60
        time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        
        reply = f"**AFK** - {afk_data['reason'] or 'No reason'} ({time_str})"
        bot_instance.api.send_message(channel_id, reply)
        
        self.last_notify[sender_id] = current_time
        
        try:
            user_response = bot_instance.api.request("GET", f"/users/{sender_id}")
            if user_response and user_response.status_code == 200:
                user_data = user_response.json()
                username = user_data.get("username", "Unknown")
            else:
                username = "Unknown"
        except:
            username = "Unknown"
        
        channel_info = f"Channel: {channel_id}"
        if guild_id:
            try:
                channel_response = bot_instance.api.request("GET", f"/channels/{channel_id}")
                if channel_response and channel_response.status_code == 200:
                    channel_data = channel_response.json()
                    channel_info = f"#{channel_data.get('name', 'Unknown')}"
            except:
                pass
        
        embed = {
            "title": "🔔 AFK Ping Received",
            "description": f"**From:** {username} (`{sender_id}`)\n**Message:** {content[:500]}",
            "color": 0xff9900,
            "fields": [
                {"name": "Channel", "value": channel_info, "inline": True},
                {"name": "Server", "value": "DM" if not guild_id else f"Server: {guild_id}", "inline": True}
            ],
            "timestamp": datetime.now().isoformat()
        }
        
        self._send_webhook(embed)
        return True
    
    def _send_webhook(self, embed):
        if not self.webhook_url:
            return
        
        data = {
            "embeds": [embed],
            "username": "AFK Alert System"
        }
        
        try:
            requests.post(self.webhook_url, json=data, timeout=5)
        except:
            pass
    
    def save_state(self):
        data = {
            "afk_users": {},
            "webhook_url": self.webhook_url
        }
        
        for user_id, afk_data in self.afk_users.items():
            data["afk_users"][user_id] = {
                "since": afk_data["since"],
                "reason": afk_data["reason"]
            }
        
        with open("afk_state.json", "w") as f:
            json.dump(data, f, indent=2)
    
    def load_state(self):
        try:
            with open("afk_state.json", "r") as f:
                data = json.load(f)
                self.afk_users = {}
                
                for user_id, afk_data in data.get("afk_users", {}).items():
                    self.afk_users[user_id] = {
                        "since": afk_data["since"],
                        "reason": afk_data["reason"],
                        "notified": set()
                    }
                
                self.webhook_url = data.get("webhook_url")
                return True
        except:
            return False

afk_system = AFKSystem()