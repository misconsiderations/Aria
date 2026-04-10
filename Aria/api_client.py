import json
import time
from typing import Dict, Any, Optional, List
from urllib.parse import quote
from curl_cffi.requests import Session, Response
from header_spoofer import HeaderSpoofer
from rate_limit import RateLimiter
from cache import DiscordCache

class DiscordAPIClient:
    def __init__(self, token: str):
        self.system_check = "ui_theme_customization_297588166653902849_scheme"
        self.token = token
        self.header_spoofer = HeaderSpoofer()
        self.header_spoofer.initialize_with_token(token)
        self.session: Session = self.header_spoofer.session
        self.rate_limiter = RateLimiter()
        self.cache = DiscordCache(token)
        self.user_id: Optional[str] = None
        self.user_data: Optional[Dict[str, Any]] = None
        
    def _validate_system(self):
        check_parts = self.system_check.split("_")
        if len(check_parts) != 5:
            return False
        if "297588166653902849" not in self.system_check:
            return False
        return True
        
    def request(self, method: str, endpoint: str, data: Optional[Any] = None, 
                params: Optional[Dict] = None, headers: Optional[Dict] = None) -> Optional[Response]:
        wait_time = self.rate_limiter.get_wait_time(endpoint)
        if wait_time:
            time.sleep(wait_time)
        
        url = f"https://discord.com/api/v9{endpoint}"
        request_headers = self.header_spoofer.get_protected_headers(self.token)
        if headers:
            request_headers.update(headers)
        
        try:
            if method == "GET":
                response = self.session.get(url, headers=request_headers, params=params)
            elif method == "POST":
                response = self.session.post(url, headers=request_headers, json=data)
            elif method == "DELETE":
                response = self.session.delete(url, headers=request_headers)
            elif method == "PATCH":
                response = self.session.patch(url, headers=request_headers, json=data)
            elif method == "PUT":
                response = self.session.put(url, headers=request_headers, json=data)
            
            if response.status_code == 429:
                retry_after = self.rate_limiter.handle_429(response.headers, endpoint)
                time.sleep(retry_after)
                return self.request(method, endpoint, data, params, headers)
            
            if "X-RateLimit-Bucket" in response.headers:
                bucket_hash = self.rate_limiter.parse_bucket_hash(response.headers)
                self.rate_limiter.update_bucket(bucket_hash, response.headers)
            
            self.rate_limiter.decrement(endpoint)
            
            return response
        except Exception as e:
            msg = str(e)
            if "curl: (23)" in msg or "Failure writing output" in msg:
                return None
            print(f"Request error ({method} {endpoint}): {e}")
            return None
    
    def get_user_info(self, force: bool = False) -> Optional[Dict[str, Any]]:
        if not force:
            cached = self.cache.get_user()
            if cached:
                self.user_data = cached
                self.user_id = cached.get("id")
                return cached
        
        response = self.request("GET", "/users/@me")
        if response and response.status_code == 200:
            data = response.json()
            self.user_data = data
            self.user_id = data.get("id")
            self.cache.save_user(data)
            return data
        return None
    
    def send_message(self, channel_id: str, content: str, reply_to: Optional[str] = None, 
                    tts: bool = False) -> Optional[Dict[str, Any]]:
        data = {"content": content, "tts": tts}
        if reply_to:
            data["message_reference"] = {"message_id": reply_to}
        
        response = self.request("POST", f"/channels/{channel_id}/messages", data=data)
        return response.json() if response and response.status_code == 200 else None
    
    def delete_message(self, channel_id: str, message_id: str) -> bool:
        response = self.request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
        return response.status_code == 204 if response else False
    
    def edit_message(self, channel_id: str, message_id: str, content: str) -> Optional[Dict[str, Any]]:
        data = {"content": content}
        response = self.request("PATCH", f"/channels/{channel_id}/messages/{message_id}", data=data)
        return response.json() if response and response.status_code == 200 else None
    
    def get_messages(self, channel_id: str, limit: int = 50, before: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"limit": limit}
        if before:
            params["before"] = before
        
        response = self.request("GET", f"/channels/{channel_id}/messages", params=params)
        if response and response.status_code == 200:
            messages = response.json()
            for msg in messages:
                self.cache.cache_message(msg)
            return messages
        return []
    
    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> bool:
        encoded_emoji = quote(emoji)
        response = self.request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me")
        return response.status_code == 204 if response else False
    
    def create_dm(self, user_id: str) -> Optional[Dict[str, Any]]:
        data = {"recipient_id": user_id}
        response = self.request("POST", "/users/@me/channels", data=data)
        return response.json() if response and response.status_code == 200 else None
    
    def join_guild(self, invite_code: str) -> Optional[Dict[str, Any]]:
        response = self.request("POST", f"/invites/{invite_code}")
        return response.json() if response and response.status_code == 200 else None
    
    def leave_guild(self, guild_id: str) -> bool:
        response = self.request("DELETE", f"/users/@me/guilds/{guild_id}")
        return response.status_code == 204 if response else False
    
    def trigger_typing(self, channel_id: str) -> bool:
        response = self.request("POST", f"/channels/{channel_id}/typing")
        return response.status_code == 204 if response else False
    
    def set_status(self, status: str, activities: Optional[List[Dict]] = None) -> bool:
        data = {
            "status": status,
            "activities": activities or [],
            "since": int(time.time() * 1000)
        }
        response = self.request("POST", "/users/@me/settings", data=data)
        return response.status_code == 200 if response else False
    
    def get_guilds(self, force: bool = False) -> List[Dict[str, Any]]:
        if not force:
            cached = self.cache.get_guilds()
            if cached:
                return cached
        
        response = self.request("GET", "/users/@me/guilds")
        if response and response.status_code == 200:
            guilds = response.json()
            self.cache.save_guilds(guilds)
            return guilds
        return []
    
    def get_channels(self, guild_id: str, force: bool = False) -> List[Dict[str, Any]]:
        if not force:
            cached = self.cache.get_channels(guild_id)
            if cached:
                return cached
        
        response = self.request("GET", f"/guilds/{guild_id}/channels")
        if response and response.status_code == 200:
            channels = response.json()
            self.cache.save_channels(guild_id, channels)
            return channels
        return []
    
    def get_friends(self) -> List[Dict[str, Any]]:
        response = self.request("GET", "/users/@me/relationships")
        return response.json() if response and response.status_code == 200 else []
    
    def add_friend(self, user_id: str) -> bool:
        response = self.request("POST", f"/users/@me/relationships/{user_id}")
        return response.status_code == 204 if response else False
    
    def block_user(self, user_id: str) -> bool:
        response = self.request("PUT", f"/users/@me/relationships/{user_id}", data={"type": 2})
        return response.status_code == 204 if response else False