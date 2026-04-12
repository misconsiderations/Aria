import asyncio
import time
import random
import json
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from curl_cffi.requests import Session, Response
import threading
import uuid

class RateLimiter:
    """Advanced rate limiter with bucket management and DM protection"""

    def __init__(self):
        self.buckets: Dict[str, Dict[str, Any]] = {}
        self.endpoint_to_bucket: Dict[str, str] = {}
        self.dm_protection: Dict[str, float] = {}  # channel_id -> last_message_time
        self.client_rate_limits: Dict[str, Dict[str, Any]] = {}  # action_type -> channel_id -> data

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

    def handle_429(self, headers: Dict[str, str], endpoint: str):
        """Handle 429 response by updating bucket info"""
        bucket_hash = self.parse_bucket_hash(headers)
        self.update_bucket(bucket_hash, headers)

    def check_dm_protection(self, channel_id: str) -> Optional[float]:
        """Check DM-specific rate limiting to prevent spam detection"""
        if not channel_id:
            return None

        now = time.time()
        last_message = self.dm_protection.get(channel_id, 0)

        # Enforce minimum 2 second delay between DMs to same channel
        if now - last_message < 2.0:
            return 2.0 - (now - last_message)

        self.dm_protection[channel_id] = now
        return None

    def check_client_rate_limit(self, action_type: str, channel_id: str) -> Optional[float]:
        """Check client-side rate limits to prevent UI restrictions"""
        key = f"{action_type}:{channel_id}"
        now = time.time()

        if key not in self.client_rate_limits:
            self.client_rate_limits[key] = {
                "last_action": 0,
                "count": 0,
                "window_start": now
            }

        data = self.client_rate_limits[key]

        # Reset window if needed
        if now - data["window_start"] > 60:  # 1 minute window
            data["count"] = 0
            data["window_start"] = now

        # Rate limits per action type
        limits = {
            "message": {"per_second": 2, "per_minute": 30},
            "typing": {"per_second": 1, "per_minute": 10},
            "reaction": {"per_second": 5, "per_minute": 100},
            "other": {"per_second": 10, "per_minute": 300}
        }

        limit = limits.get(action_type, limits["other"])

        # Check per-second limit
        if now - data["last_action"] < 1.0:
            if data["count"] >= limit["per_second"]:
                return 1.0 - (now - data["last_action"])

        # Check per-minute limit
        if data["count"] >= limit["per_minute"]:
            return 60.0 - (now - data["window_start"])

        data["last_action"] = now
        data["count"] += 1
        return None

class ProtectionCoordinator:
    """Coordinates multiple protection mechanisms for maximum safety"""

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.header_rotator = HeaderRotator()
        self.fingerprint_manager = FingerprintManager()
        self.behavior_simulator = BehaviorSimulator()
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None

    def initialize_with_token(self, token: str):
        """Initialize with bot token"""
        self.token = token
        self.user_id = self._extract_user_id_from_token(token)
        self.header_rotator.set_token(token)
        if self.user_id:
            self.fingerprint_manager.set_user_id(self.user_id)

    def _extract_user_id_from_token(self, token: str) -> Optional[str]:
        """Extract user ID from bot token"""
        try:
            # Bot tokens are base64 encoded with user_id.timestamp.signature
            import base64
            payload = token.split('.')[0]
            decoded = base64.b64decode(payload + '==').decode()
            return decoded.split('.')[0]
        except:
            return None

    def check_protection(self) -> Optional[float]:
        """Check if we need to wait for protection"""
        # Check behavior simulation
        wait_time = self.behavior_simulator.get_delay()
        if wait_time:
            return wait_time

        return None

    def get_headers(self, token: str) -> Dict[str, str]:
        """Get protected headers for request"""
        base_headers = self.header_rotator.get_headers()

        # Add fingerprint
        fingerprint = self.fingerprint_manager.get_fingerprint()
        if fingerprint:
            base_headers["X-Fingerprint"] = fingerprint

        # Add super properties
        super_props = self._get_super_properties()
        if super_props:
            base_headers["X-Super-Properties"] = super_props

        return base_headers

    def _get_super_properties(self) -> str:
        """Generate super properties for Discord"""
        props = {
            "os": "Windows",
            "browser": "Chrome",
            "device": "",
            "system_locale": "en-US",
            "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "browser_version": "120.0.0.0",
            "os_version": "10",
            "referrer": "",
            "referring_domain": "",
            "referrer_current": "",
            "referring_domain_current": "",
            "release_channel": "stable",
            "client_build_number": 9999,
            "client_event_source": None
        }

        import base64
        props_json = json.dumps(props, separators=(',', ':'))
        return base64.b64encode(props_json.encode()).decode()

    def handle_429_response(self, headers: Dict[str, str]) -> float:
        """Handle 429 response and return retry time"""
        retry_after = float(headers.get("Retry-After", "1.0"))

        # Update rate limiter
        self.rate_limiter.handle_429(headers, "")

        # Add extra delay for safety
        return retry_after + random.uniform(0.5, 2.0)

    def handle_success_response(self):
        """Handle successful response"""
        self.behavior_simulator.record_success()

