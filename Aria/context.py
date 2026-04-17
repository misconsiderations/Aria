import asyncio
import time
from typing import Dict, Any, Optional, List
from urllib.parse import quote
from curl_cffi.requests import Session, Response
from discord_api_types import RelationshipType
from discord.ext import commands as umbra
from core.client.bucket import BucketHandler
from core.shared.config import container

# Import header-spoofer v2
try:
    from header_spoofer import HeaderSpoofer
    HEADER_SPOOFER_AVAILABLE = True
except ImportError:
    HEADER_SPOOFER_AVAILABLE = False

class Context(umbra.Context):
    """Custom context with full bot access and DM protection"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.umbra = self.bot

        self.token = (
            getattr(self.umbra.http, 'token', None)
            or getattr(self.umbra, 'token', None)
            or getattr(container, 'token', None)
        )
        if not self.token:
            raise ValueError("Token is required. Set bot.token")

        # Use enhanced header generation if available
        if hasattr(self.umbra, 'api') and self.umbra.api and hasattr(self.umbra.api, 'header_spoofer'):
            # Initialize header spoofer with token
            self.umbra.api.header_spoofer.initialize_with_token(self.token)
            self.session = self.umbra.api.session
        else:
            # Fallback to basic header spoofer
            self.header_spoofer = HeaderSpoofer()
            self.header_spoofer.initialize_with_token(self.token)
            self.session = self.header_spoofer.session

        self.rate_limiter = BucketHandler()
        self.user_id: Optional[str] = None
        self.user_data: Optional[Dict[str, Any]] = None

    async def request(self, method: str, endpoint: str, data: Optional[Any] = None,
                    params: Optional[Dict] = None, headers: Optional[Dict] = None) -> Optional[Response]:
        """
        Make HTTP request with enhanced protection and DM-specific rate limiting
        """
        try:
            # Check anti-spam protection first (to prevent account suspensions)
            if "/channels/" in endpoint and "/messages" in endpoint and method == "POST":
                # This is sending a message - check if it's to a new user
                # For simplicity, we'll assume all DMs could be to new users
                if "/dm/" in endpoint or (len(endpoint.split("/")) >= 4 and endpoint.split("/")[2] == "channels"):
                    # Extract channel ID
                    parts = endpoint.split("/")
                    if len(parts) >= 4:
                        channel_id = parts[3]
                        can_proceed, reason = self.rate_limiter.check_spam_risk("dm_new_user", channel_id)
                        if not can_proceed:
                            print(f"SPAM PROTECTION: {reason}")
                            return None

            # Check client-side rate limits (optimized for speed)
            action_type = "message" if "/messages" in endpoint else "typing" if "/typing" in endpoint else "reaction" if "/reactions" in endpoint else "other"
            channel_id = "global"

            # Extract channel ID for per-channel tracking
            if "/channels/" in endpoint:
                parts = endpoint.split("/channels/")
                if len(parts) > 1:
                    channel_id = parts[1].split("/")[0]

            client_wait = self.rate_limiter.check_client_rate_limit(action_type, channel_id)
            if client_wait and client_wait > 0.01:  # Only wait if significant delay needed
                await asyncio.sleep(min(client_wait, 0.1))  # Cap at 100ms

            # Check rate limits using bucket handler (optimized)
            bucket_hash = self.rate_limiter.endpoint_to_bucket.get(endpoint, "global")
            wait_time = self.rate_limiter.should_wait(bucket_hash)
            if wait_time and wait_time > 0.01:  # Only wait if significant delay needed
                await asyncio.sleep(min(wait_time, 0.05))  # Cap at 50ms

            # Check protection coordinator first
            if hasattr(self.umbra, 'api') and self.umbra.api and hasattr(self.umbra.api, 'header_spoofer'):
                # Check DM-specific protection for message endpoints
                wait_time = None
                if '/channels/' in endpoint and '/messages' in endpoint:
                    # Extract channel ID for DM tracking
                    channel_id = None
                    if '/channels/' in endpoint:
                        parts = endpoint.split('/channels/')
                        if len(parts) > 1:
                            channel_id = parts[1].split('/')[0]

                    wait_time = self.umbra.api.rate_limiter.check_dm_protection(channel_id)
                else:
                    # Regular rate limiting for non-DM requests
                    wait_time = self.umbra.api.rate_limiter.get_wait_time(endpoint)

                if wait_time and wait_time > 0:
                    await asyncio.sleep(wait_time)

                request_headers = self.umbra.api.header_spoofer.get_protected_headers(self.token)
                if headers:
                    request_headers.update(headers)
            else:
                request_headers = headers or {}

            # Make request
            url = f"https://discord.com/api/v9{endpoint}"
            response = self.session.request(method, url, data=data, params=params, headers=request_headers)

            # Update bucket info from response headers
            if "X-RateLimit-Bucket" in response.headers:
                bucket_hash = self.rate_limiter.parse_bucket_hash(response.headers)
                self.rate_limiter.update_bucket(bucket_hash, response.headers)

            # Decrement bucket usage
            if bucket_hash:
                self.rate_limiter.decrement(bucket_hash)

            # Handle 429 responses
            if response.status_code == 429:
                # Update bucket with 429 info
                if "X-RateLimit-Bucket" in response.headers:
                    bucket_hash = self.rate_limiter.parse_bucket_hash(response.headers)
                    self.rate_limiter.handle_429(response.headers, endpoint)

                retry_after = float(response.headers.get("Retry-After", "1.0"))
                await asyncio.sleep(retry_after)

                # Retry with new headers
                if hasattr(self.umbra, 'api') and self.umbra.api and hasattr(self.umbra.api, 'header_spoofer'):
                    request_headers = self.umbra.api.header_spoofer.get_protected_headers(self.token)
                    if headers:
                        request_headers.update(headers)

                response = self.session.request(method, url, data=data, params=params, headers=request_headers)

                # Update bucket after retry
                if "X-RateLimit-Bucket" in response.headers:
                    bucket_hash = self.rate_limiter.parse_bucket_hash(response.headers)
                    self.rate_limiter.update_bucket(bucket_hash, response.headers)

            # Handle success
            if hasattr(self.umbra, 'api') and self.umbra.api and hasattr(self.umbra.api, 'header_spoofer'):
                # No specific success handling needed for HeaderSpoofer
                pass

            return response

        except Exception as e:
            msg = str(e)
            if "curl: (23)" in msg or "Failure writing output" in msg:
                return None
            print(f"Request error ({method} {endpoint}): {e}")
            return None

    async def get_user_info(self) -> Optional[Dict[str, Any]]:
        response = await self.request("GET", "/users/@me")
        if response and response.status_code == 200:
            data = response.json()
            self.user_data = data
            self.user_id = data.get("id")
            return data
        return None

    async def send_message(self, channel_id: str, content: str, reply_to: Optional[str] = None,
                    tts: bool = False) -> Optional[Dict[str, Any]]:
        try:
            if hasattr(self, "channel") and self.channel and str(self.channel.id) == str(channel_id):
                msg = await self.channel.send(content)
                return {"id": msg.id}
        except Exception:
            pass

        data = {"content": content, "tts": tts}
        if reply_to:
            data["message_reference"] = {"message_id": reply_to}

        response = await self.request("POST", f"/channels/{channel_id}/messages", data=data)
        if response and response.status_code == 200:
            return response.json()

        return None

    async def delete_message(self, channel_id: str, message_id: str) -> bool:
        response = await self.request("DELETE", f"/channels/{channel_id}/messages/{message_id}")
        if response and response.status_code == 204:
            return True

        try:
            if hasattr(self, "channel") and self.channel and str(self.channel.id) == str(channel_id):
                msg = await self.channel.fetch_message(int(message_id))
                await msg.delete()
                return True
        except Exception:
            pass

        return False

    async def delayed_message_delete(self, channel_id: str, message_id: str, delay: float = 3.0) -> bool:
        """Delete a message after a specified delay in seconds"""
        await asyncio.sleep(delay)
        return await self.delete_message(channel_id, message_id)

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> Optional[Dict[str, Any]]:
        data = {"content": content}
        response = await self.request("PATCH", f"/channels/{channel_id}/messages/{message_id}", data=data)
        if response and response.status_code == 200:
            return response.json()

        try:
            if hasattr(self, "channel") and self.channel and str(self.channel.id) == str(channel_id):
                msg = await self.channel.fetch_message(int(message_id))
                await msg.edit(content=content)
                return {"id": msg.id}
        except Exception:
            pass

        return None

    async def get_messages(self, channel_id: str, limit: int = 50, before: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"limit": limit}
        if before:
            params["before"] = before

        response = await self.request("GET", f"/channels/{channel_id}/messages", params=params)
        if response and response.status_code == 200:
            return response.json()
        return []

    async def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> bool:
        encoded_emoji = quote(emoji)
        response = await self.request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me")
        return response.status_code == 204 if response else False

    async def create_dm(self, user_id: str) -> Optional[Dict[str, Any]]:
        data = {"recipient_id": user_id}
        response = await self.request("POST", "/users/@me/channels", data=data)
        return response.json() if response and response.status_code == 200 else None

    async def join_guild(self, invite_code: str) -> Optional[Dict[str, Any]]:
        response = await self.request("POST", f"/invites/{invite_code}")
        return response.json() if response and response.status_code == 200 else None

    async def leave_guild(self, guild_id: str) -> bool:
        response = await self.request("DELETE", f"/users/@me/guilds/{guild_id}")
        return response.status_code == 204 if response else False

    async def trigger_typing(self, channel_id: str) -> bool:
        response = await self.request("POST", f"/channels/{channel_id}/typing")
        return response.status_code == 204 if response else False

    async def duration_typing(self, duration: float = 1.0):
        """Trigger typing for specified duration"""
        try:
            await self.trigger_typing(self.channel.id)
            await asyncio.sleep(duration)
        except:
            pass

    async def set_status(self, status: str, activities: Optional[List[Dict]] = None) -> bool:
        data = {
            "status": status,
            "activities": activities or [],
            "since": int(time.time() * 1000)
        }
        response = await self.request("POST", "/users/@me/settings", data=data)
        return response.status_code == 200 if response else False

    async def get_guilds(self) -> List[Dict[str, Any]]:
        response = await self.request("GET", "/users/@me/guilds")
        return response.json() if response and response.status_code == 200 else []

    async def get_channels(self, guild_id: str) -> List[Dict[str, Any]]:
        response = await self.request("GET", f"/guilds/{guild_id}/channels")
        return response.json() if response and response.status_code == 200 else []

    async def get_friends(self) -> List[Dict[str, Any]]:
        response = await self.request("GET", "/users/@me/relationships")
        return response.json() if response and response.status_code == 200 else []

    async def add_friend(self, user_id: str) -> bool:
        response = await self.request("POST", f"/users/@me/relationships/{user_id}")
        return response.status_code == 204 if response else False

    async def block_user(self, user_id: str) -> bool:
        response = await self.request(
            "PUT",
            f"/users/@me/relationships/{user_id}",
            data={"type": int(RelationshipType.Blocked)},
        )
        return response.status_code == 204 if response else False