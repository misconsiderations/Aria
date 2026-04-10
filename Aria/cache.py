import json
import os
import time
import hashlib
from typing import Dict, Any, Optional, List

class DiscordCache:
    def __init__(self, token: str):
        self.cache_dir = ".cache"
        self.token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        self.user_file = f"{self.cache_dir}/{self.token_hash}_user.json"
        self.guilds_file = f"{self.cache_dir}/{self.token_hash}_guilds.json"
        self.channels_file = f"{self.cache_dir}/{self.token_hash}_channels.json"
        self.messages_file = f"{self.cache_dir}/{self.token_hash}_messages.json"
        self._ensure_dir()
    
    def _ensure_dir(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
    def save_user(self, user_data: Dict[str, Any]):
        with open(self.user_file, 'w') as f:
            json.dump({"data": user_data, "timestamp": time.time()}, f)
    
    def get_user(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(self.user_file):
            with open(self.user_file, 'r') as f:
                cache = json.load(f)
                if time.time() - cache.get("timestamp", 0) < 3600:
                    return cache.get("data")
        return None
    
    def save_guilds(self, guilds: List[Dict[str, Any]]):
        with open(self.guilds_file, 'w') as f:
            json.dump({"data": guilds, "timestamp": time.time()}, f)
    
    def get_guilds(self) -> Optional[List[Dict[str, Any]]]:
        if os.path.exists(self.guilds_file):
            with open(self.guilds_file, 'r') as f:
                cache = json.load(f)
                if time.time() - cache.get("timestamp", 0) < 300:
                    return cache.get("data")
        return None
    
    def save_channels(self, guild_id: str, channels: List[Dict[str, Any]]):
        data = {}
        if os.path.exists(self.channels_file):
            with open(self.channels_file, 'r') as f:
                data = json.load(f)
        data[guild_id] = {"data": channels, "timestamp": time.time()}
        with open(self.channels_file, 'w') as f:
            json.dump(data, f)
    
    def get_channels(self, guild_id: str) -> Optional[List[Dict[str, Any]]]:
        if os.path.exists(self.channels_file):
            with open(self.channels_file, 'r') as f:
                data = json.load(f)
                if guild_id in data:
                    cache = data[guild_id]
                    if time.time() - cache.get("timestamp", 0) < 180:
                        return cache.get("data")
        return None
    
    def cache_message(self, message: Dict[str, Any]):
        channel_id = message["channel_id"]
        message_id = message["id"]
        
        if not os.path.exists(self.messages_file):
            messages_data = {}
        else:
            with open(self.messages_file, 'r') as f:
                messages_data = json.load(f)
        
        if channel_id not in messages_data:
            messages_data[channel_id] = {}
        
        messages_data[channel_id][message_id] = {
            "data": message,
            "timestamp": time.time()
        }
        
        with open(self.messages_file, 'w') as f:
            json.dump(messages_data, f)
    
    def get_message(self, channel_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        if os.path.exists(self.messages_file):
            with open(self.messages_file, 'r') as f:
                messages_data = json.load(f)
                if channel_id in messages_data and message_id in messages_data[channel_id]:
                    cache = messages_data[channel_id][message_id]
                    if time.time() - cache.get("timestamp", 0) < 3600:
                        return cache.get("data")
        return None
    
    def clear(self):
        for file in [self.user_file, self.guilds_file, self.channels_file, self.messages_file]:
            if os.path.exists(file):
                os.remove(file)