class HeaderRotator:
    """Rotates headers to avoid detection"""

    def __init__(self):
        self.token: Optional[str] = None
        self.user_agent_templates = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        ]
        self.last_rotation = 0
        self.rotation_interval = 300  # 5 minutes

    def set_token(self, token: str):
        """Set the bot token"""
        self.token = token

    def get_headers(self) -> Dict[str, str]:
        """Get rotated headers"""
        now = time.time()

        # Rotate headers periodically
        if now - self.last_rotation > self.rotation_interval:
            self._rotate_headers()
            self.last_rotation = now

        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": self._get_user_agent(),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }

        return headers

    def _get_user_agent(self) -> str:
        """Get a random user agent"""
        template = random.choice(self.user_agent_templates)
        version = random.randint(115, 125)
        return template.format(version=version)

    def _rotate_headers(self):
        """Rotate header values to avoid patterns"""
        # Could implement more sophisticated rotation here
        pass

class FingerprintManager:
    """Manages browser fingerprints for consistency"""

    def __init__(self):
        self.user_id: Optional[str] = None
        self.fingerprint: Optional[str] = None
        self.last_generated = 0
        self.fingerprint_lifetime = 3600  # 1 hour

    def set_user_id(self, user_id: str):
        """Set user ID for fingerprint generation"""
        self.user_id = user_id

    def get_fingerprint(self) -> Optional[str]:
        """Get or generate fingerprint"""
        now = time.time()

        if not self.fingerprint or now - self.last_generated > self.fingerprint_lifetime:
            self.fingerprint = self._generate_fingerprint()
            self.last_generated = now

        return self.fingerprint

    def _generate_fingerprint(self) -> str:
        """Generate a consistent fingerprint"""
        if not self.user_id:
            return str(uuid.uuid4())

        # Create deterministic fingerprint based on user ID
        hash_input = f"{self.user_id}:{int(time.time() // 3600)}"  # Changes hourly
        return hashlib.md5(hash_input.encode()).hexdigest()

class BehaviorSimulator:
    """Simulates human-like behavior patterns"""

    def __init__(self):
        self.last_action = 0
        self.action_count = 0
        self.burst_count = 0
        self.burst_start = 0

    def get_delay(self) -> Optional[float]:
        """Get delay to simulate human behavior"""
        now = time.time()

        # Reset counters periodically
        if now - self.last_action > 300:  # 5 minutes
            self.action_count = 0
            self.burst_count = 0

        # Simulate typing delays
        if self.action_count > 0:
            # Add random delays between actions
            base_delay = random.uniform(0.5, 2.0)

            # Add longer delays after bursts
            if self.burst_count > 5:
                base_delay += random.uniform(1.0, 3.0)
                self.burst_count = 0

            return base_delay

        return None

    def record_success(self):
        """Record successful action"""
        now = time.time()
        self.last_action = now
        self.action_count += 1
        self.burst_count += 1

class HeaderSpoofer:
    """Main header spoofer class v2"""

    def __init__(self):
        self.protection_coordinator = ProtectionCoordinator()
        self.session: Optional[Session] = None

    def initialize_with_token(self, token: str):
        """Initialize with bot token"""
        self.protection_coordinator.initialize_with_token(token)
        self.session = self._create_session()

    def _create_session(self) -> Session:
        """Create a protected session"""
        session = Session()

        # Set default headers
        session.headers.update({
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        })

        return session

    def get_protected_headers(self, token: str) -> Dict[str, str]:
        """Get fully protected headers"""
        return self.protection_coordinator.get_headers(token)

    def check_rate_limits(self) -> Optional[float]:
        """Check all rate limits"""
        return self.protection_coordinator.check_protection()

    def handle_response(self, response: Response) -> Optional[float]:
        """Handle response and return any required wait time"""
        if response.status_code == 429:
            headers = {k: v for k, v in dict(response.headers).items() if v is not None}
            return self.protection_coordinator.handle_429_response(headers)
        elif response.status_code == 200:
            self.protection_coordinator.handle_success_response()
            return None
        return None

# Export the main class
__all__ = ['HeaderSpoofer', 'ProtectionCoordinator', 'RateLimiter']