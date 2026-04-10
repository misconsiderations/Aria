import re
import time
from collections import defaultdict

class ModerationManager:
    def __init__(self, api_client):
        self.api = api_client
        self.word_filters = {}
        self.spam_trackers = defaultdict(list)
    
    def mass_kick(self, guild_id, user_ids):
        success_count = 0
        for user_id in user_ids:
            try:
                response = self.api.request("DELETE", f"/guilds/{guild_id}/members/{user_id}")
                if response and response.status_code in [200, 204]:
                    success_count += 1
                time.sleep(0.5)
            except:
                continue
        return success_count
    
    def mass_ban(self, guild_id, user_ids, delete_days=0):
        success_count = 0
        for user_id in user_ids:
            try:
                response = self.api.request("PUT", f"/guilds/{guild_id}/bans/{user_id}", data={"delete_message_days": delete_days})
                if response and response.status_code in [200, 204]:
                    success_count += 1
                time.sleep(0.5)
            except:
                continue
        return success_count
    
    def mass_delete_channels(self, guild_id, channel_ids):
        success_count = 0
        for channel_id in channel_ids:
            try:
                response = self.api.request("DELETE", f"/channels/{channel_id}")
                if response and response.status_code in [200, 204]:
                    success_count += 1
                time.sleep(0.3)
            except:
                continue
        return success_count
    
    def mass_delete_roles(self, guild_id, role_ids):
        success_count = 0
        for role_id in role_ids:
            try:
                response = self.api.request("DELETE", f"/guilds/{guild_id}/roles/{role_id}")
                if response and response.status_code in [200, 204]:
                    success_count += 1
                time.sleep(0.3)
            except:
                continue
        return success_count
    
    def create_word_filter(self, guild_id, words):
        if guild_id not in self.word_filters:
            self.word_filters[guild_id] = []
        
        for word in words:
            pattern = re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)
            self.word_filters[guild_id].append(pattern)
        
        return len(words)
    
    def check_message_filter(self, guild_id, message_content):
        if guild_id not in self.word_filters:
            return None
        
        for pattern in self.word_filters[guild_id]:
            if pattern.search(message_content):
                return pattern.pattern
        return None
    
    def check_spam(self, user_id, channel_id, message_time):
        key = f"{user_id}_{channel_id}"
        self.spam_trackers[key].append(message_time)
        
        recent_messages = [t for t in self.spam_trackers[key] if time.time() - t < 10]
        self.spam_trackers[key] = recent_messages
        
        if len(recent_messages) > 5:
            return True
        return False
    
    def get_members(self, guild_id, limit=1000):
        members = []
        after = None
        
        while len(members) < limit:
            params = {"limit": 100}
            if after:
                params["after"] = after
            
            response = self.api.request("GET", f"/guilds/{guild_id}/members", params=params)
            if not response or response.status_code != 200:
                break
            
            batch = response.json()
            if not batch:
                break
            
            members.extend(batch)
            after = batch[-1]["user"]["id"]
            
            if len(batch) < 100:
                break
        
        return members[:limit]
    
    def get_channels(self, guild_id):
        return self.api.get_channels(guild_id)
    
    def get_roles(self, guild_id):
        response = self.api.request("GET", f"/guilds/{guild_id}/roles")
        if response and response.status_code == 200:
            return response.json()
        return []