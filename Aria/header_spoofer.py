import time
import random
import json
import base64
import ssl
from typing import Dict, Any, Optional

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
    """Enhanced browser profile for spoofing with modern browsers and better randomization"""

    def __init__(self):
        timestamp = int(time.time())
        random.seed(timestamp % 1000)

        # Chrome versions (2025-2026)
        self.chrome_versions = [
            {"major": "136", "full": "136.0.7103.49"},
            {"major": "135", "full": "135.0.7049.115"},
            {"major": "134", "full": "134.0.6998.117"},
            {"major": "133", "full": "133.0.6943.141"},
            {"major": "132", "full": "132.0.6834.160"},
            {"major": "131", "full": "131.0.6778.264"},
        ]

        # Edge (Chromium-based) versions (2025-2026)
        self.edge_versions = [
            {"major": "135", "full": "135.0.3179.98"},
            {"major": "134", "full": "134.0.3124.83"},
            {"major": "133", "full": "133.0.3065.92"},
        ]

        # Firefox versions on Linux (inspired by headerspoofer-discord-plugin)
        self.firefox_versions = [
            {"major": "136", "full": "136.0"},
            {"major": "135", "full": "135.0.1"},
            {"major": "134", "full": "134.0.2"},
            {"major": "133", "full": "133.0"},
        ]

        # Linux distros for Firefox spoofing
        self.linux_distros = [
            "Ubuntu 24.04",
            "Ubuntu 22.04",
            "Debian 12",
            "Fedora 41",
        ]

        # Browser rotation: Chrome (Windows), Edge (Windows), Firefox (Linux), Firefox (macOS)
        browser_choice = random.choice([
            "chrome", "chrome", "chrome",
            "edge",
            "firefox_linux", "firefox_linux",
            "firefox_mac",
        ])

        self.is_firefox = browser_choice.startswith("firefox")

        if browser_choice == "edge":
            version_idx = random.randint(0, len(self.edge_versions) - 1)
            browser = self.edge_versions[version_idx]
            self.browser_version = browser['full']
            browser_full = f"Edg/{browser['full']}"
            ua_template = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser['full']} Safari/537.36 {browser_full}"
            self.browser = "Edge"
            self.os = "Windows"
            self.os_version = "10"
            self.platform = "Win32"
        elif browser_choice == "firefox_linux":
            version_idx = (timestamp // 3600) % len(self.firefox_versions)
            browser = self.firefox_versions[version_idx]
            self.browser_version = browser['full']
            distro = random.choice(self.linux_distros)
            self.linux_distro = distro
            ua_template = f"Mozilla/5.0 (X11; Linux x86_64; rv:{browser['major']}.0) Gecko/20100101 Firefox/{browser['full']}"
            self.browser = "Firefox"
            self.os = "Linux"
            self.os_version = distro
            self.platform = "Linux x86_64"
        elif browser_choice == "firefox_mac":
            version_idx = (timestamp // 3600) % len(self.firefox_versions)
            browser = self.firefox_versions[version_idx]
            self.browser_version = browser['full']
            ua_template = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:{browser['major']}.0) Gecko/20100101 Firefox/{browser['full']}"
            self.browser = "Firefox"
            self.os = "Mac OS X"
            self.os_version = "14.7"
            self.platform = "MacIntel"
        else:
            version_idx = (timestamp // 3600) % len(self.chrome_versions)
            browser = self.chrome_versions[version_idx]
            self.browser_version = browser['full']
            ua_template = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser['full']} Safari/537.36"
            self.browser = "Chrome"
            self.os = "Windows"
            self.os_version = "10"
            self.platform = "Win32"

        # Randomize window size for more natural spoofing
        screen_sizes = [
            "1920x1080",
            "1680x1050", 
            "1440x900",
            "1366x768",
            "2560x1440",
            "1920x1200",
            "2560x1600",
        ]

        locations = [
            {"timezone": "America/New_York", "locale": "en-US"},
            {"timezone": "America/Chicago", "locale": "en-US"},
            {"timezone": "America/Denver", "locale": "en-US"},
            {"timezone": "America/Los_Angeles", "locale": "en-US"},
            {"timezone": "Europe/London", "locale": "en-GB"},
            {"timezone": "Europe/Paris", "locale": "fr-FR"},
            {"timezone": "Asia/Tokyo", "locale": "ja-JP"},
            {"timezone": "Australia/Sydney", "locale": "en-AU"},
        ]

        location_idx = timestamp % len(locations)
        location = locations[location_idx]

        self.user_agent = ua_template
        self.locale = location['locale']
        self.timezone = location['timezone']
        self.screen_resolution = random.choice(screen_sizes)
        self.hardware_concurrency = random.choice([4, 8, 16])
        self.device_memory = random.choice([4, 8, 16, 32])



class HeaderSpoofer:
    """Main header spoofer for Discord"""

    def __init__(self):
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.fingerprint: str = ""
        self.cookies: str = ""
        self.cache_time: float = 0
        self.profile = BrowserProfile()
        self.build_number = 338000  # Updated for 2026
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
                return CurlSession(impersonate="chrome131")
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
        """Generate realistic Discord-style fingerprint"""
        # Discord fingerprints follow pattern: <timestamp_ms>.<random_64bit>
        timestamp_ms = int(time.time() * 1000)
        # 64-bit random value
        random_part = random.randint(1000000000000000000, 9999999999999999999)
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
        """Generate X-Super-Properties header with modern Discord values"""
        # Discord build numbers (2025-2026 stable range)
        build_numbers = [332494, 334140, 335603, 336468, 337240, 338000]
        build = random.choice(build_numbers)
        
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
            "client_build_number": build,
            "client_event_source": None,
            "design_id": 0,
        }

        props_json = json.dumps(props, separators=(',', ':'), ensure_ascii=True)
        return base64.b64encode(props_json.encode()).decode()

    def _generate_sec_ch_ua(self) -> Optional[str]:
        """Generate Sec-CH-UA header. Firefox does not send Client Hints — returns None for Firefox."""
        if self.profile.is_firefox:
            return None
        major_version = self.profile.browser_version.split('.')[0]
        return f'"Chromium";v="{major_version}", "Google Chrome";v="{major_version}", "Not(A:Brand";v="99"'

    def get_protected_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """Get fully protected headers for Discord API with modern spoofing"""
        if token:
            self.token = token
        
        fingerprint, cookies = self._fetch_fingerprint()

        # Build headers with randomized order for better spoofing
        headers: Dict[str, str] = {
            "Authorization": self.token or "",
            "User-Agent": self.profile.user_agent,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": f"{self.profile.locale},en;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Dnt": "1",
            "X-Debug-Options": "bugReporterEnabled",
            "X-Discord-Locale": self.profile.locale,
            "X-Discord-Timezone": self.profile.timezone,
            "X-Super-Properties": self._generate_super_properties(),
            "X-Fingerprint": fingerprint,
            "Cookie": cookies,
        }

        # Chrome/Edge sends Client Hints; Firefox does not (matches real browser behaviour)
        sec_ch_ua = self._generate_sec_ch_ua()
        if sec_ch_ua is not None:
            headers["Sec-Ch-Ua"] = sec_ch_ua
            headers["Sec-Ch-Ua-Mobile"] = "?0"
            headers["Sec-Ch-Ua-Platform"] = f'"{self.profile.os}"'
            headers["Upgrade-Insecure-Requests"] = "1"
            headers["Sec-Fetch-User"] = "?1"

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
