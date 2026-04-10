import asyncio
import time
import random
import json
import hashlib
import base64
import ssl
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import threading
import uuid

# Try to import curl_cffi, fallback to requests if not available
try:
    from curl_cffi.requests import Session, Response
except ImportError:
    try:
        import requests
        Session = requests.Session
        Response = requests.Response
    except ImportError:
        Session = None
        Response = None

class RateLimiter:
    """Advanced rate limiter with bucket management and DM protection"""

    def __init__(self):
        self.buckets: Dict[str, Dict[str, Any]] = {}
        self.dm_protection: Dict[str, float] = {}
        self.client_rate_limits: Dict[str, Dict[str, Any]] = {}

    def parse_bucket_hash(self, headers: Dict[str, str]) -> str:
        """Parse bucket hash from response headers"""
        return headers.get("X-RateLimit-Bucket", "global")

    def update_bucket(self, bucket_hash: str, headers: Dict[str, str]):
        """Update bucket information from response headers"""
        if bucket_hash not in self.buckets:
            self.buckets[bucket_hash] = {}

        bucket = self.buckets[bucket_hash]
        bucket.update({
            "limit": int(headers.get("X-RateLimit-Limit", 5)),
            "remaining": int(headers.get("X-RateLimit-Remaining", 5)),
            "reset": float(headers.get("X-RateLimit-Reset", time.time() + 1)),
            "reset_after": float(headers.get("X-RateLimit-Reset-After", 1.0))
        })

    def should_wait(self, bucket_hash: str) -> Optional[float]:
        """Check if we should wait before making a request"""
        if bucket_hash not in self.buckets:
            return None

        bucket = self.buckets[bucket_hash]
        now = time.time()

        if bucket.get("remaining", 5) <= 0:
            reset_time = bucket.get("reset", now + 1)
            if now < reset_time:
                return reset_time - now

        return None

    def decrement(self, bucket_hash: str):
        """Decrement remaining requests for a bucket"""
        if bucket_hash in self.buckets:
            self.buckets[bucket_hash]["remaining"] = max(0, self.buckets[bucket_hash].get("remaining", 5) - 1)

    def handle_429(self, headers: Dict[str, str], endpoint: str) -> float:
        """Handle 429 response and return retry time"""
        bucket_hash = self.parse_bucket_hash(headers)
        self.update_bucket(bucket_hash, headers)
        retry_after = float(headers.get("Retry-After", "1.0"))
        return retry_after + random.uniform(0.5, 2.0)

    def check_dm_protection(self, channel_id: str) -> Optional[float]:
        """Check DM-specific rate limiting"""
        if not channel_id:
            return None

        now = time.time()
        last_message = self.dm_protection.get(channel_id, 0)

        if now - last_message < 2.0:
            return 2.0 - (now - last_message)

        self.dm_protection[channel_id] = now
        return None

    def get_wait_time(self, endpoint: str) -> Optional[float]:
        """Get wait time for endpoint"""
        bucket_hash = self.parse_bucket_hash({})
        return self.should_wait(bucket_hash)


class BrowserProfile:
    """Browser profile for spoofing"""

    def __init__(self):
        timestamp = int(time.time())
        random.seed(timestamp % 1000)

        self.chrome_versions = [
            {"major": "125", "full": "125.0.6422.113"},
            {"major": "124", "full": "124.0.6367.207"},
            {"major": "123", "full": "123.0.6312.122"},
        ]

        version_idx = (timestamp // 3600) % len(self.chrome_versions)
        chrome = self.chrome_versions[version_idx]

        locations = [
            {"timezone": "America/New_York", "locale": "en-US"},
            {"timezone": "America/Chicago", "locale": "en-US"},
            {"timezone": "America/Los_Angeles", "locale": "en-US"},
            {"timezone": "Europe/London", "locale": "en-GB"},
        ]

        location_idx = timestamp % len(locations)
        location = locations[location_idx]

        self.user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome['full']} Safari/537.36"
        self.os = "Windows"
        self.browser = "Chrome"
        self.browser_version = chrome['full']
        self.os_version = "10"
        self.locale = location['locale']
        self.timezone = location['timezone']
        self.screen_resolution = "1920x1080"
        self.hardware_concurrency = 8
        self.device_memory = 8


class HeaderSpoofer:
    """Main header spoofer for Discord"""

    def __init__(self):
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.fingerprint: str = ""
        self.cookies: str = ""
        self.cache_time: float = 0
        self.profile = BrowserProfile()
        self.build_number = 284054
        self.session: Session = self._create_session()
        self.proxy_manager = None
        self._init_proxy_manager()

    def _init_proxy_manager(self):
        """Initialize proxy manager"""
        try:
            from proxy_manager import ProxyManager
            self.proxy_manager = ProxyManager()
        except:
            self.proxy_manager = None

    def _create_session(self) -> Session:
        """Create SSL-safe session"""
        try:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            # Try curl_cffi first for better spoofing
            try:
                from curl_cffi.requests import Session as CurlSession
                return CurlSession(impersonate="chrome120")
            except:
                # Fall back to requests if curl_cffi not available
                session = Session()
                session.verify = False
                return session
        except:
            # Ultimate fallback
            import requests
            session = requests.Session()
            session.verify = False
            return session

    def initialize_with_token(self, token: str):
        """Initialize with bot token"""
        self.token = token
        try:
            payload = token.split('.')[0]
            decoded = base64.b64decode(payload + '==').decode()
            self.user_id = decoded.split('.')[0]
        except:
            self.user_id = None

    def _generate_fingerprint(self) -> str:
        """Generate Discord-style fingerprint"""
        timestamp_ms = int(time.time() * 1000)
        random_part = random.randint(100000000000000000, 999999999999999999)
        return f"{timestamp_ms}.{random_part}"

    def _fetch_fingerprint(self) -> tuple:
        """Fetch fingerprint from Discord"""
        if time.time() - self.cache_time < 3600 and self.fingerprint:
            return self.fingerprint, self.cookies

        try:
            headers = {
                "User-Agent": self.profile.user_agent,
                "Accept": "application/json",
                "Accept-Language": self.profile.locale,
            }
            response = self.session.get(
                "https://discord.com/api/v9/experiments",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.fingerprint = data.get("fingerprint", self._generate_fingerprint())
                self.cookies = "; ".join([f"{k}={v}" for k, v in response.cookies.items()])
                self.cache_time = time.time()
            else:
                self.fingerprint = self._generate_fingerprint()
                self.cookies = f"locale={self.profile.locale}"
        except:
            self.fingerprint = self._generate_fingerprint()
            self.cookies = f"locale={self.profile.locale}"

        return self.fingerprint, self.cookies

    def _generate_super_properties(self) -> str:
        """Generate X-Super-Properties header"""
        props = {
            "os": self.profile.os,
            "browser": self.profile.browser,
            "device": "",
            "system_locale": self.profile.locale,
            "browser_user_agent": self.profile.user_agent,
            "browser_version": self.profile.browser_version,
            "os_version": self.profile.os_version,
            "referrer": "",
            "referring_domain": "",
            "release_channel": "stable",
            "client_build_number": self.build_number,
            "client_event_source": None,
            "design_id": 0
        }

        props_json = json.dumps(props, separators=(',', ':'))
        return base64.b64encode(props_json.encode()).decode()

    def _generate_sec_ch_ua(self) -> str:
        """Generate Sec-CH-UA header"""
        major_version = self.profile.browser_version.split('.')[0]
        return f'"Chromium";v="{major_version}", "Google Chrome";v="{major_version}", "Not=A?Brand";v="99"'

    def get_protected_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """Get fully protected headers for Discord API"""
        if token:
            self.token = token
        
        fingerprint, cookies = self._fetch_fingerprint()

        headers = {
            "Authorization": self.token or "",
            "User-Agent": self.profile.user_agent,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": f"{self.profile.locale},en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
            "Sec-Ch-Ua": self._generate_sec_ch_ua(),
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": f'"{self.profile.os}"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Dnt": "1",
            "Upgrade-Insecure-Requests": "1",
            "X-Debug-Options": "bugReporterEnabled",
            "X-Discord-Locale": self.profile.locale,
            "X-Discord-Timezone": self.profile.timezone,
            "X-Super-Properties": self._generate_super_properties(),
            "X-Fingerprint": fingerprint,
            "Cookie": cookies,
        }

        return headers

    def get_websocket_headers(self) -> Dict[str, str]:
        """Get websocket headers"""
        return {
            "User-Agent": self.profile.user_agent,
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": self.profile.locale,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
            "Sec-WebSocket-Key": base64.b64encode(str(time.time()).encode()).decode()[:24],
            "Sec-WebSocket-Version": "13",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Origin": "https://discord.com",
            "Sec-WebSocket-Protocol": "json"
        }

    def check_rate_limits(self) -> Optional[float]:
        """Check rate limits"""
        return None

    def handle_response(self, response: Response) -> Optional[float]:
        """Handle response"""
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1.0"))
            return retry_after + random.uniform(0.5, 2.0)
        return None

    def rotate_profile(self):
        """Rotate browser profile"""
        self.profile = BrowserProfile()
        self.cache_time = 0
        self.fingerprint = ""


__all__ = ['HeaderSpoofer', 'RateLimiter', 'BrowserProfile']
